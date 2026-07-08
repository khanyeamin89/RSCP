from datetime import datetime
import streamlit as st
import plotly.express as px
import pandas as pd

st.set_page_config(page_title="Reactor Shop — Commissioning Progress Dashboard", layout="wide", page_icon="⚛️")

from config import (
    SHOP_NAME, MILESTONES_ALL, MILESTONE_LABELS, SCOPE_MILESTONES,
    STATUS_OPTIONS, STATUS_COLORS, inject_custom_css
)
from database import (
    load_registry, upsert_registry_row, load_test_log, insert_test_log_row,
    upload_file_to_storage, record_file_metadata, load_uploaded_files, get_file_download_url
)
from ai_engine import (
    compute_progress, badge, find_match, parse_commissioning_note_with_ai,
    universal_ai_file_parser, new_registry_row
)

# Initialize application styles
inject_custom_css()

# Render View Header
st.markdown(f"""
<div class="main-header">
  <h1>⚛️ {SHOP_NAME} — Commissioning Progress Dashboard</h1>
  <p>All items in this registry are already installed. Tracking covers milestone executions managed through Supabase real-time persistence layer.</p>
</div>
""", unsafe_allow_html=True)

with st.expander("ℹ️ Milestone abbreviations"):
    for m in MILESTONES_ALL:
        st.markdown(f"- **{m}** — {MILESTONE_LABELS[m].split('–')[1].strip()}")

# Fetch structural elements
db = load_registry()
test_log_df = load_test_log()

# =============================================================================
# SIDEBAR CONTROL CORES
# =============================================================================
st.sidebar.header("📥 Commissioning Update Panels")

# Panel A: Dynamic AI Multi-Format Document Ingestion Engine
with st.sidebar.expander("📁 AI-Powered File Ingestion", expanded=False):
    st.caption("Upload any CSV, Excel worksheet, or TXT field log. The AI will systematically read and index assets.")
    uploaded = st.file_uploader("Upload tracker or log file", type=["xlsx", "csv", "txt"])
    
    if uploaded and st.button("Execute AI Ingestion"):
        with st.spinner("🧠 Local AI is structuralizing file matrix..."):
            file_bytes = uploaded.getvalue()
            parsed_records = universal_ai_file_parser(file_bytes, uploaded.name)
            
            if parsed_records:
                success_count = 0
                for record in parsed_records:
                    row_map = {
                        "System": record.get("System", "Unknown System"),
                        "System_KKS": record.get("System_KKS", ""),
                        "Scope_Type": record.get("Scope_Type", "Equipment"),
                        "Component": record.get("Component", "General"),
                        "Comments": record.get("Comments", "Extracted via AI File Ingestion"),
                        "Source": uploaded.name
                    }
                    for m in MILESTONES_ALL:
                        s_key = f"{m}_Status"
                        ai_status = record.get(s_key, "Pending")
                        row_map[s_key] = ai_status if ai_status in STATUS_OPTIONS else "Pending"
                    
                    try:
                        upsert_registry_row(row_map)
                        success_count += 1
                    except Exception:
                        pass
                
                try:
                    spath = upload_file_to_storage(file_bytes, uploaded.name)
                    if spath: record_file_metadata(uploaded.name, spath, success_count)
                except Exception:
                    pass
                
                st.success(f"✅ AI successfully structuralized {success_count} records into database!")
                st.rerun()
            else:
                st.error("❌ Could not extract records. Validate Ollama connection framework.")

    files_df = load_uploaded_files()
    if not files_df.empty:
        st.markdown("**Previously uploaded files**")
        for _, f in files_df.iterrows():
            try: url = get_file_download_url(f["storage_path"])
            except Exception: url = None
            label = f"{f['file_name']} — {f['rows_imported']} rows ({str(f['uploaded_at'])[:16]})"
            if url: st.markdown(f"[{label}]({url})")
            else: st.caption(label)

