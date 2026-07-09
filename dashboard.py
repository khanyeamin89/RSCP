"""
Reactor Shop Commissioning - Main Dashboard
============================================
Interactive Streamlit application for commissioning registry management.
Uses native Streamlit charts to avoid external dependencies.

KKS Coding based on Rooppur NPP document RPR-QM-AEB0001 Revision B05 (2017)
"Agreement on Using the KKS Coding System" (VGB-B 105 E 2010, VGB-B 106 E 2004)

Bilingual support: Russian (original document language) -> English translations
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
    get_system_family_ru,
    get_bilingual_system_family,
    get_bilingual_label,
    get_bilingual_display,
    sort_by_russian,
    sort_by_english,
    enforce_scope_milestones,
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
)
from ai_engine import process_file_smart, parse_shift_notes

# =============================================================================
# PAGE SETUP
# =============================================================================

st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
apply_custom_css()

st.markdown("# ⚛️ Reactor Shop Commissioning Management")
st.markdown("*Rooppur NPP - KKS Coding per RPR-QM-AEB0001 Rev B05 (2017)*")
st.markdown("*Двуязычная поддержка: Русский / English*")
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
# LANGUAGE SELECTOR (Sidebar)
# =============================================================================

with st.sidebar:
    st.markdown("### 🌐 Language / Язык")
    lang = st.radio(
        "Select display language:",
        options=["en", "ru"],
        format_func=lambda x: "English" if x == "en" else "Русский",
        index=0,
        key="lang_selector"
    )
    st.markdown("---")
    st.markdown("### 📋 KKS Document Reference")
    st.markdown("**RPR-QM-AEB0001 Rev B05 (2017)**")
    st.markdown("*Agreement on Using the KKS Coding System*")
    st.markdown("*Соглашение об использовании системы кодирования KKS*")
    st.markdown("---")
    st.markdown("### 📊 Sort Options")
    sort_by = st.selectbox(
        "Sort KKS reference tables by:",
        options=["english", "russian"],
        format_func=lambda x: "English (A-Z)" if x == "english" else "Русский (А-Я)",
        index=0,
        key="sort_selector"
    )

# =============================================================================
# TABS
# =============================================================================

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Analytics Dashboard" if lang == "en" else "📊 Панель аналитики",
    "📥 Data Import & Sync" if lang == "en" else "📥 Импорт и синхронизация",
    "🛠️ Manual/Field Updates" if lang == "en" else "🛠️ Ручной ввод/обновления",
    "📝 Shift Note Parser" if lang == "en" else "📝 Парсер сменных записей",
    "✏️ Registry Editor" if lang == "en" else "✏️ Редактор реестра",
    "📖 KKS Reference" if lang == "en" else "📖 Справочник KKS",
])

# =============================================================================
# TAB 1: ANALYTICS DASHBOARD
# =============================================================================

with tab1:
    df = load_registry_df()

    if df.empty:
        st.info("No data in registry yet. Use the Import or Manual tabs to add records." if lang == "en" else "В реестре пока нет данных. Используйте вкладки Импорт или Ручной ввод.")
    else:
        # --- Top Metrics Row ---
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            system_count = len(df[df['scope_type'] == 'System']) if 'scope_type' in df.columns else 0
            label = "Systems Tracked" if lang == "en" else "Систем отслеживается"
            st.metric(label, system_count)

        with col2:
            equip_count = len(df[df['scope_type'] == 'Equipment']) if 'scope_type' in df.columns else 0
            label = "Equipment Tracked" if lang == "en" else "Оборудования отслеживается"
            st.metric(label, equip_count)

        with col3:
            room_count = len(df[df['scope_type'] == 'Room']) if 'scope_type' in df.columns else 0
            label = "Rooms Tracked" if lang == "en" else "Помещений отслеживается"
            st.metric(label, room_count)

        with col4:
            def calc_completion(row):
                applicable = []
                scope = row.get('scope_type', '')
                for ms in MILESTONES:
                    val = str(row.get(ms, '')).strip()
                    if scope == 'Equipment' and ms in ('pt_status', 'saw_status'):
                        continue
                    if scope == 'Room':
                        continue
                    applicable.append(val.lower() == 'completed')
                return all(applicable) if applicable else False

            completed = df.apply(calc_completion, axis=1).sum()
            total = len(df)
            overall_pct = (completed / total * 100) if total > 0 else 0
            label = "Fully Completed" if lang == "en" else "Полностью завершено"
            st.metric(label, f"{completed}/{total}", f"{overall_pct:.1f}%")

        with col5:
            violations = 0
            for _, row in df.iterrows():
                issues = validate_milestone_dependencies(row.to_dict())
                if issues:
                    violations += 1
            label = "Dependency Issues" if lang == "en" else "Проблемы зависимостей"
            st.metric(label, violations, delta_color="inverse")

        st.markdown("---")

        # --- Charts Row ---
        col_left, col_right = st.columns(2)

        with col_left:
            title = "Milestone Status Distribution" if lang == "en" else "Распределение статусов этапов"
            st.subheader(title)
            if 'it_status' in df.columns:
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
                    st.info("No milestone data to display." if lang == "en" else "Нет данных по этапам для отображения.")

        with col_right:
            title = "Scope Breakdown" if lang == "en" else "Распределение по типам"
            st.subheader(title)
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
        title = "System Family Distribution" if lang == "en" else "Распределение по системным семействам"
        st.subheader(title)
        if 'system_kks' in df.columns:
            def get_family_from_kks(kks):
                if pd.isna(kks) or not isinstance(kks, str) or len(kks) < 4:
                    return "Unknown"
                family_letter = kks[1].upper() if len(kks) > 1 else ""
                return SYSTEM_FAMILY_CODES.get(family_letter, {}).get(lang, "Other/Process")

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
        title = "Registry Overview" if lang == "en" else "Обзор реестра"
        st.subheader(title)

        display_df = df.copy()

        def status_badge(val):
            val = str(val).strip().lower()
            if val == 'completed':
                return '🟢 Completed' if lang == "en" else '🟢 Выполнено'
            elif val == 'in progress':
                return '🟡 In Progress' if lang == "en" else '🟡 В работе'
            elif val == 'failed':
                return '🔴 Failed' if lang == "en" else '🔴 Не пройдено'
            elif val in ('n/a', 'not applicable'):
                return '⚪ N/A' if lang == "en" else '⚪ Н/П'
            else:
                return '⚪ Pending' if lang == "en" else '⚪ В ожидании'

        for ms in MILESTONES:
            if ms in display_df.columns:
                display_df[ms.replace('_status', '').upper()] = display_df[ms].apply(status_badge)

        display_cols = ['system', 'system_kks', 'scope_type', 'component'] +                        [ms.replace('_status', '').upper() for ms in MILESTONES if ms in display_df.columns] +                        ['comments']
        display_cols = [c for c in display_cols if c in display_df.columns]

        st.dataframe(
            display_df[display_cols],
            use_container_width=True,
            hide_index=True
        )

        # Quick action: navigate to editor
        st.markdown("---")
        nav_label = "✏️ Go to Registry Editor to edit records" if lang == "en" else "✏️ Перейти в редактор реестра для редактирования"
        if st.button(nav_label, type="primary", use_container_width=True):
            st.session_state.show_editor = True
            st.rerun()

# =============================================================================
# TAB 2: DATA IMPORT & SYNC
# =============================================================================

with tab2:
    title = "Upload & Intelligent Import" if lang == "en" else "Загрузка и интеллектуальный импорт"
    st.subheader(title)
    st.markdown("""
    Upload commissioning registry files (.csv, .xlsx) or raw text.
    The AI engine will extract structured data, validate KKS codes per Rooppur NPP RPR-QM-AEB0001 Rev B05,
    enforce scope rules, and check milestone dependencies before upserting to the database.

    Загрузите файлы реестра (.csv, .xlsx) или текст.
    AI извлечет структурированные данные, проверит коды KKS, применит правила и проверит зависимости.
    """)

    uploaded = st.file_uploader(
        "Upload Registry (.csv / .xlsx / .txt)" if lang == "en" else "Загрузить реестр (.csv / .xlsx / .txt)", 
        type=["csv", "xlsx", "xls", "txt"]
    )

    if uploaded:
        col1, col2 = st.columns([1, 3])
        with col1:
            btn_label = "🚀 Run Token-Efficient Sync" if lang == "en" else "🚀 Запустить синхронизацию"
            process_btn = st.button(btn_label, type="primary", use_container_width=True)

        if process_btn:
            with st.spinner("Processing file with Rooppur NPP KKS validation..." if lang == "en" else "Обработка файла с проверкой KKS Руппур..."):
                file_bytes = uploaded.getvalue()
                records_processed, alerts = process_file_smart(file_bytes, uploaded.name)

            if records_processed > 0:
                st.success(f"✅ Sync Complete! {records_processed} record(s) processed successfully." if lang == "en" else f"✅ Синхронизация завершена! Обработано {records_processed} записей.")
            else:
                st.warning("⚠️ No records were processed. Check alerts below." if lang == "en" else "⚠️ Записи не обработаны. Проверьте журнал.")

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
    title = "Manual Record Entry & Edit" if lang == "en" else "Ручной ввод и редактирование записей"
    st.subheader(title)
    st.markdown("""
    Add new records or update existing ones. The form enforces KKS taxonomy per Rooppur NPP RPR-QM-AEB0001 Rev B05,
    scope-based milestone rules, and dependency validation in real-time.

    **KKS Structure:** F0 (mandatory) + F1F2F3 + Fn + A1 + An + Bn
    - F0: 0=common (общестанционные), 1=Unit1 (блок 1), 2=Unit2 (блок 2), 9=temp (временные), 5=HVAC diesel
    - F1F2F3: A=networks (сети), B=power (передача энергии), C=I&C (КИПиА), E=fuel/waste (топливо/отходы), F=fuel handling (обращение с ТВС), G=water/waste (водоснабжение)
    """)

    # --- Search existing record ---
    st.markdown("#### 🔍 Load Existing Record (Optional)" if lang == "en" else "#### 🔍 Загрузить существующую запись (опционально)")
    search_col1, search_col2, search_col3 = st.columns([2, 2, 1])

    with search_col1:
        search_system = st.text_input("System Name" if lang == "en" else "Название системы", key="search_sys", placeholder="e.g., Feedwater")
    with search_col2:
        search_component = st.text_input("Component Tag" if lang == "en" else "Тег компонента", key="search_comp", placeholder="e.g., Pump-001")
    with search_col3:
        st.markdown("<br>", unsafe_allow_html=True)
        load_btn = st.button("🔎 Load" if lang == "en" else "🔎 Загрузить", use_container_width=True)

    # Pre-populate form if record found
    prefill = {}
    if load_btn and search_system and search_component:
        existing = get_registry_row(search_system, search_component)
        if existing:
            prefill = existing
            st.success(f"Loaded existing record: {existing.get('system_kks', 'N/A')}" if lang == "en" else f"Загружена существующая запись: {existing.get('system_kks', 'Н/Д')}")
        else:
            st.info("No existing record found. A new record will be created on submit." if lang == "en" else "Запись не найдена. Будет создана новая запись.")

    st.markdown("---")

    # --- Entry Form ---
    st.markdown("#### ✏️ Record Details" if lang == "en" else "#### ✏️ Детали записи")

    with st.form("manual_update", clear_on_submit=False):
        col_a, col_b = st.columns(2)

        with col_a:
            sys_name = st.text_input(
                "System Name *" if lang == "en" else "Название системы *", 
                value=prefill.get('system', ''),
                help="Name of the system this component belongs to" if lang == "en" else "Название системы, к которой относится компонент"
            )
            kks_code = st.text_input(
                "KKS Code *" if lang == "en" else "Код KKS *", 
                value=prefill.get('system_kks', ''),
                help="F0 (mandatory: 0,1,2,5,9) + F1F2F3 (3 letters). Example: 1JEA10, 0AAA01"
            )

        with col_b:
            comp_tag = st.text_input(
                "Component Tag *" if lang == "en" else "Тег компонента *", 
                value=prefill.get('component', ''),
                help="Unique component identifier" if lang == "en" else "Уникальный идентификатор компонента"
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
                "Detected Scope" if lang == "en" else "Определенный тип", 
                value=detected_scope,
                disabled=True,
                help=scope_details if scope_details else ("Auto-detected from KKS prefix" if lang == "en" else "Автоопределение по префиксу KKS")
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
                    family_ru = get_system_family_ru(kks_code[1:4])
                    if family:
                        st.info(f"📌 System Family: {family}" + (f" ({family_ru})" if family_ru else ""))
                # Check for room code
                if 'R' in kks_code[:6].upper():
                    room_valid, room_msg, _ = validate_room_code(kks_code)
                    if room_valid:
                        st.info(f"📌 Room Code: {room_msg}")
            else:
                st.error(f"❌ {msg}")

        st.markdown("---")
        st.markdown("#### 📋 Commissioning Milestones" if lang == "en" else "#### 📋 Этапы ввода в эксплуатацию")

        # Determine which milestones are active based on KKS
        is_equipment = (detected_scope == 'Equipment')
        is_room = (detected_scope == 'Room')

        ms_col1, ms_col2, ms_col3 = st.columns(3)

        with ms_col1:
            it_label = get_bilingual_label(MILESTONE_LABELS, "it_status", lang)
            it_stat = st.selectbox(
                it_label,
                ["Pending", "In Progress", "Completed", "Failed", "N/A"],
                index=["Pending", "In Progress", "Completed", "Failed", "N/A"].index(
                    prefill.get('it_status', 'Pending')
                ) if prefill.get('it_status') in ["Pending", "In Progress", "Completed", "Failed", "N/A"] else 0,
                disabled=is_room,
                help="N/A for Room scope" if lang == "en" else "Н/П для помещений"
            )
            pic_label = get_bilingual_label(MILESTONE_LABELS, "pic_status", lang)
            pic_stat = st.selectbox(
                pic_label,
                ["Pending", "In Progress", "Completed", "Failed", "N/A"],
                index=["Pending", "In Progress", "Completed", "Failed", "N/A"].index(
                    prefill.get('pic_status', 'Pending')
                ) if prefill.get('pic_status') in ["Pending", "In Progress", "Completed", "Failed", "N/A"] else 0,
                disabled=is_room,
                help="N/A for Room scope" if lang == "en" else "Н/П для помещений"
            )

        with ms_col2:
            ht_label = get_bilingual_label(MILESTONE_LABELS, "ht_status", lang)
            ht_stat = st.selectbox(
                ht_label,
                ["Pending", "In Progress", "Completed", "Failed", "N/A"],
                index=["Pending", "In Progress", "Completed", "Failed", "N/A"].index(
                    prefill.get('ht_status', 'Pending')
                ) if prefill.get('ht_status') in ["Pending", "In Progress", "Completed", "Failed", "N/A"] else 0,
                disabled=is_room,
                help="N/A for Room scope" if lang == "en" else "Н/П для помещений"
            )
            pt_label = get_bilingual_label(MILESTONE_LABELS, "pt_status", lang)
            pt_stat = st.selectbox(
                pt_label,
                ["N/A", "Pending", "In Progress", "Completed", "Failed"],
                index=0 if is_equipment or is_room else (
                    ["N/A", "Pending", "In Progress", "Completed", "Failed"].index(
                        prefill.get('pt_status', 'Pending')
                    ) if prefill.get('pt_status') in ["N/A", "Pending", "In Progress", "Completed", "Failed"] else 1
                ),
                disabled=is_equipment or is_room,
                help="N/A for Equipment and Room scope" if lang == "en" else "Н/П для оборудования и помещений"
            )

        with ms_col3:
            saw_label = get_bilingual_label(MILESTONE_LABELS, "saw_status", lang)
            saw_stat = st.selectbox(
                saw_label,
                ["N/A", "Pending", "In Progress", "Completed", "Failed"],
                index=0 if is_equipment or is_room else (
                    ["N/A", "Pending", "In Progress", "Completed", "Failed"].index(
                        prefill.get('saw_status', 'Pending')
                    ) if prefill.get('saw_status') in ["N/A", "Pending", "In Progress", "Completed", "Failed"] else 1
                ),
                disabled=is_equipment or is_room,
                help="N/A for Equipment and Room scope" if lang == "en" else "Н/П для оборудования и помещений"
            )

        comments = st.text_area(
            "Comments / Notes" if lang == "en" else "Комментарии / Примечания",
            value=prefill.get('comments', ''),
            placeholder="Enter any special notes, anomalies, KKS code context, or shift handover comments..." if lang == "en" else "Введите примечания, аномалии, контекст KKS или сменные комментарии..."
        )

      # Dependency warning
        if pic_stat != "Completed" and ht_stat == "Completed":
            warning_html = (
                '<div class="alert-box alert-warning">'
                '⚠️ <b>Dependency Warning / Предупреждение о зависимости:</b> HT is marked Completed but PIC is not. '
                'PIC must precede HT per commissioning procedure.<br>'
                'ГИ отмечено как Выполнено, но ПОМ не выполнено. ПОМ должна предшествовать ГИ.' 
                '</div>'
            )
            
            st.markdown(warning_html, unsafe_allow_html=True)

        st.markdown("---")
        submit_label = "💾 Submit Record" if lang == "en" else "💾 Сохранить запись"
        submitted = st.form_submit_button(submit_label, use_container_width=True, type="primary")

        if submitted:
            if not sys_name or not kks_code or not comp_tag:
                st.error("❌ Required fields missing: System Name, KKS Code, and Component Tag are mandatory." if lang == "en" else "❌ Обязательные поля отсутствуют: Название системы, Код KKS и Тег компонента обязательны.")
            else:
                # Validate KKS before submission
                valid, msg, scope = validate_kks(kks_code)
                if not valid:
                    st.error(f"❌ KKS Validation Failed: {msg}" if lang == "en" else f"❌ Ошибка проверки KKS: {msg}")
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
                        st.success("✅ Registry Updated Successfully!" if lang == "en" else "✅ Реестр успешно обновлен!")
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
    title = "📝 Natural Language Shift Note Parser" if lang == "en" else "📝 Парсер сменных записей на естественном языке"
    st.subheader(title)
    st.markdown("""
    Paste raw shift notes, field observations, or handover logs.
    The AI will extract structured commissioning data, validate KKS codes per Rooppur NPP rules,
    enforce scope rules, and flag any milestone dependency violations.

    Вставьте сменные записи, полевые наблюдения или журналы передачи смен.
    AI извлечет данные, проверит коды KKS, применит правила и отметит нарушения зависимостей.

    **Note:** The AI recognizes both English and Russian terminology.
    **Примечание:** AI распознает терминологию на английском и русском языках.
    """)

    notes_text = st.text_area(
        "Shift Notes" if lang == "en" else "Сменные записи",
        height=250,
        placeholder="Example: 1JEA10 feedwater pump AA001 IT completed. PIC in progress due to debris found in strainer. 0JEB20 condensate system HT passed, awaiting SAW scheduling. Room 1R101 cable shaft inspection done.\n\nПример: 1JEA10 питательный насос AA001 ИО выполнено. ПОМ в работе из-за мусора в фильтре. 0JEB20 конденсатная система ГИ пройдена, ожидает ПНР. Помещение 1R101 кабельный шахтный ствол проверен."
    )

    parse_label = "🔍 Parse & Validate" if lang == "en" else "🔍 Разобрать и проверить"
    if st.button(parse_label, type="primary", use_container_width=True) and notes_text.strip():
        with st.spinner("AI analyzing shift notes with Rooppur NPP KKS rules..." if lang == "en" else "AI анализирует сменные записи с правилами KKS Руппур..."):
            records, alerts = parse_shift_notes(notes_text)

        if records:
            st.success(f"✅ Extracted {len(records)} record(s) from shift notes." if lang == "en" else f"✅ Извлечено {len(records)} записей из сменных записей.")

            # Preview table
            preview_df = pd.DataFrame(records)
            st.subheader("📋 Extracted Records Preview" if lang == "en" else "📋 Предпросмотр извлеченных записей")
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
            commit_label = "💾 Commit All to Registry" if lang == "en" else "💾 Сохранить все в реестр"
            if st.button(commit_label, type="primary", use_container_width=True):
                success, all_msgs = upsert_registry_batch(records)
                st.success(f"✅ Committed {success}/{len(records)} records to registry." if lang == "en" else f"✅ Сохранено {success}/{len(records)} записей в реестр.")
                if success < len(records):
                    st.warning("Some records failed validation. Check logs above." if lang == "en" else "Некоторые записи не прошли проверку. Проверьте журнал выше.")
        else:
            st.error("❌ Could not extract any valid records from the provided notes." if lang == "en" else "❌ Не удалось извлечь действительные записи из предоставленных записей.")
            if alerts:
                for alert in alerts:
                    st.error(alert)

# =============================================================================
# TAB 5: REGISTRY EDITOR (Editable Data Grid)
# =============================================================================

with tab5:
    st.subheader("✏️ Registry Editor" if lang == "en" else "✏️ Редактор реестра")
    st.markdown("""
    Edit existing records directly in the data grid. Changes are validated before saving.
    Select rows to edit, or use the data editor to modify values inline.

    Редактируйте существующие записи непосредственно в таблице. Изменения проверяются перед сохранением.
    Выберите строки для редактирования или используйте редактор данных для изменения значений.
    """)

    df = load_registry_df()

    if df.empty:
        st.info("No data in registry yet. Use the Import or Manual tabs to add records." if lang == "en" else "В реестре пока нет данных. Используйте вкладки Импорт или Ручной ввод.")
    else:
        # --- Filter controls ---
        st.markdown("#### 🔍 Filter Records" if lang == "en" else "#### 🔍 Фильтр записей")
        filter_col1, filter_col2, filter_col3 = st.columns(3)

        with filter_col1:
            scope_filter = st.multiselect(
                "Scope Type" if lang == "en" else "Тип области",
                options=df['scope_type'].unique() if 'scope_type' in df.columns else [],
                default=[],
                key="editor_scope_filter"
            )
        with filter_col2:
            if 'system_kks' in df.columns:
                family_options = sorted(set([get_bilingual_system_family(kks) for kks in df['system_kks'] if isinstance(kks, str) and len(kks) >= 4]))
            else:
                family_options = []
            family_filter = st.multiselect(
                "System Family" if lang == "en" else "Системное семейство",
                options=family_options,
                default=[],
                key="editor_family_filter"
            )
        with filter_col3:
            status_filter = st.multiselect(
                "Status" if lang == "en" else "Статус",
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
                return get_bilingual_system_family(kks) in family_filter
            filtered_df = filtered_df[filtered_df['system_kks'].apply(family_matches)]
        if status_filter:
            # Filter by any milestone having the selected status
            mask = False
            for ms in MILESTONES:
                if ms in filtered_df.columns:
                    mask = mask | filtered_df[ms].isin(status_filter)
            if mask is not False:
                filtered_df = filtered_df[mask]

        st.markdown(f"**Showing {len(filtered_df)} of {len(df)} records**" if lang == "en" else f"**Показано {len(filtered_df)} из {len(df)} записей**")

        # --- Editable Data Grid ---
        st.markdown("---")
        st.markdown("#### ✏️ Edit Records Inline" if lang == "en" else "#### ✏️ Редактировать записи в таблице")

        # Prepare editable columns configuration
        column_config = {}
        editable_cols = ['system', 'system_kks', 'component', 'it_status', 'pic_status', 'ht_status', 'pt_status', 'saw_status', 'comments']

        for col in editable_cols:
            if col in filtered_df.columns:
                if col.endswith('_status'):
                    # Status columns: dropdown with valid statuses
                    column_config[col] = st.column_config.SelectboxColumn(
                        get_bilingual_label(MILESTONE_LABELS, col, lang) if col in MILESTONE_LABELS else col,
                        options=list(VALID_STATUSES),
                        help=f"Select status for {col}"
                    )
                elif col == 'system_kks':
                    column_config[col] = st.column_config.TextColumn(
                        "KKS Code" if lang == "en" else "Код KKS",
                        help="F0 (mandatory) + F1F2F3 + Fn + A1 + An + Bn"
                    )
                elif col == 'scope_type':
                    column_config[col] = st.column_config.TextColumn(
                        "Scope" if lang == "en" else "Тип",
                        disabled=True,
                        help="Auto-detected from KKS code"
                    )
                elif col == 'comments':
                    column_config[col] = st.column_config.TextColumn(
                        "Comments" if lang == "en" else "Комментарии",
                        width="large"
                    )
                else:
                    column_config[col] = st.column_config.TextColumn(col)

        # Hide non-editable columns
        display_cols = [c for c in editable_cols if c in filtered_df.columns]
        # Add scope_type if present but disabled
        if 'scope_type' in filtered_df.columns and 'scope_type' not in display_cols:
            display_cols.insert(2, 'scope_type')
            column_config['scope_type'] = st.column_config.TextColumn(
                "Scope" if lang == "en" else "Тип",
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
            num_rows="fixed",  # Don't allow adding rows here; use Manual tab for new records
        )

        # --- Detect and show changes ---
        st.markdown("---")

        # Check for changes using session state
        if editor_key in st.session_state:
            editor_state = st.session_state[editor_key]

            changes_detected = False

            # Check edited rows
            if "edited_rows" in editor_state and editor_state["edited_rows"]:
                changes_detected = True
                edited_count = len(editor_state["edited_rows"])
                st.markdown(f"#### 📝 Changes Detected ({edited_count} rows edited)" if lang == "en" else f"#### 📝 Обнаружены изменения ({edited_count} строк отредактировано)")

                with st.expander("View Changes / Просмотр изменений", expanded=True):
                    for idx, changes in editor_state["edited_rows"].items():
                        original_row = filtered_df.iloc[int(idx)]
                        st.markdown(f"**Row {idx}:** `{original_row.get('system_kks', 'N/A')}` / `{original_row.get('component', 'N/A')}`")
                        for col, new_val in changes.items():
                            old_val = original_row.get(col, 'N/A')
                            st.markdown(f"  - `{col}`: `{old_val}` → `{new_val}`")

            # Check deleted rows
            if "deleted_rows" in editor_state and editor_state["deleted_rows"]:
                changes_detected = True
                deleted_count = len(editor_state["deleted_rows"])
                st.warning(f"⚠️ {deleted_count} row(s) marked for deletion. Use database admin to delete." if lang == "en" else f"⚠️ {deleted_count} строк(и) отмечены для удаления. Используйте администратора БД.")

            # Save changes button
            if changes_detected:
                st.markdown("---")
                save_label = "💾 Save Changes to Database" if lang == "en" else "💾 Сохранить изменения в базе данных"
                if st.button(save_label, type="primary", use_container_width=True):
                    saved_count = 0
                    error_count = 0

                    with st.spinner("Saving changes..." if lang == "en" else "Сохранение изменений..."):
                        for idx, changes in editor_state["edited_rows"].items():
                            # Reconstruct full record
                            original_row = filtered_df.iloc[int(idx)].to_dict()
                            updated_row = original_row.copy()
                            updated_row.update(changes)

                            # Validate before saving
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
                                    st.error(f"Validation error for row {idx}: {issue}" if lang == "en" else f"Ошибка проверки для строки {idx}: {issue}")

                    if saved_count > 0:
                        st.success(f"✅ Saved {saved_count} record(s) successfully!" if lang == "en" else f"✅ Успешно сохранено {saved_count} записей!")
                    if error_count > 0:
                        st.error(f"❌ {error_count} record(s) failed to save. Check errors above." if lang == "en" else f"❌ {error_count} записей не удалось сохранить. Проверьте ошибки выше.")

                    # Clear editor state after save
                    if saved_count > 0 and error_count == 0:
                        st.session_state[editor_key] = {}
                        st.rerun()
            else:
                st.info("No changes detected. Edit cells in the table above to make changes." if lang == "en" else "Изменения не обнаружены. Отредактируйте ячейки в таблице выше.")
        else:
            st.info("Edit cells in the table above to make changes. Changes will be validated before saving." if lang == "en" else "Отредактируйте ячейки в таблице выше. Изменения будут проверены перед сохранением.")

        # --- Row selection for detailed edit ---
        st.markdown("---")
        st.markdown("#### 🔍 Select Row for Detailed Edit" if lang == "en" else "#### 🔍 Выберите строку для детального редактирования")

        # Use dataframe with selection
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
            st.markdown(f"#### ✏️ Editing: `{selected_row.get('system_kks', 'N/A')}` / `{selected_row.get('component', 'N/A')}`")

            with st.form("inline_edit_form"):
                edit_col1, edit_col2 = st.columns(2)

                with edit_col1:
                    edit_system = st.text_input(
                        "System Name" if lang == "en" else "Название системы",
                        value=selected_row.get('system', '')
                    )
                    edit_kks = st.text_input(
                        "KKS Code" if lang == "en" else "Код KKS",
                        value=selected_row.get('system_kks', '')
                    )

                with edit_col2:
                    edit_component = st.text_input(
                        "Component Tag" if lang == "en" else "Тег компонента",
                        value=selected_row.get('component', '')
                    )
                    edit_scope = st.text_input(
                        "Scope (auto)" if lang == "en" else "Тип (авто)",
                        value=selected_row.get('scope_type', ''),
                        disabled=True
                    )

                # Milestone editors
                st.markdown("#### 📋 Milestones" if lang == "en" else "#### 📋 Этапы")
                ms_edit_col1, ms_edit_col2, ms_edit_col3 = st.columns(3)

                scope = selected_row.get('scope_type', '')
                is_equipment_edit = (scope == 'Equipment')
                is_room_edit = (scope == 'Room')

                with ms_edit_col1:
                    edit_it = st.selectbox(
                        get_bilingual_label(MILESTONE_LABELS, "it_status", lang),
                        list(VALID_STATUSES),
                        index=list(VALID_STATUSES).index(selected_row.get('it_status', 'Pending')) if selected_row.get('it_status') in VALID_STATUSES else 0,
                        disabled=is_room_edit
                    )
                    edit_pic = st.selectbox(
                        get_bilingual_label(MILESTONE_LABELS, "pic_status", lang),
                        list(VALID_STATUSES),
                        index=list(VALID_STATUSES).index(selected_row.get('pic_status', 'Pending')) if selected_row.get('pic_status') in VALID_STATUSES else 0,
                        disabled=is_room_edit
                    )

                with ms_edit_col2:
                    edit_ht = st.selectbox(
                        get_bilingual_label(MILESTONE_LABELS, "ht_status", lang),
                        list(VALID_STATUSES),
                        index=list(VALID_STATUSES).index(selected_row.get('ht_status', 'Pending')) if selected_row.get('ht_status') in VALID_STATUSES else 0,
                        disabled=is_room_edit
                    )
                    edit_pt = st.selectbox(
                        get_bilingual_label(MILESTONE_LABELS, "pt_status", lang),
                        list(VALID_STATUSES),
                        index=list(VALID_STATUSES).index(selected_row.get('pt_status', 'N/A')) if selected_row.get('pt_status') in VALID_STATUSES else 0,
                        disabled=is_equipment_edit or is_room_edit
                    )

                with ms_edit_col3:
                    edit_saw = st.selectbox(
                        get_bilingual_label(MILESTONE_LABELS, "saw_status", lang),
                        list(VALID_STATUSES),
                        index=list(VALID_STATUSES).index(selected_row.get('saw_status', 'N/A')) if selected_row.get('saw_status') in VALID_STATUSES else 0,
                        disabled=is_equipment_edit or is_room_edit
                    )

                edit_comments = st.text_area(
                    "Comments" if lang == "en" else "Комментарии",
                    value=selected_row.get('comments', '')
                )

                # Dependency check
                if edit_pic != "Completed" and edit_ht == "Completed":
                    st.warning("⚠️ Dependency Warning: PIC must precede HT" if lang == "en" else "⚠️ Предупреждение: ПОМ должна предшествовать ГИ")

                update_label = "💾 Update Record" if lang == "en" else "💾 Обновить запись"
                if st.form_submit_button(update_label, type="primary", use_container_width=True):
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
                        st.success("✅ Record updated successfully!" if lang == "en" else "✅ Запись успешно обновлена!")
                        st.rerun()
                    else:
                        for msg in msgs:
                            st.error(msg)

# =============================================================================
# TAB 6: KKS REFERENCE
# =============================================================================

with tab6:
    st.subheader("📖 Rooppur NPP KKS Coding Reference" if lang == "en" else "📖 Справочник кодирования KKS Руппур")
    st.markdown("*Based on document RPR-QM-AEB0001 Revision B05 (2017)*")
    st.markdown("*На основе документа RPR-QM-AEB0001 Редакция B05 (2017)*")

    st.markdown("---")

    # F0 Prefixes - sorted by selected language
    st.markdown("#### F0 Prefix (Mandatory) / F0 Префикс (Обязательный)")
    if sort_by == "russian":
        sorted_f0 = sort_by_russian(F0_PREFIXES)
    else:
        sorted_f0 = sort_by_english(F0_PREFIXES)

    f0_data = []
    for k, v in sorted_f0:
        f0_data.append({
            "Prefix": k,
            "English": v["en"],
            "Русский": v["ru"],
        })
    f0_df = pd.DataFrame(f0_data)
    st.dataframe(f0_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # System Families - sorted by selected language
    st.markdown("#### System Families (F1 First Letter) / Системные семейства (F1 первая буква)")
    if sort_by == "russian":
        sorted_families = sort_by_russian(SYSTEM_FAMILY_CODES)
    else:
        sorted_families = sort_by_english(SYSTEM_FAMILY_CODES)

    family_data = []
    for k, v in sorted_families:
        family_data.append({
            "Family Code": k,
            "English": v["en"],
            "Русский": v["ru"],
        })
    family_df = pd.DataFrame(family_data)
    st.dataframe(family_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # A3 Codes - sorted by selected language
    st.markdown("#### A3 Alphabetic Codes / A3 Буквенные коды")
    if sort_by == "russian":
        sorted_a3 = sort_by_russian(A3_CODES)
    else:
        sorted_a3 = sort_by_english(A3_CODES)

    a3_data = []
    for k, v in sorted_a3:
        a3_data.append({
            "Code": k,
            "English": v["en"],
            "Русский": v["ru"],
        })
    a3_df = pd.DataFrame(a3_data)
    st.dataframe(a3_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Room Shaft Codes - sorted by selected language
    st.markdown("#### Room Shaft Codes (Special) / Коды шахтных стволов (Специальные)")
    if sort_by == "russian":
        sorted_shafts = sort_by_russian(ROOM_SHAFT_CODES)
    else:
        sorted_shafts = sort_by_english(ROOM_SHAFT_CODES)

    shaft_data = []
    for k, v in sorted_shafts:
        shaft_data.append({
            "Code": k + "NN",
            "English": v["en"],
            "Русский": v["ru"],
        })
    shaft_df = pd.DataFrame(shaft_data)
    st.dataframe(shaft_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Milestone Labels - sorted by selected language
    st.markdown("#### Commissioning Milestones / Этапы ввода в эксплуатацию")
    if sort_by == "russian":
        sorted_ms = sort_by_russian(MILESTONE_LABELS)
    else:
        sorted_ms = sort_by_english(MILESTONE_LABELS)

    ms_data = []
    for k, v in sorted_ms:
        ms_data.append({
            "Code": k.replace('_status', '').upper(),
            "English": v["en"],
            "Русский": v["ru"],
        })
    ms_df = pd.DataFrame(ms_data)
    st.dataframe(ms_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Status Labels
    st.markdown("#### Status Values / Значения статусов")
    status_data = []
    for k, v in STATUS_LABELS.items():
        status_data.append({
            "Code": k,
            "English": v["en"],
            "Русский": v["ru"],
        })
    status_df = pd.DataFrame(status_data)
    st.dataframe(status_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # KKS Structure
    st.markdown("#### KKS Code Structure / Структура кода KKS")
    st.markdown("""
    ```
    F0 + F1F2F3 + Fn + A1 + An + Bn

    F0  = Prefix (MANDATORY / ОБЯЗАТЕЛЬНЫЙ)
          0 = Common station / Общестанционные
          1 = Unit 1 / Safety train / Блок 1 / Система безопасности
          2 = Unit 2 / Safety train / Блок 2 / Система безопасности
          5 = HVAC from NO diesel-generator / ОВиК от дизель-генератора НЭ
          9 = Temporary installations / Временные установки

    F1F2F3 = Functional system (3 letters / 3 буквы)
             A = Networks/Switchgears / Сети/РУ
             B = Power transmission/Auxiliary supply / Передача энергии/Вспомогательное питание
             C = I&C equipment / КИПиА
             E = Fuel/Waste / Топливо/Отходы
             F = Nuclear fuel handling / Обращение с ядерным топливом
             G = Water supply/Waste removal / Водоснабжение/Удаление отходов

    Fn  = 00-99
    A1  = Equipment unit letter / Буква единицы оборудования
    An  = 001-999 (per Appendix B / по Приложению Б)
    Bn  = 01-99 component / компонент
    ```
    """)

    st.markdown("---")
    st.markdown("**Limitation / Ограничение:** Equipment unit numbering validation (001-900) requires Appendix B which is not fully detailed in the provided context. Codes outside this range will generate warnings.")
    st.markdown("**Ограничение:** Проверка нумерации единиц оборудования (001-900) требует Приложения Б, которое не полностью детализировано в предоставленном контексте. Коды за пределами этого диапазона будут генерировать предупреждения.")
