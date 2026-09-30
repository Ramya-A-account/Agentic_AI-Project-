"""
AgentCare Alert Detection Agent

Reads KPI results from PostgreSQL and detects operational incidents
when KPIs cross defined thresholds.

The agent writes detected incidents to the incidents table.

It does NOT modify simulation or operational source data.
"""

from datetime import datetime

from sqlalchemy import text

from agentcare.db import get_session


def utcnow():
    return datetime.utcnow()


class AlertDetectionAgent:

    # ------------------------------------------------------------
    # ALERT THRESHOLDS
    # ------------------------------------------------------------

    THRESHOLDS = {
        "BED_OCCUPANCY": {
            "warning": 80.0,
            "critical": 90.0,
        },

        "ICU_UTILIZATION": {
            "warning": 80.0,
            "critical": 90.0,
        },

        "DEPARTMENT_BED_OCCUPANCY": {
            "warning": 85.0,
            "critical": 95.0,
        },

        "EMERGENCY_EVENTS": {
            "warning": 60,
            "critical": 100,
        },
    }

    def __init__(self, session):
        self.session = session

    # ------------------------------------------------------------
    # Determine severity
    # ------------------------------------------------------------

    def determine_severity(self, kpi_name, value):

        threshold = self.THRESHOLDS.get(kpi_name)

        if threshold is None:
            return None

        if value >= threshold["critical"]:
            return "CRITICAL"

        if value >= threshold["warning"]:
            return "WARNING"

        return None

    # ------------------------------------------------------------
    # Get department name
    # ------------------------------------------------------------

    def get_department_name(self, department_id):

        if department_id is None:
            return None

        return self.session.execute(
            text("""
                SELECT name
                FROM departments
                WHERE department_id = :department_id
            """),
            {"department_id": department_id},
        ).scalar()

    # ------------------------------------------------------------
    # Check whether identical active incident already exists
    # ------------------------------------------------------------

    def incident_exists(
        self,
        kpi_name,
        department_id,
        severity,
    ):

        count = self.session.execute(
            text("""
                SELECT COUNT(*)
                FROM incidents
                WHERE kpi_name = :kpi_name
                  AND (
                      department_id = :department_id
                      OR (
                          department_id IS NULL
                          AND :department_id IS NULL
                      )
                  )
                  AND severity = :severity
                  AND status IN ('OPEN', 'ACKNOWLEDGED')
            """),
            {
                "kpi_name": kpi_name,
                "department_id": department_id,
                "severity": severity,
            },
        ).scalar()

        return count > 0

    # ------------------------------------------------------------
    # Create incident
    # ------------------------------------------------------------

    def create_incident(
        self,
        kpi_name,
        department_id,
        severity,
        trigger_value,
        threshold_value,
        baseline_value,
        detection_time,
    ):

        self.session.execute(
            text("""
                INSERT INTO incidents
                (
                    kpi_name,
                    department_id,
                    severity,
                    status,
                    trigger_value,
                    threshold_value,
                    baseline_value,
                    first_detected_time,
                    last_observed_time,
                    notification_status
                )
                VALUES
                (
                    :kpi_name,
                    :department_id,
                    :severity,
                    'OPEN',
                    :trigger_value,
                    :threshold_value,
                    :baseline_value,
                    :first_detected_time,
                    :last_observed_time,
                    'PENDING'
                )
            """),
            {
                "kpi_name": kpi_name,
                "department_id": department_id,
                "severity": severity,
                "trigger_value": trigger_value,
                "threshold_value": threshold_value,
                "baseline_value": baseline_value,
                "first_detected_time": detection_time,
                "last_observed_time": detection_time,
            },
        )

    # ------------------------------------------------------------
    # Process KPI
    # ------------------------------------------------------------

    def process_kpi(self, kpi):

        kpi_name = kpi["kpi_name"]
        value = float(kpi["value"])
        department_id = kpi["department_id"]

        severity = self.determine_severity(
            kpi_name,
            value,
        )

        if severity is None:
            return None

        threshold = self.THRESHOLDS[kpi_name]

        if severity == "CRITICAL":
            threshold_value = threshold["critical"]
        else:
            threshold_value = threshold["warning"]

        if self.incident_exists(
            kpi_name,
            department_id,
            severity,
        ):
            return {
                "status": "EXISTING",
                "kpi_name": kpi_name,
                "department_id": department_id,
                "severity": severity,
            }

        detection_time = utcnow()

        self.create_incident(
            kpi_name=kpi_name,
            department_id=department_id,
            severity=severity,
            trigger_value=value,
            threshold_value=threshold_value,
            baseline_value=None,
            detection_time=detection_time,
        )

        return {
            "status": "CREATED",
            "kpi_name": kpi_name,
            "department_id": department_id,
            "severity": severity,
            "value": value,
        }

    # ------------------------------------------------------------
    # Main
    # ------------------------------------------------------------

    def run(self):

        print("\n" + "=" * 70)
        print("AGENTCARE ALERT DETECTION AGENT")
        print("=" * 70)

        try:

            # ----------------------------------------------------
            # Get most recent KPI calculation
            # ----------------------------------------------------
            # NOTE: the original query used Postgres-only "SELECT DISTINCT ON",
            # which raises a syntax error on SQLite. ROW_NUMBER() OVER (...)
            # produces the same "latest row per (kpi_name, department_id)"
            # result and is supported by both SQLite (3.25+) and Postgres.

            rows = self.session.execute(
                text("""
                    SELECT
                        kpi_id,
                        kpi_name,
                        value,
                        unit,
                        department_id,
                        period_start,
                        period_end,
                        calculation_time
                    FROM (
                        SELECT
                            kpi_id,
                            kpi_name,
                            value,
                            unit,
                            department_id,
                            period_start,
                            period_end,
                            calculation_time,
                            ROW_NUMBER() OVER (
                                PARTITION BY kpi_name, department_id
                                ORDER BY calculation_time DESC, kpi_id DESC
                            ) AS row_num
                        FROM kpi_results
                    ) ranked
                    WHERE row_num = 1
                """)
            ).mappings()

            kpis = list(rows)

            if not kpis:
                print("\n❌ No KPI results found.")
                return {
                    "status": "FAILED",
                    "error": "No KPI results available",
                }

            print(f"\nKPIs analysed: {len(kpis)}")

            created = 0
            existing = 0
            normal = 0

            print("\nALERT EVALUATION")
            print("-" * 70)

            for kpi in kpis:

                result = self.process_kpi(kpi)

                if result is None:

                    normal += 1

                    if kpi["department_id"] is not None:
                        department_name = self.get_department_name(
                            kpi["department_id"]
                        )

                        label = (
                            f"{department_name} - "
                            f"{kpi['kpi_name']}"
                        )
                    else:
                        label = kpi["kpi_name"]

                    print(
                        f"✅ NORMAL   "
                        f"{label:<40}"
                        f"{float(kpi['value']):.2f}"
                    )

                elif result["status"] == "EXISTING":

                    existing += 1

                    print(
                        f"↪ EXISTING  "
                        f"{kpi['kpi_name']:<35}"
                        f"{result['severity']}"
                    )

                elif result["status"] == "CREATED":

                    created += 1

                    if result["department_id"] is not None:
                        department_name = self.get_department_name(
                            result["department_id"]
                        )

                        label = (
                            f"{department_name} - "
                            f"{result['kpi_name']}"
                        )
                    else:
                        label = result["kpi_name"]

                    print(
                        f"🚨 {result['severity']:<8}"
                        f"{label:<35}"
                        f"{result['value']:.2f}"
                    )

            self.session.commit()

            # ----------------------------------------------------
            # Summary
            # ----------------------------------------------------

            print("\n" + "=" * 70)
            print("ALERT SUMMARY")
            print("=" * 70)

            print(f"KPIs analysed      : {len(kpis)}")
            print(f"Normal KPIs        : {normal}")
            print(f"New incidents      : {created}")
            print(f"Existing incidents : {existing}")

            print("\n" + "=" * 70)
            print("✅ ALERT DETECTION COMPLETE")
            print("=" * 70)

            return {
                "status": "SUCCESS",
                "kpis_analysed": len(kpis),
                "normal": normal,
                "created": created,
                "existing": existing,
            }

        except Exception as exc:

            self.session.rollback()

            print("\n❌ ALERT DETECTION FAILED")
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

        agent = AlertDetectionAgent(session)
        agent.run()

    finally:

        session.close()