# Panel B: Interactive Text Stream Extraction
with st.sidebar.expander("🤖 AI Commissioning Update", expanded=True):
    st.caption("Paste field shift logs. The local model tracks, identifies, and maps targets.")
    ai_raw_text = st.text_area("Field note", placeholder="e.g., Main Coolant System JAA: flushing complete, hydraulic test in progress today.")
    if st.button("Analyze & Stage Update") and ai_raw_text.strip():
        with st.spinner("Parsing note..."):
            extracted = parse_commissioning_note_with_ai(ai_raw_text)
            if extracted:
                match = find_match(db, extracted.get("System", ""), extracted.get("Component", ""))
                base = match if match is not None else new_registry_row(extracted.get("System", ""), extracted.get("System_KKS", ""), extracted.get("Scope_Type", "Equipment"), extracted.get("Component", ""), "AI-LOG", "", "AI Update Engine")
                
                merged = dict(base)
                for k in ["System", "System_KKS", "Scope_Type", "Component", "Comments"]:
                    if extracted.get(k): merged[k] = extracted[k]
                for m in MILESTONES_ALL:
                    if extracted.get(f"{m}_Status"): merged[f"{m}_Status"] = extracted[f"{m}_Status"]
                
                st.session_state.staged_ai_data = merged
                st.success("Parsed! Review below.")
            else:
                st.error("AI parse timeout or model unreachable.")

if "staged_ai_data" in st.session_state:
    with st.sidebar.container():
        st.markdown("#### ✅ Confirm Commissioning Update")
        s = st.session_state.staged_ai_data
        conf_sys = st.text_input("System", value=s.get("System", ""))
        conf_kks = st.text_input("KKS Code", value=s.get("System_KKS", ""))
        conf_tier = st.selectbox("Scope Tier", ["System", "Equipment"], index=0 if s.get("Scope_Type") == "System" else 1)
        conf_comp = st.text_input("Component/Tag", value=s.get("Component", ""))

        applicable = SCOPE_MILESTONES[conf_tier]
        milestone_vals = {}
        cols = st.columns(len(MILESTONES_ALL))
        for i, m in enumerate(MILESTONES_ALL):
            with cols[i]:
                if m in applicable:
                    cur = s.get(f"{m}_Status", "Pending")
                    if cur not in STATUS_OPTIONS: cur = "Pending"
                    milestone_vals[m] = st.selectbox(m, STATUS_OPTIONS, index=STATUS_OPTIONS.index(cur), key=f"conf_{m}")
                else:
                    st.selectbox(m, ["N/A"], index=0, disabled=True, key=f"conf_{m}_na")
                    milestone_vals[m] = "N/A"

        conf_comm = st.text_area("Remarks", value=s.get("Comments", ""))

        if st.button("Commit Update", key="commit_ai_update"):
            row_map = {
                "System": conf_sys, "System_KKS": conf_kks, "Scope_Type": conf_tier, "Component": conf_comp,
                "Milestone_ID": s.get("Milestone_ID", "AI-LOG"), "Comments": conf_comm, "Source": "AI Update Engine",
            }
            for m in MILESTONES_ALL: row_map[f"{m}_Status"] = milestone_vals[m]
            upsert_registry_row(row_map)
            st.success("Saved into database context!")
            del st.session_state.staged_ai_data
            st.rerun()

# Panel C: Manual Explicit Operations Override
with st.sidebar.expander("🛠️ Manual Add / Update", expanded=False):
    existing_keys = []
    if not db.empty: existing_keys = (db["System"] + " — " + db["Component"]).tolist()
    pick = st.selectbox("Update existing record (optional)", ["— New record —"] + existing_keys, key="manual_pick")
    sel_row = db.iloc[existing_keys.index(pick)] if pick != "— New record —" else None

    with st.form("manual_entry_form"):
        man_sys = st.text_input("System Name", value=sel_row["System"] if sel_row is not None else "")
        man_kks = st.text_input("System KKS", value=sel_row["System_KKS"] if sel_row is not None else "")
        man_type = st.selectbox("Scope Tier", ["System", "Equipment"], index=0 if (sel_row is not None and sel_row["Scope_Type"] == "System") else 1)
        man_comp = st.text_input("Component/Tag", value=sel_row["Component"] if sel_row is not None else "")

        man_status = {}
        mcols = st.columns(len(MILESTONES_ALL))
        applicable_man = SCOPE_MILESTONES[man_type]
        for i, m in enumerate(MILESTONES_ALL):
            with mcols[i]:
                if m in applicable_man:
                    def_val = sel_row[f"{m}_Status"] if sel_row is not None and sel_row[f"{m}_Status"] in STATUS_OPTIONS else "Pending"
                    man_status[m] = st.selectbox(m, STATUS_OPTIONS, index=STATUS_OPTIONS.index(def_val), key=f"man_{m}")
                else:
                    st.selectbox(m, ["N/A"], index=0, disabled=True, key=f"man_{m}_na")
                    man_status[m] = "N/A"

        man_note = st.text_area("Remarks", value=sel_row["Comments"] if sel_row is not None else "")

        if st.form_submit_button("Save Record"):
            if man_sys and man_comp:
                row_map = {
                    "System": man_sys, "System_KKS": man_kks, "Scope_Type": man_type, "Component": man_comp,
                    "Milestone_ID": sel_row["Milestone_ID"] if sel_row is not None else "MANUAL", "Comments": man_note, "Source": "Manual Entry",
                }
                for m in MILESTONES_ALL: row_map[f"{m}_Status"] = man_status[m]
                upsert_registry_row(row_map)
                st.success("Saved explicitly!")
                st.rerun()

