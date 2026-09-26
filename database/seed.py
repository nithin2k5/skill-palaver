"""
Sample data generator.

Produces a realistic ICU admissions dataset covering every scenario the
dashboard is designed to handle:

* 3 wards, 17 beds, 13 patients, some occupied and some genuinely free
  (never-used) beds.
* A duplicate-active-record / bad transfer (patient P005: an old
  "Occupied" row in ICU-A that was never closed out, plus a new
  "Occupied" row in ICU-B -- see services/transfers.py).
* A clean, well-handled transfer for contrast (patient P009: the old
  ICU-C row is properly "Discharged" before the new ICU-B row starts).
* An early-morning discharge (patient P006, discharged at 00:15).
* An invalid bed assignment: two different patients (P012, P013) both
  recorded as occupying bed C02.
* Planned discharges spread across today, tomorrow (several patients,
  to give a meaningful next-day forecast) and later dates.

All dates are generated relative to ``date.today()`` so the sample
dataset always demonstrates a sensible "tomorrow" forecast, regardless
of which day the application is first run.

This module is intentionally the *only* place that invents data: it
builds a plain list of admission "CSV rows" and pushes them through the
exact same ``services.ingestion`` validation/persistence pipeline that a
real uploaded spreadsheet goes through, so the sample data is guaranteed
to be a valid example of the expected format.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy.orm import Session

from database.repository import ensure_wards_and_beds, reset_all_data
from services.ingestion import REQUIRED_COLUMNS, persist_admissions, validate_admissions_csv

WARD_BEDS: dict[str, list[str]] = {
    "ICU-A": ["A01", "A02", "A03", "A04", "A05", "A06"],
    "ICU-B": ["B01", "B02", "B03", "B04", "B05", "B06"],
    "ICU-C": ["C01", "C02", "C03", "C04", "C05"],
}


def _ts(days_offset: int, hour: int = 9, minute: int = 0, *, today: dt.date) -> dt.datetime:
    return dt.datetime.combine(today + dt.timedelta(days=days_offset), dt.time(hour, minute))


def _d(days_offset: int, *, today: dt.date) -> dt.date:
    return today + dt.timedelta(days=days_offset)


def build_sample_admissions(today: dt.date | None = None) -> pd.DataFrame:
    """Build the sample admissions rows as a DataFrame in CSV shape."""
    today = today or dt.date.today()
    rows: list[dict] = [
        # -- Straightforward occupied beds, with a spread of planned discharges --
        dict(patient_id="P001", ward="ICU-A", bed_id="A01",
             admission_time=_ts(-4, 8, 30, today=today), discharge_time=None,
             status="Occupied", planned_discharge_date=_d(1, today=today)),
        dict(patient_id="P002", ward="ICU-A", bed_id="A02",
             admission_time=_ts(-2, 14, 0, today=today), discharge_time=None,
             status="Occupied", planned_discharge_date=_d(2, today=today)),
        dict(patient_id="P003", ward="ICU-A", bed_id="A03",
             admission_time=_ts(-6, 11, 15, today=today), discharge_time=None,
             status="Occupied", planned_discharge_date=None),

        # -- P004: previously in A04, already discharged normally -> A04 is free --
        dict(patient_id="P004", ward="ICU-A", bed_id="A04",
             admission_time=_ts(-9, 7, 0, today=today),
             discharge_time=_ts(-3, 10, 15, today=today),
             status="Discharged", planned_discharge_date=_d(-3, today=today)),

        # A05 is left completely unused -> genuinely free bed.

        # -- P006: early-morning discharge (00:15) from A06 -> A06 is free --
        dict(patient_id="P006", ward="ICU-A", bed_id="A06",
             admission_time=_ts(-6, 9, 0, today=today),
             discharge_time=_ts(-1, 0, 15, today=today),
             status="Discharged", planned_discharge_date=_d(-1, today=today)),

        # -- P005: DUPLICATE ACTIVE RECORD / unresolved transfer --
        # Old record: still "Occupied" in ICU-A/A04's neighbour bed, even
        # though the patient actually moved to ICU-B/B05. This is the
        # exact "bed transfers create duplicate active records" bug.
        dict(patient_id="P005", ward="ICU-A", bed_id="A04",  # reuses A04 after P004 vacated it
             admission_time=_ts(-2, 9, 0, today=today), discharge_time=None,
             status="Occupied", planned_discharge_date=None),
        dict(patient_id="P005", ward="ICU-B", bed_id="B05",
             admission_time=_ts(-1, 14, 0, today=today), discharge_time=None,
             status="Occupied", planned_discharge_date=_d(4, today=today)),

        # -- ICU-B straightforward occupied beds --
        dict(patient_id="P007", ward="ICU-B", bed_id="B01",
             admission_time=_ts(-1, 9, 45, today=today), discharge_time=None,
             status="Occupied", planned_discharge_date=_d(1, today=today)),
        dict(patient_id="P008", ward="ICU-B", bed_id="B02",
             admission_time=_ts(-3, 16, 30, today=today), discharge_time=None,
             status="Occupied", planned_discharge_date=_d(3, today=today)),

        # B03 is left completely unused -> genuinely free bed.

        # -- P009: CLEAN transfer (contrast case) --
        # Old record in ICU-C/C05 was properly discharged before the new
        # ICU-B/B04 admission began, so no duplicate is flagged.
        dict(patient_id="P009", ward="ICU-C", bed_id="C05",
             admission_time=_ts(-8, 8, 0, today=today),
             discharge_time=_ts(-2, 11, 0, today=today),
             status="Discharged", planned_discharge_date=_d(-2, today=today)),
        dict(patient_id="P009", ward="ICU-B", bed_id="B04",
             admission_time=_ts(-2, 11, 30, today=today), discharge_time=None,
             status="Occupied", planned_discharge_date=_d(1, today=today)),

        dict(patient_id="P010", ward="ICU-B", bed_id="B06",
             admission_time=_ts(-7, 13, 0, today=today), discharge_time=None,
             status="Occupied", planned_discharge_date=None),

        # -- ICU-C --
        dict(patient_id="P011", ward="ICU-C", bed_id="C01",
             admission_time=_ts(-2, 10, 0, today=today), discharge_time=None,
             status="Occupied", planned_discharge_date=_d(0, today=today)),
        dict(patient_id="P012", ward="ICU-C", bed_id="C02",
             admission_time=_ts(-1, 8, 0, today=today), discharge_time=None,
             status="Occupied", planned_discharge_date=_d(1, today=today)),

        # -- P013: INVALID BED ASSIGNMENT -- collides with P012 on bed C02
        # (e.g. a bed_id typo in the source admissions sheet).
        dict(patient_id="P013", ward="ICU-C", bed_id="C02",
             admission_time=_ts(-1, 8, 5, today=today), discharge_time=None,
             status="Occupied", planned_discharge_date=None),

        # C03, C04 are left completely unused -> genuinely free beds.
    ]
    return pd.DataFrame(rows, columns=REQUIRED_COLUMNS)


def seed_database(session: Session, *, reset: bool = True, today: dt.date | None = None) -> None:
    """Populate the database with the sample dataset.

    Goes through the same validation/persistence pipeline as a CSV
    upload (see services/ingestion.py) so the sample data is guaranteed
    to satisfy the documented schema.
    """
    if reset:
        reset_all_data(session)

    # Pre-create the full bed roster so unused beds exist and read as
    # "Free" rather than simply not existing.
    ensure_wards_and_beds(session, WARD_BEDS)

    sample_df = build_sample_admissions(today=today)
    report = validate_admissions_csv(sample_df)
    if report.rejected_rows:  # pragma: no cover - defensive; sample data should always be valid
        reasons = "; ".join(f"row {i.row_number}: {i.reason}" for i in report.rejected_rows)
        raise RuntimeError(f"Sample dataset failed validation: {reasons}")

    persist_admissions(session, report.valid_rows)
