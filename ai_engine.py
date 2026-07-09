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
    validate_f0,
    validate_room_code,
    validate_a3,
    get_kks_scope,
    get_system_family,
    get_label,
    get_display,
    sort_by_label,
    validate_milestone_dependencies,
    validate_record,
    ScopeType,
    MILESTONES,
    MILESTONE_LABELS,
    VALID_STATUSES,
    STATUS_LABELS,
    SYSTEM_PREFIXES,
    EQUIPMENT_PREFIXES,
    F0_PREFIXES,
    A3_CODES,
    ROOM_SHAFT_CODES,
    SYSTEM_FAMILY_CODES,
    REGISTRY_SCHEMA,
)
from database import (
    load_registry,
    load_registry_df,
    upsert_registry_row,
    get_registry_row,
    upsert_registry_batch,
    clear_registry,
)
from ai_engine import process_file_smart, parse_shift_notes

# =============================================================================
# TIMELINE CHART HELPER
# =============================================================================

def render_milestone_timeline(record: Dict[str, Any], fig_width: float = 12, fig_height: float = 4) -> plt.Figure:
    """
    Renders a horizontal Gantt-style timeline for a single record's milestones.

    Milestones shown in commissioning order: IT -> PIC -> HT -> PT -> SAW
    Status colors:
        Completed  = #22c55e (green)
        In Progress = #eab308 (yellow/amber)
        Failed     = #ef4444 (red)
        Pending    = #94a3b8 (slate gray)
        N/A        = #e2e8f0 (light gray)
    """
    milestones = ["it_status", "pic_status", "ht_status", "pt_status", "saw_status"]
    labels = [MILESTONE_LABELS.get(m, m).replace(" (", "\n(").replace("_status", "").upper() for m in milestones]

    status_colors = {
        "completed": "#22c55e",
        "in progress": "#eab308",
        "failed": "#ef4444",
        "pending": "#94a3b8",
        "n/a": "#e2e8f0",
        "not applicable": "#e2e8f0",
    }

    status_order = {"completed": 4, "in progress": 3, "failed": 2, "pending": 1, "n/a": 0, "not applicable": 0}

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    y_positions = range(len(milestones))
    bar_height = 0.5

    for i, ms in enumerate(milestones):
        status = str(record.get(ms, "Pending")).strip().lower()
        color = status_colors.get(status, "#94a3b8")

        # Draw the milestone bar spanning the full width
        ax.barh(i, 1.0, height=bar_height, color=color, edgecolor="white", linewidth=1.5, alpha=0.9)

        # Add status text inside the bar
        display_status = status.title() if status != "n/a" else "N/A"
        text_color = "white" if status in ("completed", "failed") else "#1e293b"
        ax.text(0.5, i, display_status, ha="center", va="center", 
                fontsize=11, fontweight="bold", color=text_color)

    # Y-axis: milestone names
    ax.set_yticks(list(y_positions))
    ax.set_yticklabels(labels, fontsize=10, fontweight="600")

    # X-axis: hidden (just a visual container)
    ax.set_xlim(0, 1)
    ax.set_xticks([])
    ax.set_xticklabels([])

    # Remove spines
    for spine in ["top", "right", "bottom", "left"]:
        ax.spines[spine].set_visible(False)

    # Title
    kks = record.get("system_kks", "N/A")
    system = record.get("system", "Unknown")
    component = record.get("component", "Unknown")
    scope = record.get("scope_type", "Unknown")
    ax.set_title(f"{kks}  |  {system}  /  {component}  |  Scope: {scope}", 
                 fontsize=13, fontweight="bold", pad=15, color="#0f172a")

    # Legend
    legend_patches = [
        mpatches.Patch(color="#22c55e", label="Completed"),
        mpatches.Patch(color="#eab308", label="In Progress"),
        mpatches.Patch(color="#ef4444", label="Failed"),
        mpatches.Patch(color="#94a3b8", label="Pending"),
        mpatches.Patch(color="#e2e8f0", label="N/A"),
    ]
    ax.legend(handles=legend_patches, loc="upper right", fontsize=9, 
              frameon=True, fancybox=True, shadow=True)

    plt.tight_layout()
    return fig


