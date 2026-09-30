"""
Run this once per 30-minute window (this is what APScheduler will call
automatically once you wire up the scheduler). For now, run it manually
to test one live window at a time.

Usage:
    python run_live_cycle.py
"""
from datetime import datetime, timedelta, timezone

from agentcare.db import get_session, init_db
from agentcare.agents.orchestrator import OrchestratorAgent

WINDOW_MINUTES = 30


def main():
    init_db()
    session = get_session()

    window_end = datetime.utcnow()
    window_start = window_end - timedelta(minutes=WINDOW_MINUTES)

    orchestrator = OrchestratorAgent(session)
    print(f"Running monitoring cycle: {window_start.isoformat()} -> {window_end.isoformat()}")

    result = orchestrator.trigger_monitoring_cycle(window_start, window_end)

    if result["status"] == "SUCCESS":
        print("Monitoring cycle complete:")
        for k, v in result.items():
            if k != "status":
                print(f"  {k}: {v}")
    else:
        print("Monitoring cycle FAILED:", result.get("error"))

    session.close()


if __name__ == "__main__":
    main()
