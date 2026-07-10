"""
Reactor Shop Commissioning - Main Dashboard
============================================
Interactive Streamlit application for commissioning registry management.
Uses native Streamlit charts to avoid external dependencies.

KKS Coding based on Rooppur NPP document RPR-QM-AEB0001 Revision B05 (2017)
"Agreement on Using the KKS Coding System" (VGB-B 105 E 2010, VGB-B 106 E 2004)
"""

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from typing import Dict, Any, List

# Import centralized config and database modules
from config import (
    PAGE_TITLE,
    PAGE_ICON,
    get_supabase_client,
    apply_custom_css,
    validate_kks,
    parse_kks,
    get_kks_scope,
    get_label,
    get_display,
    sort_by_label,
    validate_milestone_dependencies,
    validate_record,
    ScopeType,
    MILESTONES,
    MILESTONE_LABELS,
    MILESTONE_DATE_FIELDS,
    VALID_STATUSES,
    STATUS_LABELS,
    SYSTEM_PREFIXES,
    EQUIPMENT_PREFIXES,
    UNIT_CODES,
    FUNCTION_KEY_LEGEND,
    EQUIPMENT_TYPE_LEGEND,
    BUILDING_CODES,
    SYSTEM_CODES,
    REGISTRY_SCHEMA,
    PPIA_LOG_SCHEMA,
    PPIA_STATUSES,
    parse_commissioning_stage,
    commissioning_stage_sort_key,
)
from database import (
    load_registry,
    load_registry_df,
    upsert_registry_row,
    get_registry_row,
    upsert_registry_batch,
    clear_registry,
    clear_processed_chunks,
    load_ppia_log,
    load_ppia_log_df,
    insert_ppia_batch,
    clear_ppia_log,
    load_milestone_history_for,
    clear_milestone_history,
)
from ai_engine import process_file_smart, parse_shift_notes

# =============================================================================
# TIMELINE CHART HELPER
# =============================================================================

def _records_to_clean_df(records: List[Dict[str, Any]], schema: Dict[str, type]) -> pd.DataFrame:
    """
    Converts a list of AI-extracted dicts into a DataFrame safe for
    st.data_editor. AI-extracted records don't always have the same set of
    keys (one record might have "commissioning_stage", another might not) —
    pd.DataFrame() on ragged dicts fills the gaps with NaN (a float) sitting
    in an otherwise string column. That mixed str/float column can crash
    PyArrow's serialization (segfault, not a catchable Python exception) when
    Streamlit tries to send it to the frontend.

    This guarantees every record has every schema field present, as a plain
    string, before a DataFrame is ever built.
    """
    normalized = []
    for rec in records:
        clean = {}
        for field in schema:
            val = rec.get(field, "")
            clean[field] = "" if val is None else str(val)
        normalized.append(clean)
    return pd.DataFrame(normalized, columns=list(schema.keys()))


def _status_to_dot_color(status: str) -> str:
    """
    Maps a status string to the 4-color scheme requested for the date-based
    timeline: Green=Pass, Red=Fail, Yellow=Ongoing, Gray=Postponed/Unknown.
    Accepts both the app's native vocabulary (Completed/Failed/In Progress/
    Pending/N/A) and the Pass/Fail/Ongoing/Postponed vocabulary so either
    naming works.
    """
    s = str(status).strip().lower()
    if s in ("completed", "pass", "passed"):
        return "#22c55e"   # green
    if s in ("failed", "fail"):
        return "#ef4444"   # red
    if s in ("in progress", "ongoing", "started"):
        return "#eab308"   # yellow
    return "#94a3b8"        # gray — pending / postponed / n/a / unknown


def render_date_timeline(points: List[Dict[str, Any]], title: str = "",
                          fig_width: float = 14, fig_height: float = 3.2) -> plt.Figure:
    """
    Horizontal timeline: a single continuous line with circular markers placed
    precisely on the line above each point's own date. The short label sits
    inside the circle, and the date sits directly beneath it — no offset
    stems, everything anchored right at the point itself. Status color-coding:
    green=Pass, red=Fail, yellow=Ongoing, gray=Postponed/unknown.

    Args:
        points: list of {"date": datetime.date, "label": str, "status": str}
                Only points with a real date are plotted; caller should filter
                out/handle missing dates (e.g. via manual entry) beforehand.
        title: chart title
    """
    import matplotlib.dates as mdates

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    valid_points = [p for p in points if p.get("date")]

    if not valid_points:
        ax.text(0.5, 0.5, "No dated milestones to plot yet.\nAdd dates below to see them here.",
                 ha="center", va="center", fontsize=13, color="#64748b")
        ax.axis("off")
        return fig

    valid_points = sorted(valid_points, key=lambda p: p["date"])
    dates = [p["date"] for p in valid_points]

    # The single continuous horizontal line, all points sit directly on it
    ax.plot([dates[0], dates[-1]], [0, 0], color="#cbd5e1", linewidth=2.5, zorder=1,
            solid_capstyle="round")

    for p in valid_points:
        color = _status_to_dot_color(p.get("status", ""))
        d = p["date"]
        label = p.get("label", "")

        ax.scatter([d], [0], s=650, color=color, edgecolor="white", linewidth=2, zorder=3)
        # Label inside the circle
        ax.text(d, 0, label, ha="center", va="center", fontsize=9, fontweight="bold",
                 color="white", zorder=4)
        # Date directly beneath the same point
        ax.text(d, -0.28, d.strftime("%d %b %Y"), ha="center", va="top",
                 fontsize=8, color="#334155", zorder=4)

    ax.set_ylim(-0.6, 0.6)
    ax.set_yticks([])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b %Y"))
    fig.autofmt_xdate(rotation=30, ha="right")

    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#cbd5e1")

    if title:
        ax.set_title(title, fontsize=13, fontweight="bold", pad=16, color="#0f172a")

    legend_patches = [
        mpatches.Patch(color="#22c55e", label="Pass / Completed"),
        mpatches.Patch(color="#ef4444", label="Fail"),
        mpatches.Patch(color="#eab308", label="Ongoing / In Progress"),
        mpatches.Patch(color="#94a3b8", label="Postponed / Pending"),
    ]
    ax.legend(handles=legend_patches, loc="upper center", bbox_to_anchor=(0.5, -0.35),
              ncol=4, fontsize=9, frameon=False)

    plt.tight_layout()
    return fig



# =============================================================================
# PAGE SETUP
# =============================================================================

st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
apply_custom_css()

st.markdown("# Reactor Shop Commissioning Management")
st.markdown("*Rooppur NPP - KKS Coding per the Reactor Shop KKS Code Master List*")
st.markdown("---")

# =============================================================================
# SESSION STATE INITIALIZATION
# =============================================================================

if "registry_edits" not in st.session_state:
    st.session_state.registry_edits = {}
if "show_editor" not in st.session_state:
    st.session_state.show_editor = False
if "selected_rows" not in st.session_state:
    st.session_state.selected_rows = []

# =============================================================================
# SIDEBAR
# =============================================================================

with st.sidebar:
    st.markdown("### KKS Reference")
    st.markdown("**Reactor Shop KKS Code Master List**")
    st.markdown("*Compiled from Rooppur NPP Reactor Shop commissioning documents*")
    st.markdown("---")
    st.markdown("### Sort Options")
    sort_by = st.selectbox(
        "Sort KKS reference tables by:",
        options=["label", "code"],
        format_func=lambda x: "Label (A-Z)" if x == "label" else "Code (A-Z)",
        index=0,
        key="sort_selector"
    )

