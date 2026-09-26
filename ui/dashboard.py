"""
Page assembly for the ICU Bed Occupancy Dashboard.

This module only orchestrates: it loads data through
``database.repository``, runs it through the ``services`` layer, and
hands the results to ``ui.components`` for rendering. No business logic
(occupancy math, transfer resolution, forecasting, data-quality rules)
lives here.
"""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import settings
from database.database import session_scope
from database.repository import (
    has_any_admissions,
    load_admissions,
    load_beds,
    load_wards,
    reset_all_data,
)
from database.seed import seed_database
from services.data_quality import annotate_discharges, build_data_quality_report
from services.forecasting import forecast_free_beds_tomorrow
from services.ingestion import RowIssue, persist_admissions, validate_admissions_csv
from services.occupancy import bed_status_board, compute_occupancy
from services.transfers import find_invalid_bed_assignments, resolve_active_admissions
from ui.components import (
    render_bed_legend,
    render_callout,
    render_data_quality_card,
    render_header,
    render_metric_row,
    render_section_title,
    render_ward_bed_grid,
)
from ui.styles import CSS

PROJECT_ID = "24CC3071-P019"
PROJECT_TITLE = "ICU Bed Occupancy Dashboard"
PROJECT_DOMAIN = "HOSPITAL ADMINISTRATION"

ALL_WARDS_LABEL = "All Wards"


def _ensure_data_loaded() -> None:
    """Seed the database with sample data on first run.

    Only runs when the admissions table is genuinely empty, so a
    real/uploaded dataset is never overwritten on a page refresh -- unless
    the operator has explicitly set ICU_RESEED_ON_START=true (useful for
    demos), which re-seeds on every process start.
    """
    with session_scope() as session:
        if settings.reseed_on_start or not has_any_admissions(session):
            seed_database(session, reset=True)


def render() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    _ensure_data_loaded()

    with session_scope() as session:
        wards_df = load_wards(session)
        beds_df = load_beds(session)
        admissions_df = load_admissions(session)

    stats_line = (
        f"{len(wards_df)} ward(s) · {len(beds_df)} bed(s) · "
        f"{admissions_df['patient_identifier'].nunique() if not admissions_df.empty else 0} patient(s) on record"
    )
    render_header(PROJECT_ID, PROJECT_TITLE, PROJECT_DOMAIN, stats_line)

    _render_data_source_section()

    # Re-read after a possible import/reset triggered above.
    with session_scope() as session:
        wards_df = load_wards(session)
        beds_df = load_beds(session)
        admissions_df = load_admissions(session)

    if beds_df.empty:
        render_callout(
            "No beds are configured yet. Upload an admissions sheet above, "
            "or reset to the sample dataset, to populate the dashboard."
        )
        return

    resolution = resolve_active_admissions(admissions_df)
    invalid_beds = find_invalid_bed_assignments(resolution.resolved)

    # ---------------------------------------------------------------- Filters
    ward_options = [ALL_WARDS_LABEL] + sorted(wards_df["name"].tolist())
    render_section_title("Filters", "Ward scopes every metric, chart and table below.")
    f_col1, f_col2, f_col3 = st.columns([1.2, 1, 1.6])
    with f_col1:
        selected_ward = st.selectbox("Ward", ward_options, key="filter_ward")
    with f_col2:
        bed_status_filter = st.selectbox("Bed status (live board)", ["All", "Occupied", "Free"], key="filter_bed_status")
    with f_col3:
        min_date, max_date = _admission_date_bounds(admissions_df)
        date_range = st.date_input(
            "Admission date range (patient table)",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            key="filter_date_range",
        )

    ward_filtered_beds = beds_df if selected_ward == ALL_WARDS_LABEL else beds_df[beds_df["ward"] == selected_ward]
    ward_filtered_resolved = (
        resolution.resolved
        if selected_ward == ALL_WARDS_LABEL
        else resolution.resolved[resolution.resolved["ward"] == selected_ward]
    )

    # ---------------------------------------------------------------- Metrics
    render_section_title("Summary Metrics")
    occ = compute_occupancy(ward_filtered_beds, ward_filtered_resolved)
    today = dt.date.today()
    forecast = forecast_free_beds_tomorrow(
        total_beds=occ.total_beds,
        currently_free=occ.free_beds,
        resolved_admissions=ward_filtered_resolved,
        reference_date=today,
    )
    planned_total = (
        int(ward_filtered_resolved["planned_discharge_date"].notna().sum())
        if not ward_filtered_resolved.empty
        else 0
    )
    render_metric_row(
        [
            ("Total ICU Beds", occ.total_beds, ""),
            ("Occupied Beds", occ.occupied_beds, "red"),
            ("Free Beds", occ.free_beds, "blue"),
            ("Occupancy %", f"{occ.occupancy_pct}%", "red" if occ.occupancy_pct >= 85 else ""),
            ("Planned Discharges", planned_total, "amber"),
            ("Forecast Free Tomorrow", forecast.forecast_free_tomorrow, "blue"),
        ]
    )

    # ---------------------------------------------------------- Live bed board
    render_section_title("Live Bed Status", "Red = occupied · amber dot = discharge planned · white = free")
    render_bed_legend()
    board = bed_status_board(ward_filtered_beds, ward_filtered_resolved)
    if bed_status_filter != "All":
        board = board[board["status"] == bed_status_filter]
    if board.empty:
        render_callout("No beds match the current filters.")
    else:
        for ward_name, ward_group in board.groupby("ward", sort=True):
            render_ward_bed_grid(ward_name, ward_group)

    # ------------------------------------------------------------------ Charts
    render_section_title("Charts")
    _render_charts(beds_df, resolution.resolved, admissions_df, selected_ward)

    # --------------------------------------------------------- Next-day forecast
    render_section_title("Next-Day Forecast", "forecast = min(total beds, currently free + planned discharges tomorrow)")
    render_metric_row(
        [
            ("Currently Free", occ.free_beds, ""),
            ("Planned Discharges Tomorrow", forecast.planned_discharges_tomorrow, "amber"),
            ("Forecast Free Tomorrow", forecast.forecast_free_tomorrow, "blue"),
        ]
    )

    # ------------------------------------------------------------- Data quality
    render_section_title(
        "Data Quality",
        "Issues detected in the underlying admissions data (ward filter does not apply -- these are dataset-wide).",
    )
    _render_data_quality(admissions_df, resolution.duplicates, resolution.transfers, invalid_beds)

    # --------------------------------------------------------- Admissions table
    render_section_title("Admissions / Patient Table", "Underlying records, one row per admission (all statuses).")
    _render_admissions_table(admissions_df, selected_ward, date_range)


