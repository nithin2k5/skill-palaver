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
├── data/
│   ├── sample_admissions.csv           # Clean example admissions sheet
│   └── sample_admissions_with_errors.csv  # Deliberately flawed, for testing validation
│
├── database/
│   ├── models.py        # SQLAlchemy ORM models (Ward, Bed, Patient, Admission, Transfer)
│   ├── database.py      # Engine/session setup (swap DATABASE_URL for Postgres later)
│   ├── repository.py    # Read queries + reset/seed helpers -- the only place that runs SQL
│   └── seed.py           # Realistic sample dataset, relative to "today"
│
├── services/             # Business logic
│   ├── ingestion.py       # Bulk CSV validation + persistence
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

1. **Data lives in SQLite** (`icu_dashboard.db`, git-ignored), accessed
   only through SQLAlchemy models (`database/models.py`) and a small
   read-oriented repository (`database/repository.py`). Switching to
   PostgreSQL later is a one-line change: set `DATABASE_URL` in `.env`
   to a `postgresql+psycopg2://...` URL.
2. **Every admissions row -- sample or uploaded -- goes through the same
   pipeline**: `services/ingestion.py` validates the CSV (required
   columns, required fields, parseable dates, valid status values) and
   reports precisely which rows were rejected and why, then
   `persist_admissions` writes the valid rows, auto-creating any new
   ward/bed/patient it encounters.
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

This reconstruction path is for *messy, already-imported* data (a CSV
that already contains the problem). A deliberate transfer started from
the **Manage Beds & Patients** panel goes through
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
above it doesn't scope these actions) covers the three things a CSV
re-upload can't do one at a time, all through `services/bed_management.py`:

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

`data/sample_admissions.csv` is a static example file in the exact
CSV format the app expects (with fixed illustrative dates) -- upload it
from the "Import / manage admissions data" panel to see the upload flow.
`data/sample_admissions_with_errors.csv` is deliberately broken (missing
patient/ward/bed, an unparseable date, an invalid status, an unknown
ward) to demonstrate the validation error reporting.

## Error handling

CSV uploads are validated before anything touches the database: missing
required columns reject the whole file with a clear message; a row
missing a required field, with an unparseable date, or an invalid status
value is rejected individually (with the row number and reason shown to
the user) without discarding the rest of the file. An unknown ward name
is not an error -- it is created automatically and reported. Any
unexpected error while rendering the dashboard is caught in `app.py`,
logged for operators, and shown to the user as a plain message -- never a
raw Python traceback.

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
