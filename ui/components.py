"""
Reusable rendering helpers for the Streamlit UI.

Keeping these separate from ui/dashboard.py means the page-assembly logic
in dashboard.py stays readable, and each visual building block (header,
metric tile, bed grid, data-quality card) can be reasoned about and
reused independently.
"""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from ui.styles import AMBER, RED


def render_header(project_id: str, title: str, domain: str, stats_line: str) -> None:
    st.markdown(
        f"""
        <div class="icu-header">
            <div class="icu-project-id">{html.escape(project_id)}</div>
            <div class="icu-title">{html.escape(title)}</div>
            <div class="icu-domain">{html.escape(domain)}</div>
            <div class="icu-meta">{html.escape(stats_line)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_title(title: str, subtitle: str | None = None) -> None:
    sub_html = f'<div class="icu-section-sub">{html.escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="icu-section">
            <div class="icu-section-title">{html.escape(title)}</div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_row(metrics: list[tuple[str, str, str]]) -> None:
    """Render a row of metric tiles.

    ``metrics`` is a list of (label, value, accent) where accent is one
    of "", "red", "blue", "amber".
    """
    tiles = []
    for label, value, accent in metrics:
        accent_class = f"accent-{accent}" if accent else ""
        tiles.append(
            f"""
            <div class="icu-metric">
                <div class="icu-metric-label">{html.escape(label)}</div>
                <div class="icu-metric-value {accent_class}">{html.escape(str(value))}</div>
            </div>
            """
        )
    st.markdown(f'<div class="icu-metric-row">{"".join(tiles)}</div>', unsafe_allow_html=True)


def render_bed_legend() -> None:
    st.markdown(
        f"""
        <div class="icu-legend">
            <span><span class="icu-legend-swatch" style="background:{RED};"></span>Occupied</span>
            <span><span class="icu-legend-swatch" style="background:#ffffff;border:1px dashed #d8dee6;"></span>Free</span>
            <span><span class="icu-legend-swatch" style="background:{AMBER};"></span>Planned discharge</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_ward_bed_grid(ward_name: str, ward_beds: pd.DataFrame) -> None:
    """Render one ward's row of bed tiles.

    ``ward_beds`` must have the columns produced by
    services.occupancy.bed_status_board.
    """
    st.markdown(f'<div class="icu-ward-label">{html.escape(ward_name)}</div>', unsafe_allow_html=True)

    tiles = []
    for _, bed in ward_beds.sort_values("bed_number").iterrows():
        if bed["status"] == "Occupied":
            flag = '<div class="icu-bed-discharge-flag" title="Planned discharge"></div>' if bed["has_planned_discharge"] else ""
            patient = html.escape(str(bed["patient_identifier"]))
            tiles.append(
                f"""
                <div class="icu-bed icu-bed-occupied">
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
                <div class="icu-bed icu-bed-free">
                    <div class="icu-bed-id">{html.escape(str(bed['bed_number']))}</div>
                    <div class="icu-bed-status">Free</div>
                </div>
                """
            )
    st.markdown(f'<div class="icu-bed-grid">{"".join(tiles)}</div>', unsafe_allow_html=True)


def render_data_quality_card(title: str, count: int, description: str) -> None:
    ok = count == 0
    card_class = "icu-dq-card ok" if ok else "icu-dq-card"
    count_class = "icu-dq-count ok" if ok else "icu-dq-count"
    st.markdown(
        f"""
        <div class="{card_class}">
            <div class="icu-dq-title">{html.escape(title)}</div>
            <div class="{count_class}">{count}</div>
            <div class="icu-dq-desc">{html.escape(description)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_callout(message: str) -> None:
    st.markdown(f'<div class="icu-callout">{html.escape(message)}</div>', unsafe_allow_html=True)
