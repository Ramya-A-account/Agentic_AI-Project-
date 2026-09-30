"""
AgentCare Demo Trigger

Guarantees a CRITICAL incident exists (with a matching AI recommendation)
right before a presentation, instead of relying on the Simulation Agent
randomly producing one. Also backdates the incident so it's immediately
eligible for escalation — run this, then click "Check Escalations Now"
on the dashboard and the alert banner / email should fire right away.

Usage:
    python demo_trigger_critical.py

Safe to run multiple times — each run creates one new incident.
"""

from datetime import datetime, timedelta

from sqlalchemy import text

from agentcare.config import ESCALATION_THRESHOLD_MINUTES
from agentcare.db import get_session, init_db


def main():
    init_db()
    session = get_session()

    # Backdate far enough that it's immediately past the escalation
    # threshold, whatever that's currently configured to (default 30 min).
    first_detected_time = datetime.utcnow() - timedelta(
        minutes=ESCALATION_THRESHOLD_MINUTES + 5
    )

    department = session.execute(
        text("SELECT department_id, name FROM departments ORDER BY department_id LIMIT 1")
    ).mappings().first()

    if department is None:
        print("❌ No departments found — run 'python -m agentcare.seed' first.")
        return

    print("\n" + "=" * 70)
    print("AGENTCARE DEMO TRIGGER — creating a guaranteed CRITICAL incident")
    print("=" * 70)

    result = session.execute(
        text("""
            INSERT INTO incidents
                (kpi_name, department_id, severity, status, trigger_value, threshold_value, baseline_value, first_detected_time, last_observed_time)
            VALUES
                ('ICU_UTILIZATION', :department_id, 'CRITICAL', 'OPEN', 97.5, 90.0, 68.0, :t, :t)
        """),
        {"department_id": department["department_id"], "t": first_detected_time},
    )
    session.commit()
    incident_id = result.lastrowid

    print(f"\n✅ Created incident #{incident_id}: ICU_UTILIZATION at 97.5% in {department['name']}")
    print(f"   Backdated {ESCALATION_THRESHOLD_MINUTES + 5} minutes so it's already overdue for escalation.")

    # Generate a matching recommendation the normal way, so it goes through
    # the real LLM reasoning path if GROQ_API_KEY/ANTHROPIC_API_KEY is set —
    # this makes the demo show off the actual reasoning feature, not a stub.
    from agentcare.agents.recommendation_agent import RecommendationAgent

    incident = session.execute(
        text("""
            SELECT i.incident_id, i.kpi_name, i.department_id, d.name AS department_name,
                   i.severity, i.status, i.trigger_value, i.threshold_value, i.baseline_value
            FROM incidents i
            LEFT JOIN departments d ON d.department_id = i.department_id
            WHERE i.incident_id = :id
        """),
        {"id": incident_id},
    ).mappings().first()

    agent = RecommendationAgent(session)
    recommendation = agent.generate_recommendation(
        kpi_name=incident["kpi_name"],
        severity=incident["severity"],
        trigger_value=float(incident["trigger_value"]),
        threshold_value=float(incident["threshold_value"]),
        baseline_value=float(incident["baseline_value"]) if incident["baseline_value"] is not None else None,
        department_name=incident["department_name"],
    )
    agent.create_recommendation(
        incident=incident,
        recommendation_text=recommendation["text"],
        priority=recommendation["priority"],
        source=recommendation["source"],
        reasoning=recommendation["reasoning"],
        retrieved_policy=recommendation.get("retrieved_policy"),
        retrieval_score=recommendation.get("retrieval_score"),
    )

    print(f"\n✅ Recommendation created (source: {recommendation['source']}):")
    print(f"   {recommendation['text']}")
    if recommendation.get("retrieved_policy"):
        print(f"\n📚 Grounded in retrieved policy: {recommendation['retrieved_policy']} "
              f"(similarity score: {recommendation['retrieval_score']})")

    print("\n" + "=" * 70)
    print("NEXT STEPS FOR YOUR DEMO")
    print("=" * 70)
    print("1. Open the dashboard — the Incidents & AI tab now has this incident/recommendation.")
    print("2. Click '🚨 Check Escalations Now' on the Agents tab — the red banner,")
    print("   sound, and browser notification should fire immediately.")
    print("3. If SMTP is configured in .env, check your inbox for the urgent escalation email.")
    print("4. To reset: Acknowledge or Resolve the incident from the dashboard, or delete it")
    print("   directly with: DELETE FROM incidents WHERE incident_id = " + str(incident_id))
    print()


if __name__ == "__main__":
    main()