def _admission_date_bounds(admissions_df: pd.DataFrame) -> tuple[dt.date, dt.date]:
    if admissions_df.empty:
        today = dt.date.today()
        return today - dt.timedelta(days=30), today
    dates = admissions_df["admission_time"].dt.date
    return dates.min(), max(dates.max(), dt.date.today())


def _render_data_source_section() -> None:
    with st.expander("Import / manage admissions data", expanded=False):
        st.caption(
            "Upload a CSV with columns: patient_id, ward, bed_id, admission_time, "
            "discharge_time, status, planned_discharge_date. Uploading replaces the "
            "current dataset after validation. Try `data/sample_admissions.csv` for a "
            "clean example, or `data/sample_admissions_with_errors.csv` to see how "
            "validation errors are reported."
        )
        uploaded = st.file_uploader("Admissions CSV", type=["csv"], key="admissions_uploader")

        col_a, col_b = st.columns([1, 1])
        with col_a:
            import_clicked = st.button("Validate & replace dataset", disabled=uploaded is None, width="stretch")
        with col_b:
            reset_clicked = st.button("Reset to sample data", width="stretch")

        if reset_clicked:
            with session_scope() as session:
                seed_database(session, reset=True)
            st.session_state.pop("last_import_report", None)
            st.success("Dataset reset to the built-in sample data.")
            st.rerun()

        if import_clicked and uploaded is not None:
            _handle_upload(uploaded)

        report = st.session_state.get("last_import_report")
        if report is not None:
            _render_import_report(report)


def _handle_upload(uploaded) -> None:
    try:
        raw_bytes = uploaded.getvalue()
        df = pd.read_csv(io.BytesIO(raw_bytes))
    except Exception:
        st.error(
            "Could not read this file as CSV. Please check the file format and try again."
        )
        return

    report = validate_admissions_csv(df)

    if not report.is_usable:
        st.session_state["last_import_report"] = {
            "column_errors": report.column_errors,
            "rejected": [],
            "warnings": [],
            "accepted": 0,
            "total": 0,
            "new_wards": [],
        }
        st.rerun()
        return

    if report.valid_rows.empty:
        st.session_state["last_import_report"] = {
            "column_errors": [],
            "rejected": [_issue_to_dict(i) for i in report.rejected_rows],
            "warnings": [_issue_to_dict(i) for i in report.warnings],
            "accepted": 0,
            "total": report.total_rows_seen,
            "new_wards": [],
        }
        st.rerun()
        return

    with session_scope() as session:
        reset_all_data(session)
        new_wards = persist_admissions(session, report.valid_rows)

    st.session_state["last_import_report"] = {
        "column_errors": [],
        "rejected": [_issue_to_dict(i) for i in report.rejected_rows],
        "warnings": [_issue_to_dict(i) for i in report.warnings],
        "accepted": len(report.valid_rows),
        "total": report.total_rows_seen,
        "new_wards": new_wards,
    }
    st.rerun()


