"""
Run this ONCE to generate 30 days of historical hospital data before
starting live monitoring cycles.

Usage:
    python run_historical.py
"""
from datetime import datetime, timedelta, timezone

from agentcare.db import get_session, init_db
from agentcare.agents.orchestrator import OrchestratorAgent

DAYS_OF_HISTORY = 30


def main():
    init_db()
    session = get_session()

    start_time = datetime.utcnow() - timedelta(days=DAYS_OF_HISTORY)

    orchestrator = OrchestratorAgent(session)
    print(f"Generating {DAYS_OF_HISTORY} days of historical data starting {start_time.isoformat()} ...")

    result = orchestrator.trigger_historical_simulation(start_time, days=DAYS_OF_HISTORY)

    if result["status"] == "SUCCESS":
        print("Historical simulation complete:")
        for k, v in result.items():
            if k != "status":
                print(f"  {k}: {v}")
    else:
        print("Historical simulation FAILED:", result.get("error"))

    session.close()


if __name__ == "__main__":
    main()
