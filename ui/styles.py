"""
CSS for the dashboard, matching the reference design:

* White / very light background, no gradients.
* Dark navy headings, blue uppercase section titles, red accent color.
* Monospace labels for IDs and stat lines.
* Thin borders, square-ish corners (minimal rounding), generous spacing.
"""
from __future__ import annotations

NAVY = "#0f1e3d"
BLUE = "#1d4ed8"
RED = "#c81e2c"
AMBER = "#c8860d"
BORDER = "#d8dee6"
MUTED = "#5b6472"
BG = "#fbfbfc"
CARD_BG = "#ffffff"

MONO_STACK = "'JetBrains Mono', 'Fira Code', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS_STACK = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

CSS = f"""
<style>
.stApp {{
    background-color: {BG};
}}
html, body, [class*="css"] {{
    font-family: {SANS_STACK};
}}
#MainMenu, footer {{visibility: hidden;}}

.block-container {{
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 1180px;
}}

/* ---------- Header ---------- */
.icu-header {{
    border-bottom: 2px solid {NAVY};
    padding-bottom: 18px;
    margin-bottom: 28px;
}}
.icu-project-id {{
    font-family: {MONO_STACK};
    color: {RED};
    font-size: 0.85rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    margin-bottom: 6px;
}}
.icu-title {{
    color: {NAVY};
    font-size: 2.05rem;
    font-weight: 800;
    line-height: 1.15;
    margin: 0 0 8px 0;
}}
.icu-domain {{
    color: {BLUE};
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 10px;
}}
.icu-meta {{
    font-family: {MONO_STACK};
    color: {MUTED};
    font-size: 0.82rem;
}}

/* ---------- Section titles ---------- */
.icu-section {{
    margin-top: 40px;
    margin-bottom: 14px;
}}
.icu-section-title {{
    color: {BLUE};
    font-size: 0.92rem;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    border-bottom: 1px solid {BORDER};
    padding-bottom: 8px;
}}
.icu-section-sub {{
    color: {MUTED};
    font-size: 0.85rem;
    margin-top: 4px;
}}

/* ---------- Metric tiles ---------- */
.icu-metric-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
}}
.icu-metric {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 14px 16px;
}}
.icu-metric-label {{
    font-family: {MONO_STACK};
    font-size: 0.7rem;
    color: {MUTED};
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 6px;
}}
.icu-metric-value {{
    color: {NAVY};
    font-size: 1.9rem;
    font-weight: 800;
    line-height: 1;
}}
.icu-metric-value.accent-red {{ color: {RED}; }}
.icu-metric-value.accent-blue {{ color: {BLUE}; }}
.icu-metric-value.accent-amber {{ color: {AMBER}; }}

/* ---------- Bed grid ---------- */
.icu-ward-label {{
    font-family: {MONO_STACK};
    font-weight: 700;
    color: {NAVY};
    font-size: 0.95rem;
    margin: 18px 0 8px 0;
    letter-spacing: 0.04em;
}}
.icu-bed-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(108px, 1fr));
    gap: 10px;
    margin-bottom: 6px;
}}
.icu-bed {{
    position: relative;
    border-radius: 3px;
    padding: 9px 10px;
    min-height: 74px;
    font-family: {MONO_STACK};
    border: 1px solid {BORDER};
}}
.icu-bed-free {{
    background: {CARD_BG};
    border: 1px dashed {BORDER};
    color: {MUTED};
}}
.icu-bed-occupied {{
    background: {RED};
    border: 1px solid {RED};
    color: #ffffff;
}}
.icu-bed-id {{
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.03em;
}}
.icu-bed-status {{
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    opacity: 0.85;
    margin-top: 2px;
}}
.icu-bed-patient {{
    font-size: 0.72rem;
    margin-top: 8px;
    font-weight: 600;
}}
.icu-bed-discharge-flag {{
    position: absolute;
    top: 6px;
    right: 6px;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: {AMBER};
    border: 1px solid #ffffff;
}}
.icu-legend {{
    display: flex;
    gap: 18px;
    font-size: 0.75rem;
    color: {MUTED};
    margin: 10px 0 4px 0;
    flex-wrap: wrap;
}}
.icu-legend-swatch {{
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 2px;
    margin-right: 5px;
    vertical-align: middle;
}}

/* ---------- Data quality ---------- */
.icu-dq-card {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-left: 3px solid {RED};
    padding: 12px 14px;
    margin-bottom: 10px;
}}
.icu-dq-card.ok {{
    border-left-color: #2f9e58;
}}
.icu-dq-title {{
    font-family: {MONO_STACK};
    font-weight: 700;
    color: {NAVY};
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}
.icu-dq-count {{
    font-size: 1.4rem;
    font-weight: 800;
    color: {RED};
}}
.icu-dq-count.ok {{ color: #2f9e58; }}
.icu-dq-desc {{
    font-size: 0.78rem;
    color: {MUTED};
    margin-top: 2px;
}}

.icu-callout {{
    background: #fff7ed;
    border: 1px solid #f2d9a8;
    border-left: 3px solid {AMBER};
    padding: 10px 14px;
    font-size: 0.82rem;
    color: #6b4a12;
    margin-bottom: 14px;
}}

hr.icu-divider {{
    border: none;
    border-top: 1px solid {BORDER};
    margin: 32px 0;
}}
</style>
"""