def render_multi_timeline(records: List[Dict[str, Any]], fig_width: float = 14, fig_height_per_record: float = 1.2) -> plt.Figure:
    """
    Renders a multi-record timeline comparison chart.
    Each record gets a row group with its 5 milestones as colored bars.
    """
    if not records:
        fig, ax = plt.subplots(figsize=(fig_width, 2))
        ax.text(0.5, 0.5, "No records selected", ha="center", va="center", fontsize=14)
        ax.axis("off")
        return fig

    milestones = ["it_status", "pic_status", "ht_status", "pt_status", "saw_status"]
    ms_short = ["IT", "PIC", "HT", "PT", "SAW"]

    status_colors = {
        "completed": "#22c55e",
        "in progress": "#eab308",
        "failed": "#ef4444",
        "pending": "#94a3b8",
        "n/a": "#e2e8f0",
        "not applicable": "#e2e8f0",
    }

    n_records = len(records)
    n_milestones = len(milestones)
    fig_height = max(4, n_records * fig_height_per_record + 1.5)

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    bar_height = 0.35
    group_gap = 0.15

    y_tick_labels = []
    y_tick_positions = []

    for r_idx, record in enumerate(records):
        group_center = r_idx * (n_milestones * bar_height + group_gap + 0.3)
        kks = record.get("system_kks", "N/A")
        component = record.get("component", "N/A")

        for m_idx, ms in enumerate(milestones):
            status = str(record.get(ms, "Pending")).strip().lower()
            color = status_colors.get(status, "#94a3b8")
            y_pos = group_center + m_idx * bar_height

            ax.barh(y_pos, 1.0, height=bar_height, color=color, 
                    edgecolor="white", linewidth=0.5, alpha=0.9)

            display_status = status.title() if status != "n/a" else "N/A"
            text_color = "white" if status in ("completed", "failed") else "#1e293b"
            ax.text(0.5, y_pos, display_status, ha="center", va="center",
                    fontsize=8, fontweight="bold", color=text_color)

        # Label for this record group
        label_y = group_center + (n_milestones * bar_height) / 2 - bar_height / 2
        y_tick_positions.append(label_y)
        y_tick_labels.append(f"{kks}\n{component}")

    ax.set_yticks(y_tick_positions)
    ax.set_yticklabels(y_tick_labels, fontsize=9, fontweight="600")
    ax.set_xlim(0, 1)
    ax.set_xticks([])
    ax.set_xticklabels([])

    for spine in ["top", "right", "bottom", "left"]:
        ax.spines[spine].set_visible(False)

    ax.set_title("Commissioning Milestone Timeline by KKS", 
                 fontsize=14, fontweight="bold", pad=15, color="#0f172a")

    legend_patches = [
        mpatches.Patch(color="#22c55e", label="Completed"),
        mpatches.Patch(color="#eab308", label="In Progress"),
        mpatches.Patch(color="#ef4444", label="Failed"),
        mpatches.Patch(color="#94a3b8", label="Pending"),
        mpatches.Patch(color="#e2e8f0", label="N/A"),
    ]
    ax.legend(handles=legend_patches, loc="upper right", fontsize=9,
              frameon=True, fancybox=True, shadow=True)

    plt.tight_layout()
    return fig


# =============================================================================
# PAGE SETUP
# =============================================================================

st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
apply_custom_css()

