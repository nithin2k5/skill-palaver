"""Unit tests for services/forecasting.py."""
import datetime as dt

import pandas as pd

from services.forecasting import forecast_free_beds_tomorrow, planned_discharges_on

COLUMNS = ["patient_id", "planned_discharge_date"]


def _resolved(rows):
    return pd.DataFrame(rows, columns=COLUMNS)


def test_forecast_matches_spec_example():
    # From the spec: current=20 beds, free=3, planned discharges tomorrow=4 -> 7
    today = dt.date(2026, 1, 1)
    tomorrow = today + dt.timedelta(days=1)
    resolved = _resolved([(i, tomorrow) for i in range(4)])

    result = forecast_free_beds_tomorrow(
        total_beds=20, currently_free=3, resolved_admissions=resolved, reference_date=today
    )

    assert result.currently_free == 3
    assert result.planned_discharges_tomorrow == 4
    assert result.forecast_free_tomorrow == 7


def test_forecast_never_exceeds_total_beds():
    today = dt.date(2026, 1, 1)
    tomorrow = today + dt.timedelta(days=1)
    resolved = _resolved([(i, tomorrow) for i in range(10)])

    result = forecast_free_beds_tomorrow(
        total_beds=5, currently_free=4, resolved_admissions=resolved, reference_date=today
    )

    assert result.forecast_free_tomorrow == 5  # capped, not 14


def test_forecast_ignores_discharges_not_tomorrow():
    today = dt.date(2026, 1, 1)
    resolved = _resolved(
        [
            (1, today),  # today, not tomorrow
            (2, today + dt.timedelta(days=2)),  # day after tomorrow
            (3, today + dt.timedelta(days=1)),  # tomorrow
        ]
    )

    result = forecast_free_beds_tomorrow(
        total_beds=20, currently_free=5, resolved_admissions=resolved, reference_date=today
    )

    assert result.planned_discharges_tomorrow == 1
    assert result.forecast_free_tomorrow == 6


def test_forecast_with_empty_admissions():
    today = dt.date(2026, 1, 1)
    resolved = _resolved([])

    result = forecast_free_beds_tomorrow(
        total_beds=10, currently_free=2, resolved_admissions=resolved, reference_date=today
    )

    assert result.planned_discharges_tomorrow == 0
    assert result.forecast_free_tomorrow == 2


def test_planned_discharges_on_filters_correctly():
    today = dt.date(2026, 1, 1)
    resolved = _resolved([(1, today), (2, today + dt.timedelta(days=1))])

    matches = planned_discharges_on(resolved, today)

    assert len(matches) == 1
    assert matches.iloc[0]["patient_id"] == 1
