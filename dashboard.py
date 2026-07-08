import io
import re
import json
from datetime import datetime
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="Reactor Shop — Commissioning Progress Dashboard", layout="wide", page_icon="⚛️")

SHOP_NAME = "Reactor Shop"

# =============================================================================
# 1. STYLING
# =============================================================================
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

# =============================================================================
# 2. CONSTANTS: COMMISSIONING MILESTONES
# =============================================================================
# All systems/equipment in this registry are assumed ALREADY INSTALLED.
# What remains to track is the commissioning test sequence only.
MILESTONES_ALL = ["IT", "PIC", "HT", "PT", "SAW"]

MILESTONE_LABELS = {
    "IT": "IT – Individual Testing",
    "PIC": "PIC – Flushing / Pipe Internal Cleaning",
    "HT": "HT – Hydraulic Test",
    "PT": "PT – Pneumatic Test",
    "SAW": "SAW – System Acceptance Walkdown",
}

# Which milestones apply to each scope tier. Assumption (stated per user's description):
# Systems go through the full sequence; standalone Equipment typically only needs
# IT / Flushing / Hydraulic checks. This is editable below if your scope differs.
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

# =============================================================================
# 3. SESSION STATE
# =============================================================================
if "db" not in st.session_state:
    st.session_state.db = pd.DataFrame(columns=REGISTRY_COLUMNS)
if "test_log" not in st.session_state:
    st.session_state.test_log = pd.DataFrame(columns=[
        "Timestamp", "System", "Component", "Test_Type",
        "Test_Result", "Severity", "Resolved", "Notes"
    ])

# =============================================================================
# 4. HELPERS
# =============================================================================
def default_status_for(scope_tier: str, milestone: str) -> str:
    return "Pending" if milestone in SCOPE_MILESTONES.get(scope_tier, []) else "N/A"