st.markdown("# Reactor Shop Commissioning Management")
st.markdown("*Rooppur NPP - KKS Coding per RPR-QM-AEB0001 Rev B05 (2017)*")
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
    st.markdown("### KKS Document Reference")
    st.markdown("**RPR-QM-AEB0001 Rev B05 (2017)**")
    st.markdown("*Agreement on Using the KKS Coding System*")
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

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "Analytics Dashboard",
    "Data Import & Sync",
    "Manual/Field Updates",
    "Shift Note Parser",
    "Registry Editor",
    "Timeline View",
    "KKS Reference",
    "Admin",
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
            room_count = len(df[df['scope_type'] == 'Room']) if 'scope_type' in df.columns else 0
            st.metric("Rooms Tracked", room_count)

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
                    st.bar_chart(pivot_df, use_container_width=True, height=400)
                else:
                    st.info("No milestone data to display.")

        with col_right:
            st.subheader("Scope Breakdown")
            if 'scope_type' in df.columns:
                scope_counts = df['scope_type'].value_counts().reset_index()
                scope_counts.columns = ['Scope', 'Count']
                st.bar_chart(
                    scope_counts.set_index('Scope'),
                    use_container_width=True,
                    height=400
                )

        st.markdown("---")

        # --- System Family Breakdown ---
        st.subheader("System Family Distribution")
        if 'system_kks' in df.columns:
            def get_family_from_kks(kks):
                if pd.isna(kks) or not isinstance(kks, str) or len(kks) < 4:
                    return "Unknown"
                family_letter = kks[1].upper() if len(kks) > 1 else ""
                return SYSTEM_FAMILY_CODES.get(family_letter, "Other/Process")

            df['family'] = df['system_kks'].apply(get_family_from_kks)
            family_counts = df['family'].value_counts().reset_index()
            family_counts.columns = ['System Family', 'Count']
            st.bar_chart(
                family_counts.set_index('System Family'),
                use_container_width=True,
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
            use_container_width=True,
            hide_index=True
        )

        # Quick action: navigate to editor
        st.markdown("---")
        if st.button("Go to Registry Editor to edit records", type="primary", use_container_width=True):
            st.session_state.show_editor = True
            st.rerun()

# =============================================================================
# TAB 2: DATA IMPORT & SYNC
# =============================================================================