# =============================================================================
# TABS
# =============================================================================

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
    "Analytics Dashboard",
    "Data Import & Sync",
    "Manual/Field Updates",
    "Shift Note Parser",
    "Registry Editor",
    "Timeline View",
    "KKS Reference",
    "Admin",
    "PPIA Log",
])

# =============================================================================
# TAB 1: ANALYTICS DASHBOARD
# =============================================================================

with tab1:
    df = load_registry_df()

    if df.empty:
        st.info("No data in registry yet. Use the Import or Manual tabs to add records.")
    else:
        # --- Top Metrics Row ---
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            system_count = len(df[df['scope_type'] == 'System']) if 'scope_type' in df.columns else 0
            st.metric("Systems Tracked", system_count)

        with col2:
            equip_count = len(df[df['scope_type'] == 'Equipment']) if 'scope_type' in df.columns else 0
            st.metric("Equipment Tracked", equip_count)

        with col3:
            building_count = len(df[df['scope_type'] == 'Building']) if 'scope_type' in df.columns else 0
            st.metric("Buildings Tracked", building_count)

        with col4:
            def calc_completion(row):
                applicable = []
                for ms in MILESTONES:
                    val = str(row.get(ms, '')).strip()
                    applicable.append(val.lower() == 'completed')
                return all(applicable) if applicable else False

            completed = df.apply(calc_completion, axis=1).sum()
            total = len(df)
            overall_pct = (completed / total * 100) if total > 0 else 0
            st.metric("Fully Completed", f"{completed}/{total}", f"{overall_pct:.1f}%")

        with col5:
            violations = 0
            for _, row in df.iterrows():
                issues = validate_milestone_dependencies(row.to_dict())
                if issues:
                    violations += 1
            st.metric("Dependency Issues", violations, delta_color="inverse")

        st.markdown("---")

        # --- Charts Row ---
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("Milestone Status Distribution")
            if 'it_status' in df.columns:
                status_summary = {ms.replace('_status', '').upper(): {} for ms in MILESTONES}

                for ms in MILESTONES:
                    ms_label = ms.replace('_status', '').upper()
                    for status in ['Completed', 'In Progress', 'Pending', 'Failed', 'N/A']:
                        count = 0
                        for _, row in df.iterrows():
                            if str(row.get(ms, '')).strip() == status:
                                count += 1
                        if count > 0:
                            status_summary[ms_label][status] = count

                chart_data = []
                for ms_label, statuses in status_summary.items():
                    for status, count in statuses.items():
                        chart_data.append({'Milestone': ms_label, 'Status': status, 'Count': count})

                if chart_data:
                    chart_df = pd.DataFrame(chart_data)
                    pivot_df = chart_df.pivot(index='Milestone', columns='Status', values='Count').fillna(0)
                    col_order = ['Completed', 'In Progress', 'Pending', 'Failed', 'N/A']
                    pivot_df = pivot_df[[c for c in col_order if c in pivot_df.columns]]
                    st.bar_chart(pivot_df, width="stretch", height=400)
                else:
                    st.info("No milestone data to display.")

        with col_right:
            st.subheader("Scope Breakdown")
            if 'scope_type' in df.columns:
                scope_counts = df['scope_type'].value_counts().reset_index()
                scope_counts.columns = ['Scope', 'Count']
                st.bar_chart(
                    scope_counts.set_index('Scope'),
                    width="stretch",
                    height=400
                )

        st.markdown("---")

        # --- System Family Breakdown ---
        st.subheader("System Family Distribution")
        if 'system_kks' in df.columns:
            def get_family_from_kks(kks):
                if pd.isna(kks) or not isinstance(kks, str):
                    return "Unknown"
                result = parse_kks(kks)
                if not result.valid:
                    return "Unknown"
                return result.function_key_desc or result.system_desc or "Other/Process"

            df['family'] = df['system_kks'].apply(get_family_from_kks)
            family_counts = df['family'].value_counts().reset_index()
            family_counts.columns = ['System Family', 'Count']
            st.bar_chart(
                family_counts.set_index('System Family'),
                width="stretch",
                height=300
            )

        st.markdown("---")

        # --- Data Table (Read-only with selection for editing) ---
        st.subheader("Registry Overview")

        display_df = df.copy()

        def status_badge(val):
            val = str(val).strip().lower()
            if val == 'completed':
                return 'Completed'
            elif val == 'in progress':
                return 'In Progress'
            elif val == 'failed':
                return 'Failed'
            elif val in ('n/a', 'not applicable'):
                return 'N/A'
            else:
                return 'Pending'

        for ms in MILESTONES:
            if ms in display_df.columns:
                display_df[ms.replace('_status', '').upper()] = display_df[ms].apply(status_badge)

        display_cols = ['system', 'system_kks', 'scope_type', 'component'] + \
                       [ms.replace('_status', '').upper() for ms in MILESTONES if ms in display_df.columns] + \
                       ['comments']
        display_cols = [c for c in display_cols if c in display_df.columns]

        st.dataframe(
            display_df[display_cols],
            width="stretch",
            hide_index=True
        )

        # Quick action: navigate to editor
        st.markdown("---")
        if st.button("Go to Registry Editor to edit records", type="primary", width="stretch"):
            st.session_state.show_editor = True
            st.rerun()

# =============================================================================
# TAB 2: DATA IMPORT & SYNC
# =============================================================================

with tab2:
    st.subheader("Upload & Intelligent Import")
    st.markdown("""
    Upload commissioning registry files (.csv, .xlsx) or raw text.
    The AI engine will extract structured data, validate KKS codes against the Reactor Shop KKS Code Master List,
    and check milestone dependencies before upserting to the database.
    """)

    uploaded = st.file_uploader(
        "Upload Registry (.csv / .xlsx / .txt)", 
        type=["csv", "xlsx", "xls", "txt"]
    )

    if uploaded:
        force_reprocess = st.checkbox(
            "Force reprocess (ignore chunk cache)",
            key="force_reprocess_chk",
            help="Turn this on if you've cleared the registry and are re-uploading a file "
                 "you've imported before. Normally the app skips chunks it has already sent "
                 "to the AI (to save tokens) — but that means re-uploading the same file "
                 "after a registry clear produces 0 records, since the cache still thinks "
                 "every chunk is done. This bypasses that cache for this run."
        )
        col1, col2 = st.columns([1, 3])
        with col1:
            process_btn = st.button("Run Token-Efficient Sync", type="primary", width="stretch")

        if process_btn:
            with st.spinner("Processing file with Rooppur NPP KKS validation..."):
                file_bytes = uploaded.getvalue()
                records_processed, alerts = process_file_smart(file_bytes, uploaded.name, force_reprocess=force_reprocess)

            if records_processed > 0:
                st.success(f"Sync Complete! {records_processed} record(s) processed successfully.")
            else:
                st.warning("No records were processed. Check alerts below.")

            if alerts:
                with st.expander(f"Processing Log ({len(alerts)} entries)", expanded=True):
                    for alert in alerts:
                        if alert.startswith("ERROR") or alert.startswith("KKS ERROR"):
                            st.error(alert)
                        elif alert.startswith("ALERT") or alert.startswith("WARNING") or alert.startswith("KKS WARNING"):
                            st.warning(alert)
                        elif alert.startswith("DEPENDENCY"):
                            st.info(alert)
                        elif alert.startswith("KKS INFO"):
                            st.success(alert)
                        else:
                            st.write(alert)

