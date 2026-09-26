"""
Reusable rendering helpers for the Streamlit UI.

Keeping these separate from ui/dashboard.py means the page-assembly logic
in dashboard.py stays readable, and each visual building block (header,
metric tile, bed grid, data-quality card) can be reasoned about and
reused independently.

All raw markup below is inserted with ``st.html()`` rather than
``st.markdown(..., unsafe_allow_html=True)``. Streamlit's markdown
renderer runs content through a CommonMark parser first and only treats
a raw HTML *block* as opaque up to the next blank line -- a multi-line,
blank-line-separated CSS/HTML string like ours gets partially
re-interpreted as Markdown (e.g. a bare `*` selector reads as a bullet
list), which visibly breaks the page. ``st.html()`` inserts the string
as-is (sanitized, but never re-tokenized as Markdown), which is what
every block here actually needs.
"""
from __future__ import annotations

import datetime as dt
import html

import pandas as pd
import streamlit as st

from ui.styles import AMBER, RED


def render_header(project_id: str, title: str, domain: str, stats_line: str) -> None:
    now = dt.datetime.now()
    st.html(
        f"""
        <div class="icu-header">
            <div class="icu-header-main">
                <div class="icu-project-id">{html.escape(project_id)}</div>
                <div class="icu-title">{html.escape(title)}</div>
                <div class="icu-domain-row">
                    <span class="icu-domain">{html.escape(domain)}</span>
                    <span class="icu-live-pill"><span class="icu-live-dot"></span>Live</span>
                </div>
                <div class="icu-meta">{html.escape(stats_line)}</div>
            </div>
            <div class="icu-header-aside">
                <div class="icu-clock">{now.strftime('%H:%M')}</div>
                <div>{now.strftime('%a, %d %b %Y')}</div>
            </div>
        </div>
        """
    )


def render_section_title(index: str, title: str, subtitle: str | None = None) -> None:
    sub_html = f'<div class="icu-section-sub">{html.escape(subtitle)}</div>' if subtitle else ""
    st.html(
        f"""
        <div class="icu-section">
            <div class="icu-section-title-row">
                <span class="icu-section-index">{html.escape(index)}</span>
                <span class="icu-section-title">{html.escape(title)}</span>
            </div>
            {sub_html}
        </div>
        """
    )


def render_metric_row(metrics: list[tuple[str, str, str, str]]) -> None:
    """Render a row of metric tiles.

    ``metrics`` is a list of (label, value, unit, accent) where accent is
    one of "", "red", "blue", "amber".
    """
    tiles = []
    for label, value, unit, accent in metrics:
        accent_class = f"accent-{accent}" if accent else ""
        unit_html = f'<span class="icu-metric-unit">{html.escape(unit)}</span>' if unit else ""
        tiles.append(
            f"""
            <div class="icu-metric {accent_class}">
                <div class="icu-metric-label">{html.escape(label)}</div>
                <div class="icu-metric-value-row">
                    <span class="icu-metric-value {accent_class}">{html.escape(str(value))}</span>
                    {unit_html}
                </div>
            </div>
            """
        )
    st.html(f'<div class="icu-metric-row">{"".join(tiles)}</div>')


def render_bed_legend() -> None:
    st.html(
        f"""
        <div class="icu-legend">
            <span class="icu-legend-item"><span class="icu-legend-swatch" style="background:{RED};"></span>Occupied</span>
            <span class="icu-legend-item"><span class="icu-legend-swatch" style="background:#f4f5f7;border:1px solid #dde2e9;"></span>Free</span>
            <span class="icu-legend-item"><span class="icu-legend-swatch" style="background:{AMBER};"></span>Planned discharge (hover a bed for details)</span>
        </div>
        """
    )


def _format_dt(value) -> str:
    if value is None or pd.isna(value):
        return "--"
    return pd.Timestamp(value).strftime("%d %b, %H:%M")


def _format_date(value) -> str:
    if value is None or pd.isna(value):
        return "not set"
    return pd.Timestamp(value).strftime("%d %b %Y")


def render_ward_bed_grid(ward_name: str, ward_beds: pd.DataFrame) -> None:
    """Render one ward's row of bed tiles.

    ``ward_beds`` must have the columns produced by
    services.occupancy.bed_status_board.
    """
    occupied_count = int((ward_beds["status"] == "Occupied").sum())
    total_count = len(ward_beds)

    tiles = []
    for _, bed in ward_beds.sort_values("bed_number").iterrows():
        if bed["status"] == "Occupied":
            flag = (
                '<div class="icu-bed-discharge-flag" title="Discharge planned"></div>'
                if bed["has_planned_discharge"]
                else ""
            )
            patient = html.escape(str(bed["patient_identifier"]))
            since = pd.Timestamp(bed["admission_time"])
            los_days = max((pd.Timestamp.now().normalize() - since.normalize()).days, 0)
            tooltip = (
                f"Patient {bed['patient_identifier']} — admitted {_format_dt(bed['admission_time'])} "
                f"({los_days}d) — planned discharge: {_format_date(bed['planned_discharge_date'])}"
            )
            tiles.append(
                f"""
                <div class="icu-bed icu-bed-occupied" title="{html.escape(tooltip)}">
                    {flag}
                    <div class="icu-bed-id">{html.escape(str(bed['bed_number']))}</div>
                    <div class="icu-bed-status">Occupied</div>
                    <div class="icu-bed-patient">{patient}</div>
                </div>
                """
            )
        else:
            tiles.append(
                f"""
                <div class="icu-bed icu-bed-free" title="Bed {html.escape(str(bed['bed_number']))} is free">
                    <div class="icu-bed-id">{html.escape(str(bed['bed_number']))}</div>
                    <div class="icu-bed-status">Free</div>
                </div>
                """
            )

    st.html(
        f"""
        <div class="icu-ward-block">
            <div class="icu-ward-header">
                <span class="icu-ward-label">{html.escape(ward_name)}</span>
                <span class="icu-ward-count">{occupied_count}/{total_count} occupied</span>
            </div>
            <div class="icu-bed-grid">{"".join(tiles)}</div>
        </div>
        """
    )


def render_data_quality_grid(cards: list[tuple[str, int, str]]) -> None:
    """Render every data-quality metric as one consistent card grid.

    ``cards`` is a list of (title, count, description).
    """
    blocks = []
    for title, count, description in cards:
        ok = count == 0
        card_class = "icu-dq-card ok" if ok else "icu-dq-card"
        count_class = "icu-dq-count ok" if ok else "icu-dq-count"
        blocks.append(
            f"""
            <div class="{card_class}">
                <div class="icu-dq-title">{html.escape(title)}</div>
                <div class="{count_class}">{count}</div>
                <div class="icu-dq-desc">{html.escape(description)}</div>
            </div>
            """
        )
    st.html(f'<div class="icu-dq-grid">{"".join(blocks)}</div>')


def render_callout(message: str) -> None:
    st.html(f'<div class="icu-callout">{html.escape(message)}</div>')


def render_footnote(message: str) -> None:
    st.html(f'<div class="icu-footnote">{html.escape(message)}</div>')
