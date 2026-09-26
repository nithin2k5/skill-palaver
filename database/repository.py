"""
Read-oriented data access layer.

Converts the current database contents into plain pandas DataFrames for
the services layer and the UI to consume. Keeping this in one module
means the Streamlit UI never issues a SQL query directly, and the
services layer (occupancy/transfers/forecasting/data_quality) never has
to know about SQLAlchemy.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Admission, Bed, Patient, Ward


def load_wards(session: Session) -> pd.DataFrame:
    rows = session.execute(select(Ward.id, Ward.name)).all()
    return pd.DataFrame(rows, columns=["id", "name"])


def load_beds(session: Session) -> pd.DataFrame:
    """All beds, joined with their ward name."""
    rows = session.execute(
        select(Bed.id, Bed.bed_number, Bed.ward_id, Ward.name.label("ward"))
        .join(Ward, Bed.ward_id == Ward.id)
    ).all()
    return pd.DataFrame(rows, columns=["id", "bed_number", "ward_id", "ward"])


def load_admissions(session: Session) -> pd.DataFrame:
    """Every admission record (all statuses), joined with patient/ward/bed labels.

    This is the raw, un-deduplicated view -- callers that need "current
    occupancy" must run this through
    services.transfers.resolve_active_admissions first.
    """
    rows = session.execute(
        select(
            Admission.id.label("admission_id"),
            Admission.patient_id,
            Patient.patient_identifier,
            Admission.ward_id,
            Ward.name.label("ward"),
            Admission.bed_id,
            Bed.bed_number,
            Admission.admission_time,
            Admission.discharge_time,
            Admission.status,
            Admission.planned_discharge_date,
        )
        .join(Patient, Admission.patient_id == Patient.id)
        .join(Ward, Admission.ward_id == Ward.id)
        .join(Bed, Admission.bed_id == Bed.id)
    ).all()

    columns = [
        "admission_id",
        "patient_id",
        "patient_identifier",
        "ward_id",
        "ward",
        "bed_id",
        "bed_number",
        "admission_time",
        "discharge_time",
        "status",
        "planned_discharge_date",
    ]
    df = pd.DataFrame(rows, columns=columns)
    if not df.empty:
        df["admission_time"] = pd.to_datetime(df["admission_time"])
        df["discharge_time"] = pd.to_datetime(df["discharge_time"])
        df["planned_discharge_date"] = pd.to_datetime(df["planned_discharge_date"]).dt.date
    return df


def has_any_admissions(session: Session) -> bool:
    return session.query(Admission.id).first() is not None


def reset_all_data(session: Session) -> None:
    """Delete every row from every table, in foreign-key-safe order.

    This is an explicit, separate step (rather than a hidden side effect
    of persisting new data) so that "replace the whole dataset" is always
    a deliberate action taken by the caller -- e.g. before loading a fresh
    admissions sheet or re-seeding the sample dataset.
    """
    session.query(Admission).delete()
    session.query(Bed).delete()
    session.query(Patient).delete()
    session.query(Ward).delete()
    session.flush()


def ensure_wards_and_beds(session: Session, ward_to_bed_numbers: dict[str, list[str]]) -> None:
    """Create any ward/bed combinations that do not already exist.

    Used by the sample-data seeder to guarantee that beds with no
    admission history (genuinely never-used beds) still exist and show
    up as Free on the live bed board.
    """
    existing_wards = {w.name: w for w in session.query(Ward).all()}
    for ward_name, bed_numbers in ward_to_bed_numbers.items():
        ward = existing_wards.get(ward_name)
        if ward is None:
            ward = Ward(name=ward_name)
            session.add(ward)
            session.flush()
            existing_wards[ward_name] = ward

        existing_bed_numbers = {
            b.bed_number for b in session.query(Bed).filter(Bed.ward_id == ward.id).all()
        }
        for bed_number in bed_numbers:
            if bed_number not in existing_bed_numbers:
                session.add(Bed(ward_id=ward.id, bed_number=bed_number, status="Free"))
    session.flush()
