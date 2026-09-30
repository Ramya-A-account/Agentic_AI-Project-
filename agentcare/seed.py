"""
One-time seed: creates the fixed 8-department, 300-bed (30 ICU) hospital
structure, a staff roster, and the medicine catalog. Safe to run once;
re-running will raise a uniqueness error rather than duplicate rows.
"""
from sqlalchemy import select

from agentcare.db import get_session, init_db
from agentcare.models import Department, Bed, Staff, Medicine
from agentcare.config import (
    DEPARTMENTS, STAFF_PER_DEPARTMENT, STAFF_ROLES, STAFF_SHIFTS, MEDICINES
)


def seed():
    init_db()
    session = get_session()

    if session.scalar(select(Department).limit(1)):
        print("Departments already seeded — skipping. Delete the DB or table rows to reseed.")
        session.close()
        return

    dept_objs = {}
    for name, total_beds, total_icu in DEPARTMENTS:
        dept = Department(name=name, total_beds=total_beds, total_icu_beds=total_icu)
        session.add(dept)
        session.flush()
        dept_objs[name] = dept

        # Create individual bed rows
        icu_beds_created = 0
        for _ in range(total_beds):
            if icu_beds_created < total_icu:
                bed_type = "ICU"
                icu_beds_created += 1
            else:
                bed_type = "GENERAL"
            session.add(Bed(department_id=dept.department_id, bed_type=bed_type, status="AVAILABLE"))

        # Create staff roster for this department
        for i in range(STAFF_PER_DEPARTMENT):
            session.add(Staff(
                department_id=dept.department_id,
                role=STAFF_ROLES[i % len(STAFF_ROLES)],
                shift=STAFF_SHIFTS[i % len(STAFF_SHIFTS)],
                status="ACTIVE",
            ))

    for name, unit, threshold in MEDICINES:
        session.add(Medicine(name=name, unit=unit, reorder_threshold=threshold))

    session.commit()
    session.close()
    print("Seed complete: 8 departments, 300 beds (30 ICU), staff roster, medicine catalog.")


if __name__ == "__main__":
    seed()
