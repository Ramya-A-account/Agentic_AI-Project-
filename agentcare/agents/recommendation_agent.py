"""
AgentCare Recommendation Agent

Reads OPEN incidents from the database and generates operational
recommendations for hospital managers.

For each incident, this agent:
  1. Retrieves the most relevant hospital SOP/policy document from the
     knowledge base (RAG) — grounding the recommendation in an actual
     written procedure rather than free-floating reasoning.
  2. Asks an LLM to reason about the specific situation using that
     retrieved policy as context, and produce a tailored recommendation
     and priority.
If no ANTHROPIC_API_KEY/GROQ_API_KEY is configured, or the LLM call
fails for any reason, it falls back to deterministic, rule-based logic —
the system always produces a recommendation, it just isn't always
reasoned about or grounded in policy.

Every recommendation's supporting_evidence records which path produced
it ("LLM" or "RULE_BASED") and which policy document (if any) was
retrieved to ground it, so the reasoning is fully auditable.
"""

from datetime import datetime

from sqlalchemy import text

from agentcare.agents import llm_reasoning, rag_retriever
from agentcare.db import get_session


def utcnow():
    return datetime.utcnow()


RECOMMENDATION_SYSTEM_PROMPT = """You are an operations reasoning assistant embedded in a \
hospital monitoring system called AgentCare AI. You are given one operational incident \
(a KPI that breached a threshold) and must reason about it like an experienced hospital \
operations manager would, then produce a specific, actionable recommendation.

You may also be given an excerpt from the hospital's actual operational policy/SOP
document relevant to this type of incident. When policy context is provided, ground your
recommendation in it — reference the specific steps it prescribes rather than inventing
generic advice, and prioritize actions from the policy's own step order. If no policy
context is provided, or it isn't actually relevant to this incident, reason from general
hospital operations expertise instead.

Guidelines:
- Be specific to the numbers given (the trigger value, threshold, and how far over it is).
- Recommend concrete next steps a manager could actually take today, not generic advice.
- Keep the recommendation to 1-3 sentences.
- Choose a priority of HIGH, MEDIUM, or LOW based on how severe and time-sensitive the \
situation is — don't just mirror the incident's severity label; use your judgment about \
patient-safety and capacity risk.
- Respond with ONLY a JSON object, no other text: \
{"text": "<the recommendation>", "priority": "HIGH|MEDIUM|LOW", "reasoning": "<one sentence on why>"}
"""


