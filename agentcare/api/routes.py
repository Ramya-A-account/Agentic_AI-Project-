from datetime import datetime, timedelta
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from agentcare.db import get_session
from agentcare.api.schemas import ManagerActionRequest


router = APIRouter(prefix="/api")


def normalize_report_payload(report_json):
    """Normalize report payloads stored as JSON strings or partial dicts.

    SQLite and some storage adapters may return JSON columns as strings
    instead of Python dicts, and older rows may be missing nested sections.
    This helper coerces the payload back into a stable dictionary shape so
    the dashboard and API do not render empty sections for a valid report.
    """
    default_payload = {
        "kpi_summary": {},
        "incident_summary": {
            "total": 0,
            "critical": 0,
            "warning": 0,
            "incidents": [],
        },
        "recommendation_summary": {
            "total": 0,
            "high_priority": 0,
            "recommendations": [],
        },
        "manager_action_summary": {
            "total": 0,
            "actions": [],
        },
        "departments": [],
    }

    if report_json is None:
        return default_payload

    if isinstance(report_json, (bytes, bytearray)):
        report_json = report_json.decode("utf-8")

    if isinstance(report_json, str):
        try:
            report_json = json.loads(report_json)
        except (TypeError, ValueError):
            return default_payload

    if not isinstance(report_json, dict):
        return default_payload

    normalized = dict(report_json)
    normalized.setdefault("kpi_summary", {})
    normalized.setdefault("incident_summary", {})
    normalized.setdefault("recommendation_summary", {})
    normalized.setdefault("manager_action_summary", {})
    normalized.setdefault("departments", [])

    if not isinstance(normalized["kpi_summary"], dict):
        normalized["kpi_summary"] = {}

    incident_summary = normalized["incident_summary"]
    if not isinstance(incident_summary, dict):
        incident_summary = {}
    incident_summary.setdefault("total", len(incident_summary.get("incidents", []) or []))
    incident_summary.setdefault("critical", 0)
    incident_summary.setdefault("warning", 0)
    incident_summary.setdefault("incidents", [])
    normalized["incident_summary"] = incident_summary

    recommendation_summary = normalized["recommendation_summary"]
    if not isinstance(recommendation_summary, dict):
        recommendation_summary = {}
    recommendation_summary.setdefault("total", len(recommendation_summary.get("recommendations", []) or []))
    recommendation_summary.setdefault("high_priority", 0)
    recommendation_summary.setdefault("recommendations", [])
    normalized["recommendation_summary"] = recommendation_summary

    manager_action_summary = normalized["manager_action_summary"]
    if not isinstance(manager_action_summary, dict):
        manager_action_summary = {}
    manager_action_summary.setdefault("total", len(manager_action_summary.get("actions", []) or []))
    manager_action_summary.setdefault("actions", [])
    normalized["manager_action_summary"] = manager_action_summary

    if not isinstance(normalized["departments"], list):
        normalized["departments"] = []

    return normalized


# ============================================================
# DATABASE DEPENDENCY
# ============================================================

def get_db():
    db = get_session()

    try:
        yield db
    finally:
        db.close()


# ============================================================
# SYSTEM STATUS
# ============================================================

@router.get("/system/status")
def system_status(db: Session = Depends(get_db)):

    try:
        db.execute(text("SELECT 1")).scalar()

        tables = {}

        for table in [
            "admissions",
            "emergency_events",
            "kpi_results",
            "incidents",
            "recommendations",
            "workflow_execution_logs",
        ]:
            tables[table] = db.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar() or 0

        return {
            "backend": "ONLINE",
            "database": "CONNECTED",
            "agent_data": {
                "admissions": tables["admissions"],
                "emergency_events": tables["emergency_events"],
                "kpis": tables["kpi_results"],
                "incidents": tables["incidents"],
                "recommendations": tables["recommendations"],
                "workflow_logs": tables["workflow_execution_logs"],
            }
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database connection failed: {str(e)}"
        )


# ============================================================
# DASHBOARD SUMMARY
# ============================================================

