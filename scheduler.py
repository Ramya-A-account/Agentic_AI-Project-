"""
AgentCare AI - Automatic Monitoring Scheduler

Runs the complete AgentCare monitoring pipeline automatically
every 30 minutes.

Pipeline:
    Simulation
        ->
    Data Cleaning
        ->
    Analysis
        ->
    Alert Detection
        ->
    Recommendation

Historical simulation is NOT triggered by this scheduler.

The existing AgentCare project currently uses timezone-naive
UTC datetimes, so this scheduler also produces naive UTC
datetimes for compatibility with the Simulation Agent and
existing database timestamps.

Usage:
    python scheduler.py
"""

from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from zoneinfo import ZoneInfo
from agentcare.services.daily_report_service import run_daily_report


from agentcare.db import get_session, init_db
from agentcare.agents.orchestrator import OrchestratorAgent


# ================================================================
# CONFIGURATION
# ================================================================

WINDOW_MINUTES = 30
ESCALATION_CHECK_MINUTES = 5


# ================================================================
# UTC TIME HELPER
# ================================================================

def utcnow():
    """
    Return current UTC time as a timezone-naive datetime.

    The project currently stores and compares UTC timestamps
    without timezone information. Therefore we intentionally
    remove tzinfo after obtaining the current UTC time.

    This avoids the deprecated datetime.utcnow() call while
    remaining compatible with the existing project.
    """

    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


# ================================================================
# RUN ONE MONITORING CYCLE
# ================================================================

def run_monitoring_cycle():
    """
    Execute one complete AgentCare monitoring cycle.
    """

    print("\n")
    print("=" * 70)
    print("🚀 AGENTCARE SCHEDULED MONITORING CYCLE")
    print("=" * 70)

    window_end = utcnow()

    window_start = (
        window_end
        - timedelta(minutes=WINDOW_MINUTES)
    )

    print(
        f"\nMonitoring window:"
        f"\n  {window_start}"
        f"\n  -> {window_end}"
    )

    session = None

    try:

        # --------------------------------------------------------
        # Initialize database
        # --------------------------------------------------------

        init_db()

        session = get_session()

        # --------------------------------------------------------
        # Create orchestrator
        # --------------------------------------------------------

        orchestrator = OrchestratorAgent(
            session
        )

        # --------------------------------------------------------
        # Run complete monitoring pipeline
        # --------------------------------------------------------

        result = (
            orchestrator.trigger_monitoring_cycle(
                window_start,
                window_end,
            )
        )

        # --------------------------------------------------------
        # Result
        # --------------------------------------------------------

        if result["status"] == "SUCCESS":

            print("\n" + "=" * 70)
            print("🎉 SCHEDULED MONITORING CYCLE SUCCESS")
            print("=" * 70)

        else:

            print("\n" + "=" * 70)
            print("❌ SCHEDULED MONITORING CYCLE FAILED")
            print("=" * 70)

            print(
                f"Failed agent: "
                f"{result.get('failed_agent')}"
            )

            print(
                f"Error: "
                f"{result.get('error')}"
            )

    except Exception as exc:

        print("\n" + "=" * 70)
        print("❌ SCHEDULER CYCLE ERROR")
        print("=" * 70)

        print(str(exc))

    finally:

        if session is not None:
            session.close()


# ================================================================
# RUN ONE ESCALATION CHECK
# ================================================================

def run_escalation_check():
    """
    Check for CRITICAL incidents that have gone unacknowledged past the
    configured threshold, and escalate (or re-remind) as needed. Runs
    far more often than the monitoring cycle since the whole point is
    to catch unnoticed critical incidents quickly.
    """

    session = None

    try:
        init_db()
        session = get_session()

        from agentcare.agents.escalation_agent import EscalationAgent

        result = EscalationAgent(session).run()

        if result["status"] != "SUCCESS":
            print("\n❌ ESCALATION CHECK FAILED")
            print(result.get("error"))

    except Exception as exc:
        print("\n❌ ESCALATION CHECK ERROR")
        print(exc)

    finally:
        if session is not None:
            session.close()


