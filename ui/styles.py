"""
CSS for the dashboard.

Design language: clean hospital-administration console. White/near-white
background, dark navy for headings and data, a single blue for section
identity, red reserved strictly for "occupied / attention" states, amber
reserved strictly for "planned discharge / review" states. Thin 1px
borders, minimal radius (4-6px, never pill-shaped), no gradients, no
drop shadows heavier than a hairline. Numbers set in tabular figures so
columns of metrics line up.

Two layers are combined:
1. Custom HTML blocks (header, section titles, metric tiles, bed grid,
   data-quality cards) -- fully our own markup/classes.
2. Overrides for Streamlit's *native* widgets (buttons, selectboxes,
   file uploader, tabs, expander, dataframe, alerts) so they read as
   part of the same system instead of default Streamlit chrome. The
   selectors below target the stable `data-testid`/class values Streamlit
   1.6x actually renders (verified against the installed package), not
   the auto-generated emotion-cache hashes, so this survives Streamlit
   point-releases.
"""
from __future__ import annotations

NAVY = "#0f1e3d"
NAVY_SOFT = "#33415c"
BLUE = "#1d4ed8"
BLUE_SOFT = "#e8eefc"
RED = "#c81e2c"
RED_SOFT = "#fbe9ea"
AMBER = "#b5790a"
AMBER_SOFT = "#fdf1dc"
GREEN = "#1c7a4d"
BORDER = "#dde2e9"
MUTED = "#5b6472"
BG = "#f4f5f7"
PAGE_EDGE = "#eef0f3"
CARD_BG = "#ffffff"

MONO_STACK = "'IBM Plex Mono', 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS_STACK = "'IBM Plex Sans', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

CSS = f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {{
    --navy: {NAVY};
    --navy-soft: {NAVY_SOFT};
    --blue: {BLUE};
    --blue-soft: {BLUE_SOFT};
    --red: {RED};
    --red-soft: {RED_SOFT};
    --amber: {AMBER};
    --amber-soft: {AMBER_SOFT};
    --green: {GREEN};
    --border: {BORDER};
    --muted: {MUTED};
    --bg: {BG};
    --card-bg: {CARD_BG};
    --mono: {MONO_STACK};
    --sans: {SANS_STACK};
    --radius: 5px;
}}

/* ================================================================
   Page shell
   ================================================================ */
.stApp {{ background-color: var(--bg); }}
html, body, [class*="css"] {{ font-family: var(--sans); }}
* {{ box-sizing: border-box; }}

#MainMenu, footer, header[data-testid="stHeader"], div[data-testid="stAppHeader"] {{ visibility: hidden; height: 0; }}
div[data-testid="stToolbar"], div[data-testid="stAppToolbar"] {{ display: none; }}
div[data-testid="stDecoration"] {{ display: none; }}

section[data-testid="stMain"] {{ background: var(--bg); }}
div[data-testid="stMainBlockContainer"], .block-container {{
    padding-top: 1.75rem;
    padding-bottom: 3.5rem;
    max-width: 1220px;
}}

/* Tighten Streamlit's default inter-element gap so custom HTML blocks
   sit at a consistent rhythm instead of floating with uneven, oversized
   whitespace. */
div[data-testid="stVerticalBlock"] {{ gap: 0.65rem; }}
div[data-testid="stHorizontalBlock"] {{ gap: 0.85rem; align-items: stretch; }}

/* Numbers line up in a column instead of jittering left/right. */
.icu-tabular, .icu-metric-value, .icu-dq-count, .icu-bed-id {{
    font-variant-numeric: tabular-nums;
}}

/* ================================================================
   Header
   ================================================================ */
.icu-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 24px;
    border-bottom: 2px solid var(--navy);
    padding-bottom: 20px;
    margin-bottom: 22px;
    flex-wrap: wrap;
}}
.icu-header-main {{ min-width: 260px; }}
.icu-project-id {{
    font-family: var(--mono);
    color: var(--red);
    font-size: 0.82rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    margin-bottom: 8px;
}}
.icu-title {{
    color: var(--navy);
    font-size: 2.1rem;
    font-weight: 800;
    line-height: 1.12;
    margin: 0 0 10px 0;
    letter-spacing: -0.01em;
}}
.icu-domain-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }}
.icu-domain {{
    color: var(--blue);
    font-size: 0.76rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}}
.icu-live-pill {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-family: var(--mono);
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--green);
    background: #eaf7f0;
    border: 1px solid #c6e9d5;
    border-radius: 999px;
    padding: 2px 10px 2px 8px;
}}
.icu-live-dot {{
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 0 2px #eaf7f0;
}}
.icu-meta {{
    font-family: var(--mono);
    color: var(--muted);
    font-size: 0.82rem;
}}
.icu-header-aside {{
    text-align: right;
    font-family: var(--mono);
    color: var(--muted);
    font-size: 0.78rem;
    line-height: 1.6;
    padding-bottom: 4px;
}}
.icu-header-aside .icu-clock {{
    color: var(--navy);
    font-weight: 700;
    font-size: 0.95rem;
}}

