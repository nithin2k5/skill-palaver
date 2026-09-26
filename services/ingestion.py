"""
CSV ingestion: validation and persistence of admissions data.

This module is the single entry point through which admissions data
enters the system -- both the initial sample dataset (database/seed.py)
and any administrator-uploaded CSV go through the same
``validate_admissions_csv`` / ``persist_admissions`` pair. That keeps
validation rules in one place and guarantees the sample data exercises
exactly the same code path a real upload would.

Validation is intentionally strict about *required* fields (a row with a
missing patient/ward/bed/admission_time/status is rejected, not guessed
at) but tolerant of new ward names -- a ward mentioned in the CSV that
does not exist yet is created automatically and reported back to the
caller, rather than rejecting an otherwise-valid row.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy.orm import Session

from database.models import Admission, AdmissionStatus, Bed, BedServiceStatus, Patient, Ward

REQUIRED_COLUMNS: list[str] = [
    "patient_id",
    "ward",
    "bed_id",
    "admission_time",
    "discharge_time",
    "status",
    "planned_discharge_date",
]

VALID_STATUSES = {s.value.lower() for s in AdmissionStatus}


@dataclass
class RowIssue:
    row_number: int  # 1-based, matches a spreadsheet's row numbering (header = row 1)
    patient_id: str | None
    reason: str


@dataclass
class ImportReport:
    """Result of validating (and optionally persisting) an admissions CSV."""

    valid_rows: pd.DataFrame
    rejected_rows: list[RowIssue] = field(default_factory=list)
    warnings: list[RowIssue] = field(default_factory=list)
    column_errors: list[str] = field(default_factory=list)
    newly_created_wards: list[str] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        """True if there were no fatal column-level errors.

        Note: a file can still be "usable" and yield zero valid rows if
        every row failed validation -- callers should check
        ``valid_rows.empty`` separately.
        """
        return not self.column_errors

    @property
    def total_rows_seen(self) -> int:
        return len(self.valid_rows) + len(self.rejected_rows)


def validate_admissions_csv(df: pd.DataFrame) -> ImportReport:
    """Validate a raw admissions DataFrame against the expected schema.

    Never mutates ``df``. Returns an :class:`ImportReport` describing
    which rows are safe to persist and which were rejected (with a
    human-readable reason for each), so the UI can show useful errors
    instead of a stack trace.
    """
    report = ImportReport(valid_rows=pd.DataFrame(columns=REQUIRED_COLUMNS))

    if df is None or df.empty:
        report.column_errors.append("The uploaded file is empty -- no rows were found.")
        return report

    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        report.column_errors.append(
            "Missing required column(s): " + ", ".join(missing_columns)
        )
        return report

    valid_records: list[dict] = []

    for idx, raw_row in df.iterrows():
        row_number = int(idx) + 2  # +1 for 0-index, +1 for the header row
        row = raw_row.to_dict()
        patient_id = _clean_str(row.get("patient_id"))

        # --- Required fields -------------------------------------------------
        if not patient_id:
            report.rejected_rows.append(RowIssue(row_number, None, "Missing patient_id"))
            continue

        ward = _clean_str(row.get("ward"))
        if not ward:
            report.rejected_rows.append(RowIssue(row_number, patient_id, "Missing ward"))
            continue

        bed_id = _clean_str(row.get("bed_id"))
        if not bed_id:
            report.rejected_rows.append(RowIssue(row_number, patient_id, "Missing bed_id"))
            continue

        admission_time = _parse_datetime(row.get("admission_time"))
        if admission_time is None:
            report.rejected_rows.append(
                RowIssue(row_number, patient_id, "Missing or unparseable admission_time")
            )
            continue

        status_raw = _clean_str(row.get("status"))
        if not status_raw or status_raw.lower() not in VALID_STATUSES:
            report.rejected_rows.append(
                RowIssue(
                    row_number,
                    patient_id,
                    f"Invalid status {status_raw!r} (expected Occupied or Discharged)",
                )
            )
            continue
        status = "Occupied" if status_raw.lower() == "occupied" else "Discharged"

        # --- Optional fields (must parse if present, but may be blank) -------
        discharge_raw = row.get("discharge_time")
        discharge_time = None
        if _clean_str(discharge_raw):
            discharge_time = _parse_datetime(discharge_raw)
            if discharge_time is None:
                report.rejected_rows.append(
                    RowIssue(row_number, patient_id, f"Unparseable discharge_time {discharge_raw!r}")
                )
                continue

        planned_raw = row.get("planned_discharge_date")
        planned_discharge_date = None
        if _clean_str(planned_raw):
            planned_dt = _parse_datetime(planned_raw)
            if planned_dt is None:
                report.rejected_rows.append(
                    RowIssue(
                        row_number,
                        patient_id,
                        f"Unparseable planned_discharge_date {planned_raw!r}",
                    )
                )
                continue
            planned_discharge_date = planned_dt.date()

        if status == "Discharged" and discharge_time is None:
            report.warnings.append(
                RowIssue(
                    row_number,
                    patient_id,
                    "Status is Discharged but discharge_time is blank",
                )
            )

        valid_records.append(
            {
                "patient_id": patient_id,
                "ward": ward,
                "bed_id": bed_id,
                "admission_time": admission_time,
                "discharge_time": discharge_time,
                "status": status,
                "planned_discharge_date": planned_discharge_date,
            }
        )

    report.valid_rows = pd.DataFrame(valid_records, columns=REQUIRED_COLUMNS)
    return report


def _none_if_na(value: object) -> object:
    """Normalize pandas' missing-value sentinels (NaT/NaN) back to None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _clean_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime(value: object) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min)
    try:
        parsed = pd.to_datetime(value, errors="raise")
    except (ValueError, TypeError):
        return None
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def persist_admissions(session: Session, valid_rows: pd.DataFrame) -> list[str]:
    """Write validated admission rows into the database.

    Auto-creates any ``Ward``, ``Bed`` and ``Patient`` referenced by the
    data that does not already exist (looking them up first, so calling
    this against an already-seeded bed roster simply reuses those rows).
    Returns the list of ward names that had to be created (useful for a
    data-quality "unknown ward" notice).

    This function never deletes anything -- clearing existing data before
    a fresh import is a separate, explicit step
    (``database.repository.reset_all_data``) so that "wipe everything" is
    never a hidden side effect of a write.
    """
    newly_created_wards: list[str] = []

    ward_cache: dict[str, Ward] = {w.name: w for w in session.query(Ward).all()}
    bed_cache: dict[tuple[int, str], Bed] = {
        (b.ward_id, b.bed_number): b for b in session.query(Bed).all()
    }
    patient_cache: dict[str, Patient] = {
        p.patient_identifier: p for p in session.query(Patient).all()
    }

    for record in valid_rows.to_dict(orient="records"):
        ward_name = record["ward"]
        ward = ward_cache.get(ward_name)
        if ward is None:
            ward = Ward(name=ward_name)
            session.add(ward)
            session.flush()  # assign ward.id
            ward_cache[ward_name] = ward
            newly_created_wards.append(ward_name)

        bed_key = (ward.id, record["bed_id"])
        bed = bed_cache.get(bed_key)
        if bed is None:
            bed = Bed(ward_id=ward.id, bed_number=record["bed_id"], status=BedServiceStatus.IN_SERVICE.value)
            session.add(bed)
            session.flush()
            bed_cache[bed_key] = bed

        patient = patient_cache.get(record["patient_id"])
        if patient is None:
            patient = Patient(patient_identifier=record["patient_id"])
            session.add(patient)
            session.flush()
            patient_cache[record["patient_id"]] = patient

        admission = Admission(
            patient_id=patient.id,
            ward_id=ward.id,
            bed_id=bed.id,
            admission_time=record["admission_time"],
            # A DataFrame column mixing None with real timestamps/dates is
            # upcast by pandas to NaT/NaN for the missing entries rather
            # than leaving them as None -- normalize back to None here so
            # SQLAlchemy/SQLite store a real NULL instead of choking on a
            # pandas sentinel value.
            discharge_time=_none_if_na(record["discharge_time"]),
            status=record["status"],
            planned_discharge_date=_none_if_na(record["planned_discharge_date"]),
        )
        session.add(admission)

    session.flush()
    return newly_created_wards
