from sqlalchemy import text
from agentcare.db import get_session


session = get_session()

print("\n" + "=" * 70)
print("AGENTCARE RECOMMENDATION VERIFICATION")
print("=" * 70)

rows = session.execute(
    text("""
        SELECT
            r.recommendation_id,
            r.incident_id,
            r.text,
            r.status,
            r.priority,
            i.kpi_name,
            i.severity
        FROM recommendations r
        JOIN incidents i
            ON r.incident_id = i.incident_id
        ORDER BY r.recommendation_id
    """)
).mappings()

rows = list(rows)

print(f"\nTotal recommendations: {len(rows)}")

print("\nRECOMMENDATIONS")
print("-" * 70)

for row in rows:
    print(
        f"{row['recommendation_id']:>3} | "
        f"Incident={row['incident_id']} | "
        f"{row['kpi_name']:<30} | "
        f"{row['severity']:<8} | "
        f"Priority={row['priority']:<6} | "
        f"Status={row['status']}"
    )

    print(f"    {row['text']}")

print("\n" + "=" * 70)

if len(rows) >= 4:
    print("🎉 RECOMMENDATION VERIFICATION PASSED")
else:
    print("❌ RECOMMENDATION VERIFICATION FAILED")

print("=" * 70)

session.close()