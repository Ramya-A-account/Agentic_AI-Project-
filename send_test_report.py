"""Send one daily manager report immediately for email testing."""

from agentcare.agents.report_agent import DailyManagerReportAgent
from agentcare.config import MANAGER_EMAILS
from agentcare.db import get_session, init_db
from agentcare.email_reports import send_report


if __name__ == "__main__":
    init_db()
    session = get_session()
    try:
        result = DailyManagerReportAgent(session).run()
        if result["status"] != "SUCCESS":
            raise RuntimeError(result.get("error", "Report generation failed"))

        recipients = list(MANAGER_EMAILS.values())
        send_report(result["report"], recipients)
        print(f"Test report sent to: {', '.join(recipients)}")
    finally:
        session.close()