def _issue_to_dict(issue: RowIssue) -> dict:
    return {"row_number": issue.row_number, "patient_id": issue.patient_id, "reason": issue.reason}


def _render_import_report(report: dict) -> None:
    if report["column_errors"]:
        for err in report["column_errors"]:
            st.error(err)
        return

    if report["accepted"]:
        st.success(f"Imported {report['accepted']} of {report['total']} row(s) successfully.")
    elif report["total"]:
        st.error(f"None of the {report['total']} row(s) passed validation -- see details below.")

    if report["new_wards"]:
        st.info("New ward(s) created automatically: " + ", ".join(report["new_wards"]))

    if report["rejected"]:
        with st.expander(f"{len(report['rejected'])} row(s) rejected", expanded=True):
            st.dataframe(pd.DataFrame(report["rejected"]), width="stretch", hide_index=True)

    if report["warnings"]:
        with st.expander(f"{len(report['warnings'])} warning(s)", expanded=False):
            st.dataframe(pd.DataFrame(report["warnings"]), width="stretch", hide_index=True)


def _render_charts(beds_df: pd.DataFrame, resolved: pd.DataFrame, admissions_df: pd.DataFrame, selected_ward: str) -> None:
    color_map = {"Occupied": "#c81e2c", "Free": "#1d4ed8"}

    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        by_ward = beds_df.groupby("ward")["id"].count().rename("Total").reset_index()
        occupied_ids = set(resolved["bed_id"].unique()) if not resolved.empty else set()
        occ_by_ward = beds_df.assign(is_occupied=beds_df["id"].isin(occupied_ids)).groupby("ward")["is_occupied"].sum()
        by_ward["Occupied"] = by_ward["ward"].map(occ_by_ward).fillna(0).astype(int)
        by_ward["Free"] = by_ward["Total"] - by_ward["Occupied"]
        melted = by_ward.melt(id_vars="ward", value_vars=["Occupied", "Free"], var_name="Status", value_name="Beds")
        fig = px.bar(
            melted, x="ward", y="Beds", color="Status", barmode="stack",
            color_discrete_map=color_map, title="ICU Occupancy by Ward",
        )
        fig.update_layout(margin=dict(t=40, l=10, r=10, b=10), height=320, legend_title_text="")
        st.plotly_chart(fig, width="stretch")

    with chart_col2:
        total_beds = len(beds_df) if selected_ward == "All Wards" else len(beds_df[beds_df["ward"] == selected_ward])
        occupied = len(occupied_ids & set(beds_df[beds_df["ward"] == selected_ward]["id"])) if selected_ward != "All Wards" else len(occupied_ids)
        free = max(total_beds - occupied, 0)
        pie_df = pd.DataFrame({"Status": ["Occupied", "Free"], "Beds": [occupied, free]})
        fig2 = go.Figure(
            data=[go.Pie(labels=pie_df["Status"], values=pie_df["Beds"], hole=0.55,
                         marker_colors=[color_map["Occupied"], color_map["Free"]])]
        )
        fig2.update_layout(title="Occupied vs Free (current filter)", margin=dict(t=40, l=10, r=10, b=10), height=320)
        st.plotly_chart(fig2, width="stretch")

    chart_col3, chart_col4 = st.columns(2)

    with chart_col3:
        if resolved.empty or resolved["planned_discharge_date"].isna().all():
            st.info("No planned discharge dates in the current data.")
        else:
            planned = resolved[resolved["planned_discharge_date"].notna()]
            counts = planned.groupby("planned_discharge_date")["patient_id"].nunique().reset_index()
            counts.columns = ["Planned Discharge Date", "Patients"]
            counts = counts.sort_values("Planned Discharge Date")
            fig3 = px.bar(counts, x="Planned Discharge Date", y="Patients", title="Planned Discharges by Date")
            fig3.update_traces(marker_color="#c8860d")
            fig3.update_layout(margin=dict(t=40, l=10, r=10, b=10), height=320)
            st.plotly_chart(fig3, width="stretch")

    with chart_col4:
        discharged = annotate_discharges(admissions_df)
        if discharged.empty:
            st.info("No discharge history yet to trend.")
        else:
            trend = discharged.groupby("operational_discharge_date").size().reset_index(name="Discharges")
            trend.columns = ["Operational Discharge Date", "Discharges"]
            trend = trend.sort_values("Operational Discharge Date").tail(14)
            fig4 = px.line(
                trend, x="Operational Discharge Date", y="Discharges", markers=True,
                title="Discharges per Operational Day (last 14)",
            )
            fig4.update_traces(line_color="#1d4ed8")
            fig4.update_layout(margin=dict(t=40, l=10, r=10, b=10), height=320)
            st.plotly_chart(fig4, width="stretch")