with tab2:
    st.subheader("Upload & Intelligent Import")
    st.markdown("""
    Upload commissioning registry files (.csv, .xlsx) or raw text.
    The AI engine will extract structured data, validate KKS codes per Rooppur NPP RPR-QM-AEB0001 Rev B05,
    and check milestone dependencies before upserting to the database.
    """)

    uploaded = st.file_uploader(
        "Upload Registry (.csv / .xlsx / .txt)", 
        type=["csv", "xlsx", "xls", "txt"]
    )

    if uploaded:
        col1, col2 = st.columns([1, 3])
        with col1:
            process_btn = st.button("Run Token-Efficient Sync", type="primary", use_container_width=True)

        if process_btn:
            with st.spinner("Processing file with Rooppur NPP KKS validation..."):
                file_bytes = uploaded.getvalue()
                records_processed, alerts = process_file_smart(file_bytes, uploaded.name)

            if records_processed > 0:
                st.success(f"Sync Complete! {records_processed} record(s) processed successfully.")
            else:
                st.warning("No records were processed. Check alerts below.")

            if alerts:
                with st.expander(f"Processing Log ({len(alerts)} entries)", expanded=True):
                    for alert in alerts:
                        if alert.startswith("ERROR") or alert.startswith("KKS ERROR") or alert.startswith("KKS F0 ERROR"):
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
    Add new records or update existing ones. The form enforces KKS taxonomy per Rooppur NPP RPR-QM-AEB0001 Rev B05,
    and validates milestone dependencies in real-time.

    **KKS Structure:** F0 (mandatory) + F1F2F3 + Fn + A1 + An + Bn
    - F0: 0=common, 1=Unit1, 2=Unit2, 9=temp, 5=HVAC diesel
    - F1F2F3: A=networks, B=power, C=I&C, E=fuel/waste, F=fuel handling, G=water/waste
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
        load_btn = st.button("Load", use_container_width=True)

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
                help="F0 (mandatory: 0,1,2,5,9) + F1F2F3 (3 letters). Example: 1JEA10, 0AAA01"
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

        # Show KKS validation details
        if kks_code:
            valid, msg, scope = validate_kks(kks_code)
            if valid:
                st.success(f"{msg}")
                # Show F0 details
                f0 = kks_code[0].upper()
                f0_valid, f0_msg = validate_f0(f0)
                if f0_valid:
                    st.info(f"F0 Validation: {f0_msg}")
                # Show system family
                if len(kks_code) >= 4:
                    family = get_system_family(kks_code[1:4])
                    if family:
                        st.info(f"System Family: {family}")
                # Check for room code
                if 'R' in kks_code[:6].upper():
                    room_valid, room_msg, _ = validate_room_code(kks_code)
                    if room_valid:
                        st.info(f"Room Code: {room_msg}")
            else:
                st.error(f"{msg}")

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
        submitted = st.form_submit_button("Submit Record", use_container_width=True, type="primary")

        if submitted:
            if not sys_name or not kks_code or not comp_tag:
                st.error("Required fields missing: System Name, KKS Code, and Component Tag are mandatory.")
            else:
                # Validate KKS before submission
                valid, msg, scope = validate_kks(kks_code)
                if not valid:
                    st.error(f"KKS Validation Failed: {msg}")
                else:
                    record = {
                        "system": sys_name,
                        "system_kks": kks_code,
                        "component": comp_tag,
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
                        if msg.startswith("ALERT") or msg.startswith("WARNING"):
                            st.warning(msg)
                        elif msg.startswith("DEPENDENCY"):
                            st.info(msg)
                        elif msg.startswith("KKS INFO"):
                            st.success(msg)
                        elif msg.startswith("KKS ERROR") or msg.startswith("KKS F0 ERROR"):
                            st.error(msg)

# =============================================================================
# TAB 4: SHIFT NOTE PARSER
# =============================================================================

with tab4:
    st.subheader("Natural Language Shift Note Parser")
    st.markdown("""
    Paste raw shift notes, field observations, or handover logs.
    The AI will extract structured commissioning data, validate KKS codes per Rooppur NPP rules,
    and flag any milestone dependency violations.
    """)

    notes_text = st.text_area(
        "Shift Notes",
        height=250,
        placeholder="Example: 1JEA10 feedwater pump AA001 IT completed. PIC in progress due to debris found in strainer. 0JEB20 condensate system HT passed, awaiting SAW scheduling. Room 1R101 cable shaft inspection done."
    )

    parse_label = "Parse & Validate"
    if st.button(parse_label, type="primary", use_container_width=True) and notes_text.strip():
        with st.spinner("AI analyzing shift notes with Rooppur NPP KKS rules..."):
            records, alerts = parse_shift_notes(notes_text)

        if records:
            st.success(f"Extracted {len(records)} record(s) from shift notes.")

            # Preview table
            preview_df = pd.DataFrame(records)
            st.subheader("Extracted Records Preview")
            st.dataframe(preview_df, use_container_width=True, hide_index=True)

            # Alerts
            if alerts:
                with st.expander(f"Validation Alerts ({len(alerts)})", expanded=True):
                    for alert in alerts:
                        if "DEPENDENCY" in alert:
                            st.markdown(
                                f'<div class="alert-box alert-error">{alert}</div>',
                                unsafe_allow_html=True
                            )
                        elif alert.startswith("KKS INFO"):
                            st.success(alert)
                        elif alert.startswith("KKS WARNING") or alert.startswith("KKS ERROR"):
                            st.error(alert)
                        else:
                            st.write(alert)

            # Commit option
            st.markdown("---")
            if st.button("Commit All to Registry", type="primary", use_container_width=True):
                success, all_msgs = upsert_registry_batch(records)
                st.success(f"Committed {success}/{len(records)} records to registry.")
                if success < len(records):
                    st.warning("Some records failed validation. Check logs above.")
        else:
            st.error("Could not extract any valid records from the provided notes.")
            if alerts:
                for alert in alerts:
                    st.error(alert)

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
            if 'system_kks' in df.columns:
                family_options = sorted(set([get_system_family(kks) for kks in df['system_kks'] if isinstance(kks, str) and len(kks) >= 4]))
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
                if not isinstance(kks, str) or len(kks) < 4:
                    return False
                return get_system_family(kks) in family_filter
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
        editable_cols = ['system', 'system_kks', 'component', 'it_status', 'pic_status', 'ht_status', 'pt_status', 'saw_status', 'comments']

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
            use_container_width=True,
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
                if st.button("Save Changes to Database", type="primary", use_container_width=True):
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
            use_container_width=True,
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

                if st.form_submit_button("Update Record", type="primary", use_container_width=True):
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
    st.subheader("Commissioning Milestone Timeline")
    st.markdown("""
    View the commissioning test timeline for individual systems or equipment.
    Select a KKS code from the dropdown to see its unique milestone progression.
    Use multi-select to compare multiple items side-by-side.
    """)

    df = load_registry_df()

    if df.empty:
        st.info("No data in registry yet. Use the Import or Manual tabs to add records.")
    else:
        # Build selector options: KKS + System + Component
        df['display_label'] = df.apply(
            lambda r: f"{r.get('system_kks', 'N/A')} | {r.get('system', 'Unknown')} / {r.get('component', 'Unknown')}",
            axis=1
        )

        # Filter options
        st.markdown("#### Filter by Scope")
        scope_filter_timeline = st.multiselect(
            "Scope Type",
            options=df['scope_type'].unique() if 'scope_type' in df.columns else [],
            default=[],
            key="timeline_scope_filter",
            help="Filter the KKS list by scope type"
        )

        filtered_for_timeline = df.copy()
        if scope_filter_timeline and 'scope_type' in filtered_for_timeline.columns:
            filtered_for_timeline = filtered_for_timeline[filtered_for_timeline['scope_type'].isin(scope_filter_timeline)]

        # Single KKS selector
        st.markdown("---")
        st.markdown("#### Single Item Timeline")

        single_options = filtered_for_timeline['display_label'].tolist()
        selected_single = st.selectbox(
            "Select a KKS to view its timeline:",
            options=["-- Select --"] + single_options,
            index=0,
            key="timeline_single_select"
        )

        if selected_single != "-- Select --":
            selected_kks = selected_single.split(" | ")[0]
            record = filtered_for_timeline[filtered_for_timeline['system_kks'] == selected_kks].iloc[0].to_dict()

            # Render single timeline
            fig = render_milestone_timeline(record, fig_width=12, fig_height=3.5)
            st.pyplot(fig)
            plt.close(fig)

            # Show milestone details table
            st.markdown("#### Milestone Details")
            detail_data = []
            for ms in MILESTONES:
                status = record.get(ms, "Pending")
                detail_data.append({
                    "Milestone": MILESTONE_LABELS.get(ms, ms),
                    "Status": status,
                })
            detail_df = pd.DataFrame(detail_data)
            st.dataframe(detail_df, use_container_width=True, hide_index=True)

            # Dependency check display
            dep_issues = validate_milestone_dependencies(record)
            if dep_issues:
                st.markdown("---")
                st.error("Dependency Violations Detected:")
                for issue in dep_issues:
                    st.markdown(f"- {issue}")
            else:
                st.success("All milestone dependencies satisfied.")

        st.markdown("---")
        st.markdown("#### Multi-Item Comparison Timeline")

        # Multi-select for comparison
        selected_multi = st.multiselect(
            "Select multiple KKS codes to compare:",
            options=single_options,
            default=[],
            key="timeline_multi_select",
            help="Select 2 or more items to compare their milestone timelines side-by-side"
        )

        if selected_multi:
            selected_kks_list = [s.split(" | ")[0] for s in selected_multi]
            selected_records = []
            for kks in selected_kks_list:
                rec = filtered_for_timeline[filtered_for_timeline['system_kks'] == kks]
                if not rec.empty:
                    selected_records.append(rec.iloc[0].to_dict())

            if selected_records:
                fig_multi = render_multi_timeline(
                    selected_records, 
                    fig_width=14, 
                    fig_height_per_record=1.2
                )
                st.pyplot(fig_multi)
                plt.close(fig_multi)

                # Summary table
                st.markdown("#### Comparison Summary")
                summary_data = []
                for rec in selected_records:
                    row = {
                        "KKS": rec.get('system_kks', 'N/A'),
                        "System": rec.get('system', 'Unknown'),
                        "Component": rec.get('component', 'Unknown'),
                        "Scope": rec.get('scope_type', 'Unknown'),
                    }
                    for ms in MILESTONES:
                        row[MILESTONE_LABELS.get(ms, ms).split(" (")[0]] = rec.get(ms, "Pending")
                    summary_data.append(row)

                summary_df = pd.DataFrame(summary_data)
                st.dataframe(summary_df, use_container_width=True, hide_index=True)

# =============================================================================
# TAB 7: KKS REFERENCE
# =============================================================================

with tab7:
    st.subheader("Rooppur NPP KKS Coding Reference")
    st.markdown("*Based on document RPR-QM-AEB0001 Revision B05 (2017)*")

    st.markdown("---")

    # F0 Prefixes
    st.markdown("#### F0 Prefix (Mandatory)")
    sorted_f0 = sort_by_label(F0_PREFIXES) if sort_by == "label" else sorted(F0_PREFIXES.items())

    f0_data = []
    for k, v in sorted_f0:
        f0_data.append({
            "Prefix": k,
            "Description": v,
        })
    f0_df = pd.DataFrame(f0_data)
    st.dataframe(f0_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # System Families
    st.markdown("#### System Families (F1 First Letter)")
    sorted_families = sort_by_label(SYSTEM_FAMILY_CODES) if sort_by == "label" else sorted(SYSTEM_FAMILY_CODES.items())

    family_data = []
    for k, v in sorted_families:
        family_data.append({
            "Family Code": k,
            "Description": v,
        })
    family_df = pd.DataFrame(family_data)
    st.dataframe(family_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # A3 Codes
    st.markdown("#### A3 Alphabetic Codes")
    sorted_a3 = sort_by_label(A3_CODES) if sort_by == "label" else sorted(A3_CODES.items())

    a3_data = []
    for k, v in sorted_a3:
        a3_data.append({
            "Code": k,
            "Description": v,
        })
    a3_df = pd.DataFrame(a3_data)
    st.dataframe(a3_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Room Shaft Codes
    st.markdown("#### Room Shaft Codes (Special)")
    sorted_shafts = sort_by_label(ROOM_SHAFT_CODES) if sort_by == "label" else sorted(ROOM_SHAFT_CODES.items())

    shaft_data = []
    for k, v in sorted_shafts:
        shaft_data.append({
            "Code": k + "NN",
            "Description": v,
        })
    shaft_df = pd.DataFrame(shaft_data)
    st.dataframe(shaft_df, use_container_width=True, hide_index=True)

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
    st.dataframe(ms_df, use_container_width=True, hide_index=True)

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
    st.dataframe(status_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # KKS Structure
    st.markdown("#### KKS Code Structure")
    st.markdown("""
    ```
    F0 + F1F2F3 + Fn + A1 + An + Bn

    F0  = Prefix (MANDATORY)
          0 = Common station
          1 = Unit 1 / Safety train
          2 = Unit 2 / Safety train
          5 = HVAC from NO diesel-generator
          9 = Temporary installations

    F1F2F3 = Functional system (3 letters)
             A = Networks/Switchgears
             B = Power transmission/Auxiliary supply
             C = I&C equipment
             E = Fuel/Waste
             F = Nuclear fuel handling
             G = Water supply/Waste removal

    Fn  = 00-99
    A1  = Equipment unit letter
    An  = 001-999 (per Appendix B)
    Bn  = 01-99 component
    ```
    """)

    st.markdown("---")
    st.markdown("**Limitation:** Equipment unit numbering validation (001-900) requires Appendix B which is not fully detailed in the provided context. Codes outside this range will generate warnings.")

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
            if st.button("PERMANENTLY CLEAR REGISTRY", type="primary", use_container_width=True):
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
