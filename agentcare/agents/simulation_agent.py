"""
Simulation Agent — the Data Simulation Engine, wrapped as an Agent.

Generates event-driven hospital operational data (Assumption 9):
    Emergency Event -> Admission -> Bed Assignment -> Inventory Consumption -> Revenue

Same core logic is used for:
    - historical mode: bulk-generate N days before live monitoring starts
    - live mode: generate exactly one monitoring window (e.g. 30 minutes)

The engine never invents independent random rows — every record is a
consequence of a simulated event, and current hospital state (bed status,
stock) is always derived from the accumulated event history in the DB.
"""

import random
from datetime import timedelta

import numpy as np
from sqlalchemy import select, func, or_

from agentcare.agents.base import Agent
from agentcare.models import (
    Department,
    Bed,
    Patient,
    Admission,
    EmergencyEvent,
    Medicine,
    InventoryTransaction,
    RevenueTransaction,
)

from agentcare.config import (
    BASE_ADMISSION_RATE_PER_HOUR,
    HOURLY_MULTIPLIER,
    EMERGENCY_ADMISSION_PROBABILITY,
    AVG_LENGTH_OF_STAY_HOURS,
    DEPARTMENT_MEDICINE_USAGE,
    DEPARTMENT_REVENUE_RANGE,
    RESTOCK_TARGET_MULTIPLIER,
)