def _render_data_quality(
    admissions_df: pd.DataFrame,
    duplicates: pd.DataFrame,
    transfers: pd.DataFrame,
    invalid_beds: pd.DataFrame,
) -> None:
    report = build_data_quality_report(
        duplicates=duplicates,
        transfers=transfers,
        invalid_beds=invalid_beds,
        admissions=admissions_df,
    )

    dq_col1, dq_col2, dq_col3, dq_col4 = st.columns(4)
    with dq_col1:
        render_data_quality_card(
            "Duplicate Active Records",
            report.duplicate_active_count,
            "Patients with more than one 'Occupied' record, resolved to their latest bed.",
        )
    with dq_col2:
        render_data_quality_card(
            "Transfers Detected",
            report.transfers_detected_count,
            "Ward/bed moves reconstructed from the admissions data.",
        )
    with dq_col3:
        render_data_quality_card(
            "Invalid Bed Assignments",
            report.invalid_bed_assignment_count,
            "Beds currently claimed by more than one patient.",
        )
    with dq_col4:
        render_data_quality_card(
            "Early-Morning Discharges",
            report.early_morning_discharge_count,
            f"Discharges logged before {settings.operational_day_cutoff_hour:02d}:00 -- review for after-midnight logging.",
        )

    with st.expander("Inspect flagged records", expanded=False):
        tabs = st.tabs(["Duplicate records", "Transfers", "Invalid bed assignments", "Early-morning discharges"])
        with tabs[0]:
            _dataframe_or_empty(report.duplicates, "No duplicate active records detected.")
        with tabs[1]:
            _dataframe_or_empty(report.transfers, "No transfers detected.")
        with tabs[2]:
            _dataframe_or_empty(report.invalid_beds, "No invalid bed assignments detected.")
        with tabs[3]:
            _dataframe_or_empty(
                report.early_morning_discharges[
                    ["patient_identifier", "ward", "bed_number", "discharge_time", "operational_discharge_date"]
                ] if not report.early_morning_discharges.empty else report.early_morning_discharges,
                "No early-morning discharges detected.",
            )


def _dataframe_or_empty(df: pd.DataFrame, empty_message: str) -> None:
    if df is None or df.empty:
        st.caption(empty_message)
    else:
        st.dataframe(df, width="stretch", hide_index=True)


def _render_admissions_table(admissions_df: pd.DataFrame, selected_ward: str, date_range) -> None:
    if admissions_df.empty:
        st.caption("No admission records yet.")
        return

    table = admissions_df.copy()
    if selected_ward != ALL_WARDS_LABEL:
        table = table[table["ward"] == selected_ward]

    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        table = table[(table["admission_time"].dt.date >= start) & (table["admission_time"].dt.date <= end)]

    status_choice = st.selectbox(
        "Admission record status", ["All", "Occupied", "Discharged"], key="filter_admission_status"
    )
    if status_choice != "All":
        table = table[table["status"] == status_choice]

    display_cols = [
        "patient_identifier",
        "ward",
        "bed_number",
        "admission_time",
        "discharge_time",
        "status",
        "planned_discharge_date",
    ]
    table = table[display_cols].sort_values("admission_time", ascending=False)
    table = table.rename(
        columns={
            "patient_identifier": "Patient ID",
            "ward": "Ward",
            "bed_number": "Bed",
            "admission_time": "Admission Time",
            "discharge_time": "Discharge Time",
            "status": "Status",
            "planned_discharge_date": "Planned Discharge Date",
        }
    )
    st.dataframe(table, width="stretch", hide_index=True)
    st.caption(f"{len(table)} record(s) shown.")
