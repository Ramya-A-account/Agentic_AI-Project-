"""
ORM models — 1:1 with the agentcare_schema.sql design.
The Simulation Agent writes directly into these tables; every other
agent (Cleaning, Analysis, Alert Detection, ...) reads from the same tables.
"""
from sqlalchemy import (
    Column, Integer, String, Numeric, ForeignKey, TIMESTAMP, JSON, Text
)
from sqlalchemy.orm import relationship
from datetime import datetime

from agentcare.db import Base


def utcnow():
    return datetime.utcnow()


# ------------------------------------------------------------
# CORE OPERATIONAL TABLES
# ------------------------------------------------------------

class Department(Base):
    __tablename__ = "departments"
    department_id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    total_beds = Column(Integer, nullable=False)
    total_icu_beds = Column(Integer, nullable=False, default=0)

    beds = relationship("Bed", back_populates="department")
    staff = relationship("Staff", back_populates="department")


class Bed(Base):
    __tablename__ = "beds"
    bed_id = Column(Integer, primary_key=True)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=False)
    bed_type = Column(String(20), nullable=False)          # GENERAL / ICU
    status = Column(String(20), nullable=False)            # OCCUPIED / AVAILABLE / MAINTENANCE / BLOCKED
    last_status_change_time = Column(TIMESTAMP, default=utcnow, nullable=False)

    department = relationship("Department", back_populates="beds")


class Staff(Base):
    __tablename__ = "staff"
    staff_id = Column(Integer, primary_key=True)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=False)
    role = Column(String(50), nullable=False)
    shift = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)             # ACTIVE / AVAILABLE / OFF

    department = relationship("Department", back_populates="staff")


class Patient(Base):
    __tablename__ = "patients"
    patient_id = Column(Integer, primary_key=True)
    synthetic_ref = Column(String(50), nullable=False, unique=True)


class Admission(Base):
    __tablename__ = "admissions"
    admission_id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.patient_id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=False)
    bed_id = Column(Integer, ForeignKey("beds.bed_id"), nullable=True)
    admission_type = Column(String(20), nullable=False)      # EMERGENCY / NORMAL
    admission_time = Column(TIMESTAMP, nullable=False)
    discharge_time = Column(TIMESTAMP, nullable=True)
    status = Column(String(20), nullable=False)              # ADMITTED / DISCHARGED


class EmergencyEvent(Base):
    __tablename__ = "emergency_events"
    event_id = Column(Integer, primary_key=True)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=False)
    event_time = Column(TIMESTAMP, nullable=False)
    resulted_admission_id = Column(Integer, ForeignKey("admissions.admission_id"), nullable=True)


class Medicine(Base):
    __tablename__ = "medicines"
    medicine_id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    unit = Column(String(20), nullable=False)
    reorder_threshold = Column(Numeric, nullable=False)


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"
    transaction_id = Column(Integer, primary_key=True)
    medicine_id = Column(Integer, ForeignKey("medicines.medicine_id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=True)
    transaction_type = Column(String(20), nullable=False)     # RESTOCK / CONSUMPTION
    quantity = Column(Numeric, nullable=False)
    transaction_time = Column(TIMESTAMP, nullable=False)


class RevenueTransaction(Base):
    __tablename__ = "revenue_transactions"
    transaction_id = Column(Integer, primary_key=True)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=False)
    admission_id = Column(Integer, ForeignKey("admissions.admission_id"), nullable=True)
    amount = Column(Numeric, nullable=False)
    category = Column(String(50), nullable=True)
    transaction_time = Column(TIMESTAMP, nullable=False)


# ------------------------------------------------------------
# ANALYSIS & DECISION-SUPPORT TABLES (used by later agents)
# ------------------------------------------------------------

class KPIResult(Base):
    __tablename__ = "kpi_results"
    kpi_id = Column(Integer, primary_key=True)
    kpi_name = Column(String(100), nullable=False)
    value = Column(Numeric, nullable=False)
    unit = Column(String(20), nullable=True)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=True)
    period_start = Column(TIMESTAMP, nullable=False)
    period_end = Column(TIMESTAMP, nullable=False)
    calculation_time = Column(TIMESTAMP, default=utcnow, nullable=False)
    data_quality_status = Column(String(20), nullable=True)


class Incident(Base):
    __tablename__ = "incidents"
    incident_id = Column(Integer, primary_key=True)
    kpi_name = Column(String(100), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=True)
    severity = Column(String(20), nullable=False)             # NORMAL / WARNING / CRITICAL
    status = Column(String(20), nullable=False)               # OPEN / ACKNOWLEDGED / RESOLVED
    trigger_value = Column(Numeric, nullable=True)
    threshold_value = Column(Numeric, nullable=True)
    baseline_value = Column(Numeric, nullable=True)
    first_detected_time = Column(TIMESTAMP, nullable=False)
    last_observed_time = Column(TIMESTAMP, nullable=False)
    resolved_time = Column(TIMESTAMP, nullable=True)
    notification_status = Column(String(20), nullable=True)