# =============================================================================
# TAB 3: MANUAL / FIELD UPDATES
# =============================================================================

with tab3:
    st.subheader("Manual Record Entry & Edit")
    st.markdown("""
    Add new records or update existing ones. The form enforces real KKS taxonomy from the
    Reactor Shop KKS Code Master List, and validates milestone dependencies in real-time.

    **KKS Structure** (mandatory 2-digit Unit prefix on every code):
    - **System:** `Unit(2) + System(2-4 letters)` — e.g. `10JAA`
    - **Building:** `Unit(2) + U + 2 letters` — e.g. `10UJA`
    - **Equipment:** `Unit(2) + System(2-4) + Subsystem(2) + Type(2) + Seq(3)` — e.g. `10JAA10BB001`

    See the **KKS Reference** tab for the full list of known Unit, System, Building, and
    Equipment Type codes.
    """)

    # --- Search existing record ---
    st.markdown("#### Load Existing Record (Optional)")
    search_col1, search_col2, search_col3 = st.columns([2, 2, 1])

    with search_col1:
        search_system = st.text_input("System Name", key="search_sys", placeholder="e.g., Feedwater")
    with search_col2:
        search_component = st.text_input("Component Tag", key="search_comp", placeholder="e.g., Pump-001")
    with search_col3:
        st.markdown("<br>", unsafe_allow_html=True)
        load_btn = st.button("Load", width="stretch")

    # Pre-populate form if record found
    prefill = {}
    if load_btn and search_system and search_component:
        existing = get_registry_row(search_system, search_component)
        if existing:
            prefill = existing
            st.success(f"Loaded existing record: {existing.get('system_kks', 'N/A')}")
        else:
            st.info("No existing record found. A new record will be created on submit.")

    st.markdown("---")

    # --- Entry Form ---
    st.markdown("#### Record Details")

    with st.form("manual_update", clear_on_submit=False):
        col_a, col_b = st.columns(2)

        with col_a:
            sys_name = st.text_input(
                "System Name *", 
                value=prefill.get('system', ''),
                help="Name of the system this component belongs to"
            )
            kks_code = st.text_input(
                "KKS Code *", 
                value=prefill.get('system_kks', ''),
                help="Unit (2 digits, mandatory) + System (2-4 letters) [+ Subsystem(2) + Type(2) + Seq(3)]. "
                     "Examples: 10JAA (system), 10UJA (building), 10JAA10BB001 (equipment)"
            )

        with col_b:
            comp_tag = st.text_input(
                "Component Tag *", 
                value=prefill.get('component', ''),
                help="Unique component identifier"
            )
            # Auto-detected scope display
            detected_scope = ""
            scope_details = ""
            if kks_code:
                valid, msg, scope = validate_kks(kks_code)
                if scope:
                    detected_scope = scope.value
                    scope_details = msg

            st.text_input(
                "Detected Scope", 
                value=detected_scope,
                disabled=True,
                help=scope_details if scope_details else "Auto-detected from KKS prefix"
            )
            stage_input = st.text_input(
                "Commissioning Stage",
                value=prefill.get('commissioning_stage', ''),
                placeholder="e.g. A, A-1, B-2",
                help="Letter, optionally with a dash and sub-stage number (A, A-1, B-2, ...)"
            )

        # Show KKS validation details (single source of truth: config.parse_kks)
        if kks_code:
            parsed = parse_kks(kks_code)
            if parsed.valid:
                st.success(parsed.message)
                st.info(f"Unit: {parsed.unit} — {parsed.unit_desc}")
                for alert in parsed.alerts:
                    st.warning(alert)
            else:
                st.error(parsed.message)

        st.markdown("---")
        st.markdown("#### Commissioning Milestones")
        st.markdown("*IT, PIC, HT, PT, and SAW are commissioning tests. All apply to every record.*")

        ms_col1, ms_col2, ms_col3 = st.columns(3)

        with ms_col1:
            it_label = get_label(MILESTONE_LABELS, "it_status")
            it_stat = st.selectbox(
                it_label,
                ["Pending", "In Progress", "Completed", "Failed", "N/A"],
                index=["Pending", "In Progress", "Completed", "Failed", "N/A"].index(
                    prefill.get('it_status', 'Pending')
                ) if prefill.get('it_status') in ["Pending", "In Progress", "Completed", "Failed", "N/A"] else 0,
            )
            pic_label = get_label(MILESTONE_LABELS, "pic_status")
            pic_stat = st.selectbox(
                pic_label,
                ["Pending", "In Progress", "Completed", "Failed", "N/A"],
                index=["Pending", "In Progress", "Completed", "Failed", "N/A"].index(
                    prefill.get('pic_status', 'Pending')
                ) if prefill.get('pic_status') in ["Pending", "In Progress", "Completed", "Failed", "N/A"] else 0,
            )

        with ms_col2:
            ht_label = get_label(MILESTONE_LABELS, "ht_status")
            ht_stat = st.selectbox(
                ht_label,
                ["Pending", "In Progress", "Completed", "Failed", "N/A"],
                index=["Pending", "In Progress", "Completed", "Failed", "N/A"].index(
                    prefill.get('ht_status', 'Pending')
                ) if prefill.get('ht_status') in ["Pending", "In Progress", "Completed", "Failed", "N/A"] else 0,
            )
            pt_label = get_label(MILESTONE_LABELS, "pt_status")
            pt_stat = st.selectbox(
                pt_label,
                ["Pending", "In Progress", "Completed", "Failed", "N/A"],
                index=["Pending", "In Progress", "Completed", "Failed", "N/A"].index(
                    prefill.get('pt_status', 'Pending')
                ) if prefill.get('pt_status') in ["Pending", "In Progress", "Completed", "Failed", "N/A"] else 0,
            )

        with ms_col3:
            saw_label = get_label(MILESTONE_LABELS, "saw_status")
            saw_stat = st.selectbox(
                saw_label,
                ["Pending", "In Progress", "Completed", "Failed", "N/A"],
                index=["Pending", "In Progress", "Completed", "Failed", "N/A"].index(
                    prefill.get('saw_status', 'Pending')
                ) if prefill.get('saw_status') in ["Pending", "In Progress", "Completed", "Failed", "N/A"] else 0,
            )

        comments = st.text_area(
            "Comments / Notes",
            value=prefill.get('comments', ''),
            placeholder="Enter any special notes, anomalies, KKS code context, or shift handover comments..."
        )

        # Dependency warning
        if pic_stat != "Completed" and ht_stat == "Completed":
            warning_html = (
                '<div class="alert-box alert-warning">'
                '<b>Dependency Warning:</b> HT is marked Completed but PIC is not. '
                'PIC must precede HT per commissioning procedure.'
                '</div>'
            )
            st.markdown(warning_html, unsafe_allow_html=True)

        st.markdown("---")
        submitted = st.form_submit_button("Submit Record", width="stretch", type="primary")

        if submitted:
            if not sys_name or not kks_code or not comp_tag:
                st.error("Required fields missing: System Name, KKS Code, and Component Tag are mandatory.")
            else:
                # Validate KKS before submission
                valid, msg, scope = validate_kks(kks_code)
                if not valid:
                    st.error(f"KKS Validation Failed: {msg}")
                else:
                    normalized_stage = parse_commissioning_stage(stage_input) if stage_input else ""
                    if stage_input and not normalized_stage:
                        st.warning(
                            f"Commissioning stage '{stage_input}' doesn't match the expected format "
                            f"(a letter, optionally with a dash and number, e.g. 'A', 'A-1') — saved as-is."
                        )
                    record = {
                        "system": sys_name,
                        "system_kks": kks_code,
                        "component": comp_tag,
                        "commissioning_stage": normalized_stage or stage_input,
                        "it_status": it_stat,
                        "pic_status": pic_stat,
                        "ht_status": ht_stat,
                        "pt_status": pt_stat,
                        "saw_status": saw_stat,
                        "comments": comments
                    }

                    ok, msgs = upsert_registry_row(record)
                    if ok:
                        st.success("Registry Updated Successfully!")
                    for msg in msgs:
                        if msg.startswith("ALERT") or msg.startswith("WARNING") or msg.startswith("KKS WARNING"):
                            st.warning(msg)
                        elif msg.startswith("DEPENDENCY"):
                            st.info(msg)
                        elif msg.startswith("KKS INFO"):
                            st.success(msg)
                        elif msg.startswith("KKS ERROR"):
                            st.error(msg)

