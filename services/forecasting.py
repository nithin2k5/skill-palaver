"""
Next-day bed availability forecasting.

Basic model (documented, deliberately simple)
----------------------------------------------
    forecast_free_beds_tomorrow = min(
        total_beds,
        current_free_beds + planned_discharges_tomorrow,
    )

``planned_discharges_tomorrow`` counts *currently occupied* (post
duplicate-resolution) patients whose ``planned_discharge_date`` equals
tomorrow's calendar date. The forecast is capped at ``total_beds`` so a
data entry mistake (e.g. two rows planning to discharge from what turns
out to be the same bed) can never report more free beds than physically
exist.

This module exposes a small ``ForecastModel`` protocol so a more
sophisticated model (e.g. one that also weighs historical no-show/delay
rates for planned discharges) can be swapped in later without touching
the UI -- only ``SimpleForecastModel`` is implemented today, per the
project's current scope.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol

import pandas as pd


@dataclass
class ForecastResult:
    currently_free: int
    planned_discharges_tomorrow: int
    forecast_free_tomorrow: int


class ForecastModel(Protocol):
    """Extension point for alternative forecasting strategies."""

    def forecast(
        self,
        *,
        total_beds: int,
        currently_free: int,
        resolved_admissions: pd.DataFrame,
        reference_date: dt.date,
    ) -> ForecastResult:
        ...


def planned_discharges_on(resolved_admissions: pd.DataFrame, target_date: dt.date) -> pd.DataFrame:
    """Currently-occupied patients whose planned_discharge_date is target_date."""
    if resolved_admissions.empty:
        return resolved_admissions
    mask = resolved_admissions["planned_discharge_date"] == target_date
    return resolved_admissions[mask]


class SimpleForecastModel:
    """The basic, transparent forecast model described in the module docstring."""

    def forecast(
        self,
        *,
        total_beds: int,
        currently_free: int,
        resolved_admissions: pd.DataFrame,
        reference_date: dt.date,
    ) -> ForecastResult:
        tomorrow = reference_date + dt.timedelta(days=1)
        planned = planned_discharges_on(resolved_admissions, tomorrow)
        planned_count = int(len(planned))

        forecast_free = min(total_beds, currently_free + planned_count)

        return ForecastResult(
            currently_free=currently_free,
            planned_discharges_tomorrow=planned_count,
            forecast_free_tomorrow=forecast_free,
        )


def forecast_free_beds_tomorrow(
    *,
    total_beds: int,
    currently_free: int,
    resolved_admissions: pd.DataFrame,
    reference_date: dt.date | None = None,
    model: ForecastModel | None = None,
) -> ForecastResult:
    """Convenience wrapper around the configured forecast model."""
    model = model or SimpleForecastModel()
    reference_date = reference_date or dt.date.today()
    return model.forecast(
        total_beds=total_beds,
        currently_free=currently_free,
        resolved_admissions=resolved_admissions,
        reference_date=reference_date,
    )
