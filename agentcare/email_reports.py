"""SMTP delivery for scheduled manager reports.

Sends a proper multipart email:
  - HTML body (branded, tables, KPI cards)
  - Plain-text fallback (for clients that don't render HTML)
  - CSV attachment of the day's KPI summary

PDF attachment generation is planned for a follow-up pass.
"""

import csv
import io
import smtplib
from email.message import EmailMessage

from agentcare.config import (
    EMAIL_FROM,
    MANAGER_EMAILS,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_TLS,
    SMTP_USERNAME,
)

DASHBOARD_URL_PLACEHOLDER = "http://127.0.0.1:8002/agentcare/dashboard.html"


# ================================================================
# PLAIN-TEXT FALLBACK
# ================================================================

def report_to_text(report):
    """Render the structured report as a readable plain-text email."""
    lines = [
        "AGENTCARE AI - DAILY HOSPITAL OPERATIONS REPORT",
        f"Report date: {report['report_date']}",
        f"Generated at: {report['generated_at']}",
        "",
        "EXECUTIVE SUMMARY",
        report["executive_summary"],
        "",
        "INCIDENTS",
        f"Total: {report['incident_summary']['total']}",
        f"Critical: {report['incident_summary']['critical']}",
        f"Warning: {report['incident_summary']['warning']}",
    ]

    for incident in report["incident_summary"]["incidents"]:
        lines.append(
            f"  - [{incident['severity']}] {incident['kpi_name']} "
            f"(trigger {incident['trigger_value']} / threshold {incident['threshold_value']}) "
            f"- {incident['status']}"
        )

    lines += [
        "",
        "RECOMMENDATIONS",
        f"Total: {report['recommendation_summary']['total']}",
        f"High priority: {report['recommendation_summary']['high_priority']}",
    ]

    for rec in report["recommendation_summary"]["recommendations"]:
        lines.append(f"  - [{rec['priority']}] {rec['text']} - {rec['status']}")

    lines += [
        "",
        "MANAGER ACTIONS",
        f"Total: {report['manager_action_summary']['total']}",
        "",
        "DEPARTMENT CAPACITY",
    ]

    for department in report["departments"]:
        lines.append(
            f"- {department['name']}: {department['total_beds']} beds, "
            f"{department['total_icu_beds']} ICU beds"
        )

    lines += [
        "",
        f"Open the live dashboard: {DASHBOARD_URL_PLACEHOLDER}",
    ]

    return "\n".join(lines)


# ================================================================
# HTML BODY
# ================================================================

SEVERITY_COLORS = {
    "CRITICAL": "#dc2626",
    "WARNING": "#d97706",
    "NORMAL": "#16a34a",
}

PRIORITY_COLORS = {
    "HIGH": "#dc2626",
    "MEDIUM": "#d97706",
    "LOW": "#2563eb",
}


def _esc(value):
    if value is None:
        return "—"
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _kpi_cards_html(kpi_summary):
    if not kpi_summary:
        return '<p style="color:#64748b;font-size:13px;">No KPI observations for this reporting window.</p>'

    cards = []
    for kpi_name, values in kpi_summary.items():
        cards.append(f"""
        <td style="padding:6px;">
          <div style="background:#f8fafc;border:1px solid #e5eaf1;border-radius:10px;padding:14px;">
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.03em;">{_esc(kpi_name)}</div>
            <div style="font-size:22px;font-weight:800;color:#101827;margin-top:4px;">{_esc(values['average'])}</div>
            <div style="font-size:11px;color:#94a3b8;margin-top:4px;">min {_esc(values['minimum'])} · max {_esc(values['maximum'])} · {_esc(values['observations'])} obs</div>
          </div>
        </td>""")

    rows = []
    for i in range(0, len(cards), 3):
        rows.append("<tr>" + "".join(cards[i:i + 3]) + "</tr>")

    return f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tbody>{"".join(rows)}</tbody></table>'


def _incidents_table_html(incidents):
    if not incidents:
        return '<p style="color:#64748b;font-size:13px;">No incidents were detected during this reporting window.</p>'

    rows = []
    for incident in incidents:
        color = SEVERITY_COLORS.get(incident["severity"], "#64748b")
        rows.append(f"""
        <tr>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">{_esc(incident['kpi_name'])}</td>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">{_esc(incident['department_id'])}</td>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">
            <span style="background:{color}1a;color:{color};padding:3px 8px;border-radius:20px;font-size:11px;font-weight:700;">{_esc(incident['severity'])}</span>
          </td>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">{_esc(incident['status'])}</td>
        </tr>""")

    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="text-align:left;">
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">Incident</th>
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">Department</th>
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">Severity</th>
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">Status</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>"""