# =============================================================================
# TAB 4: SHIFT NOTE PARSER
# =============================================================================

with tab4:
    st.subheader("Natural Language Shift Note Parser")
    st.markdown("""
    Paste raw shift notes, field observations, or handover logs.
    The AI extracts structured commissioning data (validated against Rooppur NPP KKS rules,
    with milestone dependency checks) and separately flags any **PPIA** (Process Protection
    and Interlock Actuation) events mentioned. **Review and edit both tables below before
    committing** — nothing is saved until you click a Commit button.
    """)

    notes_text = st.text_area(
        "Shift Notes",
        height=250,
        placeholder="Example: 10JAA10AP001 feedwater pump IT completed, Stage A-1. PIC in progress due to debris found in strainer. 10JEB20 condensate system HT passed, awaiting SAW scheduling. Interlock on 10JAA20 actuated at 14:20 due to low flow — under investigation."
    )

    if st.button("Parse & Validate", type="primary", width="stretch") and notes_text.strip():
        with st.spinner("AI analyzing shift notes with Rooppur NPP KKS rules..."):
            records, ppia_events, alerts = parse_shift_notes(notes_text)
        st.session_state["sn_parsed_records"] = records
        st.session_state["sn_parsed_ppia"] = ppia_events
        st.session_state["sn_alerts"] = alerts

    parsed_records = st.session_state.get("sn_parsed_records", [])
    parsed_ppia = st.session_state.get("sn_parsed_ppia", [])
    parsed_alerts = st.session_state.get("sn_alerts", [])

    if not parsed_records and not parsed_ppia and "sn_alerts" in st.session_state:
        st.error("Could not extract any valid records or PPIA events from the provided notes.")
        for alert in parsed_alerts:
            st.error(alert)

    edited_records_df = None
    edited_ppia_df = None

    if parsed_records:
        st.success(f"Extracted {len(parsed_records)} commissioning record(s). Edit any cell below before committing.")
        st.subheader("Commissioning Records — Editable Preview")
        edited_records_df = st.data_editor(
            _records_to_clean_df(parsed_records, REGISTRY_SCHEMA),
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            key="sn_records_editor",
        )

    if parsed_ppia:
        st.success(f"Extracted {len(parsed_ppia)} PPIA event(s). Edit any cell below before committing.")
        st.subheader("PPIA Events — Editable Preview")
        edited_ppia_df = st.data_editor(
            _records_to_clean_df(parsed_ppia, PPIA_LOG_SCHEMA),
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            key="sn_ppia_editor",
            column_config={
                "status": st.column_config.SelectboxColumn(options=sorted(PPIA_STATUSES)),
            },
        )

    if parsed_alerts and (parsed_records or parsed_ppia):
        with st.expander(f"Validation Alerts ({len(parsed_alerts)})", expanded=False):
            for alert in parsed_alerts:
                if "DEPENDENCY" in alert or "VALIDATION" in alert:
                    st.markdown(f'<div class="alert-box alert-error">{alert}</div>', unsafe_allow_html=True)
                elif "INFO" in alert:
                    st.success(alert)
                elif "WARNING" in alert or "ERROR" in alert:
                    st.error(alert)
                else:
                    st.write(alert)

    if edited_records_df is not None or edited_ppia_df is not None:
        st.markdown("---")
        col_a, col_b = st.columns(2)
        with col_a:
            if edited_records_df is not None and st.button(
                "Commit Records to Registry", type="primary", width="stretch"
            ):
                edited_records = edited_records_df.to_dict("records")
                success, all_msgs = upsert_registry_batch(edited_records)
                st.success(f"Committed {success}/{len(edited_records)} record(s) to registry.")
                if success < len(edited_records):
                    st.warning("Some records failed validation. Check the alerts above.")
                del st.session_state["sn_parsed_records"]
                st.rerun()
        with col_b:
            if edited_ppia_df is not None and st.button(
                "Commit PPIA Events to Log", type="primary", width="stretch"
            ):
                edited_events = edited_ppia_df.to_dict("records")
                success, all_msgs = insert_ppia_batch(edited_events)
                st.success(f"Logged {success}/{len(edited_events)} PPIA event(s).")
                if success < len(edited_events):
                    st.warning("Some events failed validation. Check the alerts above.")
                del st.session_state["sn_parsed_ppia"]
                st.rerun()

# =============================================================================
# TAB 5: REGISTRY EDITOR (Editable Data Grid)
# =============================================================================

