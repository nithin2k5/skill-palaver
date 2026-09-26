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

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import settings
from database.database import session_scope
from database.repository import (
    load_admissions,
    load_beds,
    load_wards,
)
from database.seed import seed_database
from services.bed_management import (
    BedManagementError,
    admit_patient,
    create_bed,
    discharge_patient,
    remove_bed,
    set_bed_service_status,
    transfer_patient,
)
from services.data_quality import annotate_discharges, build_data_quality_report
from services.forecasting import forecast_free_beds_tomorrow
from services.occupancy import OUT_OF_SERVICE, bed_status_board, compute_occupancy
from services.transfers import find_invalid_bed_assignments, resolve_active_admissions
from ui.components import (
    render_bed_legend,
    render_callout,
    render_data_quality_grid,
    render_footnote,
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

# Shared Plotly theming so every chart reads as part of the same system
# instead of using Plotly's stock look. Applied on top of each figure's
# own colors/data rather than baked into a registered template, so it
# stays simple to reason about per chart.
CHART_FONT = dict(family="IBM Plex Sans, Inter, sans-serif", color="#33415c", size=12)
CHART_GRID_COLOR = "#e5e8ed"
COLOR_OCCUPIED = "#c81e2c"
COLOR_FREE = "#1d4ed8"
COLOR_AMBER = "#b5790a"
COLOR_OOS = "#9aa3b0"


def _apply_chart_theme(fig, *, height: int = 320, showlegend: bool | None = None) -> None:
    fig.update_layout(
        font=CHART_FONT,
        title_font=dict(family="IBM Plex Sans, Inter, sans-serif", color="#0f1e3d", size=15),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=44, l=8, r=8, b=8),
        height=height,
        legend_title_text="",
        hoverlabel=dict(bgcolor="#0f1e3d", font_color="white", font_family="IBM Plex Mono, monospace"),
    )
    if showlegend is not None:
        fig.update_layout(showlegend=showlegend)
    fig.update_xaxes(showgrid=False, linecolor=CHART_GRID_COLOR, zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=CHART_GRID_COLOR, zeroline=False)


def _ensure_data_loaded() -> None:
    """Optionally load demo data -- off by default.

    The dashboard does **not** invent data. A fresh database stays empty
    until real wards, beds and admissions are entered through the Manage
    Beds & Patients panel, so every figure on the page reflects something
    an administrator actually recorded.

    The one exception is explicit and opt-in: setting
    ``ICU_RESEED_ON_START=true`` (see .env.example) replaces the contents
    with the synthetic demo dataset in database/seed.py. That is for
    demos and local development only -- never point it at a database
    holding real records, since it wipes what is there first.
    """
    if not settings.reseed_on_start:
        return
    with session_scope() as session:
        seed_database(session, reset=True)


