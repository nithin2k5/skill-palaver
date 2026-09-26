"""Unit tests for services/transfers.py -- duplicate/transfer resolution."""
import datetime as dt

import pandas as pd

from services.transfers import find_invalid_bed_assignments, resolve_active_admissions

COLUMNS = [
    "admission_id", "patient_id", "patient_identifier", "ward_id", "ward",
    "bed_id", "bed_number", "admission_time", "discharge_time", "status",
    "planned_discharge_date",
]


def _admissions(rows):
    return pd.DataFrame(rows, columns=COLUMNS)


def test_single_active_admission_passes_through_unchanged():
    admissions = _admissions([
        (1, 1, "P001", 1, "ICU-A", 1, "A01", dt.datetime(2026, 1, 1), None, "Occupied", None),
    ])

    result = resolve_active_admissions(admissions)

    assert len(result.resolved) == 1
    assert result.resolved.iloc[0]["bed_number"] == "A01"
    assert result.duplicates.empty
    assert result.transfers.empty


def test_duplicate_active_record_resolves_to_latest_bed():
    # Spec example: P001 old ICU-A/A01 (active) then new ICU-B/B04 (active),
    # without the old one being closed out.
    admissions = _admissions([
        (1, 1, "P001", 1, "ICU-A", 1, "A01", dt.datetime(2026, 1, 1, 8, 0), None, "Occupied", None),
        (2, 1, "P001", 2, "ICU-B", 4, "B04", dt.datetime(2026, 1, 3, 9, 0), None, "Occupied", None),
    ])

    result = resolve_active_admissions(admissions)

    # Only one currently-occupied row for this patient: the latest.
    assert len(result.resolved) == 1
    assert result.resolved.iloc[0]["ward"] == "ICU-B"
    assert result.resolved.iloc[0]["bed_number"] == "B04"

    # The stale record is flagged as a duplicate, not counted as occupied.
    assert len(result.duplicates) == 1
    assert result.duplicates.iloc[0]["bed_number"] == "A01"

    # A transfer entry was reconstructed for audit/history.
    assert len(result.transfers) == 1
    transfer = result.transfers.iloc[0]
    assert transfer["from_ward"] == "ICU-A" and transfer["from_bed"] == "A01"
    assert transfer["to_ward"] == "ICU-B" and transfer["to_bed"] == "B04"


def test_clean_transfer_with_proper_discharge_is_not_flagged_as_duplicate():
    admissions = _admissions([
        (1, 1, "P009", 3, "ICU-C", 5, "C05", dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 3, 11, 0), "Discharged", None),
        (2, 1, "P009", 2, "ICU-B", 4, "B04", dt.datetime(2026, 1, 3, 11, 30), None, "Occupied", None),
    ])

    result = resolve_active_admissions(admissions)

    assert len(result.resolved) == 1
    assert result.resolved.iloc[0]["ward"] == "ICU-B"
    assert result.duplicates.empty
    assert result.transfers.empty


def test_invalid_bed_assignment_detects_two_patients_on_one_bed():
    admissions = _admissions([
        (1, 1, "P012", 3, "ICU-C", 7, "C02", dt.datetime(2026, 1, 1), None, "Occupied", None),
        (2, 2, "P013", 3, "ICU-C", 7, "C02", dt.datetime(2026, 1, 1, 0, 5), None, "Occupied", None),
    ])

    resolved = resolve_active_admissions(admissions).resolved
    conflicts = find_invalid_bed_assignments(resolved)

    assert len(conflicts) == 2
    assert set(conflicts["patient_identifier"]) == {"P012", "P013"}


def test_empty_admissions_returns_empty_frames_without_error():
    admissions = _admissions([])

    result = resolve_active_admissions(admissions)

    assert result.resolved.empty
    assert result.duplicates.empty
    assert result.transfers.empty
