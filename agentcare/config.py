"""
Central configuration for AgentCare AI.
All 'magic numbers' live here so simulation logic never hardcodes values.
"""
import os
from dotenv import load_dotenv

load_dotenv()  # reads .env file in the project root, if present

# ------------------------------------------------------------
# Database
# ------------------------------------------------------------
# Set DATABASE_URL in your .env file, e.g.:
#   postgresql+psycopg2://user:password@localhost:5432/agentcare
# Falls back to a local SQLite file if not set (useful for quick local testing).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agentcare_local.db")

# ------------------------------------------------------------
# Daily manager report email
# ------------------------------------------------------------
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
if SMTP_HOST.lower() == "smtp.gmail.com":
    SMTP_PASSWORD = "".join(SMTP_PASSWORD.split())
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USERNAME)

# ------------------------------------------------------------
# Dashboard login
# ------------------------------------------------------------
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "manager")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "AgentCare@123")

# ------------------------------------------------------------
# LLM reasoning (Recommendation Agent + Report executive summary)
# ------------------------------------------------------------
# Optional. If neither key below is set, both agents automatically
# fall back to their deterministic, rule-based logic — nothing breaks
# without it, it just becomes a purely rule-based pipeline again.
#
# Groq (https://console.groq.com/) has a free tier and is tried first
# if GROQ_API_KEY is set. Anthropic is used instead if only
# ANTHROPIC_API_KEY is set. If both are set, Groq takes priority.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5")

if GROQ_API_KEY:
    LLM_PROVIDER = "groq"
elif ANTHROPIC_API_KEY:
    LLM_PROVIDER = "anthropic"
else:
    LLM_PROVIDER = None

LLM_ENABLED = LLM_PROVIDER is not None

# ------------------------------------------------------------
# Critical incident escalation
# ------------------------------------------------------------
# If a CRITICAL incident stays OPEN (nobody has acknowledged it) for
# longer than this, the Escalation Agent sends an urgent email and the
# dashboard shows a loud, impossible-to-miss alert. If it's still
# unacknowledged, a reminder email is re-sent every REMINDER_MINUTES.
ESCALATION_THRESHOLD_MINUTES = int(os.getenv("ESCALATION_THRESHOLD_MINUTES", "30"))
ESCALATION_REMINDER_MINUTES = int(os.getenv("ESCALATION_REMINDER_MINUTES", "60"))


def _parse_manager_emails():
    """Parse Department:email entries, or email-only entries, from .env."""
    entries = os.getenv("MANAGER_EMAILS", "").split(",")
    result = {}

    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        department, separator, email = entry.partition(":")
        if separator:
            result[department.strip()] = email.strip()
        else:
            result[entry] = entry

    return result


MANAGER_EMAILS = _parse_manager_emails()

# ------------------------------------------------------------
# Hospital model (Assumption 1)
# ------------------------------------------------------------
DEPARTMENTS = [
    # name, total_beds, total_icu_beds
    ("Emergency",       30, 0),
    ("ICU",             30, 30),
    ("General Medicine", 60, 0),
    ("Cardiology",      35, 0),
    ("Neurology",       30, 0),
    ("Orthopedics",     35, 0),
    ("General Surgery", 45, 0),
    ("Pediatrics",      35, 0),
]
# NOTE: totals sum to 300 beds / 30 ICU beds, matching Assumption 1.

STAFF_PER_DEPARTMENT = 12          # roster size per department (roles mixed)
STAFF_ROLES = ["Doctor", "Nurse", "Technician", "Ward Attendant"]
STAFF_SHIFTS = ["MORNING", "EVENING", "NIGHT"]

MEDICINES = [
    # name, unit, reorder_threshold
    ("Paracetamol", "tablet", 500),
    ("Amoxicillin", "capsule", 300),
    ("IV Saline",   "bottle", 100),
    ("Insulin",     "vial", 150),
    ("Morphine",    "vial", 50),
    ("Antibiotic-IV", "vial", 200),
]

# ------------------------------------------------------------
# Simulation parameters (Assumption 9)
# ------------------------------------------------------------
# Base expected admissions per hour, per department (before hourly multiplier)
BASE_ADMISSION_RATE_PER_HOUR = {
    "Emergency": 2.0,
    "ICU": 0.3,
    "General Medicine": 1.2,
    "Cardiology": 0.6,
    "Neurology": 0.4,
    "Orthopedics": 0.5,
    "General Surgery": 0.5,
    "Pediatrics": 0.6,
}

# Hourly multiplier curve (index = hour 0-23) — models realistic daily rhythm:
# low overnight, peaks late morning and evening.
HOURLY_MULTIPLIER = [
    0.3, 0.2, 0.2, 0.2, 0.3, 0.4,   # 00-05
    0.6, 0.9, 1.2, 1.4, 1.6, 1.5,   # 06-11
    1.3, 1.2, 1.1, 1.0, 1.1, 1.3,   # 12-17
    1.5, 1.4, 1.1, 0.8, 0.5, 0.4,   # 18-23
]

# Probability that a given admission arrives via an emergency event
EMERGENCY_ADMISSION_PROBABILITY = 0.35

# Average length of stay (hours) per department — used to sample discharge time
AVG_LENGTH_OF_STAY_HOURS = {
    "Emergency": 6,
    "ICU": 96,
    "General Medicine": 48,
    "Cardiology": 72,
    "Neurology": 60,
    "Orthopedics": 84,
    "General Surgery": 72,
    "Pediatrics": 40,
}

# Medicine consumption per admission (units), per department — simplified mapping
DEPARTMENT_MEDICINE_USAGE = {
    "Emergency":        {"Paracetamol": 2, "IV Saline": 1, "Antibiotic-IV": 1},
    "ICU":              {"IV Saline": 3, "Antibiotic-IV": 2, "Morphine": 1, "Insulin": 1},
    "General Medicine": {"Paracetamol": 3, "Amoxicillin": 2},
    "Cardiology":       {"IV Saline": 1, "Insulin": 1},
    "Neurology":        {"Paracetamol": 2, "IV Saline": 1},
    "Orthopedics":      {"Morphine": 1, "Antibiotic-IV": 1},
    "General Surgery":  {"Antibiotic-IV": 2, "IV Saline": 2, "Morphine": 1},
    "Pediatrics":       {"Paracetamol": 2, "Amoxicillin": 1},
}

# Revenue per admission (approx range), per department: (min, max)
DEPARTMENT_REVENUE_RANGE = {
    "Emergency":        (2000, 6000),
    "ICU":              (15000, 40000),
    "General Medicine": (4000, 10000),
    "Cardiology":       (8000, 25000),
    "Neurology":        (6000, 20000),
    "Orthopedics":      (7000, 22000),
    "General Surgery":  (10000, 30000),
    "Pediatrics":       (3000, 9000),
}

# Restock trigger: when current stock < reorder_threshold, restock to this multiple of threshold
RESTOCK_TARGET_MULTIPLIER = 3
