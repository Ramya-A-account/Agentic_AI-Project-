"""
AgentCare AI - Analysis Agent

Reads validated operational data from PostgreSQL and calculates
hospital-level and department-level KPIs.

Historical mode:
    Calculates the latest available 30-day historical period.

Live monitoring mode:
    Calculates KPIs only for the exact monitoring window supplied
    by the Orchestrator.

Results are written to the kpi_results table.

This agent does NOT modify simulation or operational source data.
"""

from datetime import datetime, timedelta

from sqlalchemy import text

from agentcare.db import get_session


def utcnow():
    return datetime.utcnow()


class AnalysisAgent:

    def __init__(self, session):
        self.session = session

    # ============================================================
    # SAVE KPI
    # ============================================================

    def save_kpi(
        self,
        kpi_name,
        value,
        unit,
        period_start,
        period_end,
        department_id=None,
    ):

        self.session.execute(
            text("""
                INSERT INTO kpi_results
                (
                    kpi_name,
                    value,
                    unit,
                    department_id,
                    period_start,
                    period_end,
                    calculation_time,
                    data_quality_status
                )
                VALUES
                (
                    :kpi_name,
                    :value,
                    :unit,
                    :department_id,
                    :period_start,
                    :period_end,
                    :calculation_time,
                    :data_quality_status
                )
            """),
            {
                "kpi_name": kpi_name,
                "value": value,
                "unit": unit,
                "department_id": department_id,
                "period_start": period_start,
                "period_end": period_end,
                "calculation_time": utcnow(),
                "data_quality_status": "VALID",
            },
        )

    # ============================================================
    # HOSPITAL BED OCCUPANCY
    # ============================================================

    def calculate_occupancy(
        self,
        period_start,
        period_end,
    ):
        """
        Calculate current hospital-wide bed occupancy.

        Occupancy is based on the current bed status rather than
        raw admission counts.
        """

        total_beds = self.session.execute(
            text("""
                SELECT COUNT(*)
                FROM beds
                WHERE status != 'MAINTENANCE'
            """)
        ).scalar()

        occupied_beds = self.session.execute(
            text("""
                SELECT COUNT(*)
                FROM beds
                WHERE status = 'OCCUPIED'
            """)
        ).scalar()

        if total_beds == 0:
            return 0

        return (
            occupied_beds / total_beds
        ) * 100

    # ============================================================
    # ICU UTILIZATION
    # ============================================================

    def calculate_icu_utilization(self):

        total_icu = self.session.execute(
            text("""
                SELECT COUNT(*)
                FROM beds
                WHERE bed_type = 'ICU'
            """)
        ).scalar()

        occupied_icu = self.session.execute(
            text("""
                SELECT COUNT(*)
                FROM beds
                WHERE bed_type = 'ICU'
                  AND status = 'OCCUPIED'
            """)
        ).scalar()

        if total_icu == 0:
            return 0

        return (
            occupied_icu / total_icu
        ) * 100

    # ============================================================
    # ADMISSIONS
    # ============================================================

    def calculate_admissions(
        self,
        period_start,
        period_end,
    ):

        return self.session.execute(
            text("""
                SELECT COUNT(*)
                FROM admissions
                WHERE admission_time >= :start_time
                  AND admission_time < :end_time
            """),
            {
                "start_time": period_start,
                "end_time": period_end,
            },
        ).scalar()

    # ============================================================
    # DISCHARGES
    # ============================================================

    def calculate_discharges(
        self,
        period_start,
        period_end,
    ):

        return self.session.execute(
            text("""
                SELECT COUNT(*)
                FROM admissions
                WHERE discharge_time IS NOT NULL
                  AND discharge_time >= :start_time
                  AND discharge_time < :end_time
            """),
            {
                "start_time": period_start,
                "end_time": period_end,
            },
        ).scalar()

    # ============================================================
    # EMERGENCY EVENTS
    # ============================================================

    def calculate_emergency_events(
        self,
        period_start,
        period_end,
    ):

        return self.session.execute(
            text("""
                SELECT COUNT(*)
                FROM emergency_events
                WHERE event_time >= :start_time
                  AND event_time < :end_time
            """),
            {
                "start_time": period_start,
                "end_time": period_end,
            },
        ).scalar()

    # ============================================================
    # REVENUE
    # ============================================================

    def calculate_revenue(
        self,
        period_start,
        period_end,
    ):

        result = self.session.execute(
            text("""
                SELECT COALESCE(SUM(amount), 0)
                FROM revenue_transactions
                WHERE transaction_time >= :start_time
                  AND transaction_time < :end_time
            """),
            {
                "start_time": period_start,
                "end_time": period_end,
            },
        ).scalar()

        return float(result or 0)

    # ============================================================
    # DEPARTMENT OCCUPANCY
    # ============================================================

    def calculate_department_occupancy(self):

        rows = self.session.execute(
            text("""
                SELECT
                    d.department_id,
                    d.name,
                    d.total_beds,
                    COUNT(
                        CASE
                            WHEN b.status = 'OCCUPIED'
                            THEN 1
                        END
                    ) AS occupied_beds
                FROM departments d
                LEFT JOIN beds b
                    ON d.department_id = b.department_id
                GROUP BY
                    d.department_id,
                    d.name,
                    d.total_beds
                ORDER BY d.department_id
            """)
        ).mappings()

        return list(rows)

    # ============================================================
    # MAIN ANALYSIS
    # ============================================================

    def run(
        self,
        period_start=None,
        period_end=None,
    ):
        """
        Run KPI analysis.

        If period_start and period_end are supplied:
            Use that exact monitoring window.

        If they are not supplied:
            Fall back to the latest available 30-day historical
            analysis period. This keeps manual execution possible.
        """

        print("\n" + "=" * 70)
        print("AGENTCARE ANALYSIS AGENT")
        print("=" * 70)

        # ========================================================
        # DETERMINE ANALYSIS WINDOW
        # ========================================================

        if period_start is None or period_end is None:

            # ----------------------------------------------------
            # Historical/manual fallback
            # ----------------------------------------------------

            latest_time = self.session.execute(
                text("""
                    SELECT MAX(admission_time)
                    FROM admissions
                """)
            ).scalar()

            if latest_time is None:

                print("\n❌ No admission data available.")

                return {
                    "status": "FAILED",
                    "error": "No admission data available",
                }

            period_end = latest_time
            period_start = (
                period_end - timedelta(days=30)
            )

            print("\nHISTORICAL ANALYSIS WINDOW:")

        else:

            # ----------------------------------------------------
            # Live monitoring window
            # ----------------------------------------------------

            print("\nLIVE MONITORING ANALYSIS WINDOW:")

        print(
            f"  {period_start}"
            f"\n  -> {period_end}"
        )

        # ========================================================
        # VALIDATE WINDOW
        # ========================================================

        if period_start >= period_end:

            print(
                "\n❌ Invalid analysis window:"
                " period_start must be before period_end."
            )

            return {
                "status": "FAILED",
                "error": (
                    "Invalid analysis window: "
                    "period_start must be before period_end"
                ),
            }

        try:

            # ====================================================
            # HOSPITAL KPIs
            # ====================================================

            occupancy = self.calculate_occupancy(
                period_start,
                period_end,
            )

            icu_utilization = (
                self.calculate_icu_utilization()
            )

            admissions = self.calculate_admissions(
                period_start,
                period_end,
            )

            discharges = self.calculate_discharges(
                period_start,
                period_end,
            )

            emergency_events = (
                self.calculate_emergency_events(
                    period_start,
                    period_end,
                )
            )

            revenue = self.calculate_revenue(
                period_start,
                period_end,
            )

            # ====================================================
            # SAVE HOSPITAL KPIs
            # ====================================================

            self.save_kpi(
                "BED_OCCUPANCY",
                occupancy,
                "%",
                period_start,
                period_end,
            )

            self.save_kpi(
                "ICU_UTILIZATION",
                icu_utilization,
                "%",
                period_start,
                period_end,
            )

            self.save_kpi(
                "ADMISSIONS",
                admissions,
                "COUNT",
                period_start,
                period_end,
            )

            self.save_kpi(
                "DISCHARGES",
                discharges,
                "COUNT",
                period_start,
                period_end,
            )

            self.save_kpi(
                "EMERGENCY_EVENTS",
                emergency_events,
                "COUNT",
                period_start,
                period_end,
            )

            self.save_kpi(
                "REVENUE",
                revenue,
                "CURRENCY",
                period_start,
                period_end,
            )

            # ====================================================
            # DEPARTMENT KPIs
            # ====================================================

            departments = (
                self.calculate_department_occupancy()
            )

            for department in departments:

                total_beds = department["total_beds"]
                occupied = department["occupied_beds"]

                if total_beds == 0:

                    occupancy_pct = 0

                else:

                    occupancy_pct = (
                        occupied / total_beds
                    ) * 100

                self.save_kpi(
                    "DEPARTMENT_BED_OCCUPANCY",
                    occupancy_pct,
                    "%",
                    period_start,
                    period_end,
                    department["department_id"],
                )

            # ====================================================
            # COMMIT
            # ====================================================

            self.session.commit()

            # ====================================================
            # PRINT SUMMARY
            # ====================================================

            print("\n" + "=" * 70)
            print("ANALYSIS SUMMARY")
            print("=" * 70)

            print(
                f"BED_OCCUPANCY        : "
                f"{occupancy:.2f}%"
            )

            print(
                f"ICU_UTILIZATION      : "
                f"{icu_utilization:.2f}%"
            )

            print(
                f"ADMISSIONS           : "
                f"{admissions}"
            )

            print(
                f"DISCHARGES           : "
                f"{discharges}"
            )

            print(
                f"EMERGENCY_EVENTS     : "
                f"{emergency_events}"
            )

            print(
                f"REVENUE              : "
                f"{revenue:.2f}"
            )

            print("\nDEPARTMENT OCCUPANCY")

            for department in departments:

                total = department["total_beds"]
                occupied = department["occupied_beds"]

                if total:

                    percentage = (
                        occupied / total
                    ) * 100

                else:

                    percentage = 0

                print(
                    f"{department['name']:<25}"
                    f"{occupied}/{total} "
                    f"({percentage:.2f}%)"
                )

            print("\n" + "=" * 70)
            print("✅ ANALYSIS COMPLETE")
            print("=" * 70)

            return {
                "status": "SUCCESS",
                "period_start": period_start,
                "period_end": period_end,
                "occupancy": occupancy,
                "icu_utilization": icu_utilization,
                "admissions": admissions,
                "discharges": discharges,
                "emergency_events": emergency_events,
                "revenue": revenue,
                "department_count": len(departments),
            }

        except Exception as exc:

            self.session.rollback()

            print("\n❌ ANALYSIS FAILED")
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

        agent = AnalysisAgent(session)
        agent.run()

    finally:

        session.close()