@router.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):

    now = datetime.utcnow()
    last_24h = now - timedelta(hours=24)

    # --------------------------------------------------------
    # HOSPITAL BEDS
    # --------------------------------------------------------

    total_beds = db.execute(
        text("""
            SELECT COUNT(*)
            FROM beds
            WHERE status != 'MAINTENANCE'
        """)
    ).scalar() or 0

    occupied_beds = db.execute(
        text("""
            SELECT COUNT(*)
            FROM beds
            WHERE status = 'OCCUPIED'
        """)
    ).scalar() or 0

    available_beds = total_beds - occupied_beds

    occupancy_percent = (
        occupied_beds / total_beds * 100
    ) if total_beds else 0

    # --------------------------------------------------------
    # ICU
    # --------------------------------------------------------

    icu_total = db.execute(
        text("""
            SELECT COUNT(*)
            FROM beds
            WHERE bed_type = 'ICU'
        """)
    ).scalar() or 0

    icu_occupied = db.execute(
        text("""
            SELECT COUNT(*)
            FROM beds
            WHERE bed_type = 'ICU'
              AND status = 'OCCUPIED'
        """)
    ).scalar() or 0

    icu_available = icu_total - icu_occupied

    icu_occupancy = (
        icu_occupied / icu_total * 100
    ) if icu_total else 0

    # --------------------------------------------------------
    # 24 HOUR PATIENT FLOW
    # --------------------------------------------------------

    admissions_24h = db.execute(
        text("""
            SELECT COUNT(*)
            FROM admissions
            WHERE admission_time >= :start
        """),
        {"start": last_24h}
    ).scalar() or 0

    discharges_24h = db.execute(
        text("""
            SELECT COUNT(*)
            FROM admissions
            WHERE discharge_time >= :start
        """),
        {"start": last_24h}
    ).scalar() or 0

    emergency_24h = db.execute(
        text("""
            SELECT COUNT(*)
            FROM emergency_events
            WHERE event_time >= :start
        """),
        {"start": last_24h}
    ).scalar() or 0

    total_admissions = db.execute(
        text("""
            SELECT COUNT(*)
            FROM admissions
        """)
    ).scalar() or 0

    total_discharges = db.execute(
        text("""
            SELECT COUNT(*)
            FROM admissions
            WHERE discharge_time IS NOT NULL
        """)
    ).scalar() or 0

    # --------------------------------------------------------
    # REVENUE
    # --------------------------------------------------------

    revenue = db.execute(
        text("""
            SELECT COALESCE(SUM(amount), 0)
            FROM revenue_transactions
        """)
    ).scalar() or 0

    # --------------------------------------------------------
    # INCIDENTS
    # --------------------------------------------------------

    critical_incidents = db.execute(
        text("""
            SELECT COUNT(*)
            FROM incidents
            WHERE severity = 'CRITICAL'
              AND status != 'RESOLVED'
        """)
    ).scalar() or 0

    warning_incidents = db.execute(
        text("""
            SELECT COUNT(*)
            FROM incidents
            WHERE severity = 'WARNING'
              AND status != 'RESOLVED'
        """)
    ).scalar() or 0

    active_incidents = db.execute(
        text("""
            SELECT COUNT(*)
            FROM incidents
            WHERE status != 'RESOLVED'
        """)
    ).scalar() or 0

    # --------------------------------------------------------
    # RETURN DASHBOARD STRUCTURE
    # --------------------------------------------------------

    return {

        "hospital": {
            "total_beds": total_beds,
            "occupied_beds": occupied_beds,
            "available_beds": available_beds,
            "occupancy_percent": round(
                occupancy_percent, 2
            )
        },

        "icu": {
            "total_beds": icu_total,
            "occupied_beds": icu_occupied,
            "available_beds": icu_available,
            "occupancy_percent": round(
                icu_occupancy, 2
            )
        },

        "patient_flow": {
            "admissions_24h": admissions_24h,
            "discharges_24h": discharges_24h,
            "emergency_events_24h": emergency_24h,
            "total_admissions": total_admissions,
            "total_discharges": total_discharges
        },

        "alerts": {
            "critical": critical_incidents,
            "warning": warning_incidents,
            "active": active_incidents
        },

        "revenue": float(revenue)
    }


# ============================================================
# DEPARTMENTS
# ============================================================

