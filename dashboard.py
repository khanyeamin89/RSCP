"""
Reactor Shop Commissioning - Main Dashboard
============================================
Interactive Streamlit application for commissioning registry management.
Uses native Streamlit charts to avoid external dependencies.
"""

import streamlit as st
import pandas as pd
from typing import Dict, Any, List

# Import centralized config and database modules
from config import (
    PAGE_TITLE,
    PAGE_ICON,
    get_supabase_client,
    apply_custom_css,
    validate_kks,
    enforce_scope_milestones,
    validate_milestone_dependencies,
    validate_record,
    ScopeType,
    MILESTONES,
    VALID_STATUSES,
    SYSTEM_PREFIXES,
    EQUIPMENT_PREFIXES,
    REGISTRY_SCHEMA,
)
from database import (
    load_registry,
    load_registry_df,
    upsert_registry_row,
    get_registry_row,
    upsert_registry_batch,
)
from ai_engine import process_file_smart, parse_shift_notes

# =============================================================================
# PAGE SETUP
# =============================================================================

st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
apply_custom_css()

st.markdown("# ⚛️ Reactor Shop Commissioning Management")
st.markdown("---")

# =============================================================================
# TABS
# =============================================================================

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Analytics Dashboard", 
    "📥 Data Import & Sync", 
    "🛠️ Manual/Field Updates",
    "📝 Shift Note Parser"
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
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            system_count = len(df[df['scope_type'] == 'System']) if 'scope_type' in df.columns else 0
            st.metric("Systems Tracked", system_count)

        with col2:
            equip_count = len(df[df['scope_type'] == 'Equipment']) if 'scope_type' in df.columns else 0
            st.metric("Equipment Tracked", equip_count)

        with col3:
            # Overall completion: count records where ALL applicable milestones are Completed
            def calc_completion(row):
                applicable = []
                scope = row.get('scope_type', '')
                for ms in MILESTONES:
                    val = str(row.get(ms, '')).strip()
                    if scope == 'Equipment' and ms in ('pt_status', 'saw_status'):
                        continue  # Skip N/A milestones for equipment
                    applicable.append(val.lower() == 'completed')
                return all(applicable) if applicable else False

            completed = df.apply(calc_completion, axis=1).sum()
            total = len(df)
            overall_pct = (completed / total * 100) if total > 0 else 0
            st.metric("Fully Completed", f"{completed}/{total}", f"{overall_pct:.1f}%")

        with col4:
            # Count items with dependency violations
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
                # Build a summary dataframe for the bar chart
                status_summary = {ms.replace('_status', '').upper(): {} for ms in MILESTONES}

                for ms in MILESTONES:
                    ms_label = ms.replace('_status', '').upper()
                    for status in ['Completed', 'In Progress', 'Pending', 'Failed', 'N/A']:
                        count = 0
                        for _, row in df.iterrows():
                            scope = row.get('scope_type', '')
                            if scope == 'Equipment' and ms in ('pt_status', 'saw_status'):
                                continue
                            if str(row.get(ms, '')).strip() == status:
                                count += 1
                        if count > 0:
                            status_summary[ms_label][status] = count

                # Convert to DataFrame for st.bar_chart
                chart_data = []
                for ms_label, statuses in status_summary.items():
                    for status, count in statuses.items():
                        chart_data.append({'Milestone': ms_label, 'Status': status, 'Count': count})

                if chart_data:
                    chart_df = pd.DataFrame(chart_data)
                    pivot_df = chart_df.pivot(index='Milestone', columns='Status', values='Count').fillna(0)
                    # Reorder columns for consistent colors
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

        # --- Data Table ---
        st.subheader("Registry Overview")

        # Add color-coded status columns
        display_df = df.copy()

        def status_badge(val):
            val = str(val).strip().lower()
            if val == 'completed':
                return '🟢 Completed'
            elif val == 'in progress':
                return '🟡 In Progress'
            elif val == 'failed':
                return '🔴 Failed'
            elif val in ('n/a', 'not applicable'):
                return '⚪ N/A'
            else:
                return '⚪ Pending'

        for ms in MILESTONES:
            if ms in display_df.columns:
                display_df[ms.replace('_status', '').upper()] = display_df[ms].apply(status_badge)

        # Select display columns
        display_cols = ['system', 'system_kks', 'scope_type', 'component'] + \
                       [ms.replace('_status', '').upper() for ms in MILESTONES if ms in display_df.columns] + \
                       ['comments']
        display_cols = [c for c in display_cols if c in display_df.columns]

        st.dataframe(
            display_df[display_cols],
            use_container_width=True,
            hide_index=True
        )

