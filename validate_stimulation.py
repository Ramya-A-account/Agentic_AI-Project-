from sqlalchemy import text
from agentcare.db import engine


def main():
    print("\n" + "=" * 75)
    print("AGENTCARE PHASE 1 - CORRECTED POSTGRESQL VALIDATION")
    print("=" * 75)

    with engine.connect() as conn:

        # =========================================================
        # BASIC COUNTS
        # =========================================================
        print("\n[1] DATASET COUNTS")

        tables = [
            "departments",
            "beds",
            "staff",
            "patients",
            "admissions",
            "emergency_events",
            "medicines",
            "inventory_transactions",
            "revenue_transactions",
        ]

        for table in tables:
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()

            print(f"{table:28} {count}")

        # =========================================================
        # CHECK 1 - BED OVERLAP
        # =========================================================
        print("\n[2] CHECK 1 - BED OVERLAP")

        overlaps = conn.execute(text("""
            SELECT
                a1.bed_id,
                a1.admission_id,
                a2.admission_id
            FROM admissions a1
            JOIN admissions a2
              ON a1.bed_id = a2.bed_id
             AND a1.admission_id < a2.admission_id
             AND a1.admission_time <
                 COALESCE(a2.discharge_time, '9999-12-31')
             AND a2.admission_time <
                 COALESCE(a1.discharge_time, '9999-12-31')
            WHERE a1.bed_id IS NOT NULL
              AND a2.bed_id IS NOT NULL
        """)).fetchall()

        print(f"Overlapping bed assignments: {len(overlaps)}")

        if overlaps:
            print("❌ FAIL")
        else:
            print("✅ PASS")

        # =========================================================
        # CHECK 2 - DISCHARGE TIME
        # =========================================================
        print("\n[3] CHECK 2 - DISCHARGE CONSISTENCY")

        discharge_errors = conn.execute(text("""
            SELECT admission_id
            FROM admissions
            WHERE status = 'DISCHARGED'
              AND discharge_time IS NULL
        """)).fetchall()

        print(f"Discharged without discharge_time: {len(discharge_errors)}")

        if discharge_errors:
            print("❌ FAIL")
        else:
            print("✅ PASS")

        # =========================================================
        # CHECK 3 - TIMELINE
        # =========================================================
        print("\n[4] CHECK 3 - TIMELINE")

        timeline_errors = conn.execute(text("""
            SELECT admission_id
            FROM admissions
            WHERE discharge_time IS NOT NULL
              AND discharge_time < admission_time
        """)).fetchall()

        print(f"Invalid timelines: {len(timeline_errors)}")

        if timeline_errors:
            print("❌ FAIL")
        else:
            print("✅ PASS")

        # =========================================================
        # CHECK 4 - CURRENT BED STATUS
        # =========================================================
        print("\n[5] CHECK 4 - CURRENT BED STATUS")

        status_errors = conn.execute(text("""
            SELECT
                b.bed_id,
                b.status,
                COUNT(a.admission_id) AS active_admissions
            FROM beds b
            LEFT JOIN admissions a
              ON a.bed_id = b.bed_id
             AND a.status = 'ADMITTED'
            GROUP BY b.bed_id, b.status
            HAVING
                (b.status = 'OCCUPIED'
                 AND COUNT(a.admission_id) = 0)
                OR
                (b.status = 'AVAILABLE'
                 AND COUNT(a.admission_id) > 0)
        """)).fetchall()

        print(f"Bed status mismatches: {len(status_errors)}")

        if status_errors:
            print("❌ FAIL")
        else:
            print("✅ PASS")

        # =========================================================
        # CHECK 5 - CURRENT OCCUPANCY
        # =========================================================
        print("\n[6] CHECK 5 - CURRENT OCCUPANCY")

        total_beds = conn.execute(
            text("SELECT COUNT(*) FROM beds")
        ).scalar()

        occupied_beds = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM beds
                WHERE status = 'OCCUPIED'
            """)
        ).scalar()

        active_bed_admissions = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM admissions
                WHERE status = 'ADMITTED'
                  AND bed_id IS NOT NULL
            """)
        ).scalar()

        occupancy_pct = occupied_beds / total_beds * 100

        print(f"Total beds: {total_beds}")
        print(f"Occupied beds: {occupied_beds}")
        print(f"Active admissions with beds: {active_bed_admissions}")
        print(f"Current occupancy: {occupancy_pct:.2f}%")

        if occupied_beds == active_bed_admissions:
            print("✅ PASS")
        else:
            print("❌ FAIL")

        # =========================================================
        # CHECK 6 - HISTORICAL OCCUPANCY
        # =========================================================
        print("\n[7] CHECK 6 - HISTORICAL BED CAPACITY")

        # We create 30-minute snapshots.
        # At each snapshot we count DISTINCT beds.
        #
        # This is important:
        # We are counting beds, NOT admissions.
        # Therefore a bed reused by 5 patients is still counted as 1 bed.

        historical = conn.execute(text("""
            WITH bounds AS (
                SELECT
                    date_trunc(
                        'hour',
                        MIN(admission_time)
                    ) AS start_time,
                    date_trunc(
                        'hour',
                        MAX(
                            COALESCE(
                                discharge_time,
                                admission_time
                            )
                        )
                    ) AS end_time
                FROM admissions
            ),
            snapshots AS (
                SELECT
                    generate_series(
                        start_time,
                        end_time,
                        INTERVAL '30 minutes'
                    ) AS snapshot_time
                FROM bounds
            )
            SELECT
                s.snapshot_time,
                COUNT(DISTINCT a.bed_id) AS occupied_beds
            FROM snapshots s
            LEFT JOIN admissions a
              ON a.bed_id IS NOT NULL
             AND a.admission_time <= s.snapshot_time
             AND COALESCE(
                    a.discharge_time,
                    '9999-12-31'
                 ) > s.snapshot_time
            GROUP BY s.snapshot_time
            ORDER BY s.snapshot_time
        """)).fetchall()

        values = [row.occupied_beds for row in historical]

        if values:
            minimum = min(values)
            maximum = max(values)
            average = sum(values) / len(values)

            print(f"Snapshots analysed: {len(values)}")
            print(f"Minimum occupied beds: {minimum}")
            print(f"Maximum occupied beds: {maximum}")
            print(f"Average occupied beds: {average:.2f}")
            print(f"Hospital capacity: {total_beds}")

            if maximum <= total_beds:
                print("✅ PASS")
            else:
                print("❌ FAIL")

        # =========================================================
        # CHECK 7 - DEPARTMENT CAPACITY
        # =========================================================
        print("\n[8] CHECK 7 - DEPARTMENT CAPACITY")

        department_history = conn.execute(text("""
            WITH bounds AS (
                SELECT
                    date_trunc(
                        'hour',
                        MIN(admission_time)
                    ) AS start_time,
                    date_trunc(
                        'hour',
                        MAX(
                            COALESCE(
                                discharge_time,
                                admission_time
                            )
                        )
                    ) AS end_time
                FROM admissions
            ),
            snapshots AS (
                SELECT
                    generate_series(
                        start_time,
                        end_time,
                        INTERVAL '30 minutes'
                    ) AS snapshot_time
                FROM bounds
            )
            SELECT
                s.snapshot_time,
                d.department_id,
                d.name,
                d.total_beds,
                COUNT(DISTINCT a.bed_id) AS occupied_beds
            FROM snapshots s
            CROSS JOIN departments d
            LEFT JOIN admissions a
              ON a.department_id = d.department_id
             AND a.bed_id IS NOT NULL
             AND a.admission_time <= s.snapshot_time
             AND COALESCE(
                    a.discharge_time,
                    '9999-12-31'
                 ) > s.snapshot_time
            GROUP BY
                s.snapshot_time,
                d.department_id,
                d.name,
                d.total_beds
            HAVING COUNT(DISTINCT a.bed_id) > d.total_beds
            ORDER BY s.snapshot_time
        """)).fetchall()

        print(
            f"Department capacity violations: "
            f"{len(department_history)}"
        )

        if department_history:
            print("❌ FAIL")

            for row in department_history[:10]:
                print(
                    f"{row.snapshot_time} | "
                    f"{row.name} | "
                    f"{row.occupied_beds}/{row.total_beds}"
                )
        else:
            print("✅ PASS")

        # =========================================================
        # CAPACITY PRESSURE
        # =========================================================
        print("\n[9] CAPACITY PRESSURE")

        unassigned = conn.execute(text("""
            SELECT COUNT(*)
            FROM admissions
            WHERE bed_id IS NULL
        """)).scalar()

        print(f"Admissions without a bed: {unassigned}")

        # =========================================================
        # FINAL
        # =========================================================
        print("\n" + "=" * 75)
        print("CORRECTED VALIDATION COMPLETE")
        print("=" * 75)


if __name__ == "__main__":
    main()