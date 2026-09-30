from sqlalchemy import text
from agentcare.db import get_session


session = get_session()

print("\n" + "=" * 70)
print("QUARANTINED RECORDS")
print("=" * 70)

rows = session.execute(
    text("""
        SELECT
            id,
            source_table,
            reason
        FROM quarantined_records
        ORDER BY id DESC
        LIMIT 10
    """)
).mappings()

for row in rows:
    print(dict(row))


print("\n" + "=" * 70)
print("DATA QUALITY RECORDS")
print("=" * 70)

rows = session.execute(
    text("""
        SELECT
            record_id,
            source_table,
            total_records,
            valid_records,
            invalid_records,
            quarantined_records
        FROM data_quality_records
        ORDER BY record_id DESC
        LIMIT 15
    """)
).mappings()

for row in rows:
    print(dict(row))


session.close()