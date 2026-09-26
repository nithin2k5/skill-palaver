"""Unit tests for services/occupancy.py."""
import pandas as pd

from services.occupancy import bed_status_board, compute_occupancy


def _beds(rows):
    return pd.DataFrame(rows, columns=["id", "bed_number", "ward_id", "ward"])


def _beds_with_status(rows):
    """Like _beds, but with an explicit In Service / Out of Service status column."""
    return pd.DataFrame(rows, columns=["id", "bed_number", "ward_id", "ward", "status"])


def _resolved(rows):
    columns = [
        "admission_id", "patient_id", "patient_identifier", "ward_id", "ward",
        "bed_id", "bed_number", "admission_time", "discharge_time", "status",
        "planned_discharge_date",
    ]
    return pd.DataFrame(rows, columns=columns)


def test_compute_occupancy_basic_counts():
    beds = _beds([
        (1, "A01", 1, "ICU-A"),
        (2, "A02", 1, "ICU-A"),
        (3, "A03", 1, "ICU-A"),
        (4, "A04", 1, "ICU-A"),
    ])
    resolved = _resolved([
        (10, 1, "P001", 1, "ICU-A", 1, "A01", "2026-01-01", None, "Occupied", None),
        (11, 2, "P002", 1, "ICU-A", 2, "A02", "2026-01-01", None, "Occupied", None),
    ])

    metrics = compute_occupancy(beds, resolved)

    assert metrics.total_beds == 4
    assert metrics.occupied_beds == 2
    assert metrics.free_beds == 2
    assert metrics.occupancy_pct == 50.0


def test_compute_occupancy_with_no_beds_is_zero_not_a_crash():
    beds = _beds([])
    resolved = _resolved([])

    metrics = compute_occupancy(beds, resolved)

    assert metrics.total_beds == 0
    assert metrics.occupied_beds == 0
    assert metrics.free_beds == 0
    assert metrics.occupancy_pct == 0.0


def test_compute_occupancy_ignores_occupied_beds_outside_filtered_set():
    # Simulates a ward filter: "resolved" includes a patient in another
    # ward whose bed id is not part of the filtered `beds` frame.
    beds = _beds([(1, "A01", 1, "ICU-A")])
    resolved = _resolved([
        (10, 1, "P001", 2, "ICU-B", 99, "B01", "2026-01-01", None, "Occupied", None),
    ])

    metrics = compute_occupancy(beds, resolved)

    assert metrics.total_beds == 1
    assert metrics.occupied_beds == 0
    assert metrics.free_beds == 1


def test_bed_status_board_marks_planned_discharge_flag():
    beds = _beds([(1, "A01", 1, "ICU-A"), (2, "A02", 1, "ICU-A")])
    resolved = _resolved([
        (10, 1, "P001", 1, "ICU-A", 1, "A01", "2026-01-01", None, "Occupied", pd.Timestamp("2026-01-05").date()),
    ])

    board = bed_status_board(beds, resolved)
    row_a01 = board[board["bed_number"] == "A01"].iloc[0]
    row_a02 = board[board["bed_number"] == "A02"].iloc[0]

    assert row_a01["status"] == "Occupied"
    assert bool(row_a01["has_planned_discharge"]) is True
    assert row_a02["status"] == "Free"
    assert bool(row_a02["has_planned_discharge"]) is False


def test_compute_occupancy_excludes_out_of_service_beds_from_free_and_denominator():
    beds = _beds_with_status([
        (1, "A01", 1, "ICU-A", "In Service"),
        (2, "A02", 1, "ICU-A", "In Service"),
        (3, "A03", 1, "ICU-A", "Out of Service"),
        (4, "A04", 1, "ICU-A", "Out of Service"),
    ])
    resolved = _resolved([
        (10, 1, "P001", 1, "ICU-A", 1, "A01", "2026-01-01", None, "Occupied", None),
    ])

    metrics = compute_occupancy(beds, resolved)

    assert metrics.total_beds == 4
    assert metrics.out_of_service_beds == 2
    assert metrics.in_service_beds == 2
    assert metrics.occupied_beds == 1
    # Free = in-service - occupied, NOT total - occupied.
    assert metrics.free_beds == 1
    # Occupancy % is measured against in-service capacity (1/2), not the
    # full physical roster (which would read 25%).
    assert metrics.occupancy_pct == 50.0


def test_bed_status_board_reports_out_of_service_with_reason():
    beds = _beds_with_status([(1, "A01", 1, "ICU-A", "Out of Service")])
    beds["out_of_service_reason"] = ["Equipment maintenance"]
    resolved = _resolved([])

    board = bed_status_board(beds, resolved)

    row = board.iloc[0]
    assert row["status"] == "Out of Service"
    assert row["out_of_service_reason"] == "Equipment maintenance"
    assert row["patient_identifier"] is None