/* ================================================================
   Section titles
   ================================================================ */
.icu-section {{
    margin-top: 34px;
    margin-bottom: 12px;
}}
.icu-section-title-row {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 9px;
}}
.icu-section-index {{
    font-family: var(--mono);
    color: var(--border);
    font-size: 0.78rem;
    font-weight: 700;
}}
.icu-section-title {{
    color: var(--blue);
    font-size: 0.86rem;
    font-weight: 700;
    letter-spacing: 0.13em;
    text-transform: uppercase;
}}
.icu-section-sub {{
    color: var(--muted);
    font-size: 0.83rem;
    margin-top: 5px;
}}

/* A subtle bordered panel that gives each section body a defined edge
   instead of raw HTML/widgets floating directly on the page background.
   Deliberately low-radius, no shadow heavier than a hairline, no
   gradient. */
.icu-panel {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 18px 20px;
}}
.icu-panel + .icu-panel {{ margin-top: 10px; }}

/* ================================================================
   Metric tiles
   ================================================================ */
.icu-metric-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 1px;
    background: var(--border);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
}}
.icu-metric {{
    background: var(--card-bg);
    padding: 16px 18px 14px 18px;
    border-top: 3px solid var(--navy);
}}
.icu-metric.accent-red {{ border-top-color: var(--red); }}
.icu-metric.accent-blue {{ border-top-color: var(--blue); }}
.icu-metric.accent-amber {{ border-top-color: var(--amber); }}
.icu-metric-label {{
    font-family: var(--mono);
    font-size: 0.66rem;
    color: var(--muted);
    letter-spacing: 0.07em;
    text-transform: uppercase;
    margin-bottom: 8px;
    white-space: nowrap;
}}
.icu-metric-value-row {{ display: flex; align-items: baseline; gap: 5px; }}
.icu-metric-value {{
    color: var(--navy);
    font-size: 1.85rem;
    font-weight: 800;
    line-height: 1;
}}
.icu-metric-unit {{
    color: var(--muted);
    font-size: 0.72rem;
    font-weight: 600;
}}
.icu-metric-value.accent-red {{ color: var(--red); }}
.icu-metric-value.accent-blue {{ color: var(--blue); }}
.icu-metric-value.accent-amber {{ color: var(--amber); }}

/* ================================================================
   Bed grid
   ================================================================ */
.icu-ward-block + .icu-ward-block {{ margin-top: 18px; }}
.icu-ward-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 9px;
}}
.icu-ward-label {{
    font-family: var(--mono);
    font-weight: 700;
    color: var(--navy);
    font-size: 0.92rem;
    letter-spacing: 0.03em;
}}
.icu-ward-count {{
    font-family: var(--mono);
    font-size: 0.72rem;
    color: var(--muted);
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 2px 10px;
}}
.icu-bed-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(112px, 1fr));
    gap: 8px;
}}
.icu-bed {{
    position: relative;
    border-radius: 4px;
    padding: 9px 10px 8px 10px;
    min-height: 78px;
    font-family: var(--mono);
    border: 1px solid var(--border);
    transition: box-shadow 120ms ease, transform 120ms ease;
}}
.icu-bed:hover {{ box-shadow: 0 0 0 1px var(--navy) inset; }}
.icu-bed-free {{
    background: var(--bg);
    color: var(--muted);
    cursor: default;
}}
.icu-bed-occupied {{
    background: var(--red);
    border: 1px solid var(--red);
    color: #ffffff;
    cursor: help;
}}
.icu-bed-oos {{
    background: repeating-linear-gradient(45deg, #e7e9ed, #e7e9ed 7px, #dadde3 7px, #dadde3 14px);
    color: var(--muted);
    border: 1px solid #c9ced7;
    cursor: help;
}}
.icu-bed-id {{ font-size: 0.8rem; font-weight: 700; letter-spacing: 0.02em; }}
.icu-bed-status {{
    font-size: 0.6rem;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    opacity: 0.9;
    margin-top: 2px;
}}
.icu-bed-patient {{
    font-size: 0.74rem;
    margin-top: 9px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}}
.icu-bed-discharge-flag {{
    position: absolute;
    top: 6px;
    right: 6px;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--amber);
    border: 1.5px solid #ffffff;
}}
.icu-legend {{
    display: flex;
    gap: 20px;
    font-size: 0.76rem;
    color: var(--muted);
    margin-bottom: 14px;
    flex-wrap: wrap;
}}
.icu-legend-item {{ display: inline-flex; align-items: center; gap: 6px; }}
.icu-legend-swatch {{
    display: inline-block;
    width: 11px;
    height: 11px;
    border-radius: 2px;
}}

/* ================================================================
   Data quality
   ================================================================ */