class Recommendation(Base):
    __tablename__ = "recommendations"
    recommendation_id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.incident_id"), nullable=True)
    text = Column(Text, nullable=False)
    supporting_evidence = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False)
    priority = Column(String(20), nullable=True)
    generated_time = Column(TIMESTAMP, default=utcnow, nullable=False)


class ManagerAction(Base):
    __tablename__ = "manager_actions"
    action_id = Column(Integer, primary_key=True)
    action_type = Column(String(20), nullable=False)          # ACKNOWLEDGE / DISMISS / OVERRIDE
    target_type = Column(String(20), nullable=False)          # INCIDENT / RECOMMENDATION
    target_id = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    action_time = Column(TIMESTAMP, default=utcnow, nullable=False)


# ------------------------------------------------------------
# SYSTEM / RELIABILITY TABLES
# ------------------------------------------------------------

class WorkflowExecutionLog(Base):
    __tablename__ = "workflow_execution_logs"
    execution_id = Column(Integer, primary_key=True)
    workflow_name = Column(String(50), nullable=False)        # DECISION_SUPPORT / MONITORING / HISTORICAL_SIM
    agent_name = Column(String(50), nullable=True)
    start_time = Column(TIMESTAMP, nullable=False)
    end_time = Column(TIMESTAMP, nullable=True)
    status = Column(String(20), nullable=False)                # RUNNING / COMPLETED / PARTIALLY_COMPLETED / FAILED
    error_info = Column(Text, nullable=True)


class DataQualityRecord(Base):
    __tablename__ = "data_quality_records"
    record_id = Column(Integer, primary_key=True)
    source_table = Column(String(50), nullable=False)
    total_records = Column(Integer, nullable=False)
    valid_records = Column(Integer, nullable=False)
    invalid_records = Column(Integer, nullable=False)
    repaired_records = Column(Integer, nullable=False, default=0)
    quarantined_records = Column(Integer, nullable=False, default=0)
    duplicate_records = Column(Integer, nullable=False, default=0)
    window_start = Column(TIMESTAMP, nullable=False)
    window_end = Column(TIMESTAMP, nullable=False)


class QuarantinedRecord(Base):
    __tablename__ = "quarantined_records"
    id = Column(Integer, primary_key=True)
    source_table = Column(String(50), nullable=False)
    raw_payload = Column(JSON, nullable=False)
    reason = Column(Text, nullable=False)
    quarantine_time = Column(TIMESTAMP, default=utcnow, nullable=False)


# ------------------------------------------------------------
# DAILY MANAGER REPORT — DELIVERY TRACKING
# ------------------------------------------------------------

class DailyReportLog(Base):
    """
    One row per Daily Manager Report Agent run.

    Tracks report generation + email delivery so the dashboard's
    'Agent Activity' panel and 'Report Delivery Status' section have
    something real to show, independent of the generic
    workflow_execution_logs table (which only tracks agent runtime,
    not delivery outcome).
    """
    __tablename__ = "daily_report_logs"

    report_id = Column(Integer, primary_key=True)
    report_date = Column(String(20), nullable=False)          # e.g. "2026-09-03"
    triggered_by = Column(String(20), nullable=False, default="SCHEDULER")  # SCHEDULER / MANUAL
    generated_time = Column(TIMESTAMP, nullable=True)
    report_status = Column(String(20), nullable=False)         # COMPLETED / FAILED
    report_error = Column(Text, nullable=True)

    incident_count = Column(Integer, nullable=False, default=0)
    critical_incident_count = Column(Integer, nullable=False, default=0)
    recommendation_count = Column(Integer, nullable=False, default=0)
    action_count = Column(Integer, nullable=False, default=0)

    recipients = Column(Text, nullable=True)                   # comma-separated
    email_status = Column(String(20), nullable=True)           # SENT / FAILED / SKIPPED
    email_sent_time = Column(TIMESTAMP, nullable=True)
    email_error = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)

    report_json = Column(JSON, nullable=True)                  # full report payload, for "View Latest Report"


# ------------------------------------------------------------
# CRITICAL INCIDENT ESCALATION
# ------------------------------------------------------------

class EscalationLog(Base):
    """
    Tracks the escalation lifecycle of a CRITICAL incident that stayed
    OPEN (unacknowledged) past the configured threshold.

    One row per incident that has ever been escalated. While ACTIVE,
    the Escalation Agent re-sends a reminder email every
    ESCALATION_REMINDER_MINUTES. Once a manager acknowledges or
    resolves the underlying incident, this row is marked RESOLVED and
    no further notifications are sent for it.
    """
    __tablename__ = "escalation_logs"

    escalation_id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.incident_id"), nullable=False)

    first_escalated_time = Column(TIMESTAMP, nullable=False)
    last_notified_time = Column(TIMESTAMP, nullable=False)
    notify_count = Column(Integer, nullable=False, default=1)

    channel = Column(String(20), nullable=False, default="EMAIL")
    status = Column(String(20), nullable=False, default="ACTIVE")  # ACTIVE / RESOLVED
    resolved_time = Column(TIMESTAMP, nullable=True)
