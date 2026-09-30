"""
AgentCare Escalation Agent

This is the most genuinely autonomous piece of the pipeline: unlike the
other agents, which run on a fixed schedule and produce a report for a
human to read, this one makes an independent decision — "this needs to
be escalated right now" — without anyone asking it to.

Logic:
  - Find every incident that is severity=CRITICAL, status=OPEN (i.e.
    nobody has acknowledged or resolved it), and has been open longer
    than ESCALATION_THRESHOLD_MINUTES.
  - For each one that hasn't been escalated yet, send an urgent email
    and create an EscalationLog row.
  - For each one already escalated and still unacknowledged, re-send a
    reminder every ESCALATION_REMINDER_MINUTES (so managers can't just
    ignore the first email and have it go away).
  - For each escalation whose underlying incident has since been
    acknowledged/resolved, mark it RESOLVED so it stops nagging.

This agent is meant to run frequently (every few minutes) via the
scheduler — much more often than the 30-minute monitoring cycle —
since the whole point is to catch things quickly.
"""

from datetime import datetime, timedelta

from sqlalchemy import text

from agentcare.config import ESCALATION_REMINDER_MINUTES, ESCALATION_THRESHOLD_MINUTES
from agentcare.email_reports import send_escalation_email


def utcnow():
    return datetime.utcnow()


def _parse_timestamp(value):
    """SQLite returns TIMESTAMP columns as plain strings via raw SQL
    text() queries, so datetime arithmetic needs them parsed first."""
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value.strip().replace(" ", "T", 1)
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None
    return None


class EscalationAgent:

    def __init__(self, session):
        self.session = session

    # ------------------------------------------------------------
    # Find incidents that need escalating
    # ------------------------------------------------------------

    def _get_overdue_critical_incidents(self):
        cutoff = utcnow() - timedelta(minutes=ESCALATION_THRESHOLD_MINUTES)

        return self.session.execute(
            text("""
                SELECT
                    i.incident_id,
                    i.kpi_name,
                    i.department_id,
                    d.name AS department_name,
                    i.severity,
                    i.status,
                    i.trigger_value,
                    i.threshold_value,
                    i.first_detected_time
                FROM incidents i
                LEFT JOIN departments d
                    ON i.department_id = d.department_id
                WHERE i.severity = 'CRITICAL'
                  AND i.status = 'OPEN'
                  AND i.first_detected_time <= :cutoff
                ORDER BY i.first_detected_time ASC
            """),
            {"cutoff": cutoff},
        ).mappings().all()

    def _get_active_escalation(self, incident_id):
        return self.session.execute(
            text("""
                SELECT escalation_id, first_escalated_time, last_notified_time, notify_count
                FROM escalation_logs
                WHERE incident_id = :incident_id AND status = 'ACTIVE'
            """),
            {"incident_id": incident_id},
        ).mappings().first()

    # ------------------------------------------------------------
    # Resolve escalations whose incident is no longer OPEN
    # ------------------------------------------------------------

    def _resolve_stale_escalations(self):
        resolved = self.session.execute(
            text("""
                SELECT e.escalation_id
                FROM escalation_logs e
                JOIN incidents i ON i.incident_id = e.incident_id
                WHERE e.status = 'ACTIVE' AND i.status != 'OPEN'
            """)
        ).mappings().all()

        for row in resolved:
            self.session.execute(
                text("""
                    UPDATE escalation_logs
                    SET status = 'RESOLVED', resolved_time = :now
                    WHERE escalation_id = :escalation_id
                """),
                {"now": utcnow(), "escalation_id": row["escalation_id"]},
            )

        self.session.commit()
        return len(resolved)

    # ------------------------------------------------------------
    # Main
    # ------------------------------------------------------------

    def run(self):
        print("\n" + "=" * 70)
        print("AGENTCARE ESCALATION AGENT")
        print("=" * 70)

        try:
            resolved_count = self._resolve_stale_escalations()
            if resolved_count:
                print(f"\n✅ {resolved_count} escalation(s) resolved (incident acknowledged/resolved).")

            overdue = self._get_overdue_critical_incidents()

            if not overdue:
                print(f"\nNo CRITICAL incidents open longer than {ESCALATION_THRESHOLD_MINUTES} minutes.")
                return {
                    "status": "SUCCESS",
                    "escalated_new": 0,
                    "reminders_sent": 0,
                    "resolved": resolved_count,
                }

            print(f"\nOverdue CRITICAL incidents: {len(overdue)}")

            escalated_new = 0
            reminders_sent = 0
            now = utcnow()

            for incident in overdue:
                existing = self._get_active_escalation(incident["incident_id"])

                if existing is None:
                    # First time this incident is being escalated
                    self.session.execute(
                        text("""
                            INSERT INTO escalation_logs
                                (incident_id, first_escalated_time, last_notified_time, notify_count, channel, status)
                            VALUES
                                (:incident_id, :now, :now, 1, 'EMAIL', 'ACTIVE')
                        """),
                        {"incident_id": incident["incident_id"], "now": now},
                    )
                    self.session.commit()

                    self._send_escalation(incident, notify_count=1, minutes_open=self._minutes_open(incident))
                    escalated_new += 1

                    print(f"🚨 NEW ESCALATION | Incident {incident['incident_id']} | "
                          f"{incident['department_name'] or 'Hospital-wide'} | {incident['kpi_name']}")

                else:
                    last_notified = _parse_timestamp(existing["last_notified_time"])
                    minutes_since_last_notify = (now - last_notified).total_seconds() / 60

                    if minutes_since_last_notify >= ESCALATION_REMINDER_MINUTES:
                        notify_count = existing["notify_count"] + 1

                        self.session.execute(
                            text("""
                                UPDATE escalation_logs
                                SET last_notified_time = :now, notify_count = :notify_count
                                WHERE escalation_id = :escalation_id
                            """),
                            {"now": now, "notify_count": notify_count, "escalation_id": existing["escalation_id"]},
                        )
                        self.session.commit()

                        self._send_escalation(incident, notify_count=notify_count, minutes_open=self._minutes_open(incident))
                        reminders_sent += 1

                        print(f"🔁 REMINDER #{notify_count} | Incident {incident['incident_id']} | "
                              f"still unacknowledged")

            print("\n" + "=" * 70)
            print(f"✅ ESCALATION AGENT COMPLETE — {escalated_new} new, {reminders_sent} reminders, {resolved_count} resolved")
            print("=" * 70)

            return {
                "status": "SUCCESS",
                "escalated_new": escalated_new,
                "reminders_sent": reminders_sent,
                "resolved": resolved_count,
            }

        except Exception as exc:
            self.session.rollback()
            print("\n❌ ESCALATION AGENT FAILED")
            print(exc)
            return {"status": "FAILED", "error": str(exc)}

    def _minutes_open(self, incident):
        first_detected = _parse_timestamp(incident["first_detected_time"])
        return int((utcnow() - first_detected).total_seconds() / 60)

    def _send_escalation(self, incident, notify_count, minutes_open):
        try:
            send_escalation_email(incident, notify_count=notify_count, minutes_open=minutes_open)
        except Exception as exc:
            # Never let an email failure crash the escalation logic itself —
            # the escalation is still recorded and will show on the dashboard
            # alert banner even if the email couldn't be sent.
            print(f"⚠️  Escalation email failed to send: {exc}")