.icu-dq-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 10px;
}}
.icu-dq-card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-left: 3px solid var(--red);
    border-radius: 0 var(--radius) var(--radius) 0;
    padding: 13px 15px;
}}
.icu-dq-card.ok {{ border-left-color: var(--green); }}
.icu-dq-title {{
    font-family: var(--mono);
    font-weight: 700;
    color: var(--navy);
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}}
.icu-dq-count {{ font-size: 1.55rem; font-weight: 800; color: var(--red); margin-top: 4px; }}
.icu-dq-count.ok {{ color: var(--green); }}
.icu-dq-desc {{ font-size: 0.76rem; color: var(--muted); margin-top: 3px; line-height: 1.4; }}

.icu-callout {{
    background: var(--amber-soft);
    border: 1px solid #f0dcae;
    border-left: 3px solid var(--amber);
    border-radius: 0 var(--radius) var(--radius) 0;
    padding: 11px 15px;
    font-size: 0.83rem;
    color: #6b4a12;
}}

.icu-footnote {{
    font-family: var(--mono);
    font-size: 0.72rem;
    color: var(--muted);
    margin-top: 46px;
    padding-top: 14px;
    border-top: 1px solid var(--border);
}}

/* ================================================================
   Native Streamlit widgets -- brought into the same system
   ================================================================ */

/* Buttons */
div[data-testid="stButton"] button {{
    font-family: var(--sans);
    font-weight: 600;
    font-size: 0.85rem;
    border-radius: 4px;
    border: 1px solid var(--navy);
    color: var(--navy);
    background: #ffffff;
    padding: 0.45rem 1rem;
    transition: background 120ms ease, color 120ms ease;
}}
div[data-testid="stButton"] button:hover {{
    background: var(--navy);
    color: #ffffff;
    border-color: var(--navy);
}}
div[data-testid="stButton"] button:disabled {{
    color: var(--muted);
    border-color: var(--border);
    background: var(--bg);
}}
div[data-testid="stButton"] button kbd,
div[data-testid="stButton"] button p {{ font-weight: 600; }}
/* Primary-looking action (Reset) gets the red accent via nth-of-type in
   the two-button row rendered by the data-source panel. */

/* Selectbox / multiselect / text & date inputs */
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
div[data-testid="stDateInput"] input,
div[data-testid="stTextInput"] input,
div[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {{
    border-radius: 4px !important;
    border-color: var(--border) !important;
    font-family: var(--sans);
}}
div[data-testid="stSelectbox"] label,
div[data-testid="stDateInput"] label,
div[data-testid="stTextInput"] label,
div[data-testid="stFileUploader"] label {{
    font-family: var(--mono);
    font-size: 0.72rem;
    color: var(--navy-soft);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    font-weight: 600;
}}

/* File uploader */
div[data-testid="stFileUploaderDropzone"] {{
    background: var(--bg);
    border: 1px dashed var(--border);
    border-radius: 4px;
}}

/* Tabs */
div[data-testid="stTabs"] button[data-testid="stTab"] {{
    font-family: var(--mono);
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--muted);
}}
div[data-testid="stTabs"] button[aria-selected="true"] {{
    color: var(--blue);
}}
div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{
    background-color: var(--blue);
}}
div[data-testid="stTabs"] [data-baseweb="tab-border"] {{
    background-color: var(--border);
}}

/* Expander */
div[data-testid="stExpander"] {{
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--card-bg);
}}
div[data-testid="stExpander"] summary {{
    font-family: var(--sans);
    font-weight: 600;
    color: var(--navy);
    font-size: 0.9rem;
}}

/* Dataframe */
div[data-testid="stDataFrame"] {{
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
}}

/* Alerts (st.error / st.success / st.info / st.warning) */
div[data-testid="stAlert"] {{
    border-radius: 0 var(--radius) var(--radius) 0;
    border-width: 1px 1px 1px 3px;
    border-style: solid;
    font-size: 0.86rem;
}}

/* Captions */
div[data-testid="stCaptionContainer"] {{
    color: var(--muted) !important;
    font-size: 0.8rem !important;
}}

/* Columns used as filter/metric rows: kill Streamlit's default column
   min-width collapse quirks so our grids control wrapping instead. */
div[data-testid="stColumn"] {{ min-width: 0; }}

/* ================================================================
   Phone-width layout (~400px): stack any native st.columns() row
   (filters, upload buttons, chart pairs) into full-width rows instead
   of squeezing three controls into a sliver each.
   ================================================================ */
@media (max-width: 640px) {{
    div[data-testid="stMainBlockContainer"], .block-container {{
        padding-left: 1rem;
        padding-right: 1rem;
    }}
    div[data-testid="stHorizontalBlock"] {{ flex-wrap: wrap !important; }}
    div[data-testid="stColumn"] {{
        min-width: 100% !important;
        flex: 1 1 100% !important;
    }}
    .icu-header {{ flex-direction: column; align-items: flex-start; }}
    .icu-header-aside {{ text-align: left; }}
    .icu-title {{ font-size: 1.6rem; }}
}}
</style>
"""
