from sqlalchemy import text
from agentcare.db import get_session


session = get_session()

print("\n" + "=" * 70)
print("AGENTCARE KPI RESULTS - POSTGRESQL VERIFICATION")
print("=" * 70)

rows = session.execute(
    text("""
        SELECT
            kpi_id,
            kpi_name,
            value,
            unit,
            department_id,
            data_quality_status
        FROM kpi_results
        ORDER BY kpi_id
    """)
).mappings()

rows = list(rows)

print(f"\nTotal KPI records: {len(rows)}")

print("\nKPI RESULTS")
print("-" * 70)

for row in rows:
    print(
        f"{row['kpi_id']:>3} | "
        f"{row['kpi_name']:<30} | "
        f"{row['value']} "
        f"{row['unit'] or ''} | "
        f"department={row['department_id']} | "
        f"{row['data_quality_status']}"
    )

print("\n" + "=" * 70)

hospital_kpis = [
    "BED_OCCUPANCY",
    "ICU_UTILIZATION",
    "ADMISSIONS",
    "DISCHARGES",
    "EMERGENCY_EVENTS",
    "REVENUE",
]

print("HOSPITAL KPI CHECK")
print("=" * 70)

for kpi in hospital_kpis:

    count = session.execute(
        text("""
            SELECT COUNT(*)
            FROM kpi_results
            WHERE kpi_name = :kpi_name
              AND department_id IS NULL
        """),
        {"kpi_name": kpi}
    ).scalar()

    if count > 0:
        print(f"✅ {kpi}")
    else:
        print(f"❌ {kpi}")

department_count = session.execute(
    text("""
        SELECT COUNT(*)
        FROM kpi_results
        WHERE kpi_name = 'DEPARTMENT_BED_OCCUPANCY'
    """)
).scalar()

print(
    f"\nDepartment occupancy KPI records: "
    f"{department_count}"
)

print("\n" + "=" * 70)

if (
    len(rows) >= 14
    and department_count == 8
):
    print("🎉 KPI VERIFICATION PASSED")
else:
    print("❌ KPI VERIFICATION FAILED")

print("=" * 70)

session.close()