def render() -> None:
    # st.html (not st.markdown) -- see ui/components.py module docstring
    # for why: markdown's CommonMark parser breaks a multi-line CSS block
    # at the first blank line.
    st.html(CSS)
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

    if beds_df.empty:
        # The expected state of a brand-new database: the dashboard never
        # invents data. Not a hard stop -- every section below tolerates
        # empty data, and Manage Beds & Patients (which still renders) is
        # where the first ward and bed get created.
        render_callout(
            "This database is empty. Open Manage Beds & Patients below and use the "
            "Bed Roster tab to create your first ward and beds, then admit patients "
            "from the Admit Patient tab. Every metric and chart on this page is "
            "computed from those records."
        )

    resolution = resolve_active_admissions(admissions_df)
    invalid_beds = find_invalid_bed_assignments(resolution.resolved)

    # ---------------------------------------------------------------- Filters
    ward_options = [ALL_WARDS_LABEL] + sorted(wards_df["name"].tolist())
    render_section_title("01", "Filters", "Ward scopes every metric, chart and table below.")
    with st.container(border=True):
        f_col1, f_col2, f_col3 = st.columns([1.2, 1, 1.6])
        with f_col1:
            selected_ward = st.selectbox("Ward", ward_options, key="filter_ward")
        with f_col2:
            bed_status_filter = st.selectbox(
                "Bed status (live board)",
                ["All", "Occupied", "Free", "Out of Service"],
                key="filter_bed_status",
            )
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
    ward_filtered_admissions = (
        admissions_df
        if selected_ward == ALL_WARDS_LABEL or admissions_df.empty
        else admissions_df[admissions_df["ward"] == selected_ward]
    )

    # ---------------------------------------------------------------- Metrics
    render_section_title("02", "Summary Metrics")
    occ = compute_occupancy(ward_filtered_beds, ward_filtered_resolved)
    today = dt.date.today()
    forecast = forecast_free_beds_tomorrow(
        # Capped at beds actually available for use -- an out-of-service
        # bed can never become a "free" bed tomorrow just because a
        # discharge is planned elsewhere.
        total_beds=occ.in_service_beds,
        currently_free=occ.free_beds,
        resolved_admissions=ward_filtered_resolved,
        reference_date=today,
    )
    planned_total = (
        int(ward_filtered_resolved["planned_discharge_date"].notna().sum())
        if not ward_filtered_resolved.empty
        else 0
    )
    metric_tiles = [
        ("Total ICU Beds", occ.total_beds, "beds", ""),
        ("Occupied Beds", occ.occupied_beds, "beds", "red"),
        ("Free Beds", occ.free_beds, "beds", "blue"),
        ("Occupancy", f"{occ.occupancy_pct}", "%", "red" if occ.occupancy_pct >= 85 else ""),
        ("Planned Discharges", planned_total, "patients", "amber"),
        ("Forecast Free Tomorrow", forecast.forecast_free_tomorrow, "beds", "blue"),
    ]
    if occ.out_of_service_beds:
        metric_tiles.insert(3, ("Out of Service", occ.out_of_service_beds, "beds", ""))
    render_metric_row(metric_tiles)

    # ---------------------------------------------------------- Live bed board
    render_section_title(
        "03", "Live Bed Status", "Red = occupied · amber dot = discharge planned · hover a bed for details"
    )
    with st.container(border=True):
        render_bed_legend()
        board = bed_status_board(ward_filtered_beds, ward_filtered_resolved)
        if bed_status_filter != "All":
            board = board[board["status"] == bed_status_filter]
        if board.empty:
            render_callout("No beds match the current filters.")
        else:
            for ward_name, ward_group in board.groupby("ward", sort=True):
                render_ward_bed_grid(ward_name, ward_group)

    # ------------------------------------------------------ Manage beds & patients
    render_section_title(
        "04",
        "Manage Beds & Patients",
        "Admit, discharge or transfer a patient, or change the bed roster -- dataset-wide, ward filter does not apply.",
    )
    with st.container(border=True):
        full_board = bed_status_board(beds_df, resolution.resolved)
        _render_bed_management(wards_df, beds_df, full_board, resolution.resolved, admissions_df)

    # ------------------------------------------------------------------ Charts
    render_section_title("05", "Charts")
    with st.container(border=True):
        _render_charts(ward_filtered_beds, ward_filtered_resolved, ward_filtered_admissions)

    # --------------------------------------------------------- Next-day forecast
    render_section_title(
        "06", "Next-Day Forecast", "forecast = min(total beds, currently free + planned discharges tomorrow)"
    )
    render_metric_row(
        [
            ("Currently Free", occ.free_beds, "beds", ""),
            ("Planned Discharges Tomorrow", forecast.planned_discharges_tomorrow, "patients", "amber"),
            ("Forecast Free Tomorrow", forecast.forecast_free_tomorrow, "beds", "blue"),
        ]
    )

    # ------------------------------------------------------------- Data quality
    render_section_title(
        "07",
        "Data Quality",
        "Issues detected in the underlying admissions data (ward filter does not apply -- these are dataset-wide).",
    )
    _render_data_quality(admissions_df, resolution.duplicates, resolution.transfers, invalid_beds)

    # --------------------------------------------------------- Admissions table
    render_section_title("08", "Admissions / Patient Table", "Underlying records, one row per admission (all statuses).")
    with st.container(border=True):
        _render_admissions_table(admissions_df, selected_ward, date_range)

    render_footnote(
        "Prototype -- not for clinical use. Real patient data requires access control, "
        "encryption, auditing and a compliance review before production deployment."
    )