def _recommendations_table_html(recommendations):
    if not recommendations:
        return '<p style="color:#64748b;font-size:13px;">No AI recommendations were generated during this reporting window.</p>'

    rows = []
    for rec in recommendations:
        color = PRIORITY_COLORS.get(str(rec["priority"]).upper(), "#64748b")
        rows.append(f"""
        <tr>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">
            <span style="background:{color}1a;color:{color};padding:3px 8px;border-radius:20px;font-size:11px;font-weight:700;">{_esc(rec['priority'])}</span>
          </td>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">{_esc(rec['text'])}</td>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">{_esc(rec['status'])}</td>
        </tr>""")

    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="text-align:left;">
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">Priority</th>
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">Recommendation</th>
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">Status</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>"""


def _departments_table_html(departments):
    if not departments:
        return '<p style="color:#64748b;font-size:13px;">No department data available.</p>'

    rows = []
    for dept in departments:
        rows.append(f"""
        <tr>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">{_esc(dept['name'])}</td>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">{_esc(dept['total_beds'])}</td>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">{_esc(dept['total_icu_beds'])}</td>
        </tr>""")

    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="text-align:left;">
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">Department</th>
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">Beds</th>
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">ICU Beds</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>"""


def _actions_table_html(actions):
    if not actions:
        return '<p style="color:#64748b;font-size:13px;">No manager actions were recorded during this reporting window.</p>'

    rows = []
    for action in actions[:20]:
        rows.append(f"""
        <tr>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">{_esc(action['action_type'])}</td>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">{_esc(action['target_type'])} #{_esc(action['target_id'])}</td>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">{_esc(action['comment'])}</td>
          <td style="padding:9px 10px;border-bottom:1px solid #edf0f4;">{_esc(action['action_time'])}</td>
        </tr>""")

    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="text-align:left;">
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">Action</th>
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">Target</th>
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">Comment</th>
          <th style="padding:8px 10px;font-size:11px;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e5eaf1;">Time</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>"""


def report_to_html(report):
    incident_summary = report["incident_summary"]
    recommendation_summary = report["recommendation_summary"]

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f7fb;font-family:Segoe UI,Arial,sans-serif;color:#172033;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f7fb;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="640" cellspacing="0" cellpadding="0" style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 3px 16px rgba(20,35,60,.08);">

  <tr><td style="background:#101827;padding:24px 28px;">
    <div style="color:#fff;font-size:20px;font-weight:800;">🏥 AgentCare AI</div>
    <div style="color:#aeb9cb;font-size:12px;margin-top:4px;">Daily Hospital Operations Report</div>
  </td></tr>

  <tr><td style="padding:24px 28px 8px;">
    <div style="font-size:22px;font-weight:800;">Daily Hospital Operations Report</div>
    <div style="color:#64748b;font-size:13px;margin-top:4px;">{_esc(report['report_date'])} · generated {_esc(report['generated_at'])}</div>
  </td></tr>

  <tr><td style="padding:8px 28px 20px;">
    <div style="font-size:13px;font-weight:800;color:#334155;text-transform:uppercase;letter-spacing:.04em;margin-bottom:8px;">Executive Summary</div>
    <div style="background:#eff6ff;border:1px solid #dbeafe;border-radius:10px;padding:14px;font-size:14px;line-height:1.5;color:#1e3a8a;">
      {_esc(report['executive_summary'])}
    </div>
  </td></tr>

  <tr><td style="padding:8px 28px 20px;">
    <div style="font-size:13px;font-weight:800;color:#334155;text-transform:uppercase;letter-spacing:.04em;margin-bottom:8px;">Hospital KPIs</div>
    {_kpi_cards_html(report['kpi_summary'])}
  </td></tr>

  <tr><td style="padding:8px 28px 20px;">
    <div style="font-size:13px;font-weight:800;color:#334155;text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px;">
      Critical &amp; Warning Incidents
    </div>
    <div style="font-size:12px;color:#64748b;margin-bottom:10px;">
      {incident_summary['total']} total · {incident_summary['critical']} critical · {incident_summary['warning']} warning
    </div>
    {_incidents_table_html(incident_summary['incidents'])}
  </td></tr>

  <tr><td style="padding:8px 28px 20px;">
    <div style="font-size:13px;font-weight:800;color:#334155;text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px;">
      AI Recommendations
    </div>
    <div style="font-size:12px;color:#64748b;margin-bottom:10px;">
      {recommendation_summary['total']} total · {recommendation_summary['high_priority']} high priority
    </div>
    {_recommendations_table_html(recommendation_summary['recommendations'])}
  </td></tr>

  <tr><td style="padding:8px 28px 20px;">
    <div style="font-size:13px;font-weight:800;color:#334155;text-transform:uppercase;letter-spacing:.04em;margin-bottom:8px;">Department Status</div>
    {_departments_table_html(report['departments'])}
  </td></tr>

  <tr><td style="padding:8px 28px 20px;">
    <div style="font-size:13px;font-weight:800;color:#334155;text-transform:uppercase;letter-spacing:.04em;margin-bottom:8px;">Manager Actions</div>
    {_actions_table_html(report['manager_action_summary']['actions'])}
  </td></tr>

  <tr><td style="padding:20px 28px;background:#f8fafc;text-align:center;">
    <a href="{DASHBOARD_URL_PLACEHOLDER}" style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;font-weight:700;font-size:14px;padding:11px 22px;border-radius:8px;">
      Open Live Dashboard
    </a>
  </td></tr>

  <tr><td style="padding:16px 28px;text-align:center;color:#94a3b8;font-size:11px;">
    AgentCare AI · Automated report generated at {_esc(report['generated_at'])}. A CSV of today's KPI data is attached for your records.
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


# ================================================================
# CSV ATTACHMENT (KPI summary)
# ================================================================

def kpi_summary_to_csv(report):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["KPI", "Average", "Minimum", "Maximum", "Observations"])
    for kpi_name, values in report.get("kpi_summary", {}).items():
        writer.writerow([
            kpi_name,
            values["average"],
            values["minimum"],
            values["maximum"],
            values["observations"],
        ])
    return buffer.getvalue().encode("utf-8")


# ================================================================
# SEND
# ================================================================

def _format_subject_date(report_date_str):
    """'2026-09-03' -> '03 Sep 2026' for the subject line."""
    try:
        from datetime import datetime as _dt
        return _dt.strptime(report_date_str, "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        return report_date_str


# ================================================================
# CRITICAL INCIDENT ESCALATION EMAIL
# ================================================================

def _escalation_html(incident, notify_count, minutes_open):
    department = incident["department_name"] or "Hospital-wide"
    reminder_note = (
        f"This is reminder #{notify_count} — the incident has still not been acknowledged."
        if notify_count > 1
        else "This incident has not been acknowledged by anyone yet."
    )

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f7fb;font-family:Segoe UI,Arial,sans-serif;color:#172033;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f7fb;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="580" cellspacing="0" cellpadding="0" style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 3px 16px rgba(20,35,60,.08);border:2px solid #dc2626;">

  <tr><td style="background:#dc2626;padding:20px 26px;">
    <div style="color:#fff;font-size:19px;font-weight:800;">🚨 UNACKNOWLEDGED CRITICAL INCIDENT</div>
    <div style="color:#fecaca;font-size:12px;margin-top:4px;">AgentCare AI — Escalation Alert</div>
  </td></tr>

  <tr><td style="padding:24px 26px;">
    <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:16px;margin-bottom:18px;">
      <div style="font-size:13px;color:#991b1b;font-weight:700;">{_esc(reminder_note)}</div>
      <div style="font-size:13px;color:#991b1b;margin-top:6px;">Open for {_esc(minutes_open)} minutes.</div>
    </div>

    <table role="presentation" width="100%" style="font-size:14px;">
      <tr><td style="padding:6px 0;color:#64748b;width:140px;">Department</td><td style="padding:6px 0;font-weight:700;">{_esc(department)}</td></tr>
      <tr><td style="padding:6px 0;color:#64748b;">KPI</td><td style="padding:6px 0;font-weight:700;">{_esc(incident['kpi_name'])}</td></tr>
      <tr><td style="padding:6px 0;color:#64748b;">Trigger value</td><td style="padding:6px 0;font-weight:700;">{_esc(incident['trigger_value'])}</td></tr>
      <tr><td style="padding:6px 0;color:#64748b;">Threshold</td><td style="padding:6px 0;font-weight:700;">{_esc(incident['threshold_value'])}</td></tr>
      <tr><td style="padding:6px 0;color:#64748b;">First detected</td><td style="padding:6px 0;font-weight:700;">{_esc(incident['first_detected_time'])}</td></tr>
    </table>
  </td></tr>

  <tr><td style="padding:20px 26px;background:#f8fafc;text-align:center;">
    <a href="{DASHBOARD_URL_PLACEHOLDER}" style="display:inline-block;background:#dc2626;color:#fff;text-decoration:none;font-weight:700;font-size:14px;padding:11px 22px;border-radius:8px;">
      Open Dashboard &amp; Acknowledge
    </a>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def _escalation_text(incident, notify_count, minutes_open):
    department = incident["department_name"] or "Hospital-wide"
    return (
        f"UNACKNOWLEDGED CRITICAL INCIDENT (reminder #{notify_count})\n\n"
        f"Department: {department}\n"
        f"KPI: {incident['kpi_name']}\n"
        f"Trigger value: {incident['trigger_value']}\n"
        f"Threshold: {incident['threshold_value']}\n"
        f"Open for: {minutes_open} minutes\n\n"
        f"Open the dashboard to acknowledge: {DASHBOARD_URL_PLACEHOLDER}"
    )


def send_escalation_email(incident, notify_count, minutes_open):
    """Send an urgent standalone email for one unacknowledged CRITICAL
    incident. Raises on failure — the caller (EscalationAgent) is
    responsible for catching this so an email problem doesn't stop the
    escalation from being recorded and shown on the dashboard."""
    recipients = list(MANAGER_EMAILS.values())

    if not recipients:
        raise ValueError("No manager recipients configured. Set MANAGER_EMAILS in .env.")
    if not SMTP_HOST or not EMAIL_FROM:
        raise ValueError("SMTP_HOST and EMAIL_FROM must be configured in .env.")

    department = incident["department_name"] or "Hospital-wide"

    message = EmailMessage()
    message["Subject"] = f"🚨 URGENT: Unacknowledged critical incident — {department} ({incident['kpi_name']})"
    message["From"] = EMAIL_FROM
    message["To"] = ", ".join(recipients)

    message.set_content(_escalation_text(incident, notify_count, minutes_open))
    message.add_alternative(_escalation_html(incident, notify_count, minutes_open), subtype="html")

    smtp_class = smtplib.SMTP_SSL if not SMTP_USE_TLS else smtplib.SMTP
    with smtp_class(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        if SMTP_USE_TLS:
            smtp.starttls()
        if SMTP_USERNAME:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message, to_addrs=recipients)


def send_report(report, recipients, cc=None):
    """Send one report to the configured manager recipients."""
    if not recipients:
        raise ValueError(
            "No manager recipients configured. Set MANAGER_EMAILS in .env."
        )

    if not SMTP_HOST or not EMAIL_FROM:
        raise ValueError(
            "SMTP_HOST and EMAIL_FROM must be configured in .env."
        )

    message = EmailMessage()
    message["Subject"] = (
        f"AgentCare Daily Hospital Report - "
        f"{_format_subject_date(report['report_date'])}"
    )
    message["From"] = EMAIL_FROM
    message["To"] = ", ".join(recipients)
    if cc:
        message["Cc"] = ", ".join(cc)

    # Plain-text fallback + HTML alternative
    message.set_content(report_to_text(report))
    message.add_alternative(report_to_html(report), subtype="html")

    # CSV attachment
    csv_bytes = kpi_summary_to_csv(report)
    message.add_attachment(
        csv_bytes,
        maintype="text",
        subtype="csv",
        filename=f"agentcare_kpis_{report['report_date']}.csv",
    )

    all_recipients = list(recipients) + list(cc or [])

    smtp_class = smtplib.SMTP_SSL if not SMTP_USE_TLS else smtplib.SMTP
    with smtp_class(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        if SMTP_USE_TLS:
            smtp.starttls()
        if SMTP_USERNAME:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message, to_addrs=all_recipients)
