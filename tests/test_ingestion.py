"""Unit tests for services/ingestion.py -- CSV validation and persistence."""
import io

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base
from services.ingestion import REQUIRED_COLUMNS, persist_admissions, validate_admissions_csv


def _csv_df(text: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(text))


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    s = SessionLocal()
    yield s
    s.close()


def test_missing_required_column_is_reported_as_a_column_error():
    df = _csv_df("patient_id,ward,bed_id,admission_time,status\nP001,ICU-A,A01,2026-01-01,Occupied\n")

    report = validate_admissions_csv(df)

    assert not report.is_usable
    assert any("discharge_time" in e for e in report.column_errors)
    assert any("planned_discharge_date" in e for e in report.column_errors)


def test_empty_file_is_reported_cleanly():
    report = validate_admissions_csv(pd.DataFrame())

    assert not report.is_usable
    assert report.valid_rows.empty


def test_row_with_missing_patient_id_is_rejected_not_crashed():
    csv_text = (
        "patient_id,ward,bed_id,admission_time,discharge_time,status,planned_discharge_date\n"
        ",ICU-A,A01,2026-01-01,,Occupied,\n"
    )
    df = _csv_df(csv_text)

    report = validate_admissions_csv(df)

    assert report.is_usable
    assert report.valid_rows.empty
    assert len(report.rejected_rows) == 1
    assert "patient_id" in report.rejected_rows[0].reason.lower()


def test_row_with_invalid_status_is_rejected():
    csv_text = (
        "patient_id,ward,bed_id,admission_time,discharge_time,status,planned_discharge_date\n"
        "P001,ICU-A,A01,2026-01-01,,Pending,\n"
    )
    df = _csv_df(csv_text)

    report = validate_admissions_csv(df)

    assert len(report.rejected_rows) == 1
    assert "status" in report.rejected_rows[0].reason.lower()


def test_row_with_unparseable_admission_time_is_rejected():
    csv_text = (
        "patient_id,ward,bed_id,admission_time,discharge_time,status,planned_discharge_date\n"
        "P001,ICU-A,A01,not-a-date,,Occupied,\n"
    )
    df = _csv_df(csv_text)

    report = validate_admissions_csv(df)

    assert len(report.rejected_rows) == 1


def test_valid_rows_pass_and_unknown_ward_is_auto_created(session):
    csv_text = (
        "patient_id,ward,bed_id,admission_time,discharge_time,status,planned_discharge_date\n"
        "P001,ICU-Z,Z01,2026-01-01,,Occupied,2026-01-05\n"
    )
    df = _csv_df(csv_text)

    report = validate_admissions_csv(df)
    assert report.valid_rows.shape[0] == 1

    new_wards = persist_admissions(session, report.valid_rows)

    assert new_wards == ["ICU-Z"]
    session.commit()


def test_required_columns_constant_matches_spec():
    assert REQUIRED_COLUMNS == [
        "patient_id",
        "ward",
        "bed_id",
        "admission_time",
        "discharge_time",
        "status",
        "planned_discharge_date",
    ]
