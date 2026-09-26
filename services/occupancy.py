"""
Live occupancy calculations.

Everything here is derived, on demand, from two plain DataFrames:

* ``beds`` -- every physical bed (id, ward, bed_number, and an
  operational ``status`` of "In Service" / "Out of Service" -- see
  ``database.models.BedServiceStatus``, mirrored here as a plain string
  so this module stays free of any SQLAlchemy/DB import).
* ``resolved_admissions`` -- one row per *currently occupied* patient,
  already de-duplicated by services/transfers.resolve_active_admissions.

No number here is ever hard-coded: total beds comes from the ``beds``
table, occupied beds comes from counting resolved admissions, and every
other figure is arithmetic on those two counts.

Out-of-service beds are a third state alongside Occupied/Free -- they
are excluded from "free" and from the occupancy-percentage denominator
(occupancy is measured against beds actually available for use), but
still counted in "Total ICU Beds" since that reports the physical
roster.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Must match database.models.BedServiceStatus.OUT_OF_SERVICE.value.
OUT_OF_SERVICE = "Out of Service"


@dataclass
class OccupancyMetrics:
    total_beds: int
    out_of_service_beds: int
    in_service_beds: int
    occupied_beds: int
    free_beds: int
    occupancy_pct: float


def compute_occupancy(beds: pd.DataFrame, resolved_admissions: pd.DataFrame) -> OccupancyMetrics:
    """Compute bed counts and occupancy percentage.

    ``resolved_admissions`` should already reflect one row per patient
    (post duplicate-resolution) -- this function does not itself dedupe,
    so that it stays simple and independently testable.
    """
    total_beds = int(len(beds))

    if total_beds == 0:
        return OccupancyMetrics(0, 0, 0, 0, 0, 0.0)

    status = beds["status"] if "status" in beds.columns else pd.Series(["In Service"] * total_beds, index=beds.index)
    out_of_service_mask = status == OUT_OF_SERVICE
    out_of_service_beds = int(out_of_service_mask.sum())
    in_service_beds = total_beds - out_of_service_beds

    occupied_bed_ids = set(resolved_admissions["bed_id"].unique()) if not resolved_admissions.empty else set()
    # Only count occupied beds that actually exist in the bed roster for
    # the current filter (e.g. a ward filter should not count another
    # ward's occupied beds), and that are actually in service (defensive:
    # an out-of-service bed should never have an active admission, since
    # services/bed_management.py refuses to take an occupied bed out of
    # service, but this keeps the arithmetic correct even if the
    # underlying data is inconsistent).
    in_service_beds_df = beds[~out_of_service_mask]
    occupied_beds = int(in_service_beds_df["id"].isin(occupied_bed_ids).sum())
    free_beds = in_service_beds - occupied_beds
    occupancy_pct = round((occupied_beds / in_service_beds) * 100, 1) if in_service_beds else 0.0

    return OccupancyMetrics(
        total_beds=total_beds,
        out_of_service_beds=out_of_service_beds,
        in_service_beds=in_service_beds,
        occupied_beds=occupied_beds,
        free_beds=free_beds,
        occupancy_pct=occupancy_pct,
    )


def bed_status_board(beds: pd.DataFrame, resolved_admissions: pd.DataFrame) -> pd.DataFrame:
    """Build a per-bed status table for the "live bed status" grid.

    Returns one row per bed with columns: bed_id, ward, bed_number,
    status (Free / Occupied / Out of Service), patient_identifier,
    admission_time, planned_discharge_date, has_planned_discharge (bool
    flag used to render the amber "planned discharge" indicator on an
    otherwise occupied bed), out_of_service_reason.
    """
    columns = [
        "bed_id",
        "ward",
        "bed_number",
        "status",
        "patient_identifier",
        "admission_time",
        "planned_discharge_date",
        "has_planned_discharge",
        "out_of_service_reason",
    ]
    if beds.empty:
        return pd.DataFrame(columns=columns)

    occ = resolved_admissions.set_index("bed_id") if not resolved_admissions.empty else pd.DataFrame()
    has_status_col = "status" in beds.columns

    rows = []
    for _, bed in beds.iterrows():
        if has_status_col and bed["status"] == OUT_OF_SERVICE:
            rows.append(
                {
                    "bed_id": bed["id"],
                    "ward": bed["ward"],
                    "bed_number": bed["bed_number"],
                    "status": OUT_OF_SERVICE,
                    "patient_identifier": None,
                    "admission_time": None,
                    "planned_discharge_date": None,
                    "has_planned_discharge": False,
                    "out_of_service_reason": bed.get("out_of_service_reason"),
                }
            )
            continue

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
                    "out_of_service_reason": None,
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
                    "out_of_service_reason": None,
                }
            )
    return pd.DataFrame(rows)