@router.get("/dashboard/departments")
def departments(db: Session = Depends(get_db)):

    rows = db.execute(
        text("""
            SELECT
                d.department_id,
                d.name,
                d.total_beds,

                COUNT(
                    CASE
                        WHEN b.status = 'OCCUPIED'
                        THEN 1
                    END
                ) AS occupied_beds,

                COUNT(
                    CASE
                        WHEN b.status != 'OCCUPIED'
                         AND b.status != 'MAINTENANCE'
                        THEN 1
                    END
                ) AS available_beds

            FROM departments d

            LEFT JOIN beds b
                ON d.department_id = b.department_id

            GROUP BY
                d.department_id,
                d.name,
                d.total_beds

            ORDER BY d.department_id
        """)
    ).mappings().all()

    result = []

    for row in rows:

        total = row["total_beds"] or 0
        occupied = row["occupied_beds"] or 0
        available = row["available_beds"] or 0

        occupancy = (
            occupied / total * 100
        ) if total else 0

        if occupancy >= 95:
            status = "CRITICAL"

        elif occupancy >= 85:
            status = "WARNING"

        else:
            status = "NORMAL"

        result.append({
            "department_id": row["department_id"],
            "name": row["name"],
            "total_beds": total,
            "occupied_beds": occupied,
            "available_beds": available,
            "occupancy": round(occupancy, 2),
            "status": status
        })

    return result


# ============================================================
# KPI TRENDS
# ============================================================

@router.get("/dashboard/trends")
def trends(
    kpi_name: str | None = None,
    department_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):

    query = """
        SELECT
            kpi_id,
            kpi_name,
            value,
            unit,
            department_id,
            period_start,
            period_end,
            calculation_time,
            data_quality_status
        FROM kpi_results
        WHERE 1=1
    """

    params = {}

    if kpi_name:
        query += " AND kpi_name = :kpi_name"
        params["kpi_name"] = kpi_name

    if department_id:
        query += " AND department_id = :department_id"
        params["department_id"] = department_id

    query += """
        ORDER BY calculation_time DESC
        LIMIT :limit
    """

    params["limit"] = limit

    rows = db.execute(
        text(query),
        params
    ).mappings().all()

    return [dict(row) for row in rows]


# ============================================================
# INCIDENTS
# ============================================================

@router.get("/incidents")
def get_incidents(
    status: str | None = None,
    severity: str | None = None,
    department_id: int | None = None,
    db: Session = Depends(get_db)
):

    query = """
        SELECT
            i.incident_id,
            i.kpi_name,
            i.department_id,
            d.name AS department_name,
            i.severity,
            i.status,
            i.trigger_value,
            i.threshold_value,
            i.baseline_value,
            i.first_detected_time,
            i.last_observed_time,
            i.resolved_time,
            i.notification_status

        FROM incidents i

        LEFT JOIN departments d
            ON i.department_id = d.department_id

        WHERE 1=1
    """

    params = {}

    if status:
        query += " AND i.status = :status"
        params["status"] = status

    if severity:
        query += " AND i.severity = :severity"
        params["severity"] = severity

    if department_id:
        query += " AND i.department_id = :department_id"
        params["department_id"] = department_id

    query += """
        ORDER BY i.first_detected_time DESC
    """

    rows = db.execute(
        text(query),
        params
    ).mappings().all()

    return [dict(row) for row in rows]


@router.get("/incidents/{incident_id}")
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db)
):

    row = db.execute(
        text("""
            SELECT
                i.*,
                d.name AS department_name

            FROM incidents i

            LEFT JOIN departments d
                ON i.department_id = d.department_id

            WHERE i.incident_id = :id
        """),
        {"id": incident_id}
    ).mappings().first()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Incident not found"
        )

    return dict(row)


# ============================================================
# RECOMMENDATIONS
# ============================================================

@router.get("/recommendations")
def get_recommendations(
    status: str | None = None,
    priority: str | None = None,
    db: Session = Depends(get_db)
):

    query = """
        SELECT
            r.recommendation_id,
            r.incident_id,
            r.text,
            r.supporting_evidence,
            r.status,
            r.priority,
            r.generated_time

        FROM recommendations r

        WHERE 1=1
    """

    params = {}

    if status:
        query += " AND r.status = :status"
        params["status"] = status

    if priority:
        query += " AND r.priority = :priority"
        params["priority"] = priority

    query += """
        ORDER BY r.generated_time DESC
    """

    rows = db.execute(
        text(query),
        params
    ).mappings().all()

    return [dict(row) for row in rows]


