"""
AgentCare AI - Data Cleaning Agent

Phase 2:
    Validate operational hospital data before downstream analysis.

Responsibilities:
    - Validate referential integrity
    - Validate required fields
    - Validate allowed status/type values
    - Validate numeric values
    - Detect duplicates
    - Quarantine invalid records
    - Record data-quality summaries

Important:
    This agent NEVER deletes or modifies source operational records.
"""

from datetime import datetime
from decimal import Decimal
import json

from sqlalchemy import text

from agentcare.db import get_session


class DataCleaningAgent:

    def __init__(self, session=None):
        self.session = session or get_session()

    # ============================================================
    # UTILITY
    # ============================================================

    @staticmethod
    def now():
        return datetime.utcnow()

    @staticmethod
    def json_safe(record):
        result = {}

        for key, value in record.items():
            if isinstance(value, (datetime, Decimal)):
                result[key] = str(value)
            else:
                result[key] = value

        return result

    def quarantine(self, source_table, record, reason):

        payload = self.json_safe(record)

        self.session.execute(
            text("""
                INSERT INTO quarantined_records
                (
                    source_table,
                    raw_payload,
                    reason,
                    quarantine_time
                )
                VALUES
                (
                    :source_table,
                    CAST(:raw_payload AS json),
                    :reason,
                    :quarantine_time
                )
            """),
            {
                "source_table": source_table,
                "raw_payload": json.dumps(payload, default=str),
                "reason": reason,
                "quarantine_time": self.now(),
            },
        )

    # ============================================================
    # GENERIC TABLE VALIDATION
    # ============================================================

    def validate_patients(self):

        rows = self.session.execute(
            text("""
                SELECT patient_id, synthetic_ref
                FROM patients
            """)
        ).mappings().all()

        valid = 0
        invalid = 0

        for row in rows:

            record = dict(row)
            reason = None

            if not record["synthetic_ref"]:
                reason = "Missing synthetic_ref."

            if reason:
                self.quarantine(
                    "patients",
                    record,
                    reason
                )
                invalid += 1
            else:
                valid += 1

        return valid, invalid, len(rows)

    # ============================================================
    # DEPARTMENTS
    # ============================================================

    def validate_departments(self):

        rows = self.session.execute(
            text("""
                SELECT
                    department_id,
                    name,
                    total_beds,
                    total_icu_beds
                FROM departments
            """)
        ).mappings().all()

        valid = 0
        invalid = 0

        for row in rows:

            record = dict(row)
            reason = None

            if not record["name"]:
                reason = "Missing department name."

            elif record["total_beds"] <= 0:
                reason = "Department must have at least one bed."

            elif record["total_icu_beds"] < 0:
                reason = "ICU bed count cannot be negative."

            elif record["total_icu_beds"] > record["total_beds"]:
                reason = "ICU beds exceed total beds."

            if reason:
                self.quarantine(
                    "departments",
                    record,
                    reason
                )
                invalid += 1
            else:
                valid += 1

        return valid, invalid, len(rows)

    # ============================================================
    # BEDS
    # ============================================================

    def validate_beds(self):

        rows = self.session.execute(
            text("""
                SELECT
                    bed_id,
                    department_id,
                    bed_type,
                    status
                FROM beds
            """)
        ).mappings().all()

        valid = 0
        invalid = 0

        for row in rows:

            record = dict(row)
            reason = None

            department_exists = self.session.execute(
                text("""
                    SELECT EXISTS(
                        SELECT 1
                        FROM departments
                        WHERE department_id = :department_id
                    )
                """),
                {
                    "department_id":
                        record["department_id"]
                }
            ).scalar()

            if not department_exists:
                reason = "Referenced department does not exist."

            elif record["bed_type"] not in (
                "GENERAL",
                "ICU",
            ):
                reason = "Invalid bed type."

            elif record["status"] not in (
                "AVAILABLE",
                "OCCUPIED",
                "MAINTENANCE",
                "BLOCKED",
            ):
                reason = "Invalid bed status."

            if reason:
                self.quarantine(
                    "beds",
                    record,
                    reason
                )
                invalid += 1
            else:
                valid += 1

        return valid, invalid, len(rows)

    # ============================================================
    # STAFF
    # ============================================================

    def validate_staff(self):

        rows = self.session.execute(
            text("""
                SELECT
                    staff_id,
                    department_id,
                    role,
                    shift,
                    status
                FROM staff
            """)
        ).mappings().all()

        valid = 0
        invalid = 0

        for row in rows:

            record = dict(row)
            reason = None

            department_exists = self.session.execute(
                text("""
                    SELECT EXISTS(
                        SELECT 1
                        FROM departments
                        WHERE department_id = :department_id
                    )
                """),
                {
                    "department_id":
                        record["department_id"]
                }
            ).scalar()

            if not department_exists:
                reason = "Referenced department does not exist."

            elif not record["role"]:
                reason = "Missing staff role."

            elif record["status"] not in (
                "ACTIVE",
                "AVAILABLE",
                "OFF",
            ):
                reason = "Invalid staff status."

            if reason:
                self.quarantine(
                    "staff",
                    record,
                    reason
                )
                invalid += 1
            else:
                valid += 1

        return valid, invalid, len(rows)

    # ============================================================
    # MEDICINES
    # ============================================================

    def validate_medicines(self):

        rows = self.session.execute(
            text("""
                SELECT
                    medicine_id,
                    name,
                    unit,
                    reorder_threshold
                FROM medicines
            """)
        ).mappings().all()

        valid = 0
        invalid = 0

        for row in rows:

            record = dict(row)
            reason = None

            if not record["name"]:
                reason = "Missing medicine name."

            elif not record["unit"]:
                reason = "Missing medicine unit."

            elif record["reorder_threshold"] < 0:
                reason = "Reorder threshold cannot be negative."

            if reason:
                self.quarantine(
                    "medicines",
                    record,
                    reason
                )
                invalid += 1
            else:
                valid += 1

        return valid, invalid, len(rows)

    # ============================================================
    # ADMISSIONS
    # ============================================================

    def validate_admissions(self):

        rows = self.session.execute(
            text("""
                SELECT
                    admission_id,
                    patient_id,
                    department_id,
                    bed_id,
                    admission_type,
                    admission_time,
                    discharge_time,
                    status
                FROM admissions
            """)
        ).mappings().all()

        valid = 0
        invalid = 0

        for row in rows:

            record = dict(row)
            reason = None

            patient_exists = self.session.execute(
                text("""
                    SELECT EXISTS(
                        SELECT 1
                        FROM patients
                        WHERE patient_id = :patient_id
                    )
                """),
                {
                    "patient_id":
                        record["patient_id"]
                }
            ).scalar()

            if not patient_exists:
                reason = "Referenced patient does not exist."

            department_exists = self.session.execute(
                text("""
                    SELECT EXISTS(
                        SELECT 1
                        FROM departments
                        WHERE department_id = :department_id
                    )
                """),
                {
                    "department_id":
                        record["department_id"]
                }
            ).scalar()

            if not reason and not department_exists:
                reason = "Referenced department does not exist."

            if record["bed_id"] is not None:

                bed_exists = self.session.execute(
                    text("""
                        SELECT EXISTS(
                            SELECT 1
                            FROM beds
                            WHERE bed_id = :bed_id
                        )
                    """),
                    {
                        "bed_id":
                            record["bed_id"]
                    }
                ).scalar()

                if not bed_exists:
                    reason = "Referenced bed does not exist."

            if not reason and record["admission_type"] not in (
                "EMERGENCY",
                "NORMAL",
            ):
                reason = "Invalid admission type."

            if not reason and record["status"] not in (
                "ADMITTED",
                "DISCHARGED",
            ):
                reason = "Invalid admission status."

            if not reason and record["admission_time"] is None:
                reason = "Missing admission time."

            if (
                not reason
                and record["discharge_time"] is not None
                and record["discharge_time"]
                < record["admission_time"]
            ):
                reason = "Discharge time precedes admission time."

            if reason:
                self.quarantine(
                    "admissions",
                    record,
                    reason
                )
                invalid += 1
            else:
                valid += 1

        return valid, invalid, len(rows)

    # ============================================================
    # EMERGENCY EVENTS
    # ============================================================

    def validate_emergency_events(self):

        rows = self.session.execute(
            text("""
                SELECT
                    event_id,
                    department_id,
                    event_time,
                    resulted_admission_id
                FROM emergency_events
            """)
        ).mappings().all()

        valid = 0
        invalid = 0

        for row in rows:

            record = dict(row)
            reason = None

            department_exists = self.session.execute(
                text("""
                    SELECT EXISTS(
                        SELECT 1
                        FROM departments
                        WHERE department_id = :department_id
                    )
                """),
                {
                    "department_id":
                        record["department_id"]
                }
            ).scalar()

            if not department_exists:
                reason = "Referenced department does not exist."

            elif record["event_time"] is None:
                reason = "Missing event time."

            if (
                not reason
                and record["resulted_admission_id"] is not None
            ):

                admission_exists = self.session.execute(
                    text("""
                        SELECT EXISTS(
                            SELECT 1
                            FROM admissions
                            WHERE admission_id = :admission_id
                        )
                    """),
                    {
                        "admission_id":
                            record["resulted_admission_id"]
                    }
                ).scalar()

                if not admission_exists:
                    reason = "Referenced admission does not exist."

            if reason:
                self.quarantine(
                    "emergency_events",
                    record,
                    reason
                )
                invalid += 1
            else:
                valid += 1

        return valid, invalid, len(rows)

    # ============================================================
    # INVENTORY
    # ============================================================

    def validate_inventory(self):

        rows = self.session.execute(
            text("""
                SELECT
                    transaction_id,
                    medicine_id,
                    department_id,
                    transaction_type,
                    quantity,
                    transaction_time
                FROM inventory_transactions
            """)
        ).mappings().all()

        valid = 0
        invalid = 0

        for row in rows:

            record = dict(row)
            reason = None

            medicine_exists = self.session.execute(
                text("""
                    SELECT EXISTS(
                        SELECT 1
                        FROM medicines
                        WHERE medicine_id = :medicine_id
                    )
                """),
                {
                    "medicine_id":
                        record["medicine_id"]
                }
            ).scalar()

            if not medicine_exists:
                reason = "Referenced medicine does not exist."

            elif record["transaction_type"] not in (
                "RESTOCK",
                "CONSUMPTION",
            ):
                reason = "Invalid transaction type."

            elif (
                record["quantity"] is None
                or record["quantity"] <= 0
            ):
                reason = "Quantity must be greater than zero."

            elif record["transaction_time"] is None:
                reason = "Missing transaction time."

            if (
                not reason
                and record["department_id"] is not None
            ):

                department_exists = self.session.execute(
                    text("""
                        SELECT EXISTS(
                            SELECT 1
                            FROM departments
                            WHERE department_id = :department_id
                        )
                    """),
                    {
                        "department_id":
                            record["department_id"]
                    }
                ).scalar()

                if not department_exists:
                    reason = "Referenced department does not exist."

            if reason:
                self.quarantine(
                    "inventory_transactions",
                    record,
                    reason
                )
                invalid += 1
            else:
                valid += 1

        return valid, invalid, len(rows)

    # ============================================================
    # REVENUE
    # ============================================================

    def validate_revenue(self):

        rows = self.session.execute(
            text("""
                SELECT
                    transaction_id,
                    department_id,
                    admission_id,
                    amount,
                    category,
                    transaction_time
                FROM revenue_transactions
            """)
        ).mappings().all()

        valid = 0
        invalid = 0

        for row in rows:

            record = dict(row)
            reason = None

            department_exists = self.session.execute(
                text("""
                    SELECT EXISTS(
                        SELECT 1
                        FROM departments
                        WHERE department_id = :department_id
                    )
                """),
                {
                    "department_id":
                        record["department_id"]
                }
            ).scalar()

            if not department_exists:
                reason = "Referenced department does not exist."

            elif (
                record["amount"] is None
                or record["amount"] < 0
            ):
                reason = "Revenue amount cannot be negative."

            elif record["transaction_time"] is None:
                reason = "Missing transaction time."

            if (
                not reason
                and record["admission_id"] is not None
            ):

                admission_exists = self.session.execute(
                    text("""
                        SELECT EXISTS(
                            SELECT 1
                            FROM admissions
                            WHERE admission_id = :admission_id
                        )
                    """),
                    {
                        "admission_id":
                            record["admission_id"]
                    }
                ).scalar()

                if not admission_exists:
                    reason = "Referenced admission does not exist."

            if reason:
                self.quarantine(
                    "revenue_transactions",
                    record,
                    reason
                )
                invalid += 1
            else:
                valid += 1

        return valid, invalid, len(rows)

    # ============================================================
    # DUPLICATES
    # ============================================================

    def detect_duplicate_admissions(self):

        result = self.session.execute(
            text("""
                SELECT COALESCE(
                    SUM(duplicate_count - 1),
                    0
                )
                FROM (
                    SELECT COUNT(*) AS duplicate_count
                    FROM admissions
                    GROUP BY
                        patient_id,
                        department_id,
                        bed_id,
                        admission_type,
                        admission_time,
                        discharge_time,
                        status
                    HAVING COUNT(*) > 1
                ) duplicates
            """)
        ).scalar()

        return int(result or 0)

    # ============================================================
    # RUN
    # ============================================================

    def run(self, window_start=None, window_end=None):

        print("\n" + "=" * 70)
        print("AGENTCARE DATA CLEANING AGENT")
        print("=" * 70)
        if window_start and window_end:
            print(
                f"\nMonitoring window:"
                f"\n  {window_start}"
                f"\n  -> {window_end}"
            )
        checks = {
            "departments": self.validate_departments,
            "beds": self.validate_beds,
            "staff": self.validate_staff,
            "patients": self.validate_patients,
            "medicines": self.validate_medicines,
            "admissions": self.validate_admissions,
            "emergency_events": self.validate_emergency_events,
            "inventory_transactions": self.validate_inventory,
            "revenue_transactions": self.validate_revenue,
        }

        results = {}

        try:

            for table_name, validator in checks.items():

                valid, invalid, total = validator()

                results[table_name] = {
                    "total": total,
                    "valid": valid,
                    "invalid": invalid,
                }

            duplicates = self.detect_duplicate_admissions()

            print("\nCLEANING SUMMARY")

            for table_name, values in results.items():

                print(
                    f"{table_name:28} "
                    f"total={values['total']} "
                    f"valid={values['valid']} "
                    f"invalid={values['invalid']}"
                )

            print(
                f"{'duplicate_admissions':28} "
                f"duplicates={duplicates}"
            )

            # ----------------------------------------------------
            # Data-quality summary
            # ----------------------------------------------------

            now = self.now()

            for table_name, values in results.items():

                self.session.execute(
                    text("""
                        INSERT INTO data_quality_records
                        (
                            source_table,
                            total_records,
                            valid_records,
                            invalid_records,
                            repaired_records,
                            quarantined_records,
                            duplicate_records,
                            window_start,
                            window_end
                        )
                        VALUES
                        (
                            :source_table,
                            :total_records,
                            :valid_records,
                            :invalid_records,
                            0,
                            :quarantined_records,
                            0,
                            :window_start,
                            :window_end
                        )
                    """),
                    {
                        "source_table": table_name,
                        "total_records":
                            values["total"],
                        "valid_records":
                            values["valid"],
                        "invalid_records":
                            values["invalid"],
                        "quarantined_records":
                            values["invalid"],
                        "window_start": now,
                        "window_end": now,
                    }
                )

            self.session.commit()

            print("\n" + "=" * 70)
            print("✅ DATA CLEANING COMPLETE")
            print("=" * 70)

            return {
                "status": "SUCCESS",
                "results": results,
                "duplicates": duplicates,
            }

        except Exception as exc:

            self.session.rollback()

            print("\n❌ DATA CLEANING FAILED")
            print(str(exc))

            return {
                "status": "FAILED",
                "error": str(exc),
            }


if __name__ == "__main__":
    agent = DataCleaningAgent()
    agent.run()