import re
import streamlit as st
from supabase import create_client, Client

PAGE_TITLE = "Reactor Shop Commissioning Dashboard"
PAGE_ICON = "⚛️"

# =============================================================================
# Single source of truth for commissioning milestones and KKS scope rules.
# Imported by database.py, ai_engine.py, and dashboard.py so all three stay
# in sync — previously each file re-implemented parts of this independently.
# =============================================================================
MILESTONES = ["IT", "PIC", "HT", "PT", "SAW"]

MILESTONE_LABELS = {
    "IT": "IT – Individual Test",
    "PIC": "PIC – Post Installation Cleaning / Flushing",
    "HT": "HT – Hydro Test",
    "PT": "PT – Pneumatic Test",
    "SAW": "SAW – Start-up and Adjustment Work",
}

# System-scope KKS codes (3-letter prefix) go through the full sequence.
# Equipment-scope KKS codes (2-letter prefix) skip PT and SAW.
SCOPE_MILESTONES = {
    "System": ["IT", "PIC", "HT", "PT", "SAW"],
    "Equipment": ["IT", "PIC", "HT"],
}

STATUS_OPTIONS = ["Pending", "In Progress", "Completed", "Failed", "N/A"]

STATUS_BADGE_CLASS = {
    "Completed": "badge-verified",
    "In Progress": "badge-progress",
    "Pending": "badge-pending",
    "Failed": "badge-failed",
    "N/A": "badge-na",
}


@st.cache_resource
def get_supabase_client() -> Client:
    """
    Initializes and caches the connection to the Supabase backend.
    Enforces strict verification of environment variables before allowing execution.

    This is the ONLY place the client should be constructed — database.py
    previously duplicated this logic locally, which risked the two copies
    drifting out of sync. Import this function instead of redefining it.
    """
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")

    if not url or not key:
        st.error(
            "CRITICAL ERROR: Supabase connection parameters ('SUPABASE_URL' and 'SUPABASE_KEY') "
            "are missing from the Streamlit Secrets environment. Application execution halted."
        )
        st.stop()

    try:
        return create_client(url, key)
    except Exception as initialization_error:
        st.error(f"Failed to establish Supabase Client core interface: {str(initialization_error)}")
        st.stop()


def get_kks_scope(kks_code: str) -> str:
    """
    General KKS taxonomy rule:
      - 3-letter alphabetic prefix -> "System"    (e.g. JEA, JAA, JEC)
      - 2-letter alphabetic prefix -> "Equipment" (e.g. AA, AP)

    This replaces the previous hardcoded whitelist of specific prefixes
    (which silently misclassified any valid code it hadn't seen before).
    Falls back to "Equipment" — the narrower, more conservative scope —
    if the code doesn't cleanly resolve to 2 or 3 letters.
    """
    code = str(kks_code).strip().upper()
    match = re.match(r"^[A-Z]+", code)
    prefix = match.group(0) if match else ""

    if len(prefix) == 3:
        return "System"
    if len(prefix) == 2:
        return "Equipment"
    return "Equipment"  # ambiguous/unrecognized code — flagged by caller for review


def default_status_for(scope_tier: str, milestone: str) -> str:
    return "Pending" if milestone in SCOPE_MILESTONES.get(scope_tier, []) else "N/A"


def badge(status: str) -> str:
    """Render a status value as a colored HTML badge using the CSS classes below."""
    css_class = STATUS_BADGE_CLASS.get(status, "badge-pending")
    label = status if status else "N/A"
    return f'<span class="badge {css_class}">{label}</span>'


def apply_custom_css():
    """
    Injects custom CSS styling into the Streamlit DOM to optimize workspace layout,
    improve visual hierarchy, and enforce professional engineering aesthetics.

    NOTE: this must be called explicitly near the top of dashboard.py — it was
    defined but never invoked in the original file, so none of this ever rendered.
    """
    st.markdown(
        """
        <style>
        /* Optimize viewport real estate */
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 1.5rem;
            max-width: 95% !important;
        }

        /* Typography Polish */
        h1 { color: #0F172A; font-weight: 800; letter-spacing: -0.05em; }
        h2 { color: #1E3A8A; font-weight: 700; border-bottom: 2px solid #E2E8F0; padding-bottom: 0.25rem; }
        h3 { color: #0369A1; font-weight: 600; }

        /* Metric Box Adjustments */
        [data-testid="stMetricValue"] { font-size: 2.2rem; font-weight: 700; color: #1E293B; }
        [data-testid="stMetricLabel"] { font-weight: 600; color: #64748B; text-transform: uppercase; font-size: 0.8rem; }

        /* Status Badges */
        .badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block; min-width: 76px; text-align: center; }
        .badge-verified { background-color: #DCFCE7; color: #15803D; }
        .badge-progress { background-color: #FEF9C3; color: #A16207; }
        .badge-pending  { background-color: #F1F5F9; color: #475569; }
        .badge-failed   { background-color: #FEE2E2; color: #B91C1C; }
        .badge-na       { background-color: #F1F5F9; color: #94A3B8; }

        .matrix-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
        .matrix-table th { background: #0F172A; color: white; padding: 8px 10px; text-align: left; }
        .matrix-table td { padding: 7px 10px; border-bottom: 1px solid #eef2f7; vertical-align: middle; }
        .matrix-table tr:hover { background: #f8fafc; }
        </style>
        """,
        unsafe_allow_html=True,
    )