# =============================================================================
# TAB 2: DATA IMPORT & SYNC
# =============================================================================

with tab2:
    st.subheader("Upload & Intelligent Import")
    st.markdown("""
    Upload commissioning registry files (.csv, .xlsx) or raw text.
    The AI engine will extract structured data, validate KKS codes, enforce scope rules,
    and check milestone dependencies before upserting to the database.
    """)

    uploaded = st.file_uploader(
        "Upload Registry (.csv / .xlsx / .txt)", 
        type=["csv", "xlsx", "xls", "txt"]
    )

    if uploaded:
        col1, col2 = st.columns([1, 3])
        with col1:
            process_btn = st.button("🚀 Run Token-Efficient Sync", type="primary", use_container_width=True)

        if process_btn:
            with st.spinner("Processing file..."):
                file_bytes = uploaded.getvalue()
                records_processed, alerts = process_file_smart(file_bytes, uploaded.name)

            if records_processed > 0:
                st.success(f"✅ Sync Complete! {records_processed} record(s) processed successfully.")
            else:
                st.warning("⚠️ No records were processed. Check alerts below.")

            if alerts:
                with st.expander(f"📋 Processing Log ({len(alerts)} entries)", expanded=True):
                    for alert in alerts:
                        if alert.startswith("ERROR"):
                            st.error(alert)
                        elif alert.startswith("ALERT") or alert.startswith("WARNING"):
                            st.warning(alert)
                        elif alert.startswith("DEPENDENCY"):
                            st.info(alert)
                        else:
                            st.write(alert)

# =============================================================================
# TAB 3: MANUAL / FIELD UPDATES
# =============================================================================

with tab3:
    st.subheader("Manual Record Entry & Edit")
    st.markdown("""
    Add new records or update existing ones. The form enforces KKS taxonomy,
    scope-based milestone rules, and dependency validation in real-time.
    """)

    # --- Search existing record ---
    st.markdown("#### 🔍 Load Existing Record (Optional)")
    search_col1, search_col2, search_col3 = st.columns([2, 2, 1])

    with search_col1:
        search_system = st.text_input("System Name", key="search_sys", placeholder="e.g., Feedwater")
    with search_col2:
        search_component = st.text_input("Component Tag", key="search_comp", placeholder="e.g., Pump-001")
    with search_col3:
        st.markdown("<br>", unsafe_allow_html=True)
        load_btn = st.button("🔎 Load", use_container_width=True)

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
    st.markdown("#### ✏️ Record Details")

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
                help="3-letter prefix = System (JEA, JAA...). 2-letter prefix = Equipment (AA, AP...)"
            )

        with col_b:
            comp_tag = st.text_input(
                "Component Tag *", 
                value=prefill.get('component', ''),
                help="Unique component identifier"
            )
            # Auto-detected scope display
            detected_scope = ""
            if kks_code:
                valid, msg, scope = validate_kks(kks_code)
                if scope:
                    detected_scope = scope.value

            st.text_input(
                "Detected Scope", 
                value=detected_scope,
                disabled=True,
                help="Auto-detected from KKS prefix"
            )

        st.markdown("---")
        st.markdown("#### 📋 Commissioning Milestones")

        # Determine which milestones are active based on KKS
        is_equipment = (detected_scope == 'Equipment')

        ms_col1, ms_col2, ms_col3 = st.columns(3)

        with ms_col1:
            it_stat = st.selectbox(
                "IT (Individual Test)",
                ["Pending", "In Progress", "Completed", "Failed"],
                index=["Pending", "In Progress", "Completed", "Failed"].index(
                    prefill.get('it_status', 'Pending')
                ) if prefill.get('it_status') in ["Pending", "In Progress", "Completed", "Failed"] else 0
            )
            pic_stat = st.selectbox(
                "PIC (Post-Install Cleaning)",
                ["Pending", "In Progress", "Completed", "Failed"],
                index=["Pending", "In Progress", "Completed", "Failed"].index(
                    prefill.get('pic_status', 'Pending')
                ) if prefill.get('pic_status') in ["Pending", "In Progress", "Completed", "Failed"] else 0
            )

        with ms_col2:
            ht_stat = st.selectbox(
                "HT (Hydro Test)",
                ["Pending", "In Progress", "Completed", "Failed"],
                index=["Pending", "In Progress", "Completed", "Failed"].index(
                    prefill.get('ht_status', 'Pending')
                ) if prefill.get('ht_status') in ["Pending", "In Progress", "Completed", "Failed"] else 0
            )
            pt_stat = st.selectbox(
                "PT (Pneumatic Test)",
                ["N/A", "Pending", "In Progress", "Completed", "Failed"],
                index=0 if is_equipment else (
                    ["N/A", "Pending", "In Progress", "Completed", "Failed"].index(
                        prefill.get('pt_status', 'Pending')
                    ) if prefill.get('pt_status') in ["N/A", "Pending", "In Progress", "Completed", "Failed"] else 1
                ),
                disabled=is_equipment,
                help="N/A for Equipment scope" if is_equipment else ""
            )

        with ms_col3:
            saw_stat = st.selectbox(
                "SAW (Start-up & Adjustment)",
                ["N/A", "Pending", "In Progress", "Completed", "Failed"],
                index=0 if is_equipment else (
                    ["N/A", "Pending", "In Progress", "Completed", "Failed"].index(
                        prefill.get('saw_status', 'Pending')
                    ) if prefill.get('saw_status') in ["N/A", "Pending", "In Progress", "Completed", "Failed"] else 1
                ),
                disabled=is_equipment,
                help="N/A for Equipment scope" if is_equipment else ""
            )

        comments = st.text_area(
            "Comments / Notes",
            value=prefill.get('comments', ''),
            placeholder="Enter any special notes, anomalies, or shift handover comments..."
        )

        # Dependency warning
        if pic_stat != "Completed" and ht_stat == "Completed":
            warning_html = (
                '<div class="alert-box alert-warning">'
                '⚠️ <b>Dependency Warning:</b> HT is marked Completed but PIC is not. '
                'PIC must precede HT per commissioning procedure.</div>'
            )
            st.markdown(warning_html, unsafe_allow_html=True)

        st.markdown("---")
        submitted = st.form_submit_button("💾 Submit Record", use_container_width=True, type="primary")

        if submitted:
            if not sys_name or not kks_code or not comp_tag:
                st.error("❌ Required fields missing: System Name, KKS Code, and Component Tag are mandatory.")
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
                    st.success("✅ Registry Updated Successfully!")
                for msg in msgs:
                    if msg.startswith("ALERT"):
                        st.warning(msg)
                    elif msg.startswith("DEPENDENCY"):
                        st.info(msg)

