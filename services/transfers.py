"""
Resolution of duplicate active admission records ("bed transfers between
wards create duplicate active records").

The problem
-----------
When a patient is moved from one ward/bed to another, the source system
sometimes logs this as a *new* admission row without properly closing out
the old one. The result is two (or more) ``Admission`` rows for the same
patient that both have ``status == "Occupied"``. If the dashboard counted
every "Occupied" row as an occupied bed, that single patient would appear
to occupy two beds at once, silently inflating the occupancy count and
hiding a truly free bed.

The fix implemented here
-------------------------
For each patient, among their currently-"Occupied" admission rows:

1. If there is exactly one -- nothing to resolve, it is simply their
   current admission.
2. If there is more than one -- the row with the *latest*
   ``admission_time`` is treated as authoritative (the patient's real,
   current location). Every earlier "Occupied" row for that patient is:
     * excluded from live occupancy counts (the whole point), and
     * recorded as a resolved :class:`Transfer` from its ward/bed to the
       latest row's ward/bed, using the latest admission's
       ``admission_time`` as the transfer time (the exact transfer instant
       is not separately logged in this simplified schema, so the new
       admission's start time is the best available proxy -- this
       assumption is documented here rather than hidden).
     * flagged in ``duplicates`` for the Data Quality panel.

This function is pure (no DB or Streamlit dependency) and operates on
plain DataFrames, which keeps it straightforward to unit test.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

ADMISSIONS_COLUMNS = [
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


@dataclass
class ResolutionResult:
    # One row per patient: their current, authoritative admission.
    resolved: pd.DataFrame
    # One row per superseded admission that was folded into a transfer.
    duplicates: pd.DataFrame
    # Derived transfer log entries (from_ward/from_bed -> to_ward/to_bed).
    transfers: pd.DataFrame


def resolve_active_admissions(admissions: pd.DataFrame) -> ResolutionResult:
    """Resolve duplicate-active-record situations into one row per patient.

    ``admissions`` must contain (at least) the columns in
    ``ADMISSIONS_COLUMNS``. Rows with status other than "Occupied" are
    passed through untouched (a patient with only discharged history has
    no "current" bed, and is simply omitted from the resolved/current
    view unless that is their only record -- callers that need discharge
    history should query ``admissions`` directly).
    """
    if admissions.empty:
        empty = pd.DataFrame(columns=ADMISSIONS_COLUMNS)
        return ResolutionResult(resolved=empty.copy(), duplicates=empty.copy(), transfers=pd.DataFrame())

    occupied = admissions[admissions["status"] == "Occupied"].copy()
    occupied["admission_time"] = pd.to_datetime(occupied["admission_time"])

    resolved_rows: list[dict] = []
    duplicate_rows: list[dict] = []
    transfer_rows: list[dict] = []

    for patient_id, group in occupied.groupby("patient_id", sort=False):
        group_sorted = group.sort_values("admission_time", ascending=False)
        current = group_sorted.iloc[0]
        resolved_rows.append(current.to_dict())

        superseded = group_sorted.iloc[1:]
        for _, old in superseded.iterrows():
            duplicate_rows.append(
                {
                    **old.to_dict(),
                    "superseded_by_admission_id": current["admission_id"],
                    "current_ward": current["ward"],
                    "current_bed_number": current["bed_number"],
                }
            )
            transfer_rows.append(
                {
                    "patient_id": patient_id,
                    "patient_identifier": current["patient_identifier"],
                    "from_ward": old["ward"],
                    "from_bed": old["bed_number"],
                    "to_ward": current["ward"],
                    "to_bed": current["bed_number"],
                    "transfer_time": current["admission_time"],
                }
            )

    resolved = pd.DataFrame(resolved_rows, columns=list(occupied.columns))
    duplicates = pd.DataFrame(
        duplicate_rows,
        columns=list(occupied.columns) + ["superseded_by_admission_id", "current_ward", "current_bed_number"],
    )
    transfers = pd.DataFrame(
        transfer_rows,
        columns=["patient_id", "patient_identifier", "from_ward", "from_bed", "to_ward", "to_bed", "transfer_time"],
    )

    return ResolutionResult(resolved=resolved, duplicates=duplicates, transfers=transfers)


def find_invalid_bed_assignments(resolved: pd.DataFrame) -> pd.DataFrame:
    """Find beds assigned to more than one patient *after* duplicate resolution.

    This is a genuine data conflict (two different patients both
    resolved as "currently" occupying the same bed) as opposed to the
    duplicate-active-record case above, which is one patient counted
    twice. It typically indicates a bed_id typo or a missing discharge
    for the previous occupant of that bed.
    """
    if resolved.empty:
        return resolved.iloc[0:0]

    counts = resolved.groupby("bed_id")["patient_id"].transform("nunique")
    return resolved[counts > 1].sort_values(["bed_id", "admission_time"])
