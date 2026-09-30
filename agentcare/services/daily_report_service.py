"""
AgentCare AI - Daily Manager Report service

Single shared entry point for running the Daily Manager Report Agent.
Used by:
  - scheduler.py            (automatic 7:00 PM run)
  - api/routes.py            ("Run Now" button on the dashboard)

Responsible for:
  - Logging the run in workflow_execution_logs (so it shows up in the
    agent pipeline monitor like every other agent)
  - Running the DailyManagerReportAgent
  - Sending the HTML/plain-text manager email (with one retry on failure)
  - Recording a DailyReportLog row for delivery tracking + the
    dashboard's "View Latest Report" button
"""

from datetime import datetime, timezone

from agentcare.agents.report_agent import DailyManagerReportAgent
from agentcare.config import MANAGER_EMAILS
from agentcare.email_reports import send_report
from agentcare.models import DailyReportLog, WorkflowExecutionLog

WORKFLOW_NAME = "DAILY_REPORT"
AGENT_NAME = "DailyManagerReportAgent"


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def run_daily_report(session, triggered_by="SCHEDULER", send_email=True):
    """
    Run the Daily Manager Report Agent end-to-end.

    Returns a dict:
        {
            "status": "SUCCESS" | "FAILED",
            "report": {...} | None,
            "email_status": "SENT" | "FAILED" | "SKIPPED",
            "report_log_id": int,
        }
    """

    start_time = _utcnow()

    workflow_log = WorkflowExecutionLog(
        workflow_name=WORKFLOW_NAME,
        agent_name=AGENT_NAME,
        start_time=start_time,
        status="RUNNING",
    )
    session.add(workflow_log)
    session.commit()

    report_log = DailyReportLog(
        report_date=str(start_time.date()),
        triggered_by=triggered_by,
        report_status="RUNNING",
        email_status="SKIPPED",
        retry_count=0,
    )
    session.add(report_log)
    session.commit()

    # ------------------------------------------------------------
    # 1. Generate the report
    # ------------------------------------------------------------
    try:
        agent = DailyManagerReportAgent(session)
        result = agent.run()
    except Exception as exc:
        session.rollback()
        workflow_log.status = "FAILED"
        workflow_log.end_time = _utcnow()
        workflow_log.error_info = str(exc)
        report_log.report_status = "FAILED"
        report_log.report_error = str(exc)
        report_log.generated_time = _utcnow()
        session.commit()
        return {
            "status": "FAILED",
            "report": None,
            "email_status": "SKIPPED",
            "report_log_id": report_log.report_id,
            "error": str(exc),
        }

    if result.get("status") != "SUCCESS":
        error = result.get("error", "Report generation failed")
        workflow_log.status = "FAILED"
        workflow_log.end_time = _utcnow()
        workflow_log.error_info = error
        report_log.report_status = "FAILED"
        report_log.report_error = error
        report_log.generated_time = _utcnow()
        session.commit()
        return {
            "status": "FAILED",
            "report": None,
            "email_status": "SKIPPED",
            "report_log_id": report_log.report_id,
            "error": error,
        }

    report = result["report"]

    report_log.report_status = "COMPLETED"
    report_log.generated_time = _utcnow()
    report_log.report_date = report["report_date"]
    report_log.incident_count = report["incident_summary"]["total"]
    report_log.critical_incident_count = report["incident_summary"]["critical"]
    report_log.recommendation_count = report["recommendation_summary"]["total"]
    report_log.action_count = report["manager_action_summary"]["total"]
    report_log.report_json = report
    session.commit()

    workflow_log.status = "COMPLETED"
    workflow_log.end_time = _utcnow()
    session.commit()

    # ------------------------------------------------------------
    # 2. Send the email (best-effort, one retry)
    # ------------------------------------------------------------
    email_status = "SKIPPED"
    recipients = list(MANAGER_EMAILS.values())
    report_log.recipients = ", ".join(recipients) if recipients else None

    if send_email:
        email_log = WorkflowExecutionLog(
            workflow_name=WORKFLOW_NAME,
            agent_name="EmailDeliveryAgent",
            start_time=_utcnow(),
            status="RUNNING",
        )
        session.add(email_log)
        session.commit()

        last_error = None
        for attempt in range(2):  # try once, retry once on failure
            try:
                send_report(report, recipients)
                email_status = "SENT"
                report_log.email_sent_time = _utcnow()
                report_log.email_error = None
                last_error = None
                break
            except Exception as exc:
                last_error = str(exc)
                report_log.retry_count = attempt + 1

        if email_status == "SENT":
            email_log.status = "COMPLETED"
        else:
            email_status = "FAILED"
            email_log.status = "FAILED"
            email_log.error_info = last_error
            report_log.email_error = last_error

        email_log.end_time = _utcnow()
        session.commit()

    report_log.email_status = email_status
    session.commit()

    return {
        "status": "SUCCESS",
        "report": report,
        "email_status": email_status,
        "report_log_id": report_log.report_id,
    }
