from sqlalchemy import text
from agentcare.db import get_session


session = get_session()

print("\n" + "=" * 70)
print("AGENTCARE INCIDENT VERIFICATION")
print("=" * 70)

rows = session.execute(
    text("""
        SELECT
            i.incident_id,
            i.kpi_name,
            i.department_id,
            d.name AS department_name,
            i.severity,
            i.status,
            i.trigger_value,
            i.threshold_value
        FROM incidents i
        LEFT JOIN departments d
            ON i.department_id = d.department_id
        ORDER BY i.incident_id
    """)
).mappings()

rows = list(rows)

print(f"\nTotal incidents: {len(rows)}")

print("\nINCIDENTS")
print("-" * 70)

for row in rows:
    department = row["department_name"] or "HOSPITAL"

    print(
        f"{row['incident_id']:>3} | "
        f"{department:<20} | "
        f"{row['kpi_name']:<30} | "
        f"{row['severity']:<8} | "
        f"{row['status']:<12} | "
        f"value={row['trigger_value']} | "
        f"threshold={row['threshold_value']}"
    )

print("\n" + "=" * 70)

if len(rows) >= 4:
    print("🎉 INCIDENT VERIFICATION PASSED")
else:
    print("❌ INCIDENT VERIFICATION FAILED")

print("=" * 70)

session.close()