# =============================================================================
# TAB 4: SHIFT NOTE PARSER
# =============================================================================

with tab4:
    st.subheader("📝 Natural Language Shift Note Parser")
    st.markdown("""
    Paste raw shift notes, field observations, or handover logs.
    The AI will extract structured commissioning data, validate KKS codes,
    enforce scope rules, and flag any milestone dependency violations.
    """)

    notes_text = st.text_area(
        "Shift Notes",
        height=250,
        placeholder="Example: JEA10 feedwater pump AA001 IT completed. PIC in progress due to debris found in strainer. JEB20 condensate system HT passed, awaiting SAW scheduling."
    )

    if st.button("🔍 Parse & Validate", type="primary", use_container_width=True) and notes_text.strip():
        with st.spinner("AI analyzing shift notes..."):
            records, alerts = parse_shift_notes(notes_text)

        if records:
            st.success(f"✅ Extracted {len(records)} record(s) from shift notes.")

            # Preview table
            preview_df = pd.DataFrame(records)
            st.subheader("📋 Extracted Records Preview")
            st.dataframe(preview_df, use_container_width=True, hide_index=True)

            # Alerts
            if alerts:
                with st.expander(f"⚠️ Validation Alerts ({len(alerts)})", expanded=True):
                    for alert in alerts:
                        if "N/A" in alert and "Equipment" in alert:
                            st.markdown(
                                f'<div class="alert-box alert-warning">{alert}</div>',
                                unsafe_allow_html=True
                            )
                        elif "DEPENDENCY" in alert:
                            st.markdown(
                                f'<div class="alert-box alert-error">{alert}</div>',
                                unsafe_allow_html=True
                            )
                        else:
                            st.write(alert)

            # Commit option
            st.markdown("---")
            if st.button("💾 Commit All to Registry", type="primary", use_container_width=True):
                success, all_msgs = upsert_registry_batch(records)
                st.success(f"✅ Committed {success}/{len(records)} records to registry.")
                if success < len(records):
                    st.warning("Some records failed validation. Check logs above.")
        else:
            st.error("❌ Could not extract any valid records from the provided notes.")
            if alerts:
                for alert in alerts:
                    st.error(alert)
