"""
Entry point for the ICU Bed Occupancy Dashboard.

Run with:
    streamlit run app.py
"""
from __future__ import annotations

import logging
import traceback

import streamlit as st

from database.database import init_db
from ui.dashboard import render

logger = logging.getLogger("icu_dashboard")


def main() -> None:
    st.set_page_config(
        page_title="ICU Bed Occupancy Dashboard",
        page_icon="\U0001FA7A",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    init_db()

    try:
        render()
    except Exception:
        # Never leak a raw Python traceback to a hospital-administration
        # end user. Log the full detail for operators (visible in the
        # terminal running `streamlit run`) and show a plain message in
        # the UI instead. See README "Error handling" for details.
        logger.error("Unhandled error while rendering the dashboard:\n%s", traceback.format_exc())
        st.error(
            "Something went wrong while loading the dashboard. "
            "Please try again, or reset to the sample dataset from the "
            "'Import / manage admissions data' panel above."
        )


if __name__ == "__main__":
    main()