class SimulationAgent(Agent):
    name = "SimulationAgent"

    def __init__(self, session):
        self.session = session
        self._patient_counter = None

    # ------------------------------------------------------------
    # Public Agent interface — called by the Orchestrator
    # ------------------------------------------------------------

    def run(self, context: dict) -> dict:
        """
        context must include:
            mode: "HISTORICAL" or "LIVE"
            start_time: datetime
            end_time: datetime
        """

        try:
            mode = context["mode"]
            start_time = context["start_time"]
            end_time = context["end_time"]

            if mode == "HISTORICAL":
                summary = self._generate_period(
                    start_time,
                    end_time,
                    hourly_step=True,
                )

            elif mode == "LIVE":
                summary = self._generate_period(
                    start_time,
                    end_time,
                    hourly_step=False,
                )

            else:
                return {
                    "status": "FAILED",
                    "error": f"Unknown mode: {mode}",
                }

            self.session.commit()

            return {
                "status": "SUCCESS",
                **summary,
            }

        except Exception as e:
            self.session.rollback()

            return {
                "status": "FAILED",
                "error": str(e),
            }

    # ------------------------------------------------------------
    # Core generation logic
    # ------------------------------------------------------------

    def _generate_period(self, start_time, end_time, hourly_step: bool):
        """
        Walk through the simulation period in hourly buckets.

        For LIVE mode, a 30-minute period is handled as a half-hour bucket.
        """

        departments = {
            d.name: d
            for d in self.session.scalars(
                select(Department)
            ).all()
        }

        counters = {
            "admissions": 0,
            "emergency_events": 0,
            "discharges": 0,
            "inventory_transactions": 0,
            "revenue_transactions": 0,
        }

        cursor = start_time

        while cursor < end_time:

            bucket_end = min(
                cursor + timedelta(hours=1),
                end_time,
            )

            hour_of_day = cursor.hour
            multiplier = HOURLY_MULTIPLIER[hour_of_day]

            # ----------------------------------------------------
            # 1. Process discharges first
            # ----------------------------------------------------

            counters["discharges"] += self._process_discharges(
                cursor,
                bucket_end,
            )

            # ----------------------------------------------------
            # 2. Generate new admissions
            # ----------------------------------------------------

            for dept_name, dept in departments.items():

                base_rate = (
                    BASE_ADMISSION_RATE_PER_HOUR[dept_name]
                    * multiplier
                )

                fraction_of_hour = (
                    bucket_end - cursor
                ).total_seconds() / 3600.0

                expected = base_rate * fraction_of_hour

                n_admissions = (
                    np.random.poisson(expected)
                    if expected > 0
                    else 0
                )

                for _ in range(n_admissions):

                    event_time = cursor + timedelta(
                        seconds=random.uniform(
                            0,
                            (bucket_end - cursor).total_seconds(),
                        )
                    )

                    self._create_admission_event(
                        dept,
                        event_time,
                        counters,
                    )

            cursor = bucket_end

        # --------------------------------------------------------
        # 3. Restock medicines
        # --------------------------------------------------------

        counters["inventory_transactions"] += (
            self._run_restock_check(end_time)
        )

        return counters

    # ------------------------------------------------------------
    # Deterministic discharge calculation
    # ------------------------------------------------------------

    def _expected_discharge_time(self, adm: Admission):
        """
        Calculate the expected discharge time deterministically.

        The same admission_id always produces the same LOS.
        This prevents discharge time from changing every hour.
        """

        dept = self.session.get(
            Department,
            adm.department_id,
        )

        los_hours = AVG_LENGTH_OF_STAY_HOURS.get(
            dept.name,
            48,
        )

        rng = random.Random(adm.admission_id)

        jitter_hours = rng.gauss(
            los_hours,
            los_hours * 0.15,
        )

        return (
            adm.admission_time
            + timedelta(hours=jitter_hours)
        )

    # ------------------------------------------------------------
    # Discharge processing
    # ------------------------------------------------------------

    def _process_discharges(self, window_start, window_end) -> int:
        """
        Discharge admitted patients whose deterministic LOS has elapsed.
        """

        admitted = self.session.scalars(
            select(Admission).where(
                Admission.status == "ADMITTED"
            )
        ).all()

        discharged_count = 0

        for adm in admitted:

            expected_discharge = (
                self._expected_discharge_time(adm)
            )

            if (
                window_start
                <= expected_discharge
                < window_end
            ):

                adm.status = "DISCHARGED"

                adm.discharge_time = expected_discharge

                if adm.bed_id:

                    bed = self.session.get(
                        Bed,
                        adm.bed_id,
                    )

                    if bed:

                        bed.status = "AVAILABLE"

                        bed.last_status_change_time = (
                            expected_discharge
                        )

                discharged_count += 1

        return discharged_count

    # ------------------------------------------------------------
    # Admission event + event cascade
    # ------------------------------------------------------------

    def _create_admission_event(
        self,
        dept: Department,
        event_time,
        counters: dict,
    ):
        """
        Runs the complete event cascade:

        Admission
            ↓
        Bed assignment
            ↓
        Emergency event (if applicable)
            ↓
        Inventory consumption
            ↓
        Revenue
        """

        is_emergency = (
            random.random()
            < EMERGENCY_ADMISSION_PROBABILITY
        )

        admission_type = (
            "EMERGENCY"
            if is_emergency
            else "NORMAL"
        )

        # --------------------------------------------------------
        # Determine required bed type
        # --------------------------------------------------------

        bed_type = (
            "ICU"
            if dept.name == "ICU"
            else "GENERAL"
        )

        # --------------------------------------------------------
        # Find a genuinely available bed
        # --------------------------------------------------------

        bed = self._find_available_bed(
            dept,
            bed_type,
            event_time,
        )

        # --------------------------------------------------------
        # Create synthetic patient
        # --------------------------------------------------------

        patient = self._create_synthetic_patient()

        # --------------------------------------------------------
        # Create admission
        # --------------------------------------------------------

        admission = Admission(
            patient_id=patient.patient_id,
            department_id=dept.department_id,
            bed_id=bed.bed_id if bed else None,
            admission_type=admission_type,
            admission_time=event_time,
            status="ADMITTED",
        )

        self.session.add(admission)

        # Get admission_id
        self.session.flush()

        counters["admissions"] += 1

        # --------------------------------------------------------
        # Occupy selected bed
        # --------------------------------------------------------

        if bed:

            bed.status = "OCCUPIED"

            bed.last_status_change_time = event_time

        # If no bed is available, we intentionally keep
        # bed_id=None. This represents capacity pressure.

        # --------------------------------------------------------
        # Emergency event
        # --------------------------------------------------------

        if is_emergency:

            self.session.add(
                EmergencyEvent(
                    department_id=dept.department_id,
                    event_time=event_time,
                    resulted_admission_id=admission.admission_id,
                )
            )

            counters["emergency_events"] += 1

        # --------------------------------------------------------
        # Inventory consumption
        # --------------------------------------------------------

        self._consume_inventory(
            dept,
            event_time,
            counters,
        )

        # --------------------------------------------------------
        # Revenue
        # --------------------------------------------------------

        self._record_revenue(
            dept,
            admission.admission_id,
            event_time,
            counters,
        )

    # ------------------------------------------------------------
    # Historical-safe bed allocation
    # ------------------------------------------------------------

    def _find_available_bed(
        self,
        dept: Department,
        bed_type: str,
        event_time,
    ):
        """
        Find a bed that is genuinely available at event_time.

        A bed is eligible only when:

        1. It belongs to the correct department.
        2. It has the correct bed type.
        3. Its current status is AVAILABLE.
        4. No previous admission assigned to this bed overlaps
           the new admission's event_time.

        This protects the historical simulation from reusing a bed
        while a previous patient is still occupying it.
        """

        beds = self.session.scalars(
            select(Bed).where(
                Bed.department_id == dept.department_id,
                Bed.bed_type == bed_type,
                Bed.status == "AVAILABLE",
            )
        ).all()

        for bed in beds:

            previous_admissions = self.session.scalars(
                select(Admission).where(
                    Admission.bed_id == bed.bed_id,
                    Admission.admission_time < event_time,
                )
            ).all()

            bed_is_occupied_at_event = False

            for adm in previous_admissions:

                # If the patient has an actual discharge time,
                # use it directly.
                if adm.discharge_time is not None:

                    if adm.discharge_time > event_time:
                        bed_is_occupied_at_event = True
                        break

                # If the patient is still ADMITTED and has no
                # recorded discharge time yet, calculate the
                # deterministic expected discharge.
                elif adm.status == "ADMITTED":

                    expected_discharge = (
                        self._expected_discharge_time(adm)
                    )

                    if expected_discharge > event_time:
                        bed_is_occupied_at_event = True
                        break

            if not bed_is_occupied_at_event:
                return bed

        return None

    # ------------------------------------------------------------
    # Synthetic patient creation
    # ------------------------------------------------------------

    def _create_synthetic_patient(self) -> Patient:

        if self._patient_counter is None:

            existing = self.session.scalar(
                select(func.count(Patient.patient_id))
            )

            self._patient_counter = existing or 0

        self._patient_counter += 1

        patient = Patient(
            synthetic_ref=(
                f"SIM-PT-{self._patient_counter:07d}"
            )
        )

        self.session.add(patient)

        self.session.flush()

        return patient

    # ------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------

    def _consume_inventory(
        self,
        dept: Department,
        event_time,
        counters: dict,
    ):

        usage = DEPARTMENT_MEDICINE_USAGE.get(
            dept.name,
            {},
        )

        for med_name, qty in usage.items():

            medicine = self.session.scalar(
                select(Medicine).where(
                    Medicine.name == med_name
                )
            )

            if not medicine:
                continue

            self.session.add(
                InventoryTransaction(
                    medicine_id=medicine.medicine_id,
                    department_id=dept.department_id,
                    transaction_type="CONSUMPTION",
                    quantity=qty,
                    transaction_time=event_time,
                )
            )

            counters["inventory_transactions"] += 1

    # ------------------------------------------------------------
    # Revenue
    # ------------------------------------------------------------

    def _record_revenue(
        self,
        dept: Department,
        admission_id,
        event_time,
        counters: dict,
    ):

        low, high = DEPARTMENT_REVENUE_RANGE.get(
            dept.name,
            (2000, 8000),
        )

        amount = round(
            random.uniform(low, high),
            2,
        )

        self.session.add(
            RevenueTransaction(
                department_id=dept.department_id,
                admission_id=admission_id,
                amount=amount,
                category="ADMISSION_BILLING",
                transaction_time=event_time,
            )
        )

        counters["revenue_transactions"] += 1

    # ------------------------------------------------------------
    # Inventory stock
    # ------------------------------------------------------------

    def _current_stock(self, medicine_id) -> float:

        restocked = self.session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        InventoryTransaction.quantity
                    ),
                    0,
                )
            ).where(
                InventoryTransaction.medicine_id == medicine_id,
                InventoryTransaction.transaction_type == "RESTOCK",
            )
        )

        consumed = self.session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        InventoryTransaction.quantity
                    ),
                    0,
                )
            ).where(
                InventoryTransaction.medicine_id == medicine_id,
                InventoryTransaction.transaction_type == "CONSUMPTION",
            )
        )

        return (
            float(restocked or 0)
            - float(consumed or 0)
        )

    # ------------------------------------------------------------
    # Restocking
    # ------------------------------------------------------------

    def _run_restock_check(self, at_time) -> int:
        """
        If stock falls below the reorder threshold,
        restock up to threshold * RESTOCK_TARGET_MULTIPLIER.
        """

        restock_txns = 0

        medicines = self.session.scalars(
            select(Medicine)
        ).all()

        for med in medicines:

            stock = self._current_stock(
                med.medicine_id
            )

            threshold = float(
                med.reorder_threshold
            )

            if stock < threshold:

                target = (
                    threshold
                    * RESTOCK_TARGET_MULTIPLIER
                )

                self.session.add(
                    InventoryTransaction(
                        medicine_id=med.medicine_id,
                        department_id=None,
                        transaction_type="RESTOCK",
                        quantity=target - stock,
                        transaction_time=at_time,
                    )
                )

                restock_txns += 1

        return restock_txns