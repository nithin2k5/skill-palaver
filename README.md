# ICU Bed Occupancy Dashboard

`24CC3071-P019` · Hospital Administration

A working Streamlit dashboard that gives hospital administrators a
real-time view of ICU bed occupancy across wards and forecasts how many
beds will free up tomorrow, based on planned discharges. Built around two
real operational bottlenecks: **bed transfers that create duplicate
active records**, and **discharge timestamps logged after midnight**
that distort daily counts.

Every number on the dashboard is computed live from the database --
nothing is hard-coded.

## Project structure

```
.
├── app.py                          # Streamlit entry point (streamlit run app.py)
├── config.py                       # Environment-driven settings
├── requirements.txt
├── .env.example                    # Copy to .env to override configuration
├── .streamlit/config.toml          # Theme + "no raw tracebacks to users"
│
├── database/
│   ├── models.py        # SQLAlchemy ORM models (Ward, Bed, Patient, Admission, Transfer)
│   ├── database.py      # Engine/session setup (swap DATABASE_URL for Postgres/Neon)
│   ├── repository.py    # Read queries + reset/seed helpers -- the only place that runs SQL
│   └── seed.py           # Realistic sample dataset, relative to "today"
│
├── services/             # Business logic
│   ├── ingestion.py       # Bulk validation + persistence (used internally by seeding)
│   ├── bed_management.py  # One-at-a-time writes: admit/discharge/transfer, bed roster
│   ├── transfers.py       # Duplicate-active-record & transfer resolution (pure, no DB imports)
│   ├── occupancy.py       # Bed/occupancy math (pure, no DB imports)
│   ├── forecasting.py     # Next-day bed forecast (pure, no DB imports)
│   └── data_quality.py    # Midnight-discharge rule + data-quality aggregation
│
├── ui/
│   ├── styles.py          # CSS design system (also native-widget theming)
│   ├── components.py      # Reusable render helpers (header, metrics, bed grid, ...)
│   └── dashboard.py        # Page assembly -- orchestrates services + components
│
└── tests/                 # 48 unit tests, see "Running tests" below
```

## Installation

Requires Python 3.11+ (developed and tested on 3.12).

```bash
git clone <this-repo-url>
cd skill-palaver
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # optional -- defaults already work locally
```

## Running the app

```bash
streamlit run app.py
```