@router.get("/recommendations/{recommendation_id}")
def get_recommendation(
    recommendation_id: int,
    db: Session = Depends(get_db)
):

    row = db.execute(
        text("""
            SELECT
                r.*,
                i.kpi_name,
                i.severity,
                i.trigger_value,
                i.threshold_value

            FROM recommendations r

            LEFT JOIN incidents i
                ON r.incident_id = i.incident_id

            WHERE r.recommendation_id = :id
        """),
        {"id": recommendation_id}
    ).mappings().first()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Recommendation not found"
        )

    return dict(row)


# ============================================================
# MANAGER ACTIONS - POST
# ============================================================

@router.post("/manager-actions")
def manager_action(
    request: ManagerActionRequest,
    db: Session = Depends(get_db)
):

    action = request.action_type.upper()
    target_type = request.target_type.upper()

    allowed_actions = {

        "INCIDENT": {
            "ACKNOWLEDGE",
            "RESOLVE",
            "DISMISS"
        },

        "RECOMMENDATION": {
            "ACCEPT",
            "REJECT",
            "ACKNOWLEDGE",
            "RESOLVE"
        }
    }

    if target_type not in allowed_actions:
        raise HTTPException(
            status_code=400,
            detail="Invalid target_type"
        )

    if action not in allowed_actions[target_type]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{action}' for {target_type}"
        )

    # --------------------------------------------------------
    # INCIDENT
    # --------------------------------------------------------

    if target_type == "INCIDENT":

        exists = db.execute(
            text("""
                SELECT COUNT(*)
                FROM incidents
                WHERE incident_id = :id
            """),
            {"id": request.target_id}
        ).scalar()

        if not exists:
            raise HTTPException(
                status_code=404,
                detail="Incident not found"
            )

        if action == "ACKNOWLEDGE":

            db.execute(
                text("""
                    UPDATE incidents
                    SET status = 'ACKNOWLEDGED'
                    WHERE incident_id = :id
                """),
                {"id": request.target_id}
            )

        elif action in ("RESOLVE", "DISMISS"):

            db.execute(
                text("""
                    UPDATE incidents
                    SET
                        status = 'RESOLVED',
                        resolved_time = CURRENT_TIMESTAMP
                    WHERE incident_id = :id
                """),
                {"id": request.target_id}
            )

    # --------------------------------------------------------
    # RECOMMENDATION
    # --------------------------------------------------------

    elif target_type == "RECOMMENDATION":

        exists = db.execute(
            text("""
                SELECT COUNT(*)
                FROM recommendations
                WHERE recommendation_id = :id
            """),
            {"id": request.target_id}
        ).scalar()

        if not exists:
            raise HTTPException(
                status_code=404,
                detail="Recommendation not found"
            )

        if action in ("ACCEPT", "ACKNOWLEDGE"):

            db.execute(
                text("""
                    UPDATE recommendations
                    SET status = 'ACCEPTED'
                    WHERE recommendation_id = :id
                """),
                {"id": request.target_id}
            )

        elif action == "REJECT":

            db.execute(
                text("""
                    UPDATE recommendations
                    SET status = 'REJECTED'
                    WHERE recommendation_id = :id
                """),
                {"id": request.target_id}
            )

        elif action == "RESOLVE":

            db.execute(
                text("""
                    UPDATE recommendations
                    SET status = 'RESOLVED'
                    WHERE recommendation_id = :id
                """),
                {"id": request.target_id}
            )

    # --------------------------------------------------------
    # SAVE MANAGER ACTION
    # --------------------------------------------------------

    db.execute(
        text("""
            INSERT INTO manager_actions
            (
                action_type,
                target_type,
                target_id,
                comment,
                action_time
            )

            VALUES
            (
                :action_type,
                :target_type,
                :target_id,
                :comment,
                CURRENT_TIMESTAMP
            )
        """),
        {
            "action_type": action,
            "target_type": target_type,
            "target_id": request.target_id,
            "comment": request.comment
        }
    )

    db.commit()

    return {
        "status": "SUCCESS",
        "message": "Manager action recorded",
        "action_type": action,
        "target_type": target_type,
        "target_id": request.target_id
    }