# =============================================================================
# DATA GRAPH INTERFACES
# =============================================================================
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
    tab_charts, tab_matrix, tab_logs, tab_master = st.tabs(["📈 Progress Overview", "🧩 Commissioning Status Matrix", "🧪 Test Logs", "📋 Master Registry"])

    with tab_charts:
        g1, g2 = st.columns(2)
        with g1:
            sys_progress = db.groupby("System")["Progress_%"].mean().reset_index().sort_values("Progress_%")
            fig1 = px.bar(sys_progress, x="Progress_%", y="System", orientation="h", color="Progress_%", color_continuous_scale=["#ef4444", "#f59e0b", "#22c55e"], range_color=[0, 100], title="Average Commissioning Completion by System")
            fig1.update_layout(coloraxis_showscale=False, xaxis_title="Progress (%)", yaxis_title="")
            st.plotly_chart(fig1, use_container_width=True)
        with g2:
            melted = db.melt(id_vars=["System", "Component", "Scope_Type"], value_vars=[f"{m}_Status" for m in MILESTONES_ALL], var_name="Milestone", value_name="Status")
            melted["Milestone"] = melted["Milestone"].str.replace("_Status", "", regex=False)
            fig2 = px.histogram(melted, x="Milestone", color="Status", barmode="stack", category_orders={"Milestone": MILESTONES_ALL}, color_discrete_map=STATUS_COLORS, title="Milestone Status Distribution (Shop-wide)")
            st.plotly_chart(fig2, use_container_width=True)

    with tab_matrix:
        search = st.text_input("🔍 Filter by system or component", "")
        scope_filter = st.radio("Scope", ["All", "System", "Equipment"], horizontal=True)
        view = db.copy()
        if scope_filter != "All": view = view[view["Scope_Type"] == scope_filter]
        if search.strip():
            s_lower = search.strip().lower()
            view = view[view["System"].str.lower().str.contains(s_lower) | view["Component"].str.lower().str.contains(s_lower)]

        if view.empty: st.info("No records match this filter.")
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
            table_html = f"""<table class="matrix-table"><thead><tr><th>System</th><th>Component</th><th>Scope</th>{header_cells}<th>Progress</th><th>Remarks</th></tr></thead><tbody>{''.join(html_rows)}</tbody></table>"""
            st.markdown(table_html, unsafe_allow_html=True)

    with tab_logs:
        st.markdown("#### Log a Commissioning Test Result")
        with st.form("test_logging_subform"):
            tl1, tl2 = st.columns(2)
            with tl1:
                log_sys = st.selectbox("System", options=db["System"].unique().tolist() if not db.empty else [""])
                log_comp = st.text_input("Component")
            with tl2:
                log_phase = st.selectbox("Milestone Tested", MILESTONES_ALL)
                log_res = st.selectbox("Result", ["Passed", "Failed", "Partial"])
                log_sev = st.selectbox("Anomaly Severity (if any)", ["None", "Low", "Medium", "High"])
            log_text = st.text_area("Findings / Notes")
            if st.form_submit_button("Save Test Log"):
                new_log = {"Timestamp": datetime.now().isoformat(), "System": log_sys, "Component": log_comp, "Test_Type": log_phase, "Test_Result": log_res, "Severity": log_sev, "Resolved": log_res == "Passed", "Notes": log_text}
                insert_test_log_row(new_log)
                st.success("Test log saved to Supabase.")
                st.rerun()
        if not test_log_df.empty: st.dataframe(test_log_df, use_container_width=True)

    with tab_master:
        st.dataframe(db, use_container_width=True)
        csv_bytes = db.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Export Registry (.CSV)", csv_bytes, "reactor_shop_commissioning_registry.csv", "text/csv")
else:
    st.info("💡 The registry database is completely unpopulated. Execute initialization routines via file upload or text processors on the left panel.")