with tab5:
    st.subheader("Registry Editor")
    st.markdown("""
    Edit existing records directly in the data grid. Changes are validated before saving.
    Select rows to edit, or use the data editor to modify values inline.
    """)

    df = load_registry_df()

    if df.empty:
        st.info("No data in registry yet. Use the Import or Manual tabs to add records.")
    else:
        # --- Filter controls ---
        st.markdown("#### Filter Records")
        filter_col1, filter_col2, filter_col3 = st.columns(3)

        with filter_col1:
            scope_filter = st.multiselect(
                "Scope Type",
                options=df['scope_type'].unique() if 'scope_type' in df.columns else [],
                default=[],
                key="editor_scope_filter"
            )
        with filter_col2:
            def _family_for(kks):
                if not isinstance(kks, str):
                    return None
                result = parse_kks(kks)
                return (result.function_key_desc or result.system_desc) if result.valid else None

            if 'system_kks' in df.columns:
                family_options = sorted(set(
                    f for f in (_family_for(kks) for kks in df['system_kks']) if f
                ))
            else:
                family_options = []
            family_filter = st.multiselect(
                "System Family",
                options=family_options,
                default=[],
                key="editor_family_filter"
            )
        with filter_col3:
            status_filter = st.multiselect(
                "Status",
                options=list(VALID_STATUSES),
                default=[],
                key="editor_status_filter"
            )

        # Apply filters
        filtered_df = df.copy()
        if scope_filter and 'scope_type' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['scope_type'].isin(scope_filter)]
        if family_filter and 'system_kks' in filtered_df.columns:
            def family_matches(kks):
                return _family_for(kks) in family_filter
            filtered_df = filtered_df[filtered_df['system_kks'].apply(family_matches)]
        if status_filter:
            mask = False
            for ms in MILESTONES:
                if ms in filtered_df.columns:
                    mask = mask | filtered_df[ms].isin(status_filter)
            if mask is not False:
                filtered_df = filtered_df[mask]

        st.markdown(f"**Showing {len(filtered_df)} of {len(df)} records**")

        # --- Editable Data Grid ---
        st.markdown("---")
        st.markdown("#### Edit Records Inline")

        # Prepare editable columns configuration
        column_config = {}
        editable_cols = ['system', 'system_kks', 'component', 'commissioning_stage', 'it_status', 'pic_status', 'ht_status', 'pt_status', 'saw_status', 'comments']

        for col in editable_cols:
            if col in filtered_df.columns:
                if col.endswith('_status'):
                    column_config[col] = st.column_config.SelectboxColumn(
                        get_label(MILESTONE_LABELS, col) if col in MILESTONE_LABELS else col,
                        options=list(VALID_STATUSES),
                        help=f"Select status for {col}"
                    )
                elif col == 'system_kks':
                    column_config[col] = st.column_config.TextColumn(
                        "KKS Code",
                        help="F0 (mandatory) + F1F2F3 + Fn + A1 + An + Bn"
                    )
                elif col == 'scope_type':
                    column_config[col] = st.column_config.TextColumn(
                        "Scope",
                        disabled=True,
                        help="Auto-detected from KKS code"
                    )
                elif col == 'commissioning_stage':
                    column_config[col] = st.column_config.TextColumn(
                        "Stage",
                        help="Commissioning stage, e.g. A, A-1, B-2"
                    )
                elif col == 'comments':
                    column_config[col] = st.column_config.TextColumn(
                        "Comments",
                        width="large"
                    )
                else:
                    column_config[col] = st.column_config.TextColumn(col)

        # Hide non-editable columns
        display_cols = [c for c in editable_cols if c in filtered_df.columns]
        if 'scope_type' in filtered_df.columns and 'scope_type' not in display_cols:
            display_cols.insert(2, 'scope_type')
            column_config['scope_type'] = st.column_config.TextColumn(
                "Scope",
                disabled=True
            )

        # Use data_editor for inline editing
        editor_key = "registry_data_editor"
        edited_df = st.data_editor(
            filtered_df[display_cols],
            column_config=column_config,
            disabled=[c for c in display_cols if c not in editable_cols or c == 'scope_type'],
            hide_index=True,
            width="stretch",
            key=editor_key,
            num_rows="fixed",
        )

        # --- Detect and show changes ---
        st.markdown("---")

        if editor_key in st.session_state:
            editor_state = st.session_state[editor_key]

            changes_detected = False

            if "edited_rows" in editor_state and editor_state["edited_rows"]:
                changes_detected = True
                edited_count = len(editor_state["edited_rows"])
                st.markdown(f"#### Changes Detected ({edited_count} rows edited)")

                with st.expander("View Changes", expanded=True):
                    for idx, changes in editor_state["edited_rows"].items():
                        original_row = filtered_df.iloc[int(idx)]
                        st.markdown(f"**Row {idx}:** `{original_row.get('system_kks', 'N/A')}` / `{original_row.get('component', 'N/A')}`")
                        for col, new_val in changes.items():
                            old_val = original_row.get(col, 'N/A')
                            st.markdown(f"  - `{col}`: `{old_val}` -> `{new_val}`")

            if "deleted_rows" in editor_state and editor_state["deleted_rows"]:
                changes_detected = True
                deleted_count = len(editor_state["deleted_rows"])
                st.warning(f"{deleted_count} row(s) marked for deletion. Use database admin to delete.")

            if changes_detected:
                st.markdown("---")
                if st.button("Save Changes to Database", type="primary", width="stretch"):
                    saved_count = 0
                    error_count = 0

                    with st.spinner("Saving changes..."):
                        for idx, changes in editor_state["edited_rows"].items():
                            original_row = filtered_df.iloc[int(idx)].to_dict()
                            updated_row = original_row.copy()
                            updated_row.update(changes)

                            valid, issues = validate_record(updated_row)
                            if valid:
                                ok, msgs = upsert_registry_row(updated_row)
                                if ok:
                                    saved_count += 1
                                else:
                                    error_count += 1
                                    for msg in msgs:
                                        st.error(msg)
                            else:
                                error_count += 1
                                for issue in issues:
                                    st.error(f"Validation error for row {idx}: {issue}")

                    if saved_count > 0:
                        st.success(f"Saved {saved_count} record(s) successfully!")
                    if error_count > 0:
                        st.error(f"{error_count} record(s) failed to save. Check errors above.")

                    if saved_count > 0 and error_count == 0:
                        st.session_state[editor_key] = {}
                        st.rerun()
            else:
                st.info("No changes detected. Edit cells in the table above to make changes.")
        else:
            st.info("Edit cells in the table above to make changes. Changes will be validated before saving.")

        # --- Row selection for detailed edit ---
        st.markdown("---")
        st.markdown("#### Select Row for Detailed Edit")

        selection = st.dataframe(
            filtered_df[display_cols],
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="registry_selector"
        )

        if selection and selection.selection and selection.selection.rows:
            selected_idx = selection.selection.rows[0]
            selected_row = filtered_df.iloc[selected_idx]

            st.markdown("---")
            st.markdown(f"#### Editing: `{selected_row.get('system_kks', 'N/A')}` / `{selected_row.get('component', 'N/A')}`")

            with st.form("inline_edit_form"):
                edit_col1, edit_col2 = st.columns(2)

                with edit_col1:
                    edit_system = st.text_input(
                        "System Name",
                        value=selected_row.get('system', '')
                    )
                    edit_kks = st.text_input(
                        "KKS Code",
                        value=selected_row.get('system_kks', '')
                    )

                with edit_col2:
                    edit_component = st.text_input(
                        "Component Tag",
                        value=selected_row.get('component', '')
                    )
                    edit_scope = st.text_input(
                        "Scope (auto)",
                        value=selected_row.get('scope_type', ''),
                        disabled=True
                    )

                # Milestone editors
                st.markdown("#### Milestones")
                ms_edit_col1, ms_edit_col2, ms_edit_col3 = st.columns(3)

                with ms_edit_col1:
                    edit_it = st.selectbox(
                        get_label(MILESTONE_LABELS, "it_status"),
                        list(VALID_STATUSES),
                        index=list(VALID_STATUSES).index(selected_row.get('it_status', 'Pending')) if selected_row.get('it_status') in VALID_STATUSES else 0,
                    )
                    edit_pic = st.selectbox(
                        get_label(MILESTONE_LABELS, "pic_status"),
                        list(VALID_STATUSES),
                        index=list(VALID_STATUSES).index(selected_row.get('pic_status', 'Pending')) if selected_row.get('pic_status') in VALID_STATUSES else 0,
                    )

                with ms_edit_col2:
                    edit_ht = st.selectbox(
                        get_label(MILESTONE_LABELS, "ht_status"),
                        list(VALID_STATUSES),
                        index=list(VALID_STATUSES).index(selected_row.get('ht_status', 'Pending')) if selected_row.get('ht_status') in VALID_STATUSES else 0,
                    )
                    edit_pt = st.selectbox(
                        get_label(MILESTONE_LABELS, "pt_status"),
                        list(VALID_STATUSES),
                        index=list(VALID_STATUSES).index(selected_row.get('pt_status', 'Pending')) if selected_row.get('pt_status') in VALID_STATUSES else 0,
                    )

                with ms_edit_col3:
                    edit_saw = st.selectbox(
                        get_label(MILESTONE_LABELS, "saw_status"),
                        list(VALID_STATUSES),
                        index=list(VALID_STATUSES).index(selected_row.get('saw_status', 'Pending')) if selected_row.get('saw_status') in VALID_STATUSES else 0,
                    )

                edit_comments = st.text_area(
                    "Comments",
                    value=selected_row.get('comments', '')
                )

                # Dependency check
                if edit_pic != "Completed" and edit_ht == "Completed":
                    st.warning("Dependency Warning: PIC must precede HT")

                if st.form_submit_button("Update Record", type="primary", width="stretch"):
                    updated_record = {
                        "system": edit_system,
                        "system_kks": edit_kks,
                        "component": edit_component,
                        "it_status": edit_it,
                        "pic_status": edit_pic,
                        "ht_status": edit_ht,
                        "pt_status": edit_pt,
                        "saw_status": edit_saw,
                        "comments": edit_comments
                    }

                    ok, msgs = upsert_registry_row(updated_record)
                    if ok:
                        st.success("Record updated successfully!")
                        st.rerun()
                    else:
                        for msg in msgs:
                            st.error(msg)