# ============================================================
# MANAGER ACTION HISTORY - GET
# ============================================================

@router.get("/manager-actions")
def manager_actions(db: Session = Depends(get_db)):

    rows = db.execute(
        text("""
            SELECT
                action_id,
                action_type,
                target_type,
                target_id,
                comment,
                action_time

            FROM manager_actions

            ORDER BY action_time DESC

            LIMIT 100
        """)
    ).mappings().all()

    return [dict(row) for row in rows]


# ============================================================
# DATA QUALITY
# ============================================================

@router.get("/data-quality")
def data_quality(db: Session = Depends(get_db)):

    rows = db.execute(
        text("""
            SELECT
                record_id,
                source_table,
                total_records,
                valid_records,
                invalid_records,
                repaired_records,
                quarantined_records,
                duplicate_records,
                window_start,
                window_end

            FROM data_quality_records

            ORDER BY window_end DESC
        """)
    ).mappings().all()

    result = []

    for row in rows:

        total = row["total_records"] or 0
        valid = row["valid_records"] or 0

        quality_score = (
            valid / total * 100
        ) if total else 100

        result.append({
            **dict(row),
            "quality_score": round(
                quality_score, 2
            )
        })

    return result


# ============================================================
# QUARANTINED RECORDS
# ============================================================

@router.get("/data-quality/quarantined")
def quarantined_records(db: Session = Depends(get_db)):

    rows = db.execute(
        text("""
            SELECT
                id,
                source_table,
                raw_payload,
                reason,
                quarantine_time

            FROM quarantined_records

            ORDER BY quarantine_time DESC
        """)
    ).mappings().all()

    return [dict(row) for row in rows]


# ============================================================
# WORKFLOW - LATEST
# ============================================================

@router.get("/workflow/latest")
def latest_workflow(db: Session = Depends(get_db)):

    rows = db.execute(
        text("""
            SELECT
                execution_id,
                workflow_name,
                agent_name,
                start_time,
                end_time,
                status,
                error_info

            FROM workflow_execution_logs

            ORDER BY execution_id DESC

            LIMIT 10
        """)
    ).mappings().all()

    result = []

    for row in rows:

        data = dict(row)

        if data["start_time"] and data["end_time"]:

            data["duration_seconds"] = (
                data["end_time"] -
                data["start_time"]
            ).total_seconds()

        else:
            data["duration_seconds"] = None

        result.append(data)

    return result


# ============================================================
# WORKFLOW - HISTORY
# ============================================================

@router.get("/workflow/history")
def workflow_history(db: Session = Depends(get_db)):

    rows = db.execute(
        text("""
            SELECT
                execution_id,
                workflow_name,
                agent_name,
                start_time,
                end_time,
                status,
                error_info

            FROM workflow_execution_logs

            ORDER BY execution_id DESC

            LIMIT 100
        """)
    ).mappings().all()

    result = []

    for row in rows:

        data = dict(row)

        if data["start_time"] and data["end_time"]:

            data["duration_seconds"] = (
                data["end_time"] -
                data["start_time"]
            ).total_seconds()

        else:
            data["duration_seconds"] = None

        result.append(data)

    return result


# ============================================================
# INVENTORY
# ============================================================

