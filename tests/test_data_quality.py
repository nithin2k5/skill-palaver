"""Unit tests for services/data_quality.py -- the midnight-discharge rule."""
import datetime as dt

import pandas as pd

from services.data_quality import (
    annotate_discharges,
    build_data_quality_report,
    is_early_morning_discharge,
    operational_date,
)

ADMISSION_COLUMNS = ["patient_identifier", "ward", "bed_number", "discharge_time"]


def test_late_night_discharge_stays_on_its_own_day():
    ts = dt.datetime(2026, 1, 5, 23, 55)
    assert operational_date(ts, cutoff_hour=6) == dt.date(2026, 1, 5)
    assert is_early_morning_discharge(ts, cutoff_hour=6) is False


def test_just_after_midnight_discharge_rolls_back_to_previous_operational_day():
    ts = dt.datetime(2026, 1, 6, 0, 5)
    assert operational_date(ts, cutoff_hour=6) == dt.date(2026, 1, 5)
    assert is_early_morning_discharge(ts, cutoff_hour=6) is True


def test_discharge_after_cutoff_is_not_flagged():
    ts = dt.datetime(2026, 1, 6, 7, 0)
    assert operational_date(ts, cutoff_hour=6) == dt.date(2026, 1, 6)
    assert is_early_morning_discharge(ts, cutoff_hour=6) is False


def test_annotate_discharges_does_not_mutate_original_discharge_time():
    df = pd.DataFrame(
        [("P001", "ICU-A", "A01", dt.datetime(2026, 1, 6, 0, 15))],
        columns=ADMISSION_COLUMNS,
    )
    original_value = df.loc[0, "discharge_time"]

    annotated = annotate_discharges(df)

    # Original frame/column is untouched.
    assert df.loc[0, "discharge_time"] == original_value
    # New, separate derived columns were added to the (copied) result.
    assert annotated.loc[0, "operational_discharge_date"] == dt.date(2026, 1, 5)
    assert bool(annotated.loc[0, "is_early_morning"]) is True


def test_annotate_discharges_ignores_rows_without_a_discharge_time():
    df = pd.DataFrame(
        [("P001", "ICU-A", "A01", None), ("P002", "ICU-A", "A02", dt.datetime(2026, 1, 6, 10, 0))],
        columns=ADMISSION_COLUMNS,
    )

    annotated = annotate_discharges(df)

    assert len(annotated) == 1
    assert annotated.iloc[0]["patient_identifier"] == "P002"


def test_build_data_quality_report_counts_early_morning_discharges():
    admissions = pd.DataFrame(
        [
            ("P001", "ICU-A", "A01", dt.datetime(2026, 1, 6, 0, 20)),
            ("P002", "ICU-A", "A02", dt.datetime(2026, 1, 6, 14, 0)),
        ],
        columns=ADMISSION_COLUMNS,
    )
    empty = pd.DataFrame()

    report = build_data_quality_report(
        duplicates=empty, transfers=empty, invalid_beds=empty, admissions=admissions
    )

    assert report.early_morning_discharge_count == 1
    assert report.duplicate_active_count == 0
    assert report.transfers_detected_count == 0