def _admission_date_bounds(admissions_df: pd.DataFrame) -> tuple[dt.date, dt.date]:
    if admissions_df.empty:
        today = dt.date.today()
        return today - dt.timedelta(days=30), today
    dates = admissions_df["admission_time"].dt.date
    return dates.min(), max(dates.max(), dt.date.today())


# ============================================================================
# Manage Beds & Patients -- admit / discharge / transfer a single patient,
# and add / remove / retire beds. Deliberately scoped to the *full* dataset
# (not the page's ward filter) so an administrator can always act on any
# bed regardless of what they happen to be viewing.
# ============================================================================

def _render_bed_management(
    wards_df: pd.DataFrame,
    beds_df: pd.DataFrame,
    board: pd.DataFrame,
    resolved: pd.DataFrame,
    admissions_df: pd.DataFrame,
) -> None:
    ward_names = sorted(wards_df["name"].tolist())
    tab_admit, tab_discharge, tab_roster = st.tabs(["Admit Patient", "Discharge / Transfer", "Bed Roster"])

    with tab_admit:
        _render_admit_tab(ward_names, board)
    with tab_discharge:
        _render_discharge_transfer_tab(ward_names, board, resolved)
    with tab_roster:
        _render_bed_roster_tab(ward_names, beds_df, board, admissions_df)


def _bed_options(board: pd.DataFrame, ward_name: str, status: str) -> list[str]:
    subset = board[(board["ward"] == ward_name) & (board["status"] == status)]
    return sorted(subset["bed_number"].tolist())