Open the URL Streamlit prints (typically http://localhost:8501). On
first run the app automatically seeds a realistic sample dataset (3
wards, 17 beds, 13 patients) so there is something to look at
immediately -- see "Sample data" below for exactly what it contains.

## Using Neon (managed Postgres)

The app runs on SQLite with zero setup, but the whole point of reading
`DATABASE_URL` from the environment (`config.py`) is that switching
backends never touches application code. To point it at
[Neon](https://neon.tech):

1. Create a Neon project (or a new database inside an existing one) from
   the Neon console. Free tier is plenty for this app.
2. In the project's **Dashboard > Connect** panel, copy the *pooled*
   connection string (Neon fronts Postgres with PgBouncer for exactly
   this kind of short-lived-connection app; use the direct one only if
   you specifically need a session-level feature the pooler doesn't
   support, which this app doesn't).
3. Put it in your `.env` as `DATABASE_URL`, with the SQLAlchemy driver
   prefix and `sslmode=require` (Neon requires TLS):
   ```
   DATABASE_URL=postgresql+psycopg2://<user>:<password>@<endpoint>.neon.tech/<dbname>?sslmode=require
   ```
4. Run the app normally (`streamlit run app.py`). `init_db()` creates the
   schema on first connect via `Base.metadata.create_all()` -- there's no
   separate migration step to run for a fresh database.

Nothing else changes: the same SQLAlchemy models, the same
`services/*`/`database/repository.py` code path, and the same seeded
sample data on first run (now persisted in Neon instead of a local
file). `psycopg2-binary` (in `requirements.txt`) is the Postgres driver;
`database/database.py` also sets `pool_pre_ping=True` for any non-SQLite
URL, so a connection Neon has silently closed after idling gets
transparently replaced instead of surfacing as a query error.

Never commit a real `DATABASE_URL` -- it contains a password. `.env` is
already git-ignored; keep the connection string there or in your
deployment platform's secret store, never in code.

## Running the tests

```bash
pytest
# or, for a verbose per-test list:
pytest -v
```

48 tests cover occupancy math, forecasting, duplicate/transfer
resolution, the midnight-discharge rule, CSV validation/error handling
(missing columns, missing fields, bad dates, invalid status values,
unknown wards), and the bed/patient management actions (admit, discharge,
transfer, add/remove a bed, take a bed in/out of service, and every
rejection path -- occupied bed, out-of-service bed, bed with admission
history, transfer time before admission time, and so on).

## How it works

1. **Data lives in SQLite by default** (`icu_dashboard.db`, git-ignored),
   accessed only through SQLAlchemy models (`database/models.py`) and a
   small read-oriented repository (`database/repository.py`). Pointing it
   at a managed Postgres instead -- Neon included -- is a one-line change:
   set `DATABASE_URL` in `.env`. See "Using Neon" below.
2. **The sample dataset goes through a real validation pipeline, not a
   direct insert**: `database/seed.py` builds the admissions rows and
   pushes them through `services/ingestion.py` (required columns,
   required fields, parseable dates, valid status values) exactly as an
   uploaded sheet would have been validated, then `persist_admissions`
   writes the valid rows, auto-creating any new ward/bed/patient it
   encounters. There is no live upload UI -- day-to-day changes go
   through **Manage Beds & Patients** (admit/discharge/transfer, bed
   roster) instead, which is dataset-wide and doesn't require replacing
   the whole dataset for a single change.
3. **The UI (`ui/dashboard.py`) never talks to the database or does
   business math directly** -- it loads DataFrames from the repository,
   passes them through `services/*`, and hands the results to
   `ui/components.py` for rendering.

## Duplicate-transfer handling

**Problem:** if a patient moves ward/bed and the source system logs a
new "Occupied" admission without properly closing the old one, that
patient now has two "Occupied" rows -- and naive counting would show
them occupying two beds at once, hiding a bed that is actually free.

**Implementation** (`services/transfers.py`, `resolve_active_admissions`):
for each patient, among their "Occupied" rows, the one with the latest
`admission_time` is treated as their true current location. Every
earlier "Occupied" row for that patient is excluded from the live
occupancy count, recorded as a reconstructed `Transfer` (old ward/bed ->
new ward/bed), and surfaced in the **Data Quality** section under
"Duplicate Active Records" / "Transfers Detected" for the administrator
to review. The raw historical rows are never deleted or modified -- only
the *live* view is corrected. Separately, `find_invalid_bed_assignments`
detects the different problem of two different patients both resolving
onto the same bed (e.g. a bed-id typo), reported as "Invalid Bed
Assignments".

This reconstruction path is for *messy, already-imported* data (the
sample/seed data contains the problem on purpose). A deliberate transfer
started from the **Manage Beds & Patients** panel goes through
`services/bed_management.transfer_patient` instead, which does the clean
version directly: it closes the old admission (`Discharged`, with
`discharge_time` set) and opens a new one in the destination bed in the
same transaction, so it is never flagged as a duplicate -- and it writes
a `Transfer` row straight to the database rather than reconstructing one
later. The sample data's P005 (an unresolved duplicate) and P009 (a
clean, already-closed-out transfer) exist side by side specifically to
show both outcomes.

## Midnight-discharge handling

**Problem:** a discharge logged at 23:55 and one logged at 00:05 the next
calendar day are usually the same shift's work -- grouping strictly by
calendar date splits one shift across two days and distorts both days'
counts.

**Implementation** (`services/data_quality.py`): discharge timestamps are
**never modified**. Instead, a derived, separate field is computed:

```
operational_date(ts) = ts.date() - 1 day   if ts.hour < CUTOFF_HOUR
                        ts.date()          otherwise
```

`CUTOFF_HOUR` defaults to 6 (06:00) and is configurable via
`OPERATIONAL_DAY_CUTOFF_HOUR` in `.env`. Any discharge whose raw
timestamp falls in that ambiguous `00:00`-cutoff window is additionally
flagged as an **early-morning discharge** for manual review, and listed
individually in the Data Quality section. The "Discharges per Operational
Day" chart groups by this derived date, not the raw calendar date.

## Next-day forecasting logic

```
forecast_free_beds_tomorrow = min(
    total_beds,
    current_free_beds + planned_discharges_tomorrow,
)
```

`planned_discharges_tomorrow` counts currently-occupied (post
duplicate-resolution) patients whose `planned_discharge_date` equals
tomorrow. The result is capped at `total_beds` so a data mistake can
never report more free beds than physically exist -- in practice the
dashboard passes the **in-service** bed count as that cap (see below), so
a bed under maintenance can never be forecast as "available tomorrow."
The model is implemented behind a small `ForecastModel` protocol
(`services/forecasting.py`) so a more advanced model (e.g. one that
weighs historical discharge-delay rates) can be added later without
touching the UI.

## Managing beds and patients

The **Manage Beds & Patients** section (dataset-wide -- the ward filter
above it doesn't scope these actions) is how day-to-day changes actually
happen -- one admission, discharge, transfer or bed roster change at a
time, all through `services/bed_management.py`:

* **Admit a patient** into a specific free, in-service bed, with an
  admission time and an optional planned discharge date. If the patient
  already has an active admission elsewhere, admitting them again is
  blocked unless you explicitly confirm it -- which deliberately lets you
  reproduce the duplicate-active-record scenario on demand rather than
  making it impossible to happen.
* **Discharge or transfer** an occupied bed's patient. Discharge sets
  `discharge_time` (try a time just after midnight to see the
  early-morning-discharge flag). Transfer performs the clean
  close-old/open-new sequence described above.
* **Manage the bed roster**: add a bed to an existing or brand-new ward;
  remove a bed (only allowed if it's free and has no admission history --
  a bed with real history can't be deleted without breaking the audit
  trail); and take a bed **out of service** (with an optional reason) or
  bring it back. Out of service is a third state alongside Occupied/Free
  -- it's excluded from "Free Beds" and from the occupancy-percentage
  denominator (occupancy is measured against beds actually available for
  use), and forecasting can never count it as free tomorrow. A bed must
  be vacated before it can be taken out of service.

Every action validates in `services/bed_management.py` before touching
the database and raises a `BedManagementError` with a plain-English
message on failure -- shown via `st.error`, never a stack trace.

## Sample data

`database/seed.py` generates dates **relative to the day the app is
run**, so the forecast is always meaningful. It deliberately covers every
scenario the dashboard is built to handle:

| Scenario | Patient(s) |
|---|---|
| Duplicate active record / unresolved transfer | P005: stale "Occupied" row in ICU-A, real current bed in ICU-B |
| Clean, well-handled transfer (contrast case) | P009: old ICU-C row properly discharged before the new ICU-B row starts |
| Early-morning discharge | P006: discharged at 00:15 |
| Invalid bed assignment | P012 and P013 both recorded on bed C02 |
| Multiple planned discharges, several dates | P001, P002, P007, P008, P009, P011, P012 |
| Genuinely free (never-used) beds | A05, C03, C04 |
| Bed out of service | B03 (equipment maintenance) |

## Error handling

There is no CSV upload in the UI, but the same strict validation that
kind of interface would need still runs every time the sample dataset is
(re-)seeded, in `services/ingestion.py` -- see `tests/test_ingestion.py`
for the exact rules (missing required columns, a missing required field,
an unparseable date, an invalid status value, an unknown ward that gets
auto-created rather than rejected). It stays in place because
`database/seed.py` depends on it, and because it is the natural place to
plug a real bulk-import path back in later without redesigning the
validation rules.

Day-to-day changes go through **Manage Beds & Patients** instead, and
every action there (admit, discharge, transfer, add/remove a bed,
in/out of service) is validated in `services/bed_management.py` before
touching the database, raising a `BedManagementError` with a
plain-English message on failure. Any other unexpected error while
rendering the dashboard is caught in `app.py`, logged for operators, and
shown to the user as a plain message -- never a raw Python traceback.

## Security & production considerations

This is a prototype. Before handling real patient data in production:

* Add authentication and role-based access control (only authorized
  hospital staff should see patient identifiers or bed assignments).
* Encrypt data at rest and in transit; SQLite is convenient for local
  development but has no built-in encryption or access control.
* Add an audit log of who viewed/exported patient-identifiable data.
* Review applicable healthcare data regulations (e.g. HIPAA, or your
  local equivalent) and complete a formal compliance/security review.
* Replace SQLite with a managed PostgreSQL instance (already supported
  via `DATABASE_URL`) with proper backups and network isolation.
* Never commit `.env` or `*.db` files -- both are already git-ignored.
