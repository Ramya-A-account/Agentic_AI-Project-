# AgentCare AI — Simulation Engine (Phase 1)

This is the Simulation Agent, its Postgres data models, and an Orchestrator
that triggers it — covering the project up through 30-day historical data
generation and live 30-minute monitoring windows.

## What's included

```
agentcare/
  config.py              -> all tunable parameters (rates, thresholds, revenue ranges)
  db.py                   -> DB connection/session setup
  models.py               -> SQLAlchemy models matching the Postgres schema
  seed.py                 -> one-time setup: departments, beds, staff, medicines
  agents/
    base.py               -> Agent base class every agent implements
    simulation_agent.py    -> the Data Simulation Engine, as an Agent
    orchestrator.py        -> triggers Simulation Agent, logs execution
run_historical.py         -> generates 30 days of history (run ONCE)
run_live_cycle.py         -> runs one 30-min live window (run repeatedly/on a schedule)
requirements.txt
.env.example
```

## Setup — exact steps

### 1. Install PostgreSQL locally (if you haven't already)
Install Postgres, then create a database:
```bash
createdb agentcare
```

### 2. Set up the Python project
```bash
cd agentcare_project
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure your database connection
```bash
cp .env.example .env
```
Edit `.env` and put in your real Postgres username/password:
```
DATABASE_URL=postgresql+psycopg2://postgres:yourpassword@localhost:5432/agentcare
```
(If you skip this step entirely, the app automatically falls back to a local
SQLite file — fine for a quick test run, but switch to Postgres before
building further agents on top of it.)

### 4. Seed the hospital structure
Run once — creates the 8 departments, 300 beds (30 ICU), staff roster, and
medicine catalog:
```bash
python -m agentcare.seed
```

### 5. Generate 30 days of historical data
Run once — this seeds realistic baseline data using the same event-driven
engine that live monitoring will use:
```bash
python run_historical.py
```
You should see output like:
```
Historical simulation complete:
  admissions: ~3800-4000
  emergency_events: ~1300-1400
  discharges: ~2300-2500
  inventory_transactions: ~9500-10000
  revenue_transactions: ~3800-4000
```

### 6. Run a live monitoring window
This simulates exactly one 30-minute window of new operational activity —
this is the function the Orchestrator will call every 30 minutes once
APScheduler is wired in:
```bash
python run_live_cycle.py
```

### 7. Enable the daily manager email
Add SMTP credentials and manager recipients to `.env` using the values shown in
`.env.example`:
```dotenv
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=reports@example.com
SMTP_PASSWORD=your-mailbox-password
SMTP_USE_TLS=true
EMAIL_FROM=reports@example.com
MANAGER_EMAILS=Emergency:emergency.manager@example.com,ICU:icu.manager@example.com
```
Start `scheduler.py` and it will generate and email the daily report at 7:00 PM
Asia/Kolkata time. Each `Department:email` entry identifies the manager who
should receive the report. The scheduler must remain running for the job to run.

To send one report immediately for testing, run:
```bash
python send_test_report.py
```

## Known tuning note

In testing, the default arrival-rate / length-of-stay config in `config.py`
causes bed occupancy to saturate at or near 100% rather than settling around
a realistic 70-85% baseline with occasional surges. Before moving on to the
Alert Detection Agent (which needs a believable "normal" baseline to compare
against), tune these two settings in `config.py`:

- `BASE_ADMISSION_RATE_PER_HOUR` — lower this per department
- `AVG_LENGTH_OF_STAY_HOURS` — and/or lower this

A good target: run `run_historical.py`, then check bed occupancy per
department — aim for ~70-85% average occupied, not 100%.

## What's next

Once occupancy is tuned to a realistic level, the next agent to build is the
**Data Cleaning Agent** — it will read from the same tables and validate/
quarantine records before the Data Analysis Agent computes KPIs from them.