# ================================================================
# START SCHEDULER
# ================================================================

def main():

    print("\n" + "=" * 70)
    print("AGENTCARE AI - AUTOMATIC SCHEDULER")
    print("=" * 70)

    print(
        "\nMonitoring interval:"
        f" Every {WINDOW_MINUTES} minutes"
    )

    print(
        "\nHistorical simulation:"
        " DISABLED"
    )

    print(
        "\nPipeline:"
        "\n  Simulation"
        "\n      ↓"
        "\n  Data Cleaning"
        "\n      ↓"
        "\n  Analysis"
        "\n      ↓"
        "\n  Alert Detection"
        "\n      ↓"
        "\n  Recommendation"
    )

    # ------------------------------------------------------------
    # Create scheduler
    # ------------------------------------------------------------

    scheduler = BlockingScheduler(
    timezone=ZoneInfo("Asia/Kolkata")
)

    # ------------------------------------------------------------
    # Schedule monitoring every 30 minutes
    # ------------------------------------------------------------

    scheduler.add_job(
        run_monitoring_cycle,
        trigger="interval",
        minutes=WINDOW_MINUTES,
        id="agentcare_monitoring",
        name="AgentCare 30-Minute Monitoring",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # ------------------------------------------------------------
    # Schedule escalation checks every 5 minutes
    # ------------------------------------------------------------

    scheduler.add_job(
        run_escalation_check,
        trigger="interval",
        minutes=ESCALATION_CHECK_MINUTES,
        id="agentcare_escalation_check",
        name="AgentCare Critical Incident Escalation Check",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )

    # ------------------------------------------------------------
    # Run one cycle immediately
    # ------------------------------------------------------------

    print(
        "\n▶ Running initial monitoring cycle..."
    )

    run_monitoring_cycle()

    scheduler.add_job(
    run_daily_manager_report,
    trigger="cron",
    hour=19,
    minute=0,
    id="agentcare_daily_report",
    name="AgentCare Daily Manager Report - 7 PM IST ",
    max_instances=1,
    coalesce=True,
    misfire_grace_time=900,)
    # ------------------------------------------------------------
    # Start scheduler
    # ------------------------------------------------------------

    print("\n" + "=" * 70)
    print("🟢 AGENTCARE SCHEDULER STARTED")
    print("=" * 70)

    print(
        "\nNext monitoring cycle will run automatically"
        f" every {WINDOW_MINUTES} minutes."
    )

    print("\nPress Ctrl+C to stop the scheduler.\n")

    try:

        scheduler.start()

    except (KeyboardInterrupt, SystemExit):

        print("\n")
        print("=" * 70)
        print("🛑 AGENTCARE SCHEDULER STOPPED")
        print("=" * 70)

        scheduler.shutdown(
            wait=False
        )

# ================================================================
# DAILY MANAGER REPORT
# ================================================================

def run_daily_manager_report():

    print("\n")
    print("=" * 70)
    print("📊 AGENTCARE 7 PM DAILY MANAGER REPORT")
    print("=" * 70)

    session = None

    try:

        init_db()

        session = get_session()

        result = run_daily_report(session, triggered_by="SCHEDULER", send_email=True)

        if result["status"] == "SUCCESS":
            print(f"\n🎉 DAILY MANAGER REPORT SUCCESS — email {result['email_status']}")
        else:
            print("\n❌ DAILY MANAGER REPORT FAILED")
            print(result.get("error"))

    except Exception as exc:

        print("\n❌ DAILY REPORT ERROR")
        print(exc)

    finally:

        if session is not None:
            session.close()
# ================================================================
# ENTRY POINT
# ================================================================

if __name__ == "__main__":
    main()