@router.get("/inventory")
def inventory(db: Session = Depends(get_db)):

    rows = db.execute(
        text("""
            SELECT
                m.medicine_id,
                m.name,
                m.unit,
                m.reorder_threshold,

                COALESCE(
                    SUM(
                        CASE
                            WHEN it.transaction_type = 'RESTOCK'
                            THEN it.quantity
                            ELSE 0
                        END
                    ),
                    0
                )

                -

                COALESCE(
                    SUM(
                        CASE
                            WHEN it.transaction_type = 'CONSUMPTION'
                            THEN it.quantity
                            ELSE 0
                        END
                    ),
                    0
                ) AS current_stock

            FROM medicines m

            LEFT JOIN inventory_transactions it
                ON m.medicine_id = it.medicine_id

            GROUP BY
                m.medicine_id,
                m.name,
                m.unit,
                m.reorder_threshold

            ORDER BY m.name
        """)
    ).mappings().all()

    result = []

    for row in rows:

        stock = float(
            row["current_stock"] or 0
        )

        threshold = float(
            row["reorder_threshold"] or 0
        )

        if stock <= 0:
            status = "OUT_OF_STOCK"

        elif stock <= threshold:
            status = "LOW"

        else:
            status = "NORMAL"

        result.append({
            "medicine_id": row["medicine_id"],
            "name": row["name"],
            "unit": row["unit"],
            "stock": stock,
            "threshold": threshold,
            "status": status
        })

    return result


# ============================================================
# STAFF
# ============================================================

@router.get("/staff")
def staff(db: Session = Depends(get_db)):

    rows = db.execute(
        text("""
            SELECT
                d.department_id,
                d.name,

                COUNT(s.staff_id) AS total_staff,

                COUNT(
                    CASE
                        WHEN s.status IN ('AVAILABLE', 'ACTIVE')
                        THEN 1
                    END
                ) AS available_staff,

                COUNT(
                    CASE
                        WHEN s.status = 'ACTIVE'
                        THEN 1
                    END
                ) AS active_staff

            FROM departments d

            LEFT JOIN staff s
                ON d.department_id = s.department_id

            GROUP BY
                d.department_id,
                d.name

            ORDER BY d.department_id
        """)
    ).mappings().all()

    return [dict(row) for row in rows]


# ============================================================
# ANALYTICS
# ============================================================

@router.get("/analytics")
def analytics(
    kpi_name: str | None = None,
    department_id: int | None = None,
    db: Session = Depends(get_db)
):

    query = """
        SELECT
            kpi_id,
            kpi_name,
            value,
            unit,
            department_id,
            period_start,
            period_end,
            calculation_time,
            data_quality_status

        FROM kpi_results

        WHERE 1=1
    """

    params = {}

    if kpi_name:
        query += " AND kpi_name = :kpi_name"
        params["kpi_name"] = kpi_name

    if department_id:
        query += " AND department_id = :department_id"
        params["department_id"] = department_id

    query += """
        ORDER BY calculation_time DESC
        LIMIT 500
    """

    rows = db.execute(
        text(query),
        params
    ).mappings().all()

    return [dict(row) for row in rows]


# ============================================================
# AGENT ACTIVITY — Daily Manager Report Agent + pipeline monitor
# ============================================================

PIPELINE_AGENTS = [
    ("SimulationAgent", "Simulation", "MONITORING"),
    ("DataCleaningAgent", "Data Cleaning", "MONITORING"),
    ("AnalysisAgent", "Analysis", "MONITORING"),
    ("AlertDetectionAgent", "Alert Detection", "MONITORING"),
    ("RecommendationAgent", "Recommendation", "MONITORING"),
    ("DailyManagerReportAgent", "Daily Manager Report", "DAILY_REPORT"),
    ("EmailDeliveryAgent", "Email Delivery", "DAILY_REPORT"),
]


def _next_scheduled_report_time():
    """Next 7:00 PM IST run, formatted for the dashboard."""
    from zoneinfo import ZoneInfo

    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    today_seven_pm = now_ist.replace(hour=19, minute=0, second=0, microsecond=0)

    if now_ist >= today_seven_pm:
        next_run = today_seven_pm + timedelta(days=1)
        label = f"Tomorrow at 7:00 PM"
    else:
        next_run = today_seven_pm
        label = "Today at 7:00 PM"

    return {
        "iso": next_run.isoformat(),
        "label": label,
    }


def _parse_timestamp(value):
    """SQLite returns TIMESTAMP columns as plain strings via raw SQL text()
    queries (only the ORM layer applies automatic type conversion), so we
    need to parse them ourselves before doing datetime arithmetic."""
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value.strip()
        # SQLite sometimes stores a space instead of 'T' between date/time
        s = s.replace(" ", "T", 1) if "T" not in s else s
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None
    return None