# =============================================================================
# TAB 6: TIMELINE VIEW
# =============================================================================

with tab6:
    st.subheader("Commissioning Timeline")
    st.markdown("""
    Select a KKS record to see its full commissioning timeline — each milestone
    (IT, PIC, HT, PT, SAW) plotted on a single line, positioned by date and
    color-coded by status.
    """)

    df = load_registry_df()

    if df.empty:
        st.info("No data in registry yet. Use the Import or Manual tabs to add records.")
    else:
        df['display_label'] = df.apply(
            lambda r: f"{r.get('system_kks', 'N/A')} | {r.get('system', 'Unknown')} / {r.get('component', 'Unknown')}",
            axis=1
        )

        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            scope_filter_timeline = st.multiselect(
                "Filter by Scope Type",
                options=df['scope_type'].unique() if 'scope_type' in df.columns else [],
                default=[],
                key="timeline_scope_filter",
            )
        with filter_col2:
            stage_options = sorted(
                {parse_commissioning_stage(s) for s in df.get('commissioning_stage', pd.Series(dtype=str)).unique()
                 if parse_commissioning_stage(s)},
                key=commissioning_stage_sort_key
            )
            stage_filter_timeline = st.multiselect(
                "Filter by Commissioning Stage",
                options=stage_options,
                default=[],
                key="timeline_stage_filter",
            )

        filtered_for_timeline = df.copy()
        if scope_filter_timeline and 'scope_type' in filtered_for_timeline.columns:
            filtered_for_timeline = filtered_for_timeline[filtered_for_timeline['scope_type'].isin(scope_filter_timeline)]
        if stage_filter_timeline and 'commissioning_stage' in filtered_for_timeline.columns:
            filtered_for_timeline = filtered_for_timeline[
                filtered_for_timeline['commissioning_stage'].apply(parse_commissioning_stage).isin(stage_filter_timeline)
            ]

        single_options = filtered_for_timeline['display_label'].tolist()

        def _parse_date_str(s):
            if not s:
                return None
            try:
                return pd.to_datetime(s).date()
            except Exception:
                return None

        dt_selected = st.selectbox(
            "Select a KKS record:",
            options=["-- Select --"] + single_options,
            index=0,
            key="date_timeline_single_select"
        )

        if dt_selected != "-- Select --":
            dt_kks = dt_selected.split(" | ")[0]
            dt_record = filtered_for_timeline[filtered_for_timeline['system_kks'] == dt_kks].iloc[0].to_dict()

            stage_display = parse_commissioning_stage(dt_record.get('commissioning_stage', '')) or "Not set"

            # --- Header strip: quick facts about this record ---
            hcol1, hcol2, hcol3, hcol4 = st.columns(4)
            hcol1.metric("KKS Code", dt_kks)
            hcol2.metric("Scope", dt_record.get('scope_type', 'Unknown'))
            hcol3.metric("Commissioning Stage", stage_display)
            statuses_now = [dt_record.get(ms, "Pending") for ms in MILESTONES]
            completed_count = sum(1 for s in statuses_now if s == "Completed")
            hcol4.metric("Milestones Complete", f"{completed_count}/{len(MILESTONES)}")

            with st.expander("Fill in missing milestone dates (optional)", expanded=False):
                edited_dates = {}
                cols = st.columns(len(MILESTONES))
                for idx, ms in enumerate(MILESTONES):
                    date_field = MILESTONE_DATE_FIELDS[ms]
                    existing = _parse_date_str(dt_record.get(date_field))
                    short_label = MILESTONE_LABELS.get(ms, ms).split(" (")[0]
                    with cols[idx]:
                        if existing:
                            st.caption(f"{short_label}: {existing.strftime('%d %b %Y')}")
                            edited_dates[ms] = existing
                        else:
                            edited_dates[ms] = st.date_input(short_label, value=None, key=f"dt_{dt_kks}_{ms}")

                if st.button("Save entered dates to registry", key="save_dates_single"):
                    updated_record = dict(dt_record)
                    any_saved = False
                    for ms in MILESTONES:
                        date_field = MILESTONE_DATE_FIELDS[ms]
                        val = edited_dates.get(ms)
                        if val:
                            updated_record[date_field] = val.strftime("%Y-%m-%d")
                            any_saved = True
                    if any_saved:
                        ok, msgs = upsert_registry_row(updated_record)
                        if ok:
                            st.success("Dates saved.")
                            st.rerun()
                        else:
                            for m in msgs:
                                st.error(m)
                    else:
                        st.info("No new dates entered.")

            history_events = load_milestone_history_for(dt_kks, dt_record.get('component', ''))

            points = []
            if history_events:
                for ev in history_events:
                    d = _parse_date_str(ev.get("event_date"))
                    if d:
                        points.append({
                            "date": d,
                            "label": MILESTONE_LABELS.get(ev.get("milestone", ""), ev.get("milestone", "")).split(" (")[0],
                            "status": ev.get("status", "Pending"),
                        })
                st.caption(
                    f"Showing all {len(history_events)} recorded test attempt(s) for this record — "
                    f"every retest is preserved, not just the latest."
                )
            else:
                # No history logged yet for this record (e.g. it predates this
                # feature, or was bulk-imported before any change occurred) —
                # fall back to showing the current single snapshot per milestone.
                for ms in MILESTONES:
                    date_field = MILESTONE_DATE_FIELDS[ms]
                    d = edited_dates.get(ms) or _parse_date_str(dt_record.get(date_field))
                    points.append({
                        "date": d,
                        "label": MILESTONE_LABELS.get(ms, ms).split(" (")[0],
                        "status": dt_record.get(ms, "Pending"),
                    })
                st.caption("No retest history logged yet for this record — showing the current status of each milestone.")

            stage_suffix = f"  |  Stage {stage_display}" if stage_display != "Not set" else ""
            fig_dt = render_date_timeline(
                points,
                title=f"{dt_kks}  |  {dt_record.get('system', 'Unknown')} / {dt_record.get('component', 'Unknown')}{stage_suffix}",
            )
            st.pyplot(fig_dt)
            plt.close(fig_dt)

            if history_events:
                with st.expander("Full test history (table)", expanded=False):
                    hist_df = pd.DataFrame(history_events)
                    display_cols = [c for c in ["event_date", "milestone", "status", "comments", "source"] if c in hist_df.columns]
                    hist_df = hist_df[display_cols].sort_values("event_date")
                    hist_df["milestone"] = hist_df["milestone"].apply(lambda m: MILESTONE_LABELS.get(m, m).split(" (")[0])
                    st.dataframe(hist_df, width="stretch", hide_index=True)

            dep_issues = validate_milestone_dependencies(dt_record)
            if dep_issues:
                st.error("Dependency Violations Detected:")
                for issue in dep_issues:
                    st.markdown(f"- {issue}")
            else:
                st.success("All milestone dependencies satisfied.")

            if dt_record.get("comments"):
                st.caption(f"Comments: {dt_record.get('comments')}")

