"""
Shared configuration for the Reactor Shop Commissioning Dashboard.
Single source of truth for page settings, styling, and the KKS / milestone
rules so database.py, ai_engine.py, and dashboard.py never disagree with
each other about what a "System" or "Equipment" record is allowed to have.
"""
import streamlit as st

PAGE_TITLE = "Reactor Shop Commissioning Dashboard"
PAGE_ICON = "⚛️"

BUCKET_NAME = "commissioning-files"

# =============================================================================
# COMMISSIONING MILESTONES (per ROLE spec)
# =============================================================================
MILESTONES = ["it", "pic", "ht", "pt", "saw"]

MILESTONE_LABELS = {
    "it": "IT – Individual Test",
    "pic": "PIC – Post Installation Cleaning / Flushing",
    "ht": "HT – Hydro Test",
    "pt": "PT – Pneumatic Test",
    "saw": "SAW – Start-up and Adjustment Work",
}

# System scope = full 5-stage lifecycle. Equipment scope = PT/SAW are N/A.
SCOPE_MILESTONES = {
    "System": ["it", "pic", "ht", "pt", "saw"],
    "Equipment": ["it", "pic", "ht"],
}

STATUS_OPTIONS = ["Pending", "In Progress", "Completed", "Failed", "N/A"]

STATUS_BADGE_CLASS = {
    "Completed": "badge-verified",
    "In Progress": "badge-progress",
    "Pending": "badge-pending",
    "Failed": "badge-failed",
    "N/A": "badge-pending",
}

# NOTE: get_supabase_client() lives in database.py — it is intentionally NOT
# redefined here. Two independently-cached clients (the previous bug) meant
# the app could silently hold two separate connections. Import it from
# database instead: `from database import get_supabase_client`.


def apply_custom_css():
    """
    Injects custom CSS styling into the Streamlit DOM to optimize workspace layout,
    improve visual hierarchy, and enforce professional engineering aesthetics.
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
        .badge { padding: 4px 10px; border-radius: 999px; font-weight: 700; font-size: 12px; display: inline-block; min-width: 90px; text-align: center; }
        .badge-verified { background-color: #DCFCE7; color: #15803D; }
        .badge-progress { background-color: #FEF9C3; color: #A16207; }
        .badge-pending { background-color: #F1F5F9; color: #475569; }
        .badge-failed { background-color: #FEE2E2; color: #B91C1C; }

        .status-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
        .status-table th { background: #0F172A; color: white; padding: 8px 10px; text-align: left; }
        .status-table td { padding: 7px 10px; border-bottom: 1px solid #eef2f7; vertical-align: middle; }
        .status-table tr:hover { background: #f8fafc; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def badge_html(status: str) -> str:
    """Renders a status value as a colored pill using the CSS classes above."""
    cls = STATUS_BADGE_CLASS.get(status, "badge-pending")
    label = status if status else "N/A"
    return f'<span class="badge {cls}">{label}</span>'