def new_registry_row(system, kks, scope_tier, component, milestone_id, comments, source):
    row = {
        "System": system, "System_KKS": kks, "Scope_Type": scope_tier, "Component": component,
        "Milestone_ID": milestone_id if pd.notna(milestone_id) else "",
        "Comments": comments, "Source": source,
        "Last_Updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    for m in MILESTONES_ALL:
        row[f"{m}_Status"] = default_status_for(scope_tier, m)
    return row

def compute_progress(row) -> float:
    applicable = SCOPE_MILESTONES.get(row["Scope_Type"], [])
    if not applicable:
        return 0.0
    completed = sum(1 for m in applicable if row.get(f"{m}_Status") == "Completed")
    return round(100 * completed / len(applicable), 1)

def badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#cbd5e1")
    label = status if status else "N/A"
    return f'<span class="badge" style="background:{color};">{label}</span>'

def find_match(df, system, component):
    if df.empty or not system or not component:
        return None
    mask = (df["System"].str.strip().str.lower() == str(system).strip().lower()) & \
           (df["Component"].str.strip().str.lower() == str(component).strip().lower())
    idx = df.index[mask]
    return idx[0] if len(idx) else None

# =============================================================================
# 5. LOCAL OLLAMA INTEGRATION — COMMISSIONING NOTE PARSER
# =============================================================================
OLLAMA_URL = "http://localhost:11434/api/generate"

def parse_commissioning_note_with_ai(user_input_text: str):
    """
    Parses a free-text shift/commissioning note into structured milestone
    updates. Only fields the note actually addresses are populated; anything
    not mentioned is returned as null so existing data isn't overwritten.
    """
    try:
        prompt = f"""
        You are a commissioning data extractor at a nuclear power plant Reactor Shop.
        All equipment and systems here are ALREADY INSTALLED. Only commissioning
        test work remains: IT (Individual Testing), PIC (Flushing/pipe cleaning),
        HT (Hydraulic Test), PT (Pneumatic Test), SAW (System Acceptance Walkdown).

        Analyze this note from site commissioning personnel:
        "{user_input_text}"

        Rules:
        1. Scope_Type is "System" if the note discusses an entire system, circuit, or loop.
           Scope_Type is "Equipment" if it refers to one pump, valve, sensor, or vessel.
        2. Equipment normally only goes through IT, PIC, HT — set PT_Status and SAW_Status to null
           unless the note explicitly says a pneumatic test or acceptance walkdown was done on it.
        3. Systems can go through IT, PIC, HT, PT, SAW.
        4. For every milestone status field, output one of "Pending", "In Progress",
           "Completed", "Failed", "N/A" ONLY IF the note actually addresses that milestone.
           If the note does not mention a milestone, output null for that field (do not guess).
        5. Do not output markdown or explanation — JSON only.

        Return strictly this JSON structure:
        {{
            "System": "Name of system",
            "System_KKS": "KKS code or empty string",
            "Scope_Type": "Equipment" or "System",
            "Component": "Tag identifier of component or name",
            "IT_Status": "status or null",
            "PIC_Status": "status or null",
            "HT_Status": "status or null",
            "PT_Status": "status or null",
            "SAW_Status": "status or null",
            "Comments": "Brief summary of the note"
        }}
        """
        response = requests.post(
            OLLAMA_URL,
            json={"model": "llama3.2", "prompt": prompt, "stream": False, "format": "json"},
            timeout=10
        )
        if response.status_code == 200:
            return json.loads(response.json().get("response", "{}"))
    except Exception:
        pass
    return None

# =============================================================================
# 6. LEGACY REGISTRY IMPORT (system/equipment list only — no install %)
# =============================================================================
def _find_header_row(raw: pd.DataFrame):
    for i in range(len(raw)):
        for v in raw.iloc[i]:
            if isinstance(v, str) and "milestone id" in v.lower():
                return i
    return None

def _find_col(header_row: pd.Series, keyword: str):
    for c in header_row.index:
        v = header_row[c]
        if isinstance(v, str) and keyword in v.lower():
            return c
    return None

def _extract_system_name(raw: pd.DataFrame, fallback: str):
    for i in range(min(15, len(raw))):
        for v in raw.iloc[i]:
            if isinstance(v, str) and "part 1" in v.lower():
                pieces = v.split(":")
                if len(pieces) >= 2 and pieces[-1].strip():
                    return pieces[-1].strip()
    return fallback

def _system_kks_from_sheetname(sheet_name: str):
    m = re.match(r"^\s*\d+\s*\.?\s*(.*)$", sheet_name)
    return m.group(1).strip() if m else sheet_name.strip()

def parse_workbook(file_bytes):
    xl = pd.ExcelFile(io.BytesIO(file_bytes))
    sheets = [s for s in xl.sheet_names if not s.strip().lower().startswith("report")]
    rows, skipped = [], []

    for sheet in sheets:
        try:
            raw = xl.parse(sheet, header=None)
            header_idx = _find_header_row(raw)
            if header_idx is None:
                skipped.append(sheet)
                continue

            header_row = raw.iloc[header_idx]
            col_milestone = _find_col(header_row, "milestone id")
            col_type = _find_col(header_row, "type of equipment")
            col_comments = _find_col(header_row, "comment")

            system_kks = _system_kks_from_sheetname(sheet)
            system_name = _extract_system_name(raw, fallback=system_kks)

            r = header_idx + 1
            blank_streak = 0
            while r < len(raw):
                row = raw.iloc[r]
                if any(isinstance(v, str) and ("part 3" in v.lower() or "part 4" in v.lower()) for v in row):
                    break

                milestone = row[col_milestone] if col_milestone is not None else None
                comp_type = row[col_type] if col_type is not None else None

                if pd.isna(milestone) and pd.isna(comp_type):
                    blank_streak += 1
                    r += 1
                    if blank_streak >= 2:
                        break
                    continue
                blank_streak = 0

                comment = str(row[col_comments]).strip() if col_comments is not None and pd.notna(row[col_comments]) else ""
                component_name = comp_type if isinstance(comp_type, str) and comp_type.strip() not in ("", "-") else "Unnamed Component/System"

                is_system = any(kw in component_name.lower() for kw in ["circuit", "system", "loop", "assembly"])
                scope_tier = "System" if is_system else "Equipment"

                rows.append(new_registry_row(system_name, system_kks, scope_tier, component_name, milestone, comment, source=sheet))
                r += 1
        except Exception as exc:
            skipped.append(f"{sheet} ({exc})")

    return pd.DataFrame(rows), skipped

# =============================================================================
# 7. HEADER
# =============================================================================
st.markdown(f"""
<div class="main-header">
  <h1>⚛️ {SHOP_NAME} — Commissioning Progress Dashboard</h1>
  <p>All systems and equipment in this registry are already installed. Tracking covers commissioning
  test milestones only: IT, PIC (flushing), HT, PT, and SAW.</p>
</div>
""", unsafe_allow_html=True)

with st.expander("ℹ️ Milestone abbreviations"):
    for m in MILESTONES_ALL:
        st.markdown(f"- **{m}** — {MILESTONE_LABELS[m].split('–')[1].strip()}")
    st.caption("Systems are tracked through all five milestones. Standalone equipment is tracked through "
               "IT, PIC and HT by default — adjust in code if a specific component also needs PT/SAW.")

# =============================================================================
# 8. SIDEBAR — DATA INPUT PANELS
# =============================================================================
st.sidebar.header("📥 Commissioning Update Panels")

# --- Panel A: Import registry (system/equipment list only) ---
with st.sidebar.expander("📁 Import System/Equipment Registry", expanded=False):
    st.caption("Brings in the list of already-installed systems/equipment. Commissioning milestones start at Pending.")
    uploaded = st.file_uploader("Upload systems/equipment tracker (.xlsx)", type=["xlsx"])
    if uploaded and st.button("Run Registry Import"):
        with st.spinner("Reading workbook..."):
            reg_df, skipped = parse_workbook(uploaded.getvalue())
            if not reg_df.empty:
                st.session_state.db = pd.concat([st.session_state.db, reg_df], ignore_index=True) \
                    .drop_duplicates(subset=["System", "Component"], keep="last")
                st.success(f"✅ Imported {len(reg_df)} registry lines.")
            if skipped:
                st.warning(f"Skipped {len(skipped)} non-conforming sheets.")

# --- Panel B: AI free-text commissioning update ---
with st.sidebar.expander("🤖 AI Commissioning Update", expanded=True):
    st.caption("Paste a shift/field note. The local AI model will figure out which system/equipment and "
               "which milestone(s) it refers to — only the mentioned fields are changed.")
    ai_raw_text = st.text_area(
        "Field note",
        placeholder="e.g., Main Coolant System JAA: flushing complete, hydraulic test in progress today."
    )
    if st.button("Analyze & Stage Update") and ai_raw_text.strip():
        with st.spinner("Parsing note..."):
            extracted = parse_commissioning_note_with_ai(ai_raw_text)
            if extracted:
                match_idx = find_match(st.session_state.db, extracted.get("System", ""), extracted.get("Component", ""))
                if match_idx is not None:
                    base = st.session_state.db.loc[match_idx].to_dict()
                    is_update = True
                else:
                    scope_guess = extracted.get("Scope_Type", "Equipment")
                    base = new_registry_row(
                        extracted.get("System", ""), extracted.get("System_KKS", ""),
                        scope_guess, extracted.get("Component", ""), "AI-LOG", "", "AI Update Engine"
                    )
                    is_update = False

                merged = dict(base)
                merged["System"] = extracted.get("System") or base.get("System", "")
                merged["System_KKS"] = extracted.get("System_KKS") or base.get("System_KKS", "")
                merged["Scope_Type"] = extracted.get("Scope_Type") or base.get("Scope_Type", "Equipment")
                merged["Component"] = extracted.get("Component") or base.get("Component", "")
                for m in MILESTONES_ALL:
                    key = f"{m}_Status"
                    ai_val = extracted.get(key)
                    if ai_val:
                        merged[key] = ai_val
                if extracted.get("Comments"):
                    merged["Comments"] = extracted["Comments"]

                st.session_state.staged_ai_data = merged
                st.session_state.staged_ai_is_update = is_update
                st.session_state.staged_ai_match_idx = match_idx
                st.success("Parsed! Review below.")
            else:
                st.error("Couldn't reach the local AI model (Ollama/llama3.2). You can fill the update in manually below instead.")

# --- Confirmation panel for staged AI data ---
if "staged_ai_data" in st.session_state:
    with st.sidebar.container():
        st.markdown("#### ✅ Confirm Commissioning Update")
        s = st.session_state.staged_ai_data
        is_update = st.session_state.get("staged_ai_is_update", False)
        st.caption("Updating existing record" if is_update else "Creating new record")

        conf_sys = st.text_input("System", value=s.get("System", ""), key="conf_sys")
        conf_kks = st.text_input("KKS Code", value=s.get("System_KKS", ""), key="conf_kks")
        conf_tier = st.selectbox("Scope Tier", ["System", "Equipment"],
                                  index=0 if s.get("Scope_Type") == "System" else 1, key="conf_tier")
        conf_comp = st.text_input("Component/Tag", value=s.get("Component", ""), key="conf_comp")

        applicable = SCOPE_MILESTONES[conf_tier]
        milestone_vals = {}
        cols = st.columns(len(MILESTONES_ALL))
        for i, m in enumerate(MILESTONES_ALL):
            with cols[i]:
                if m in applicable:
                    current_val = s.get(f"{m}_Status", "Pending")
                    if current_val not in STATUS_OPTIONS:
                        current_val = "Pending"
                    milestone_vals[m] = st.selectbox(m, STATUS_OPTIONS, index=STATUS_OPTIONS.index(current_val), key=f"conf_{m}")
                else:
                    st.selectbox(m, ["N/A"], index=0, key=f"conf_{m}_na", disabled=True)
                    milestone_vals[m] = "N/A"

        conf_comm = st.text_area("Remarks", value=s.get("Comments", ""), key="conf_comm")

        if st.button("Commit Update", key="commit_ai_update"):
            row_map = {
                "System": conf_sys, "System_KKS": conf_kks, "Scope_Type": conf_tier, "Component": conf_comp,
                "Milestone_ID": s.get("Milestone_ID", "AI-LOG"),
                "Comments": conf_comm, "Source": "AI Update Engine",
                "Last_Updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            for m in MILESTONES_ALL:
                row_map[f"{m}_Status"] = milestone_vals[m]

            match_idx = st.session_state.get("staged_ai_match_idx")
            if match_idx is not None and match_idx in st.session_state.db.index:
                for key, val in row_map.items():
                    st.session_state.db.loc[match_idx, key] = val
            else:
                st.session_state.db = pd.concat([st.session_state.db, pd.DataFrame([row_map])], ignore_index=True)

            st.success("Commissioning record updated!")
            del st.session_state.staged_ai_data
            st.session_state.pop("staged_ai_is_update", None)
            st.session_state.pop("staged_ai_match_idx", None)
            st.rerun()

# --- Panel C: Manual add / quick update ---
with st.sidebar.expander("🛠️ Manual Add / Update", expanded=False):
    existing_keys = []
    if not st.session_state.db.empty:
        existing_keys = (st.session_state.db["System"] + " — " + st.session_state.db["Component"]).tolist()
    pick = st.selectbox("Update existing record (optional)", ["— New record —"] + existing_keys, key="manual_pick")

    if pick != "— New record —":
        sel_idx = existing_keys.index(pick)
        sel_row = st.session_state.db.iloc[sel_idx]
    else:
        sel_idx = None
        sel_row = None

    with st.form("manual_entry_form"):
        man_sys = st.text_input("System Name", value=sel_row["System"] if sel_row is not None else "")
        man_kks = st.text_input("System KKS", value=sel_row["System_KKS"] if sel_row is not None else "")
        man_type = st.selectbox("Scope Tier", ["System", "Equipment"],
                                 index=0 if (sel_row is not None and sel_row["Scope_Type"] == "System") else 1)
        man_comp = st.text_input("Component/Tag", value=sel_row["Component"] if sel_row is not None else "")

        man_status = {}
        mcols = st.columns(len(MILESTONES_ALL))
        applicable_man = SCOPE_MILESTONES[man_type]
        for i, m in enumerate(MILESTONES_ALL):
            with mcols[i]:
                if m in applicable_man:
                    default_val = sel_row[f"{m}_Status"] if sel_row is not None and sel_row[f"{m}_Status"] in STATUS_OPTIONS else "Pending"
                    man_status[m] = st.selectbox(m, STATUS_OPTIONS, index=STATUS_OPTIONS.index(default_val), key=f"man_{m}")
                else:
                    st.selectbox(m, ["N/A"], index=0, disabled=True, key=f"man_{m}_na")
                    man_status[m] = "N/A"

        man_note = st.text_area("Remarks", value=sel_row["Comments"] if sel_row is not None else "")

        if st.form_submit_button("Save Record"):
            if man_sys and man_comp:
                row_map = {
                    "System": man_sys, "System_KKS": man_kks, "Scope_Type": man_type, "Component": man_comp,
                    "Milestone_ID": sel_row["Milestone_ID"] if sel_row is not None else "MANUAL",
                    "Comments": man_note, "Source": "Manual Entry",
                    "Last_Updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                for m in MILESTONES_ALL:
                    row_map[f"{m}_Status"] = man_status[m]

                if sel_idx is not None:
                    real_idx = st.session_state.db.index[sel_idx]
                    for key, val in row_map.items():
                        st.session_state.db.loc[real_idx, key] = val
                else:
                    st.session_state.db = pd.concat([st.session_state.db, pd.DataFrame([row_map])], ignore_index=True)
                st.success("Saved!")
                st.rerun()

# =============================================================================
# 9. MAIN DASHBOARD
# =============================================================================
db = st.session_state.db.copy()

if not db.empty:
    db["Progress_%"] = db.apply(compute_progress, axis=1)

    total_systems = len(db[db["Scope_Type"] == "System"])
    total_equipment = len(db[db["Scope_Type"] == "Equipment"])
    overall_progress = db["Progress_%"].mean()

    all_status_cells = db[[f"{m}_Status" for m in MILESTONES_ALL]].values.flatten()
    completed_count = sum(1 for s in all_status_cells if s == "Completed")
    failed_count = sum(1 for s in all_status_cells if s == "Failed")
    inprogress_count = sum(1 for s in all_status_cells if s == "In Progress")

    k1, k2, k3, k4, k5 = st.columns(5)
    kpi_data = [
        ("Systems Tracked", total_systems, "commissioning scope"),
        ("Equipment Tracked", total_equipment, "commissioning scope"),
        ("Overall Progress", f"{overall_progress:.1f}%", "avg. milestone completion"),
        ("Milestones In Progress", inprogress_count, "across all records"),
        ("Milestones Failed", failed_count, "needs attention" if failed_count else "none flagged"),
    ]
    for col, (label, value, sub) in zip([k1, k2, k3, k4, k5], kpi_data):
        col.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div>
            <div class="kpi-sub">{sub}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("###")
    tab_charts, tab_matrix, tab_logs, tab_master = st.tabs(
        ["📈 Progress Overview", "🧩 Commissioning Status Matrix", "🧪 Test Logs", "📋 Master Registry"]
    )

    # --- Charts ---
    with tab_charts:
        g1, g2 = st.columns(2)
        with g1:
            sys_progress = db.groupby("System")["Progress_%"].mean().reset_index().sort_values("Progress_%")
            fig1 = px.bar(
                sys_progress, x="Progress_%", y="System", orientation="h",
                color="Progress_%", color_continuous_scale=["#ef4444", "#f59e0b", "#22c55e"], range_color=[0, 100],
                title="Average Commissioning Completion by System"
            )
            fig1.update_layout(coloraxis_showscale=False, xaxis_title="Progress (%)", yaxis_title="")
            st.plotly_chart(fig1, use_container_width=True)
        with g2:
            melted = db.melt(
                id_vars=["System", "Component", "Scope_Type"],
                value_vars=[f"{m}_Status" for m in MILESTONES_ALL],
                var_name="Milestone", value_name="Status"
            )
            melted["Milestone"] = melted["Milestone"].str.replace("_Status", "", regex=False)
            fig2 = px.histogram(
                melted, x="Milestone", color="Status", barmode="stack",
                category_orders={"Milestone": MILESTONES_ALL},
                color_discrete_map=STATUS_COLORS,
                title="Milestone Status Distribution (Shop-wide)"
            )
            fig2.update_layout(yaxis_title="Number of Records")
            st.plotly_chart(fig2, use_container_width=True)

    # --- Status Matrix (colored badge table) ---
    with tab_matrix:
        search = st.text_input("🔍 Filter by system or component", "")
        scope_filter = st.radio("Scope", ["All", "System", "Equipment"], horizontal=True)

        view = db.copy()
        if scope_filter != "All":
            view = view[view["Scope_Type"] == scope_filter]
        if search.strip():
            s_lower = search.strip().lower()
            view = view[
                view["System"].str.lower().str.contains(s_lower) |
                view["Component"].str.lower().str.contains(s_lower)
            ]

        if view.empty:
            st.info("No records match this filter.")
        else:
            html_rows = []
            for _, r in view.sort_values(["System", "Component"]).iterrows():
                cells = "".join(f"<td>{badge(r[f'{m}_Status'])}</td>" for m in MILESTONES_ALL)
                html_rows.append(f"""
                <tr>
                    <td><b>{r['System']}</b><br><span style="color:#94a3b8;font-size:0.75rem;">{r['System_KKS']}</span></td>
                    <td>{r['Component']}</td>
                    <td>{r['Scope_Type']}</td>
                    {cells}
                    <td><b>{r['Progress_%']:.0f}%</b></td>
                    <td style="max-width:220px;color:#64748b;font-size:0.8rem;">{r['Comments']}</td>
                </tr>""")

            header_cells = "".join(f"<th>{m}</th>" for m in MILESTONES_ALL)
            table_html = f"""
            <table class="matrix-table">
                <thead><tr>
                    <th>System</th><th>Component</th><th>Scope</th>{header_cells}<th>Progress</th><th>Remarks</th>
                </tr></thead>
                <tbody>{''.join(html_rows)}</tbody>
            </table>"""
            st.markdown(table_html, unsafe_allow_html=True)

    # --- Test Logs ---
    with tab_logs:
        st.markdown("#### Log a Commissioning Test Result")
        with st.form("test_logging_subform"):
            tl1, tl2 = st.columns(2)
            with tl1:
                log_sys = st.selectbox("System", options=db["System"].unique().tolist())
                log_comp = st.text_input("Component")
            with tl2:
                log_phase = st.selectbox("Milestone Tested", MILESTONES_ALL)
                log_res = st.selectbox("Result", ["Passed", "Failed", "Partial"])
                log_sev = st.selectbox("Anomaly Severity (if any)", ["None", "Low", "Medium", "High"])
            log_text = st.text_area("Findings / Notes")

            if st.form_submit_button("Save Test Log"):
                new_log = {
                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "System": log_sys, "Component": log_comp, "Test_Type": log_phase,
                    "Test_Result": log_res, "Severity": log_sev,
                    "Resolved": log_res == "Passed", "Notes": log_text,
                }
                st.session_state.test_log = pd.concat([st.session_state.test_log, pd.DataFrame([new_log])], ignore_index=True)
                st.success("Test log saved.")
                st.rerun()

        if not st.session_state.test_log.empty:
            st.dataframe(st.session_state.test_log, use_container_width=True)

    # --- Master Registry ---
    with tab_master:
        st.dataframe(db, use_container_width=True)
        csv_bytes = db.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Export Registry (.CSV)", csv_bytes, "reactor_shop_commissioning_registry.csv", "text/csv")

else:
    st.info("💡 The registry is empty. Import your system/equipment list on the left, or log the first "
            "commissioning update using the AI panel or the manual form.")