# =============================================================================
# TAB 7: KKS REFERENCE
# =============================================================================

with tab7:
    st.subheader("Rooppur NPP KKS Coding Reference")
    st.markdown("*Hard-coded from the Reactor Shop KKS Code Master List (compiled from project commissioning documents)*")
    st.markdown(
        "KKS code shapes — **Equipment**: `Unit(2) + System(2-4) + Subsystem(2) + Type(2) + Seq(3)` "
        "(e.g. `10JAA10BB001`) · **Building**: `Unit(2) + U + 2 letters` (e.g. `10UJA`) · "
        "**System**: `Unit(2) + System(2-4)` (e.g. `10JAA`)"
    )

    st.markdown("---")

    # Unit Codes
    st.markdown("#### Unit Codes (mandatory 2-digit prefix)")
    sorted_units = sort_by_label(UNIT_CODES) if sort_by == "label" else sorted(UNIT_CODES.items())
    unit_df = pd.DataFrame([{"Unit": k, "Description": v} for k, v in sorted_units])
    st.dataframe(unit_df, width="stretch", hide_index=True)
    st.caption("Other 2-digit codes (e.g. 05, 11-15, 17) denote auxiliary/shared facility zones.")

    st.markdown("---")

    # Function Key Legend
    st.markdown("#### Function Key Legend (1st letter of System code)")
    sorted_fkeys = sort_by_label(FUNCTION_KEY_LEGEND) if sort_by == "label" else sorted(FUNCTION_KEY_LEGEND.items())
    fkey_df = pd.DataFrame([{"Function Key": k, "Description": v} for k, v in sorted_fkeys])
    st.dataframe(fkey_df, width="stretch", hide_index=True)

    st.markdown("---")

    # Equipment Type Legend
    st.markdown("#### Equipment Type Legend (2-letter type code)")
    sorted_types = sort_by_label(EQUIPMENT_TYPE_LEGEND) if sort_by == "label" else sorted(EQUIPMENT_TYPE_LEGEND.items())
    type_df = pd.DataFrame([{"Type Code": k, "Description": v} for k, v in sorted_types])
    st.dataframe(type_df, width="stretch", hide_index=True)

    st.markdown("---")

    # System Codes (searchable — 439 known codes)
    st.markdown(f"#### Known System Codes ({len(SYSTEM_CODES)})")
    sys_search = st.text_input("Filter system codes", key="sys_code_search", placeholder="e.g. JAA, cooling, pump")
    sorted_systems = sort_by_label({k: v[0] for k, v in SYSTEM_CODES.items()}) if sort_by == "label" else sorted(SYSTEM_CODES.items())
    sys_rows = [{"System Code": k, "Description": (v[0] if isinstance(v, tuple) else v), "Function Key": (v[1] if isinstance(v, tuple) else SYSTEM_CODES.get(k, ("", ""))[1])} for k, v in (sorted_systems if sort_by == "label" else SYSTEM_CODES.items())]
    sys_df = pd.DataFrame(sys_rows)
    if sys_search:
        mask = sys_df["System Code"].str.contains(sys_search, case=False, na=False) | sys_df["Description"].str.contains(sys_search, case=False, na=False)
        sys_df = sys_df[mask]
    st.dataframe(sys_df, width="stretch", hide_index=True, height=300)

    st.markdown("---")

    # Building Codes (searchable — 257 known codes)
    st.markdown(f"#### Known Building Codes ({len(BUILDING_CODES)})")
    bld_search = st.text_input("Filter building codes", key="bld_code_search", placeholder="e.g. 10UJA, ventilation")
    sorted_buildings = sort_by_label(BUILDING_CODES) if sort_by == "label" else sorted(BUILDING_CODES.items())
    bld_df = pd.DataFrame([{"Building Code": k, "Description": v} for k, v in sorted_buildings])
    if bld_search:
        mask = bld_df["Building Code"].str.contains(bld_search, case=False, na=False) | bld_df["Description"].str.contains(bld_search, case=False, na=False)
        bld_df = bld_df[mask]
    st.dataframe(bld_df, width="stretch", hide_index=True, height=300)

    st.markdown("---")

    # Milestone Labels
    st.markdown("#### Commissioning Milestones")
    sorted_ms = sort_by_label(MILESTONE_LABELS) if sort_by == "label" else sorted(MILESTONE_LABELS.items())

    ms_data = []
    for k, v in sorted_ms:
        ms_data.append({
            "Code": k.replace('_status', '').upper(),
            "Description": v,
        })
    ms_df = pd.DataFrame(ms_data)
    st.dataframe(ms_df, width="stretch", hide_index=True)

    st.markdown("---")

    # Status Labels
    st.markdown("#### Status Values")
    status_data = []
    for k, v in STATUS_LABELS.items():
        status_data.append({
            "Code": k,
            "Description": v,
        })
    status_df = pd.DataFrame(status_data)
    st.dataframe(status_df, width="stretch", hide_index=True)

    st.markdown("---")

    # KKS Structure
    st.markdown("#### KKS Code Structure")
    st.markdown("""
    ```
    Unit(2 digits, MANDATORY) + one of:

    SYSTEM     Unit + System(2-4 letters)
               e.g. 10JAA

    BUILDING   Unit + "U" + 2 letters
               e.g. 10UJA

    EQUIPMENT  Unit + System(2-4) + Subsystem(2 digits)
                    + Type(2 letters) + Sequence(3 digits)
               e.g. 10JAA10BB001
                    │  │   │  │  └─ Sequence 001
                    │  │   │  └──── Type BB (vessel/tank)
                    │  │   └─────── Subsystem 10
                    │  └─────────── System JAA
                    └────────────── Unit 10 (Unit 1)
    ```

    Unit, System, Building, and Equipment Type codes are validated against the
    hard-coded Reactor Shop KKS Code Master List (see the tables above). A code that
    matches the structural shape but isn't yet in the master list is still accepted —
    it's flagged as a warning for manual verification rather than rejected outright,
    since legitimately new equipment appears in the field before any master list is updated.
    """)

    st.markdown("---")
    st.markdown(
        "**Note:** Sequence numbers of `000` are flagged as invalid (numbering starts at 001); "
        "unrecognized system or equipment-type codes are flagged as warnings, not hard errors."
    )