@router.get("/agent/pipeline")
def agent_pipeline(db: Session = Depends(get_db)):
    """Latest status + duration for every stage of the pipeline, in order."""

    result = []

    for agent_name, display_name, workflow_name in PIPELINE_AGENTS:
        row = db.execute(
            text("""
                SELECT execution_id, start_time, end_time, status, error_info
                FROM workflow_execution_logs
                WHERE agent_name = :agent_name
                  AND workflow_name = :workflow_name
                ORDER BY execution_id DESC
                LIMIT 1
            """),
            {"agent_name": agent_name, "workflow_name": workflow_name}
        ).mappings().first()

        if row is None:
            result.append({
                "agent_name": agent_name,
                "display_name": display_name,
                "status": "IDLE",
                "last_start_time": None,
                "last_end_time": None,
                "duration_seconds": None,
                "error_info": None,
            })
            continue

        start_time = _parse_timestamp(row["start_time"])
        end_time = _parse_timestamp(row["end_time"])

        duration = None
        if start_time and end_time:
            duration = (end_time - start_time).total_seconds()

        status = row["status"]
        if status == "RUNNING":
            display_status = "RUNNING"
        elif status == "COMPLETED":
            display_status = "COMPLETED"
        elif status == "FAILED":
            display_status = "FAILED"
        else:
            display_status = status or "IDLE"

        result.append({
            "agent_name": agent_name,
            "display_name": display_name,
            "status": display_status,
            "last_start_time": row["start_time"],
            "last_end_time": row["end_time"],
            "duration_seconds": duration,
            "error_info": row["error_info"],
        })

    return result


@router.get("/agent/report/status")
def daily_report_status(db: Session = Depends(get_db)):
    """Status for the Agent Activity panel (Daily Manager Report Agent)."""

    workflow_row = db.execute(
        text("""
            SELECT execution_id, start_time, end_time, status, error_info
            FROM workflow_execution_logs
            WHERE agent_name = 'DailyManagerReportAgent'
            ORDER BY execution_id DESC
            LIMIT 1
        """)
    ).mappings().first()

    report_row = db.execute(
        text("""
            SELECT
                report_id, report_date, triggered_by, generated_time,
                report_status, report_error, incident_count,
                critical_incident_count, recommendation_count, action_count,
                recipients, email_status, email_sent_time, email_error,
                retry_count
            FROM daily_report_logs
            ORDER BY report_id DESC
            LIMIT 1
        """)
    ).mappings().first()

    status = "IDLE"
    if workflow_row is not None:
        status = workflow_row["status"] or "IDLE"

    next_scheduled = _next_scheduled_report_time()

    from agentcare.agents import llm_reasoning

    return {
        "agent_name": "Daily Manager Report Agent",
        "status": status,
        "last_execution_time": workflow_row["end_time"] if workflow_row else None,
        "next_scheduled_execution": next_scheduled["iso"],
        "next_scheduled_label": next_scheduled["label"],
        "report_date": report_row["report_date"] if report_row else None,
        "incident_count": report_row["incident_count"] if report_row else 0,
        "critical_incident_count": report_row["critical_incident_count"] if report_row else 0,
        "recommendation_count": report_row["recommendation_count"] if report_row else 0,
        "action_count": report_row["action_count"] if report_row else 0,
        "generated_time": report_row["generated_time"] if report_row else None,
        "recipients": report_row["recipients"] if report_row else None,
        "email_status": report_row["email_status"] if report_row else None,
        "email_sent_time": report_row["email_sent_time"] if report_row else None,
        "email_error": report_row["email_error"] if report_row else None,
        "retry_count": report_row["retry_count"] if report_row else 0,
        "report_error": report_row["report_error"] if report_row else None,
        "llm_provider": llm_reasoning.provider_name(),
        "llm_active": llm_reasoning.is_available(),
        "llm_last_error": llm_reasoning.last_error(),
    }


@router.post("/agent/report/run-now")
def run_report_now(db: Session = Depends(get_db)):
    """Manual 'Run Now' trigger for the Daily Manager Report Agent."""
    from agentcare.services.daily_report_service import run_daily_report

    result = run_daily_report(db, triggered_by="MANUAL", send_email=True)

    if result["status"] != "SUCCESS":
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Report generation failed"),
        )

    return {
        "status": "SUCCESS",
        "email_status": result["email_status"],
        "report_log_id": result["report_log_id"],
        "report": result["report"],
    }


