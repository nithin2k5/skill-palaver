"""
Live occupancy calculations.

Everything here is derived, on demand, from two plain DataFrames:

* ``beds`` -- every physical bed (id, ward, bed_number).
* ``resolved_admissions`` -- one row per *currently occupied* patient,
  already de-duplicated by services/transfers.resolve_active_admissions.

No number here is ever hard-coded: total beds comes from the ``beds``
table, occupied beds comes from counting resolved admissions, and every
other figure is arithmetic on those two counts.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class OccupancyMetrics:
    total_beds: int
    occupied_beds: int
    free_beds: int
    occupancy_pct: float


def compute_occupancy(beds: pd.DataFrame, resolved_admissions: pd.DataFrame) -> OccupancyMetrics:
    """Compute total/occupied/free beds and occupancy percentage.

    ``resolved_admissions`` should already reflect one row per patient
    (post duplicate-resolution) -- this function does not itself dedupe,
    so that it stays simple and independently testable.
    """
    total_beds = int(len(beds))

    if total_beds == 0:
        return OccupancyMetrics(total_beds=0, occupied_beds=0, free_beds=0, occupancy_pct=0.0)

    occupied_bed_ids = set(resolved_admissions["bed_id"].unique()) if not resolved_admissions.empty else set()
    # Only count occupied beds that actually exist in the bed roster for
    # the current filter (e.g. a ward filter should not count another
    # ward's occupied beds).
    occupied_beds = int(beds["id"].isin(occupied_bed_ids).sum())
    free_beds = total_beds - occupied_beds
    occupancy_pct = round((occupied_beds / total_beds) * 100, 1) if total_beds else 0.0

    return OccupancyMetrics(
        total_beds=total_beds,
        occupied_beds=occupied_beds,
        free_beds=free_beds,
        occupancy_pct=occupancy_pct,
    )


def bed_status_board(beds: pd.DataFrame, resolved_admissions: pd.DataFrame) -> pd.DataFrame:
    """Build a per-bed status table for the "live bed status" grid.

    Returns one row per bed with columns: bed_id, ward, bed_number,
    status (Free / Occupied), patient_identifier, admission_time,
    planned_discharge_date, has_planned_discharge (bool flag used to
    render the amber "planned discharge" indicator on an otherwise
    occupied bed).
    """
    if beds.empty:
        return pd.DataFrame(
            columns=[
                "bed_id",
                "ward",
                "bed_number",
                "status",
                "patient_identifier",
                "admission_time",
                "planned_discharge_date",
                "has_planned_discharge",
            ]
        )

    occ = resolved_admissions.set_index("bed_id") if not resolved_admissions.empty else pd.DataFrame()

    rows = []
    for _, bed in beds.iterrows():
        occ_row = occ.loc[bed["id"]] if not occ.empty and bed["id"] in occ.index else None
        if isinstance(occ_row, pd.DataFrame):
            # Two patients resolved onto the same bed (an invalid bed
            # assignment, surfaced separately in the Data Quality panel).
            # Show the most recently admitted one here rather than crash.
            occ_row = occ_row.sort_values("admission_time", ascending=False).iloc[0]
        if occ_row is not None:
            rows.append(
                {
                    "bed_id": bed["id"],
                    "ward": bed["ward"],
                    "bed_number": bed["bed_number"],
                    "status": "Occupied",
                    "patient_identifier": occ_row["patient_identifier"],
                    "admission_time": occ_row["admission_time"],
                    "planned_discharge_date": occ_row["planned_discharge_date"],
                    "has_planned_discharge": bool(pd.notna(occ_row["planned_discharge_date"])),
                }
            )
        else:
            rows.append(
                {
                    "bed_id": bed["id"],
                    "ward": bed["ward"],
                    "bed_number": bed["bed_number"],
                    "status": "Free",
                    "patient_identifier": None,
                    "admission_time": None,
                    "planned_discharge_date": None,
                    "has_planned_discharge": False,
                }
            )
    return pd.DataFrame(rows)
