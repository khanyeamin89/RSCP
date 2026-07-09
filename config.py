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
    enforce_scope_milestones,
    validate_milestone_dependencies,
    validate_record,
    ScopeType,
    MILESTONES,
    VALID_STATUSES,
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
)
from ai_engine import process_file_smart, parse_shift_notes

# =============================================================================
# PAGE SETUP
# =============================================================================

st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
apply_custom_css()

st.markdown("# ⚛️ Reactor Shop Commissioning Management")
st.markdown("*Rooppur NPP - KKS Coding per RPR-QM-AEB0001 Rev B05 (2017)*")
st.markdown("---")

# =============================================================================
# TABS
# =============================================================================

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Analytics Dashboard", 
    "📥 Data Import & Sync", 
    "🛠️ Manual/Field Updates",
    "📝 Shift Note Parser",
    "📖 KKS Reference"
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
            # Overall completion: count records where ALL applicable milestones are Completed
            def calc_completion(row):
                applicable = []
                scope = row.get('scope_type', '')
                for ms in MILESTONES:
                    val = str(row.get(ms, '')).strip()
                    if scope == 'Equipment' and ms in ('pt_status', 'saw_status'):
                        continue  # Skip N/A milestones for equipment
                    if scope == 'Room':
                        continue  # Skip all milestones for room codes
                    applicable.append(val.lower() == 'completed')
                return all(applicable) if applicable else False

            completed = df.apply(calc_completion, axis=1).sum()
            total = len(df)
            overall_pct = (completed / total * 100) if total > 0 else 0
            st.metric("Fully Completed", f"{completed}/{total}", f"{overall_pct:.1f}%")

        with col5:
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
                            if scope == 'Room':
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
        display_cols = ['system', 'system_kks', 'scope_type', 'component'] +                        [ms.replace('_status', '').upper() for ms in MILESTONES if ms in display_df.columns] +                        ['comments']
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
    The AI engine will extract structured data, validate KKS codes per Rooppur NPP RPR-QM-AEB0001 Rev B05,
    enforce scope rules, and check milestone dependencies before upserting to the database.
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
            with st.spinner("Processing file with Rooppur NPP KKS validation..."):
                file_bytes = uploaded.getvalue()
                records_processed, alerts = process_file_smart(file_bytes, uploaded.name)

            if records_processed > 0:
                st.success(f"✅ Sync Complete! {records_processed} record(s) processed successfully.")
            else:
                st.warning("⚠️ No records were processed. Check alerts below.")

            if alerts:
                with st.expander(f"📋 Processing Log ({len(alerts)} entries)", expanded=True):
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
    scope-based milestone rules, and dependency validation in real-time.

    **KKS Structure:** F0 (mandatory) + F1F2F3 + Fn + A1 + An + Bn
    - F0: 0=common, 1=Unit1, 2=Unit2, 9=temp, 5=HVAC diesel
    - F1F2F3: A=networks, B=power, C=I&C, E=fuel/waste, F=fuel handling, G=water/waste
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
                st.success(f"✅ {msg}")
                # Show F0 details
                f0 = kks_code[0].upper()
                f0_valid, f0_msg = validate_f0(f0)
                if f0_valid:
                    st.info(f"📌 F0 Validation: {f0_msg}")
                # Show system family
                if len(kks_code) >= 4:
                    family = get_system_family(kks_code[1:4])
                    if family:
                        st.info(f"📌 System Family: {family}")
                # Check for room code
                if 'R' in kks_code[:6].upper():
                    room_valid, room_msg, _ = validate_room_code(kks_code)
                    if room_valid:
                        st.info(f"📌 Room Code: {room_msg}")
            else:
                st.error(f"❌ {msg}")

        st.markdown("---")
        st.markdown("#### 📋 Commissioning Milestones")

        # Determine which milestones are active based on KKS
        is_equipment = (detected_scope == 'Equipment')
        is_room = (detected_scope == 'Room')

        ms_col1, ms_col2, ms_col3 = st.columns(3)

        with ms_col1:
            it_stat = st.selectbox(
                "IT (Individual Test)",
                ["Pending", "In Progress", "Completed", "Failed", "N/A"],
                index=["Pending", "In Progress", "Completed", "Failed", "N/A"].index(
                    prefill.get('it_status', 'Pending')
                ) if prefill.get('it_status') in ["Pending", "In Progress", "Completed", "Failed", "N/A"] else 0,
                disabled=is_room,
                help="N/A for Room scope" if is_room else ""
            )
            pic_stat = st.selectbox(
                "PIC (Post-Install Cleaning)",
                ["Pending", "In Progress", "Completed", "Failed", "N/A"],
                index=["Pending", "In Progress", "Completed", "Failed", "N/A"].index(
                    prefill.get('pic_status', 'Pending')
                ) if prefill.get('pic_status') in ["Pending", "In Progress", "Completed", "Failed", "N/A"] else 0,
                disabled=is_room,
                help="N/A for Room scope" if is_room else ""
            )

        with ms_col2:
            ht_stat = st.selectbox(
                "HT (Hydro Test)",
                ["Pending", "In Progress", "Completed", "Failed", "N/A"],
                index=["Pending", "In Progress", "Completed", "Failed", "N/A"].index(
                    prefill.get('ht_status', 'Pending')
                ) if prefill.get('ht_status') in ["Pending", "In Progress", "Completed", "Failed", "N/A"] else 0,
                disabled=is_room,
                help="N/A for Room scope" if is_room else ""
            )
            pt_stat = st.selectbox(
                "PT (Pneumatic Test)",
                ["N/A", "Pending", "In Progress", "Completed", "Failed"],
                index=0 if is_equipment or is_room else (
                    ["N/A", "Pending", "In Progress", "Completed", "Failed"].index(
                        prefill.get('pt_status', 'Pending')
                    ) if prefill.get('pt_status') in ["N/A", "Pending", "In Progress", "Completed", "Failed"] else 1
                ),
                disabled=is_equipment or is_room,
                help="N/A for Equipment and Room scope" if is_equipment or is_room else ""
            )

        with ms_col3:
            saw_stat = st.selectbox(
                "SAW (Start-up & Adjustment)",
                ["N/A", "Pending", "In Progress", "Completed", "Failed"],
                index=0 if is_equipment or is_room else (
                    ["N/A", "Pending", "In Progress", "Completed", "Failed"].index(
                        prefill.get('saw_status', 'Pending')
                    ) if prefill.get('saw_status') in ["N/A", "Pending", "In Progress", "Completed", "Failed"] else 1
                ),
                disabled=is_equipment or is_room,
                help="N/A for Equipment and Room scope" if is_equipment or is_room else ""
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
                # Validate KKS before submission
                valid, msg, scope = validate_kks(kks_code)
                if not valid:
                    st.error(f"❌ KKS Validation Failed: {msg}")
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
    st.subheader("📝 Natural Language Shift Note Parser")
    st.markdown("""
    Paste raw shift notes, field observations, or handover logs.
    The AI will extract structured commissioning data, validate KKS codes per Rooppur NPP rules,
    enforce scope rules, and flag any milestone dependency violations.

    **Note:** The AI is instructed to identify mandatory F0 prefixes and Rooppur-specific KKS structures.
    """)

    notes_text = st.text_area(
        "Shift Notes",
        height=250,
        placeholder="Example: 1JEA10 feedwater pump AA001 IT completed. PIC in progress due to debris found in strainer. 0JEB20 condensate system HT passed, awaiting SAW scheduling. Room 1R101 cable shaft inspection done."
    )

    if st.button("🔍 Parse & Validate", type="primary", use_container_width=True) and notes_text.strip():
        with st.spinner("AI analyzing shift notes with Rooppur NPP KKS rules..."):
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
                        elif alert.startswith("KKS INFO"):
                            st.success(alert)
                        elif alert.startswith("KKS WARNING") or alert.startswith("KKS ERROR"):
                            st.error(alert)
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

# =============================================================================
# TAB 5: KKS REFERENCE
# =============================================================================

with tab5:
    st.subheader("📖 Rooppur NPP KKS Coding Reference")
    st.markdown("*Based on document RPR-QM-AEB0001 Revision B05 (2017)*")

    st.markdown("---")

    # F0 Prefixes
    st.markdown("#### F0 Prefix (Mandatory)")
    f0_df = pd.DataFrame([
        {"Prefix": k, "Description": v} for k, v in F0_PREFIXES.items()
    ])
    st.dataframe(f0_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # System Families
    st.markdown("#### System Families (F1 First Letter)")
    family_df = pd.DataFrame([
        {"Family Code": k, "Description": v} for k, v in SYSTEM_FAMILY_CODES.items()
    ])
    st.dataframe(family_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # A3 Codes
    st.markdown("#### A3 Alphabetic Codes")
    a3_df = pd.DataFrame([
        {"Code": k, "Description": v} for k, v in A3_CODES.items()
    ])
    st.dataframe(a3_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Room Shaft Codes
    st.markdown("#### Room Shaft Codes (Special)")
    shaft_df = pd.DataFrame([
        {"Code": k + "NN", "Description": v} for k, v in ROOM_SHAFT_CODES.items()
    ])
    st.dataframe(shaft_df, use_container_width=True, hide_index=True)

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
             J = Process systems (VVER typical)

    Fn  = 00-99
    A1  = Equipment unit letter
    An  = 001-999 (per Appendix B)
    Bn  = 01-99 component
    ```
    """)

    st.markdown("---")
    st.markdown("**Limitation:** Equipment unit numbering validation (001-900) requires Appendix B which is not fully detailed in the provided context. Codes outside this range will generate warnings.")
