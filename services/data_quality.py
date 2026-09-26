"""
Data-quality analytics: the "operational day" discharge rule, and the
aggregation of every data-quality signal shown in the DATA QUALITY
section of the dashboard.

Midnight discharge problem
---------------------------
A discharge logged at 23:55 and one logged at 00:05 the "next" calendar
day are, operationally, almost certainly the same shift's work -- the
patient at 00:05 likely left before midnight and was simply logged a few
minutes late by night staff. Grouping discharges by raw calendar date
would therefore split one shift's discharges across two days and distort
both days' counts.

The approach implemented here does **not** modify ``discharge_time``
(the recorded fact is never silently changed). Instead it derives a new,
separate field -- ``operational_date`` -- using a configurable cutoff
hour (``OPERATIONAL_DAY_CUTOFF_HOUR``, default 6 AM, see config.py):

    operational_date(ts) =
        ts.date() - 1 day   if ts.time() < cutoff_hour:00
        ts.date()           otherwise

Any discharge whose *raw* timestamp falls between 00:00 and the cutoff
hour is additionally flagged as an "early-morning discharge" for manual
review -- it is exactly the ambiguous window where a human should confirm
the patient did not, in fact, leave before midnight.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from config import settings


def operational_date(timestamp: dt.datetime, cutoff_hour: int | None = None) -> dt.date:
    """Map a raw discharge timestamp to its operational (shift) date.

    See module docstring for the rule. ``cutoff_hour`` defaults to the
    configured ``OPERATIONAL_DAY_CUTOFF_HOUR``.
    """
    cutoff = settings.operational_day_cutoff_hour if cutoff_hour is None else cutoff_hour
    if timestamp.hour < cutoff:
        return (timestamp - dt.timedelta(days=1)).date()
    return timestamp.date()


def is_early_morning_discharge(timestamp: dt.datetime, cutoff_hour: int | None = None) -> bool:
    """True if a discharge timestamp falls in the ambiguous 00:00-cutoff window."""
    cutoff = settings.operational_day_cutoff_hour if cutoff_hour is None else cutoff_hour
    return 0 <= timestamp.hour < cutoff


def annotate_discharges(admissions: pd.DataFrame, cutoff_hour: int | None = None) -> pd.DataFrame:
    """Return discharged admissions with derived (non-destructive) columns.

    Adds ``operational_discharge_date`` and ``is_early_morning`` columns
    without touching the original ``discharge_time`` values.
    """
    discharged = admissions[admissions["discharge_time"].notna()].copy()
    if discharged.empty:
        discharged["operational_discharge_date"] = pd.Series(dtype="object")
        discharged["is_early_morning"] = pd.Series(dtype="bool")
        return discharged

    discharged["discharge_time"] = pd.to_datetime(discharged["discharge_time"])
    discharged["operational_discharge_date"] = discharged["discharge_time"].apply(
        lambda ts: operational_date(ts, cutoff_hour)
    )
    discharged["is_early_morning"] = discharged["discharge_time"].apply(
        lambda ts: is_early_morning_discharge(ts, cutoff_hour)
    )
    return discharged


@dataclass
class DataQualityReport:
    duplicate_active_count: int
    transfers_detected_count: int
    invalid_bed_assignment_count: int
    early_morning_discharge_count: int
    missing_field_rows_count: int
    newly_created_wards: list[str] = field(default_factory=list)

    duplicates: pd.DataFrame = field(default_factory=pd.DataFrame)
    transfers: pd.DataFrame = field(default_factory=pd.DataFrame)
    invalid_beds: pd.DataFrame = field(default_factory=pd.DataFrame)
    early_morning_discharges: pd.DataFrame = field(default_factory=pd.DataFrame)


def build_data_quality_report(
    *,
    duplicates: pd.DataFrame,
    transfers: pd.DataFrame,
    invalid_beds: pd.DataFrame,
    admissions: pd.DataFrame,
    missing_field_rows_count: int = 0,
    newly_created_wards: list[str] | None = None,
) -> DataQualityReport:
    """Assemble every data-quality signal into one report for the UI."""
    early_morning = annotate_discharges(admissions)
    early_morning = early_morning[early_morning["is_early_morning"]]

    return DataQualityReport(
        duplicate_active_count=int(duplicates["patient_id"].nunique()) if not duplicates.empty else 0,
        transfers_detected_count=int(len(transfers)),
        invalid_bed_assignment_count=int(invalid_beds["bed_id"].nunique()) if not invalid_beds.empty else 0,
        early_morning_discharge_count=int(len(early_morning)),
        missing_field_rows_count=missing_field_rows_count,
        newly_created_wards=newly_created_wards or [],
        duplicates=duplicates,
        transfers=transfers,
        invalid_beds=invalid_beds,
        early_morning_discharges=early_morning,
    )
