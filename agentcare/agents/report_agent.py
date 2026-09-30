# ================================================================
# AGENTCARE AI - DAILY MANAGER REPORT AGENT
# ================================================================

import json
from datetime import datetime, timedelta

from sqlalchemy import func

from agentcare.agents import llm_reasoning
from agentcare.models import (
    KPIResult,
    Incident,
    Recommendation,
    ManagerAction,
    Department,
)


EXECUTIVE_SUMMARY_SYSTEM_PROMPT = (
    "You are the reasoning layer behind AgentCare AI's daily hospital "
    "operations report. You are given a structured summary of one day's "
    "KPIs, incidents, AI recommendations, and manager actions. Write a "
    "concise executive summary (3-5 sentences) that a hospital operations "
    "manager would want to read first thing - synthesize the day's "
    "operational picture, call out what actually needs attention, and note "
    "anything reassuring if the day was quiet. Do not just restate the "
    "counts; add judgment about what they mean together (e.g. rising "
    "occupancy and high-priority recommendations pointing at the same "
    "department is worth connecting explicitly).\n\n"
    'Respond with ONLY a JSON object, no other text: {"summary": "<the executive summary>"}'
)


class DailyManagerReportAgent:
    """
    Generates the daily operational report for hospital managers.

    Responsibilities:
    - Summarize hospital KPIs
    - Identify incidents detected during the day
    - Summarize AI recommendations
    - Summarize manager actions
    - Produce an executive summary
    - Return structured report data

    This agent is decision-support only.
    It does not modify operational source data.
    """

    def __init__(self, session):
        self.session = session

    # ============================================================
    # DATE / TIME
    # ============================================================

    def _get_report_date(self, report_date=None):
        """
        Returns the date for which the report should be generated.

        Database timestamps in AgentCare are stored as naive UTC.
        Therefore this agent uses UTC dates for database filtering.
        """

        if report_date is not None:
            return report_date

        return datetime.utcnow().date()

    # ============================================================
    # DAY WINDOW
    # ============================================================

    def _get_day_window(self, report_date):
        day_start = datetime.combine(
            report_date,
            datetime.min.time()
        )

        day_end = day_start + timedelta(days=1)

        return day_start, day_end

    # ============================================================
    # KPI SUMMARY
    # ============================================================

    def _get_kpi_summary(self, day_start, day_end):

        rows = (
            self.session.query(
                KPIResult.kpi_name,
                func.avg(KPIResult.value).label("average_value"),
                func.min(KPIResult.value).label("minimum_value"),
                func.max(KPIResult.value).label("maximum_value"),
                func.count(KPIResult.kpi_id).label("observations"),
            )
            .filter(
                KPIResult.calculation_time >= day_start,
                KPIResult.calculation_time < day_end,
            )
            .group_by(KPIResult.kpi_name)
            .all()
        )

        result = {}

        for row in rows:

            result[row.kpi_name] = {
                "average": round(
                    float(row.average_value), 2
                ) if row.average_value is not None else 0,

                "minimum": round(
                    float(row.minimum_value), 2
                ) if row.minimum_value is not None else 0,

                "maximum": round(
                    float(row.maximum_value), 2
                ) if row.maximum_value is not None else 0,

                "observations": int(row.observations),
            }

        return result

    # ============================================================
    # INCIDENT SUMMARY
    # ============================================================

    def _get_incidents(self, day_start, day_end):

        incidents = (
            self.session.query(Incident)
            .filter(
                Incident.first_detected_time >= day_start,
                Incident.first_detected_time < day_end,
            )
            .order_by(
                Incident.first_detected_time.desc()
            )
            .all()
        )

        result = []

        for incident in incidents:

            result.append({
                "incident_id": incident.incident_id,
                "kpi_name": incident.kpi_name,
                "department_id": incident.department_id,
                "severity": incident.severity,
                "status": incident.status,
                "trigger_value": (
                    float(incident.trigger_value)
                    if incident.trigger_value is not None
                    else None
                ),
                "threshold_value": (
                    float(incident.threshold_value)
                    if incident.threshold_value is not None
                    else None
                ),
                "baseline_value": (
                    float(incident.baseline_value)
                    if incident.baseline_value is not None
                    else None
                ),
                "first_detected_time": (
                    incident.first_detected_time.isoformat()
                    if incident.first_detected_time
                    else None
                ),
                "last_observed_time": (
                    incident.last_observed_time.isoformat()
                    if incident.last_observed_time
                    else None
                ),
            })

        return result

    # ============================================================
    # RECOMMENDATION SUMMARY
    # ============================================================

    def _get_recommendations(self, day_start, day_end):

        recommendations = (
            self.session.query(Recommendation)
            .filter(
                Recommendation.generated_time >= day_start,
                Recommendation.generated_time < day_end,
            )
            .order_by(
                Recommendation.generated_time.desc()
            )
            .all()
        )

        result = []

        for recommendation in recommendations:

            result.append({
                "recommendation_id": recommendation.recommendation_id,
                "incident_id": recommendation.incident_id,
                "text": recommendation.text,
                "supporting_evidence": (
                    recommendation.supporting_evidence
                ),
                "status": recommendation.status,
                "priority": recommendation.priority,
                "generated_time": (
                    recommendation.generated_time.isoformat()
                    if recommendation.generated_time
                    else None
                ),
            })

        return result

    # ============================================================
    # MANAGER ACTION SUMMARY
    # ============================================================

    def _get_manager_actions(self, day_start, day_end):

        actions = (
            self.session.query(ManagerAction)
            .filter(
                ManagerAction.action_time >= day_start,
                ManagerAction.action_time < day_end,
            )
            .order_by(
                ManagerAction.action_time.desc()
            )
            .all()
        )

        result = []

        for action in actions:

            result.append({
                "action_id": action.action_id,
                "action_type": action.action_type,
                "target_type": action.target_type,
                "target_id": action.target_id,
                "comment": action.comment,
                "action_time": (
                    action.action_time.isoformat()
                    if action.action_time
                    else None
                ),
            })

        return result

    # ============================================================
    # DEPARTMENT SUMMARY
    # ============================================================

    def _get_departments(self):

        departments = (
            self.session.query(Department)
            .order_by(Department.department_id)
            .all()
        )

        result = []

        for department in departments:

            result.append({
                "department_id": department.department_id,
                "name": department.name,
                "total_beds": department.total_beds,
                "total_icu_beds": department.total_icu_beds,
            })

        return result

    # ============================================================
    # EXECUTIVE SUMMARY
    # ============================================================

    def _build_executive_summary_llm(
        self,
        kpis,
        incidents,
        recommendations,
        manager_actions,
    ):
        """Ask the LLM to reason about the day's data holistically and
        write a synthesized summary. Returns None on any failure so the
        caller falls back to the deterministic version."""

        user_prompt = (
            "Today's operational data:\n\n"
            f"KPI summary: {json.dumps(kpis, default=str)}\n\n"
            f"Incidents ({len(incidents)} total): "
            f"{json.dumps([dict(i) for i in incidents], default=str)}\n\n"
            f"Recommendations ({len(recommendations)} total): "
            f"{json.dumps([dict(r) for r in recommendations], default=str)}\n\n"
            f"Manager actions ({len(manager_actions)} total): "
            f"{json.dumps([dict(a) for a in manager_actions], default=str)}\n\n"
            "Write the executive summary."
        )

        result = llm_reasoning.reason(
            EXECUTIVE_SUMMARY_SYSTEM_PROMPT, user_prompt, max_tokens=400
        )

        if not result or "summary" not in result:
            return None

        return result["summary"]

    def _build_executive_summary(
        self,
        kpis,
        incidents,
        recommendations,
        manager_actions,
    ):
        llm_summary = self._build_executive_summary_llm(
            kpis=kpis,
            incidents=incidents,
            recommendations=recommendations,
            manager_actions=manager_actions,
        )

        if llm_summary is not None:
            return llm_summary

        return self._build_executive_summary_rule_based(
            kpis=kpis,
            incidents=incidents,
            recommendations=recommendations,
            manager_actions=manager_actions,
        )

    def _build_executive_summary_rule_based(
        self,
        kpis,
        incidents,
        recommendations,
        manager_actions,
    ):

        critical_incidents = [
            incident
            for incident in incidents
            if str(incident["severity"]).upper() == "CRITICAL"
        ]

        warning_incidents = [
            incident
            for incident in incidents
            if str(incident["severity"]).upper() == "WARNING"
        ]

        high_priority_recommendations = [
            recommendation
            for recommendation in recommendations
            if str(recommendation["priority"]).upper() == "HIGH"
        ]

        summary_parts = []

        # --------------------------------------------------------
        # Incident summary
        # --------------------------------------------------------

        if critical_incidents:
            summary_parts.append(
                f"{len(critical_incidents)} critical operational "
                f"incident(s) require manager attention."
            )
        elif warning_incidents:
            summary_parts.append(
                f"{len(warning_incidents)} warning-level "
                f"operational incident(s) were detected."
            )
        else:
            summary_parts.append(
                "No critical or warning incidents were detected "
                "during the reporting period."
            )

        # --------------------------------------------------------
        # Recommendation summary
        # --------------------------------------------------------

        if high_priority_recommendations:
            summary_parts.append(
                f"{len(high_priority_recommendations)} high-priority "
                f"AI recommendation(s) were generated."
            )
        elif recommendations:
            summary_parts.append(
                f"{len(recommendations)} AI recommendation(s) "
                f"were generated."
            )
        else:
            summary_parts.append(
                "No new AI recommendations were generated."
            )

        # --------------------------------------------------------
        # Manager actions
        # --------------------------------------------------------

        if manager_actions:
            summary_parts.append(
                f"{len(manager_actions)} manager action(s) "
                f"were recorded."
            )
        else:
            summary_parts.append(
                "No manager actions were recorded."
            )

        # --------------------------------------------------------
        # Occupancy
        # --------------------------------------------------------

        occupancy = kpis.get("BED_OCCUPANCY")

        if occupancy:

            average_occupancy = occupancy["average"]

            if average_occupancy >= 90:
                summary_parts.append(
                    f"Average bed occupancy was {average_occupancy:.1f}%, "
                    "indicating critical capacity pressure."
                )

            elif average_occupancy >= 80:
                summary_parts.append(
                    f"Average bed occupancy was {average_occupancy:.1f}%, "
                    "indicating elevated capacity pressure."
                )

            else:
                summary_parts.append(
                    f"Average bed occupancy was "
                    f"{average_occupancy:.1f}%."
                )

        return " ".join(summary_parts)

    # ============================================================
    # REPORT GENERATION
    # ============================================================

    def run(self, report_date=None):

        try:

            report_date = self._get_report_date(
                report_date
            )

            day_start, day_end = self._get_day_window(
                report_date
            )

            # ----------------------------------------------------
            # Collect report data
            # ----------------------------------------------------

            kpis = self._get_kpi_summary(
                day_start,
                day_end
            )

            incidents = self._get_incidents(
                day_start,
                day_end
            )

            recommendations = self._get_recommendations(
                day_start,
                day_end
            )

            manager_actions = self._get_manager_actions(
                day_start,
                day_end
            )

            departments = self._get_departments()

            # ----------------------------------------------------
            # Executive summary
            # ----------------------------------------------------

            executive_summary = self._build_executive_summary(
                kpis=kpis,
                incidents=incidents,
                recommendations=recommendations,
                manager_actions=manager_actions,
            )

            # ----------------------------------------------------
            # Incident counts
            # ----------------------------------------------------

            critical_count = sum(
                1
                for incident in incidents
                if str(incident["severity"]).upper()
                == "CRITICAL"
            )

            warning_count = sum(
                1
                for incident in incidents
                if str(incident["severity"]).upper()
                == "WARNING"
            )

            # ----------------------------------------------------
            # Report object
            # ----------------------------------------------------

            report = {

                "report_date": str(report_date),

                "generated_at": datetime.utcnow().isoformat(),

                "report_type": "DAILY_MANAGER_REPORT",

                "reporting_window": {
                    "start": day_start.isoformat(),
                    "end": day_end.isoformat(),
                },

                "executive_summary": executive_summary,

                "kpi_summary": kpis,

                "incident_summary": {
                    "total": len(incidents),
                    "critical": critical_count,
                    "warning": warning_count,
                    "incidents": incidents,
                },

                "recommendation_summary": {
                    "total": len(recommendations),
                    "high_priority": sum(
                        1
                        for recommendation in recommendations
                        if str(
                            recommendation["priority"]
                        ).upper() == "HIGH"
                    ),
                    "recommendations": recommendations,
                },

                "manager_action_summary": {
                    "total": len(manager_actions),
                    "actions": manager_actions,
                },

                "departments": departments,
            }

            # ----------------------------------------------------
            # Print manager report
            # ----------------------------------------------------

            self._print_report(report)

            return {
                "status": "SUCCESS",
                "report": report,
            }

        except Exception as exc:

            self.session.rollback()

            return {
                "status": "FAILED",
                "error": str(exc),
            }

    # ============================================================
    # PRINT REPORT
    # ============================================================

    def _print_report(self, report):

        print("\n")
        print("=" * 70)
        print("📊 AGENTCARE AI - DAILY MANAGER REPORT")
        print("=" * 70)

        print(
            f"\n📅 Report Date: "
            f"{report['report_date']}"
        )

        print(
            f"🕐 Generated At: "
            f"{report['generated_at']}"
        )

        print("\n" + "-" * 70)
        print("EXECUTIVE SUMMARY")
        print("-" * 70)

        print(
            report["executive_summary"]
        )

        # --------------------------------------------------------
        # KPIs
        # --------------------------------------------------------

        print("\n" + "-" * 70)
        print("HOSPITAL KPI SUMMARY")
        print("-" * 70)

        if report["kpi_summary"]:

            for kpi_name, values in report[
                "kpi_summary"
            ].items():

                print(
                    f"{kpi_name}: "
                    f"avg={values['average']} | "
                    f"min={values['minimum']} | "
                    f"max={values['maximum']} | "
                    f"observations={values['observations']}"
                )

        else:

            print("No KPI observations found.")

        # --------------------------------------------------------
        # Incidents
        # --------------------------------------------------------

        print("\n" + "-" * 70)
        print("INCIDENTS")
        print("-" * 70)

        incident_summary = report[
            "incident_summary"
        ]

        print(
            f"Total: {incident_summary['total']} | "
            f"Critical: {incident_summary['critical']} | "
            f"Warning: {incident_summary['warning']}"
        )

        for incident in incident_summary["incidents"]:

            print(
                f"\n  [{incident['severity']}] "
                f"{incident['kpi_name']}"
            )

            print(
                f"  Incident ID: "
                f"{incident['incident_id']}"
            )

            print(
                f"  Trigger: "
                f"{incident['trigger_value']}"
            )

            print(
                f"  Threshold: "
                f"{incident['threshold_value']}"
            )

            print(
                f"  Status: "
                f"{incident['status']}"
            )

        # --------------------------------------------------------
        # Recommendations
        # --------------------------------------------------------

        print("\n" + "-" * 70)
        print("AI RECOMMENDATIONS")
        print("-" * 70)

        recommendation_summary = report[
            "recommendation_summary"
        ]

        print(
            f"Total: {recommendation_summary['total']} | "
            f"High Priority: "
            f"{recommendation_summary['high_priority']}"
        )

        for recommendation in recommendation_summary[
            "recommendations"
        ]:

            print(
                f"\n  [{recommendation['priority']}] "
                f"{recommendation['text']}"
            )

            print(
                f"  Recommendation ID: "
                f"{recommendation['recommendation_id']}"
            )

            print(
                f"  Status: "
                f"{recommendation['status']}"
            )

        # --------------------------------------------------------
        # Manager actions
        # --------------------------------------------------------

        print("\n" + "-" * 70)
        print("MANAGER ACTIONS")
        print("-" * 70)

        action_summary = report[
            "manager_action_summary"
        ]

        print(
            f"Total Actions: "
            f"{action_summary['total']}"
        )

        for action in action_summary["actions"]:

            print(
                f"\n  {action['action_type']} "
                f"→ {action['target_type']} "
                f"#{action['target_id']}"
            )

            if action["comment"]:

                print(
                    f"  Comment: "
                    f"{action['comment']}"
                )

        # --------------------------------------------------------
        # Departments
        # --------------------------------------------------------

        print("\n" + "-" * 70)
        print("DEPARTMENTS")
        print("-" * 70)

        for department in report["departments"]:

            print(
                f"  {department['name']} | "
                f"Beds: {department['total_beds']} | "
                f"ICU Beds: {department['total_icu_beds']}"
            )

        print("\n" + "=" * 70)
        print("✅ DAILY MANAGER REPORT COMPLETE")
        print("=" * 70)

    # ============================================================
    # JSON EXPORT HELPER
    # ============================================================

    def to_json(self, report_result):

        return json.dumps(
            report_result,
            indent=2,
            default=str
        )