# =============================================================================
# TAB 8: ADMIN - REGISTRY CLEAN
# =============================================================================

with tab8:
    st.subheader("Admin - Registry Management")
    st.markdown("---")

    st.markdown("#### Clear Registry")
    st.warning("""
    **WARNING: This action is IRREVERSIBLE.**

    Clearing the registry will permanently delete ALL records from the database.
    This is intended for starting fresh with a clean slate.
    """)

    st.markdown("---")

    # Confirmation steps
    confirm_step1 = st.checkbox("I understand this will delete ALL records from the registry", key="confirm1")
    confirm_step2 = st.checkbox("I have verified that any needed data has been exported/backed up", key="confirm2")

    if confirm_step1 and confirm_step2:
        st.error("Type 'DELETE ALL' below to confirm permanent deletion:")
        confirm_text = st.text_input("Confirmation", key="confirm_text", placeholder="Type DELETE ALL")

        if confirm_text == "DELETE ALL":
            if st.button("PERMANENTLY CLEAR REGISTRY", type="primary", width="stretch"):
                with st.spinner("Clearing registry..."):
                    success, message = clear_registry()

                if success:
                    st.success(message)
                    st.balloons()
                    st.info("Registry is now empty. You can start adding new records via the Import or Manual tabs.")
                else:
                    st.error(message)
        else:
            st.info("Type 'DELETE ALL' exactly to enable the clear button.")
    else:
        st.info("Check both confirmation boxes above to proceed.")

    st.markdown("---")
    st.markdown("#### Clear Import Chunk Cache")
    st.info("""
    **Why you need this:** to save AI tokens, the importer remembers (by file hash)
    which chunks of a file it has already sent to the AI, and skips them on the next
    upload. Clearing the **registry** does NOT clear this cache — so re-uploading the
    same file afterward will show "0 records processed" because every chunk still looks
    already-done. Clear the cache here to make a file re-importable from scratch, or
    just use the "Force reprocess" checkbox on the Import tab for a one-off re-run.
    """)

    if st.button("Clear Chunk Cache (all files)", width="stretch"):
        with st.spinner("Clearing chunk cache..."):
            success, message = clear_processed_chunks()
        if success:
            st.success(message)
        else:
            st.error(message)

    st.markdown("---")
    st.markdown("#### Clear Milestone Test History")
    st.warning("""
    This permanently deletes every logged test attempt (every retest, every past
    pass/fail) across all records — not just the current status shown in the registry.
    This cannot be undone. Only use this if you're intentionally resetting the
    commissioning history, not for routine cleanup.
    """)
    if st.button("Clear Entire Milestone Test History", type="secondary"):
        with st.spinner("Clearing milestone test history..."):
            success, message = clear_milestone_history()
        if success:
            st.success(message)
        else:
            st.error(message)

# =============================================================================
# TAB 9: PPIA LOG (Process Protection and Interlock Actuation)
# =============================================================================

with tab9:
    st.subheader("PPIA Log — Process Protection and Interlock Actuation")
    st.markdown("""
    A running log of protection/interlock actuation events — reactor trips, interlock
    actuations, protection system alarms — captured automatically from the **Shift Note
    Parser** and **Data Import & Sync** tabs, or entered manually below. This is a
    separate, append-only log from the main commissioning registry.
    """)

    ppia_df = load_ppia_log_df()

    if ppia_df.empty:
        st.info("No PPIA events logged yet. They'll appear here automatically once the "
                 "Shift Note Parser or file import detects one, or add one manually below.")
    else:
        # --- Summary metrics ---
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Events", len(ppia_df))
        m2.metric("Confirmed", int((ppia_df['status'] == 'Confirmed').sum()) if 'status' in ppia_df.columns else 0)
        m3.metric("Under Investigation", int((ppia_df['status'] == 'Under Investigation').sum()) if 'status' in ppia_df.columns else 0)
        m4.metric("False Alarms", int((ppia_df['status'] == 'False Alarm').sum()) if 'status' in ppia_df.columns else 0)

        st.markdown("---")
        st.markdown("#### Filter")
        f1, f2 = st.columns(2)
        with f1:
            ppia_status_filter = st.multiselect(
                "Status",
                options=sorted(PPIA_STATUSES),
                default=[],
                key="ppia_status_filter",
            )
        with f2:
            ppia_search = st.text_input(
                "Search (system, KKS, or description)",
                key="ppia_search",
            )

        filtered_ppia = ppia_df.copy()
        if ppia_status_filter and 'status' in filtered_ppia.columns:
            filtered_ppia = filtered_ppia[filtered_ppia['status'].isin(ppia_status_filter)]
        if ppia_search:
            search_lower = ppia_search.lower()
            search_cols = [c for c in ['system', 'system_kks', 'interlock_description', 'trigger_cause'] if c in filtered_ppia.columns]
            if search_cols:
                mask = False
                for c in search_cols:
                    mask = mask | filtered_ppia[c].astype(str).str.lower().str.contains(search_lower, na=False)
                filtered_ppia = filtered_ppia[mask]

        st.markdown(f"**Showing {len(filtered_ppia)} of {len(ppia_df)} events**")
        st.dataframe(filtered_ppia, width="stretch", hide_index=True)

    st.markdown("---")
    st.markdown("#### Log a PPIA Event Manually")

    with st.form("manual_ppia_entry", clear_on_submit=True):
        pc1, pc2 = st.columns(2)
        with pc1:
            ppia_system = st.text_input("System Name", placeholder="e.g., Reactor Protection System")
            ppia_kks = st.text_input("KKS Code (optional)", placeholder="e.g., 10JAA20")
            ppia_date = st.date_input("Event Date", value=None)
            ppia_time = st.text_input("Event Time (optional, HH:MM)", placeholder="14:20")
        with pc2:
            ppia_status_input = st.selectbox("Status", options=sorted(PPIA_STATUSES))
            ppia_description = st.text_area(
                "What actuated/tripped? *",
                placeholder="e.g., Reactor trip on low pressurizer level"
            )
            ppia_cause = st.text_area("Trigger Cause (if known)", placeholder="e.g., Sensor drift during calibration")

        ppia_comments = st.text_area("Additional Comments")

        ppia_submitted = st.form_submit_button("Log PPIA Event", type="primary", width="stretch")

        if ppia_submitted:
            if not ppia_description.strip():
                st.error("The 'What actuated/tripped?' field is required.")
            else:
                entry = {
                    "system": ppia_system,
                    "system_kks": ppia_kks,
                    "event_date": ppia_date.strftime("%Y-%m-%d") if ppia_date else "",
                    "event_time": ppia_time,
                    "interlock_description": ppia_description,
                    "trigger_cause": ppia_cause,
                    "status": ppia_status_input,
                    "comments": ppia_comments,
                    "source": "Manual Entry",
                }
                ok, msgs = insert_ppia_batch([entry])
                if ok:
                    st.success("PPIA event logged.")
                    st.rerun()
                else:
                    for m in msgs:
                        st.error(m)

    st.markdown("---")
    with st.expander("Admin: Clear PPIA Log"):
        st.warning("This permanently deletes every PPIA event. This cannot be undone.")
        if st.button("Clear Entire PPIA Log", type="secondary"):
            ok, msg = clear_ppia_log()
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