@router.get("/agent/report/latest")
def latest_report(db: Session = Depends(get_db)):
    """Full JSON of the most recently generated report, for 'View Latest Report'."""

    row = db.execute(
        text("""
            SELECT report_id, report_date, generated_time, report_status, report_json
            FROM daily_report_logs
            WHERE report_status = 'COMPLETED'
            ORDER BY report_id DESC
            LIMIT 1
        """)
    ).mappings().first()

    if not row or not row["report_json"]:
        raise HTTPException(status_code=404, detail="No report has been generated yet")

    # SQLite returns JSON columns as raw strings via raw SQL text() queries
    # (only the ORM layer auto-deserializes) — parse it back into an
    # object, or the dashboard ends up trying to read fields off a string.
    report_json = normalize_report_payload(row["report_json"])

    return {
        "report_id": row["report_id"],
        "report_date": row["report_date"],
        "generated_time": row["generated_time"],
        "report": report_json,
    }


@router.get("/agent/report/history")
def report_history(db: Session = Depends(get_db)):
    """Delivery-tracking history for the 'Report Delivery Status' panel."""

    rows = db.execute(
        text("""
            SELECT
                report_id, report_date, triggered_by, generated_time,
                report_status, incident_count, critical_incident_count,
                recommendation_count, action_count, recipients,
                email_status, email_sent_time, email_error, retry_count
            FROM daily_report_logs
            ORDER BY report_id DESC
            LIMIT 30
        """)
    ).mappings().all()

    return [dict(row) for row in rows]


# ============================================================
# CRITICAL INCIDENT ESCALATION
# ============================================================

@router.get("/escalations/active")
def active_escalations(db: Session = Depends(get_db)):
    """Currently unacknowledged CRITICAL incidents that have been
    escalated — this is what powers the dashboard's loud alert banner.

    Resolves any escalation whose underlying incident has since been
    acknowledged/resolved before returning results, so the banner
    reflects reality on every poll rather than only after the next
    scheduled escalation check or a manual 'Check Escalations Now'.
    """

    db.execute(
        text("""
            UPDATE escalation_logs
            SET status = 'RESOLVED', resolved_time = CURRENT_TIMESTAMP
            WHERE status = 'ACTIVE'
              AND incident_id IN (
                  SELECT incident_id FROM incidents WHERE status != 'OPEN'
              )
        """)
    )
    db.commit()

    rows = db.execute(
        text("""
            SELECT
                e.escalation_id,
                e.incident_id,
                e.first_escalated_time,
                e.last_notified_time,
                e.notify_count,
                i.kpi_name,
                i.department_id,
                d.name AS department_name,
                i.trigger_value,
                i.threshold_value,
                i.first_detected_time
            FROM escalation_logs e
            JOIN incidents i ON i.incident_id = e.incident_id
            LEFT JOIN departments d ON d.department_id = i.department_id
            WHERE e.status = 'ACTIVE'
            ORDER BY e.first_escalated_time ASC
        """)
    ).mappings().all()

    return [dict(row) for row in rows]


@router.post("/escalations/check-now")
def check_escalations_now(db: Session = Depends(get_db)):
    """Manually trigger the Escalation Agent (mainly for testing/demo —
    it normally runs automatically every few minutes via the scheduler)."""
    from agentcare.agents.escalation_agent import EscalationAgent

    result = EscalationAgent(db).run()

    if result["status"] != "SUCCESS":
        raise HTTPException(status_code=500, detail=result.get("error", "Escalation check failed"))

    return result


# ============================================================
# ROOT API
# ============================================================

@router.get("/")
def api_root():

    return {
        "system": "AgentCare AI",
        "backend": "FastAPI",
        "status": "ONLINE",
        "version": "1.0.0",

        "modules": [
            "Dashboard",
            "Departments",
            "Incidents",
            "AI Recommendations",
            "Manager Actions",
            "Analytics",
            "Data Quality",
            "Workflow Monitor",
            "Inventory",
            "Staff"
        ]
    }