def _render_admit_tab(ward_names: list[str], board: pd.DataFrame) -> None:
    if not ward_names:
        st.caption("No wards yet -- add one from the Bed Roster tab first.")
        return

    st.caption("Puts a patient into a specific free, in-service bed.")
    # The ward select lives outside the form so the bed list below it
    # updates immediately when the ward changes (widgets inside a form do
    # not trigger a rerun until submit).
    ward_name = st.selectbox("Ward", ward_names, key="admit_ward")
    free_beds = _bed_options(board, ward_name, "Free")

    with st.form("admit_patient_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            patient_id = st.text_input("Patient ID", placeholder="e.g. P014")
            bed_number = st.selectbox(
                "Free bed", free_beds or ["No free beds in this ward"], disabled=not free_beds
            )
        with c2:
            admission_time = st.datetime_input("Admission time", value=dt.datetime.now(), step=300)
            has_plan = st.checkbox("Planned discharge date is known")
            planned_date = (
                st.date_input("Planned discharge date", value=dt.date.today() + dt.timedelta(days=2))
                if has_plan
                else None
            )
        allow_duplicate = st.checkbox(
            "Admit anyway if this patient already has an active admission elsewhere "
            "(creates a duplicate-active record, flagged under Data Quality)"
        )
        submitted = st.form_submit_button("Admit patient", width="stretch")

    if submitted:
        if not free_beds:
            st.error("There is no free bed in this ward to admit into.")
            return
        try:
            with session_scope() as session:
                admit_patient(
                    session,
                    patient_identifier=patient_id,
                    ward_name=ward_name,
                    bed_number=bed_number,
                    admission_time=admission_time,
                    planned_discharge_date=planned_date,
                    allow_duplicate_active=allow_duplicate,
                )
            st.success(f"Admitted {patient_id} to {ward_name}/{bed_number}.")
            st.rerun()
        except BedManagementError as e:
            st.error(str(e))


def _render_discharge_transfer_tab(ward_names: list[str], board: pd.DataFrame, resolved: pd.DataFrame) -> None:
    if resolved.empty:
        st.caption("No occupied beds to discharge or transfer.")
        return

    occupied = resolved.sort_values(["ward", "bed_number"])
    options = {
        f"{row.ward} / {row.bed_number} — {row.patient_identifier}": row.admission_id
        for row in occupied.itertuples()
    }
    label = st.selectbox("Select an occupied bed", list(options.keys()), key="dt_select")
    admission_id = options[label]
    selected = occupied[occupied["admission_id"] == admission_id].iloc[0]

    action = st.radio("Action", ["Discharge", "Transfer"], horizontal=True, key="dt_action")

    if action == "Discharge":
        with st.form("discharge_form", clear_on_submit=True):
            discharge_time = st.datetime_input("Discharge time", value=dt.datetime.now(), step=60)
            st.caption(
                "Tip: set a time between 00:00 and the operational cutoff hour to see the "
                "early-morning discharge flag in Data Quality."
            )
            submitted = st.form_submit_button("Discharge patient", width="stretch")
        if submitted:
            try:
                with session_scope() as session:
                    discharge_patient(session, admission_id=int(admission_id), discharge_time=discharge_time)
                st.success(f"Discharged {selected['patient_identifier']} from {selected['ward']}/{selected['bed_number']}.")
                st.session_state.pop("dt_select", None)
                st.rerun()
            except BedManagementError as e:
                st.error(str(e))
    else:
        remaining_wards = ward_names
        dest_ward = st.selectbox("Destination ward", remaining_wards, key="dt_dest_ward")
        dest_free_beds = _bed_options(board, dest_ward, "Free")
        with st.form("transfer_form", clear_on_submit=True):
            dest_bed = st.selectbox(
                "Destination bed", dest_free_beds or ["No free beds in this ward"], disabled=not dest_free_beds
            )
            transfer_time = st.datetime_input("Transfer time", value=dt.datetime.now(), step=60)
            submitted = st.form_submit_button("Transfer patient", width="stretch")
        if submitted:
            if not dest_free_beds:
                st.error("There is no free bed in that ward to transfer into.")
            else:
                try:
                    with session_scope() as session:
                        transfer_patient(
                            session,
                            admission_id=int(admission_id),
                            to_ward_name=dest_ward,
                            to_bed_number=dest_bed,
                            transfer_time=transfer_time,
                        )
                    st.success(f"Transferred {selected['patient_identifier']} to {dest_ward}/{dest_bed}.")
                    st.session_state.pop("dt_select", None)
                    st.rerun()
                except BedManagementError as e:
                    st.error(str(e))


def _render_bed_roster_tab(
    ward_names: list[str], beds_df: pd.DataFrame, board: pd.DataFrame, admissions_df: pd.DataFrame
) -> None:
    st.markdown("**Add a bed**")
    with st.form("add_bed_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            ward_choice = st.selectbox("Ward", ward_names, key="add_bed_ward") if ward_names else None
            new_ward = st.text_input("...or a new ward name", placeholder="e.g. ICU-D")
        with c2:
            bed_number = st.text_input("Bed number", placeholder="e.g. D01")
        submitted = st.form_submit_button("Add bed", width="stretch")
    if submitted:
        ward_name = new_ward.strip() or ward_choice
        if not ward_name:
            st.error("Choose an existing ward or enter a new ward name.")
        else:
            try:
                with session_scope() as session:
                    create_bed(session, ward_name=ward_name, bed_number=bed_number)
                st.success(f"Added bed {ward_name}/{bed_number}.")
                st.rerun()
            except BedManagementError as e:
                st.error(str(e))

    st.markdown("---")
    st.markdown("**Remove a bed**")
    never_used_ids = set(beds_df["id"]) - (set(admissions_df["bed_id"].unique()) if not admissions_df.empty else set())
    removable = board[board["bed_id"].isin(never_used_ids) & (board["status"] == "Free")]
    if removable.empty:
        st.caption(
            "No beds are eligible for removal. Only a free bed with no admission history can "
            "be deleted (to protect the audit trail) -- use Out of Service below for anything else."
        )
    else:
        options = {f"{r.ward} / {r.bed_number}": r.bed_id for r in removable.sort_values(["ward", "bed_number"]).itertuples()}
        label = st.selectbox("Bed (never used, free)", list(options.keys()), key="remove_bed_select")
        if st.button("Remove bed", key="remove_bed_button"):
            try:
                with session_scope() as session:
                    remove_bed(session, bed_id=int(options[label]))
                st.success(f"Removed bed {label}.")
                st.session_state.pop("remove_bed_select", None)
                st.rerun()
            except BedManagementError as e:
                st.error(str(e))

    st.markdown("---")
    st.markdown("**Out of service**")
    oos_col1, oos_col2 = st.columns(2)
    with oos_col1:
        free_beds = board[board["status"] == "Free"]
        if free_beds.empty:
            st.caption("No free beds available to take out of service.")
        else:
            options = {f"{r.ward} / {r.bed_number}": r.bed_id for r in free_beds.sort_values(["ward", "bed_number"]).itertuples()}
            label = st.selectbox("Take out of service", list(options.keys()), key="oos_select")
            reason = st.text_input("Reason (optional)", key="oos_reason", placeholder="e.g. Equipment maintenance")
            if st.button("Mark out of service", key="oos_button"):
                try:
                    with session_scope() as session:
                        set_bed_service_status(
                            session, bed_id=int(options[label]), new_status="Out of Service", reason=reason
                        )
                    st.success(f"{label} marked out of service.")
                    st.session_state.pop("oos_select", None)
                    st.rerun()
                except BedManagementError as e:
                    st.error(str(e))
    with oos_col2:
        oos_beds = board[board["status"] == "Out of Service"]
        if oos_beds.empty:
            st.caption("No beds are currently out of service.")
        else:
            options2 = {}
            for r in oos_beds.sort_values(["ward", "bed_number"]).itertuples():
                label = f"{r.ward} / {r.bed_number}"
                if r.out_of_service_reason:
                    label += f" — {r.out_of_service_reason}"
                options2[label] = r.bed_id
            label2 = st.selectbox("Return to service", list(options2.keys()), key="return_service_select")
            if st.button("Return to service", key="return_service_button"):
                try:
                    with session_scope() as session:
                        set_bed_service_status(session, bed_id=int(options2[label2]), new_status="In Service")
                    st.success(f"{label2} returned to service.")
                    st.session_state.pop("return_service_select", None)
                    st.rerun()
                except BedManagementError as e:
                    st.error(str(e))


def _render_charts(beds_df: pd.DataFrame, resolved: pd.DataFrame, admissions_df: pd.DataFrame) -> None:
    """Render the four charts from already ward-filtered frames.

    Every series here is derived from the same numbers the metric tiles
    use -- in particular out-of-service beds are their own category, not
    silently folded into "Free", so a bar/segment can never disagree with
    the Free Beds tile above it.
    """
    color_map = {"Occupied": COLOR_OCCUPIED, "Free": COLOR_FREE, "Out of Service": COLOR_OOS}
    status_order = ["Occupied", "Free", "Out of Service"]

    chart_col1, chart_col2 = st.columns(2)
    occupied_ids: set = set(resolved["bed_id"].unique()) if not resolved.empty else set()

    if beds_df.empty:
        with chart_col1:
            st.info("No beds yet -- add beds in Manage Beds & Patients to populate the ward chart.")
        with chart_col2:
            st.info("No beds yet -- nothing to break down as occupied vs free.")
    else:
        by_bed = beds_df.assign(
            _oos=beds_df["status"] == OUT_OF_SERVICE,
            _occupied=beds_df["id"].isin(occupied_ids),
        )
        # An out-of-service bed is never counted as occupied *or* free --
        # it is unavailable, matching services/occupancy.compute_occupancy.
        by_bed["Status"] = "Free"
        by_bed.loc[by_bed["_occupied"] & ~by_bed["_oos"], "Status"] = "Occupied"
        by_bed.loc[by_bed["_oos"], "Status"] = OUT_OF_SERVICE

        with chart_col1:
            counts = by_bed.groupby(["ward", "Status"]).size().reset_index(name="Beds")
            fig = px.bar(
                counts, x="ward", y="Beds", color="Status", barmode="stack",
                color_discrete_map=color_map, category_orders={"Status": status_order},
                title="ICU Occupancy by Ward",
            )
            fig.update_traces(marker_line_width=0)
            fig.update_layout(xaxis_title="", yaxis_title="Beds")
            fig.update_yaxes(dtick=1)
            _apply_chart_theme(fig)
            st.plotly_chart(fig, width="stretch")

        with chart_col2:
            split = by_bed["Status"].value_counts()
            labels = [s for s in status_order if split.get(s, 0) > 0]
            values = [int(split[s]) for s in labels]
            fig2 = go.Figure(
                data=[go.Pie(
                    labels=labels, values=values, hole=0.6,
                    marker=dict(colors=[color_map[s] for s in labels], line=dict(color="#ffffff", width=2)),
                    sort=False,
                    textinfo="value+percent",
                )]
            )
            fig2.update_layout(title="Bed availability (current filter)")
            _apply_chart_theme(fig2, showlegend=True)
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
            fig3.update_traces(marker_color=COLOR_AMBER, marker_line_width=0)
            fig3.update_layout(xaxis_title="", yaxis_title="Patients")
            _apply_chart_theme(fig3)
            st.plotly_chart(fig3, width="stretch")

    with chart_col4:
        discharged = annotate_discharges(admissions_df)
        if discharged.empty:
            st.info("No discharge history yet to trend.")
        else:
            trend = discharged.groupby("operational_discharge_date").size().reset_index(name="Discharges")
            trend.columns = ["Operational Discharge Date", "Discharges"]
            trend = trend.sort_values("Operational Discharge Date").tail(14)
            # Format as a label string rather than a raw date: with only a
            # handful of sparse points, Plotly's continuous date axis
            # infers a sub-day tick scale (00:00, 06:00, ...) which reads
            # as noise. A categorical string axis keeps one tick per day.
            trend["Operational Discharge Date"] = trend["Operational Discharge Date"].apply(
                lambda d: pd.Timestamp(d).strftime("%d %b")
            )
            fig4 = px.line(
                trend, x="Operational Discharge Date", y="Discharges", markers=True,
                title="Discharges per Operational Day (last 14)",
            )
            fig4.update_traces(line_color=COLOR_FREE, marker=dict(size=7, color=COLOR_FREE))
            fig4.update_layout(xaxis_title="", yaxis_title="Discharges")
            fig4.update_yaxes(dtick=1)
            _apply_chart_theme(fig4)
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

    with st.container(border=True):
        render_data_quality_grid(
            [
                (
                    "Duplicate Active Records",
                    report.duplicate_active_count,
                    "Patients with more than one 'Occupied' record, resolved to their latest bed.",
                ),
                (
                    "Transfers Detected",
                    report.transfers_detected_count,
                    "Ward/bed moves reconstructed from the admissions data.",
                ),
                (
                    "Invalid Bed Assignments",
                    report.invalid_bed_assignment_count,
                    "Beds currently claimed by more than one patient.",
                ),
                (
                    "Early-Morning Discharges",
                    report.early_morning_discharge_count,
                    f"Discharges logged before {settings.operational_day_cutoff_hour:02d}:00 -- review for after-midnight logging.",
                ),
            ]
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
                cols = ["patient_identifier", "ward", "bed_number", "discharge_time", "operational_discharge_date"]
                _dataframe_or_empty(
                    report.early_morning_discharges[cols] if not report.early_morning_discharges.empty else report.early_morning_discharges,
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
    # Format for display only -- the underlying data/table object used
    # elsewhere is never touched, only this render-time copy.
    table["admission_time"] = table["admission_time"].dt.strftime("%d %b %Y, %H:%M")
    table["discharge_time"] = table["discharge_time"].apply(
        lambda v: "—" if pd.isna(v) else pd.Timestamp(v).strftime("%d %b %Y, %H:%M")
    )
    table["planned_discharge_date"] = table["planned_discharge_date"].apply(
        lambda v: "—" if pd.isna(v) else pd.Timestamp(v).strftime("%d %b %Y")
    )
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