class RecommendationAgent:

    def __init__(self, session):
        self.session = session

    # ------------------------------------------------------------
    # RAG — retrieve grounding policy for this incident type
    # ------------------------------------------------------------

    def _retrieve_policy(self, kpi_name, severity):
        # Deliberately excludes department name from the query — department
        # names (e.g. "General Surgery") can accidentally collide with
        # unrelated policy vocabulary (e.g. "General Incident Response").
        # KPI name + severity is what actually determines which SOP applies.
        query = f"{kpi_name} {severity} incident hospital operations capacity"
        results = rag_retriever.retrieve(query, top_k=1, min_score=0.08)
        return results[0] if results else None

    # ------------------------------------------------------------
    # LLM-based reasoning path
    # ------------------------------------------------------------

    def _generate_recommendation_llm(
        self,
        kpi_name,
        severity,
        trigger_value,
        threshold_value,
        baseline_value,
        department_name=None,
    ):
        policy = self._retrieve_policy(kpi_name, severity)

        policy_context = ""
        if policy:
            policy_context = (
                f"\nRelevant hospital policy — \"{policy['title']}\":\n"
                f"{policy['text']}\n"
            )

        user_prompt = (
            f"Incident details:\n"
            f"- KPI: {kpi_name}\n"
            f"- Department: {department_name or 'Hospital-wide'}\n"
            f"- Severity flagged by monitoring: {severity}\n"
            f"- Trigger value: {trigger_value}\n"
            f"- Threshold: {threshold_value}\n"
            f"- Baseline (normal) value: {baseline_value}\n"
            f"{policy_context}\n"
            f"Reason about this incident and produce your recommendation."
        )

        result = llm_reasoning.reason(RECOMMENDATION_SYSTEM_PROMPT, user_prompt)

        if not result or "text" not in result or "priority" not in result:
            return None

        priority = str(result["priority"]).upper()
        if priority not in ("HIGH", "MEDIUM", "LOW"):
            priority = "MEDIUM"

        return {
            "text": result["text"],
            "priority": priority,
            "reasoning": result.get("reasoning", ""),
            "source": "LLM",
            "retrieved_policy": policy["title"] if policy else None,
            "retrieval_score": round(policy["score"], 3) if policy else None,
        }

    # ------------------------------------------------------------
    # Deterministic fallback rules
    # ------------------------------------------------------------

    def _generate_recommendation_rule_based(
        self,
        kpi_name,
        severity,
        trigger_value,
        department_name=None,
    ):

        # --------------------------------------------------------
        # Department bed occupancy
        # --------------------------------------------------------

        if kpi_name == "DEPARTMENT_BED_OCCUPANCY":

            if severity == "CRITICAL":

                text_value = (
                    f"{department_name} is operating at "
                    f"{trigger_value:.2f}% bed occupancy. "
                    "Immediately review pending discharges, "
                    "identify clinically appropriate transfer "
                    "opportunities, and assess available capacity "
                    "in other departments."
                )

                priority = "HIGH"

            else:

                text_value = (
                    f"{department_name} has reached "
                    f"{trigger_value:.2f}% bed occupancy. "
                    "Monitor admissions and discharges closely "
                    "and prepare temporary capacity reallocation "
                    "if occupancy continues to increase."
                )

                priority = "MEDIUM"

            return text_value, priority

        # --------------------------------------------------------
        # Emergency events
        # --------------------------------------------------------

        if kpi_name == "EMERGENCY_EVENTS":

            if severity == "CRITICAL":

                text_value = (
                    f"Emergency activity has reached "
                    f"{trigger_value:.0f} events for the analysis "
                    "period. Review emergency staffing levels, "
                    "available inpatient beds, patient flow, and "
                    "capacity for additional emergency arrivals."
                )

                priority = "HIGH"

            else:

                text_value = (
                    f"Emergency activity is elevated at "
                    f"{trigger_value:.0f} events. Monitor emergency "
                    "volume and prepare additional operational "
                    "capacity if the trend continues."
                )

                priority = "MEDIUM"

            return text_value, priority

        # --------------------------------------------------------
        # Hospital bed occupancy
        # --------------------------------------------------------

        if kpi_name == "BED_OCCUPANCY":

            if severity == "CRITICAL":

                text_value = (
                    f"Hospital-wide bed occupancy has reached "
                    f"{trigger_value:.2f}%. Review discharge planning, "
                    "bed turnover, and inter-department capacity "
                    "reallocation immediately."
                )

                priority = "HIGH"

            else:

                text_value = (
                    f"Hospital-wide bed occupancy is elevated at "
                    f"{trigger_value:.2f}%. Monitor capacity and "
                    "discharge flow closely."
                )

                priority = "MEDIUM"

            return text_value, priority

        # --------------------------------------------------------
        # ICU utilization
        # --------------------------------------------------------

        if kpi_name == "ICU_UTILIZATION":

            if severity == "CRITICAL":

                text_value = (
                    f"ICU utilization has reached "
                    f"{trigger_value:.2f}%. Review ICU capacity, "
                    "patient transfers, discharge readiness, and "
                    "availability of critical-care resources."
                )

                priority = "HIGH"

            else:

                text_value = (
                    f"ICU utilization is elevated at "
                    f"{trigger_value:.2f}%. Closely monitor ICU "
                    "admissions, discharges, and available beds."
                )

                priority = "MEDIUM"

            return text_value, priority

        # --------------------------------------------------------
        # Generic fallback
        # --------------------------------------------------------

        text_value = (
            f"The KPI {kpi_name} has reached "
            f"{trigger_value:.2f} and requires operational review."
        )

        priority = "MEDIUM"

        return text_value, priority

    # ------------------------------------------------------------
    # Dispatcher — try LLM reasoning first, fall back to rules
    # ------------------------------------------------------------

    def generate_recommendation(
        self,
        kpi_name,
        severity,
        trigger_value,
        threshold_value=None,
        baseline_value=None,
        department_name=None,
    ):
        llm_result = self._generate_recommendation_llm(
            kpi_name=kpi_name,
            severity=severity,
            trigger_value=trigger_value,
            threshold_value=threshold_value,
            baseline_value=baseline_value,
            department_name=department_name,
        )

        if llm_result is not None:
            return llm_result

        text_value, priority = self._generate_recommendation_rule_based(
            kpi_name=kpi_name,
            severity=severity,
            trigger_value=trigger_value,
            department_name=department_name,
        )

        return {
            "text": text_value,
            "priority": priority,
            "reasoning": "",
            "source": "RULE_BASED",
            "retrieved_policy": None,
            "retrieval_score": None,
        }

    # ------------------------------------------------------------
    # Check for existing recommendation
    # ------------------------------------------------------------

    def recommendation_exists(self, incident_id):

        count = self.session.execute(
            text("""
                SELECT COUNT(*)
                FROM recommendations
                WHERE incident_id = :incident_id
                  AND status IN ('OPEN', 'ACTIVE', 'PENDING')
            """),
            {
                "incident_id": incident_id
            },
        ).scalar()

        return count > 0

    # ------------------------------------------------------------
    # Create recommendation
    # ------------------------------------------------------------

    def create_recommendation(
        self,
        incident,
        recommendation_text,
        priority,
        source="RULE_BASED",
        reasoning="",
        retrieved_policy=None,
        retrieval_score=None,
    ):

        evidence = {
            "kpi_name": incident["kpi_name"],
            "trigger_value": float(incident["trigger_value"]),
            "threshold_value": float(incident["threshold_value"]),
            "severity": incident["severity"],
            "department_id": incident["department_id"],
            "department_name": incident["department_name"],
            "source": source,                       # "LLM" or "RULE_BASED" — audit trail
            "reasoning": reasoning,                  # LLM's stated reasoning, if applicable
            "retrieved_policy": retrieved_policy,    # RAG: which SOP document grounded this, if any
            "retrieval_score": retrieval_score,      # RAG: TF-IDF cosine similarity score
        }

        self.session.execute(
            text("""
                INSERT INTO recommendations
                (
                    incident_id,
                    text,
                    supporting_evidence,
                    status,
                    priority,
                    generated_time
                )
                VALUES
                (
                    :incident_id,
                    :text,
                    :supporting_evidence,
                    'PENDING',
                    :priority,
                    :generated_time
                )
            """),
            {
                "incident_id": incident["incident_id"],
                "text": recommendation_text,
                "supporting_evidence": __import__("json").dumps(evidence),
                "priority": priority,
                "generated_time": utcnow(),
            },
        )

    # ------------------------------------------------------------
    # Main
    # ------------------------------------------------------------

    def run(self):

        print("\n" + "=" * 70)
        print("AGENTCARE RECOMMENDATION AGENT")
        print("=" * 70)

        try:

            # ----------------------------------------------------
            # Get currently open incidents
            # ----------------------------------------------------

            incidents = self.session.execute(
                text("""
                    SELECT
                        i.incident_id,
                        i.kpi_name,
                        i.department_id,
                        d.name AS department_name,
                        i.severity,
                        i.status,
                        i.trigger_value,
                        i.threshold_value,
                        i.baseline_value
                    FROM incidents i
                    LEFT JOIN departments d
                        ON i.department_id = d.department_id
                    WHERE i.status = 'OPEN'
                    ORDER BY i.incident_id
                """)
            ).mappings()

            incidents = list(incidents)

            if not incidents:

                print("\nNo OPEN incidents found.")

                return {
                    "status": "SUCCESS",
                    "incidents_found": 0,
                    "created": 0,
                    "existing": 0,
                }

            print(f"\nOpen incidents found: {len(incidents)}")

            created = 0
            existing = 0

            # ----------------------------------------------------
            # Process each incident
            # ----------------------------------------------------

            print("\nRECOMMENDATIONS")
            print("-" * 70)

            for incident in incidents:

                if self.recommendation_exists(
                    incident["incident_id"]
                ):

                    existing += 1

                    print(
                        f"↪ EXISTING | "
                        f"Incident {incident['incident_id']} | "
                        f"{incident['kpi_name']}"
                    )

                    continue

                recommendation = self.generate_recommendation(
                    kpi_name=incident["kpi_name"],
                    severity=incident["severity"],
                    trigger_value=float(incident["trigger_value"]),
                    threshold_value=float(incident["threshold_value"]),
                    baseline_value=float(incident["baseline_value"])
                        if incident["baseline_value"] is not None else None,
                    department_name=incident["department_name"],
                )

                recommendation_text = recommendation["text"]
                priority = recommendation["priority"]

                self.create_recommendation(
                    incident=incident,
                    recommendation_text=recommendation_text,
                    priority=priority,
                    source=recommendation["source"],
                    reasoning=recommendation["reasoning"],
                    retrieved_policy=recommendation.get("retrieved_policy"),
                    retrieval_score=recommendation.get("retrieval_score"),
                )

                created += 1

                department = (
                    incident["department_name"]
                    or "HOSPITAL"
                )

                print(
                    f"🚨 Incident {incident['incident_id']} | "
                    f"{department} | "
                    f"{incident['severity']} | "
                    f"Priority={priority} | "
                    f"Source={recommendation['source']}"
                )

                print(
                    f"   → {recommendation_text}"
                )

            self.session.commit()

            # ----------------------------------------------------
            # Summary
            # ----------------------------------------------------

            print("\n" + "=" * 70)
            print("RECOMMENDATION SUMMARY")
            print("=" * 70)

            print(
                f"Open incidents      : {len(incidents)}"
            )

            print(
                f"New recommendations : {created}"
            )

            print(
                f"Existing            : {existing}"
            )

            print("\n" + "=" * 70)
            print("✅ RECOMMENDATION AGENT COMPLETE")
            print("=" * 70)

            return {
                "status": "SUCCESS",
                "incidents_found": len(incidents),
                "created": created,
                "existing": existing,
            }

        except Exception as exc:

            self.session.rollback()

            print("\n❌ RECOMMENDATION AGENT FAILED")
            print(exc)

            return {
                "status": "FAILED",
                "error": str(exc),
            }


# ================================================================
# MANUAL ENTRY POINT
# ================================================================

if __name__ == "__main__":

    session = get_session()

    try:

        agent = RecommendationAgent(session)
        agent.run()

    finally:

        session.close()