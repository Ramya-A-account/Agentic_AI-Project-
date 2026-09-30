from datetime import datetime, timedelta

from sqlalchemy import text

from agentcare.db import get_session
from agentcare.agents.cleaning_agent import DataCleaningAgent


TEST_REF = "DQ_TEST_PATIENT_001"


def main():

    session = get_session()

    print("\n" + "=" * 70)
    print("AGENTCARE - CONTROLLED DATA QUALITY TEST")
    print("=" * 70)

    patient_id = None
    admission_id = None
    duplicate_admission_id = None
    inventory_id = None
    revenue_id = None

    try:

        # --------------------------------------------------------
        # 1. Create test patient
        # --------------------------------------------------------

        print("\n[1] Creating test patient...")

        session.execute(
            text("""
                INSERT INTO patients (synthetic_ref)
                VALUES (:synthetic_ref)
            """),
            {"synthetic_ref": TEST_REF}
        )

        patient_id = session.execute(
            text("""
                SELECT patient_id
                FROM patients
                WHERE synthetic_ref = :synthetic_ref
            """),
            {"synthetic_ref": TEST_REF}
        ).scalar()

        print(f"Test patient created: {patient_id}")

        department_id = session.execute(
            text("""
                SELECT department_id
                FROM departments
                LIMIT 1
            """)
        ).scalar()

        medicine_id = session.execute(
            text("""
                SELECT medicine_id
                FROM medicines
                LIMIT 1
            """)
        ).scalar()

        # --------------------------------------------------------
        # 2. BAD ADMISSION
        # Discharge before admission
        # --------------------------------------------------------

        print("\n[2] Inserting BAD admission...")

        admission_time = datetime.utcnow()
        discharge_time = admission_time - timedelta(hours=2)

        result = session.execute(
            text("""
                INSERT INTO admissions
                (
                    patient_id,
                    department_id,
                    bed_id,
                    admission_type,
                    admission_time,
                    discharge_time,
                    status
                )
                VALUES
                (
                    :patient_id,
                    :department_id,
                    NULL,
                    'NORMAL',
                    :admission_time,
                    :discharge_time,
                    'DISCHARGED'
                )
                RETURNING admission_id
            """),
            {
                "patient_id": patient_id,
                "department_id": department_id,
                "admission_time": admission_time,
                "discharge_time": discharge_time,
            }
        )

        admission_id = result.scalar()

        print(f"Bad admission created: {admission_id}")

        # --------------------------------------------------------
        # 3. DUPLICATE ADMISSION
        # Exact same values
        # --------------------------------------------------------

        print("[3] Inserting DUPLICATE admission...")

        result = session.execute(
            text("""
                INSERT INTO admissions
                (
                    patient_id,
                    department_id,
                    bed_id,
                    admission_type,
                    admission_time,
                    discharge_time,
                    status
                )
                VALUES
                (
                    :patient_id,
                    :department_id,
                    NULL,
                    'NORMAL',
                    :admission_time,
                    :discharge_time,
                    'DISCHARGED'
                )
                RETURNING admission_id
            """),
            {
                "patient_id": patient_id,
                "department_id": department_id,
                "admission_time": admission_time,
                "discharge_time": discharge_time,
            }
        )

        duplicate_admission_id = result.scalar()

        print(
            f"Duplicate admission created: "
            f"{duplicate_admission_id}"
        )

        # --------------------------------------------------------
        # 4. BAD INVENTORY
        # Negative quantity
        # --------------------------------------------------------

        print("[4] Inserting BAD inventory transaction...")

        result = session.execute(
            text("""
                INSERT INTO inventory_transactions
                (
                    medicine_id,
                    department_id,
                    transaction_type,
                    quantity,
                    transaction_time
                )
                VALUES
                (
                    :medicine_id,
                    :department_id,
                    'CONSUMPTION',
                    -50,
                    :transaction_time
                )
                RETURNING transaction_id
            """),
            {
                "medicine_id": medicine_id,
                "department_id": department_id,
                "transaction_time": datetime.utcnow(),
            }
        )

        inventory_id = result.scalar()

        print(
            f"Bad inventory transaction created: "
            f"{inventory_id}"
        )

        # --------------------------------------------------------
        # 5. BAD REVENUE
        # Negative amount
        # --------------------------------------------------------

        print("[5] Inserting BAD revenue transaction...")

        result = session.execute(
            text("""
                INSERT INTO revenue_transactions
                (
                    department_id,
                    admission_id,
                    amount,
                    category,
                    transaction_time
                )
                VALUES
                (
                    :department_id,
                    NULL,
                    -1000,
                    'DQ_TEST',
                    :transaction_time
                )
                RETURNING transaction_id
            """),
            {
                "department_id": department_id,
                "transaction_time": datetime.utcnow(),
            }
        )

        revenue_id = result.scalar()

        print(
            f"Bad revenue transaction created: "
            f"{revenue_id}"
        )

        session.commit()

        print("\n✅ Bad test records inserted successfully.")

    except Exception as exc:

        session.rollback()

        print("\n❌ Failed while inserting test data:")
        print(exc)

        session.close()
        return

    finally:
        session.close()

    # ============================================================
    # RUN CLEANING AGENT
    # ============================================================

    print("\n" + "=" * 70)
    print("RUNNING DATA CLEANING AGENT")
    print("=" * 70)

    cleaner = DataCleaningAgent()
    result = cleaner.run()

    if result["status"] != "SUCCESS":
        print("\n❌ Cleaning Agent failed.")
        return

    # ============================================================
    # VERIFY
    # ============================================================

    print("\n" + "=" * 70)
    print("VERIFYING DATA QUALITY DETECTION")
    print("=" * 70)

    session = get_session()

    try:

        quarantine_count = session.execute(
            text("""
                SELECT COUNT(*)
                FROM quarantined_records
                WHERE quarantine_time >= NOW() - INTERVAL '5 minutes'
                  AND source_table IN (
                      'admissions',
                      'inventory_transactions',
                      'revenue_transactions'
                  )
            """)
        ).scalar()

        duplicate_count = result.get("duplicates", 0)

        invalid_quality_count = session.execute(
            text("""
                SELECT COUNT(*)
                FROM data_quality_records
                WHERE window_start >= NOW() - INTERVAL '5 minutes'
                  AND invalid_records > 0
            """)
        ).scalar()

        print(
            f"\nRecently quarantined records: "
            f"{quarantine_count}"
        )

        print(
            f"Duplicate admissions detected: "
            f"{duplicate_count}"
        )

        print(
            f"Data-quality records with invalid data: "
            f"{invalid_quality_count}"
        )

        if (
            quarantine_count >= 3
            and duplicate_count >= 1
            and invalid_quality_count >= 3
        ):

            print("\n" + "=" * 70)
            print("🎉 CONTROLLED DATA QUALITY TEST PASSED")
            print("=" * 70)

        else:

            print("\n❌ CONTROLLED DATA QUALITY TEST FAILED")

    finally:
        session.close()

    # ============================================================
    # CLEANUP
    # ============================================================

    print("\n" + "=" * 70)
    print("CLEANING UP TEST RECORDS")
    print("=" * 70)

    session = get_session()

    try:

        if revenue_id:
            session.execute(
                text("""
                    DELETE FROM revenue_transactions
                    WHERE transaction_id = :id
                """),
                {"id": revenue_id}
            )

        if inventory_id:
            session.execute(
                text("""
                    DELETE FROM inventory_transactions
                    WHERE transaction_id = :id
                """),
                {"id": inventory_id}
            )

        if duplicate_admission_id:
            session.execute(
                text("""
                    DELETE FROM admissions
                    WHERE admission_id = :id
                """),
                {"id": duplicate_admission_id}
            )

        if admission_id:
            session.execute(
                text("""
                    DELETE FROM admissions
                    WHERE admission_id = :id
                """),
                {"id": admission_id}
            )

        if patient_id:
            session.execute(
                text("""
                    DELETE FROM patients
                    WHERE patient_id = :id
                """),
                {"id": patient_id}
            )

        session.commit()

        print("\n✅ Test records removed.")
        print("✅ Historical baseline remains intact.")

    except Exception as exc:

        session.rollback()
        print("\n⚠️ Cleanup failed:")
        print(exc)

    finally:
        session.close()


if __name__ == "__main__":
    main()