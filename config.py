import streamlit as st
from supabase import create_client, Client

SHOP_NAME = "Reactor Shop"
BUCKET_NAME = "commissioning-files"
# Fall back to localhost if the cloud secret isn't defined
OLLAMA_URL = st.secrets.get("OLLAMA_URL", "http://localhost:11434/api/generate")

MILESTONES_ALL = ["IT", "PIC", "HT", "PT", "SAW"]

MILESTONE_LABELS = {
    "IT": "IT – Individual Testing",
    "PIC": "PIC – Flushing / Pipe Internal Cleaning",
    "HT": "HT – Hydraulic Test",
    "PT": "PT – Pneumatic Test",
    "SAW": "SAW – Start-Up and Adjustment Works",
}

SCOPE_MILESTONES = {
    "System": ["IT", "PIC", "HT", "PT", "SAW"],
    "Equipment": ["IT", "PIC", "HT"],
}

STATUS_OPTIONS = ["Pending", "In Progress", "Completed", "Failed", "N/A"]

STATUS_COLORS = {
    "Pending": "#94a3b8",
    "In Progress": "#f59e0b",
    "Completed": "#22c55e",
    "Failed": "#ef4444",
    "N/A": "#cbd5e1",
}

REGISTRY_COLUMNS = (
    ["System", "System_KKS", "Scope_Type", "Component", "Milestone_ID"]
    + [f"{m}_Status" for m in MILESTONES_ALL]
    + ["Comments", "Source", "Last_Updated"]
)

COLS_PY_TO_DB = {
    "System": "system", "System_KKS": "system_kks", "Scope_Type": "scope_type",
    "Component": "component", "Milestone_ID": "milestone_id",
    "IT_Status": "it_status", "PIC_Status": "pic_status", "HT_Status": "ht_status",
    "PT_Status": "pt_status", "SAW_Status": "saw_status",
    "Comments": "comments", "Source": "source", "Last_Updated": "last_updated",
}
COLS_DB_TO_PY = {v: k for k, v in COLS_PY_TO_DB.items()}

TESTLOG_PY_TO_DB = {
    "Timestamp": "timestamp", "System": "system", "Component": "component",
    "Test_Type": "test_type", "Test_Result": "test_result", "Severity": "severity",
    "Resolved": "resolved", "Notes": "notes",
}
TESTLOG_DB_TO_PY = {v: k for k, v in TESTLOG_PY_TO_DB.items()}

def inject_custom_css():
    st.markdown("""
    <style>
    .main-header {
        background: linear-gradient(120deg, #0f172a 0%, #1e3a5f 55%, #0f4c75 100%);
        padding: 1.6rem 2rem; border-radius: 14px; color: white; margin-bottom: 1.2rem;
        box-shadow: 0 6px 18px rgba(15,23,42,0.25);
    }
    .main-header h1 { margin: 0; font-size: 1.6rem; font-weight: 700; }
    .main-header p { margin: 0.25rem 0 0 0; opacity: 0.85; font-size: 0.95rem; }

    .kpi-card {
        background: white; border-radius: 12px; padding: 1rem 1.1rem;
        border: 1px solid #e5e7eb; box-shadow: 0 2px 6px rgba(0,0,0,0.04);
    }
    .kpi-card .kpi-label { font-size: 0.8rem; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }
    .kpi-card .kpi-value { font-size: 1.9rem; font-weight: 700; color: #0f172a; margin-top: 0.2rem; }
    .kpi-card .kpi-sub { font-size: 0.78rem; color: #94a3b8; margin-top: 0.15rem; }

    .badge {
        display: inline-block; padding: 0.18rem 0.55rem; border-radius: 999px;
        font-size: 0.72rem; font-weight: 700; color: white; min-width: 78px; text-align: center;
    }
    .matrix-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    .matrix-table th { background: #0f172a; color: white; padding: 8px 10px; text-align: left; position: sticky; top: 0; }
    .matrix-table td { padding: 7px 10px; border-bottom: 1px solid #eef2f7; vertical-align: middle; }
    .matrix-table tr:hover { background: #f8fafc; }
    </style>
    """, unsafe_allow_html=True)

@st.cache_resource
def get_supabase_client() -> Client:
    url = st.secrets.get("SUPABASE_URL", "https://ccflqpamuyjwrithqkhi.supabase.co")
    key = st.secrets.get("SUPABASE_KEY", "")
    return create_client(url, key)

supabase = get_supabase_client()
