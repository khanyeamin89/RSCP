import streamlit as st
import pandas as pd
import plotly.express as px

from config import PAGE_TITLE, PAGE_ICON, MILESTONES, MILESTONE_LABELS, SCOPE_MILESTONES, \
    STATUS_OPTIONS, apply_custom_css, badge_html
from database import load_registry, upsert_registry_row, delete_registry_row, load_uploaded_files, \
    get_file_download_url, load_kks_glossary, upsert_kks_glossary_row
from ai_engine import process_file_smart, parse_shift_note, get_kks_scope

st.set_page_config(page_title=PAGE_TITLE, layout="wide", page_icon=PAGE_ICON)
apply_custom_css()

st.markdown(f"# {PAGE_ICON} {PAGE_TITLE}")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Analytics Dashboard",
    "📥 Data Import & Sync",
    "🛠️ Manual/Field Updates",
    "📝 Shift Note Parser",
    "📖 KKS Reference",
])

# =============================================================================
# TAB 1 — ANALYTICS
# =============================================================================
with tab1:
    df = load_registry()

    if df.empty:
        st.info("💡 The registry is empty. Import a file or add a record in the other tabs to get started.")
    else:
        def progress_pct(row):
            applicable = SCOPE_MILESTONES.get(row["scope_type"], [])
            if not applicable:
                return 0.0
            completed = sum(1 for m in applicable if row.get(f"{m}_status") == "Completed")
            return round(100 * completed / len(applicable), 1)

        # Overall Progress previously only checked it_status, ignoring PIC/HT/PT/SAW
        # entirely. This now averages completion across every milestone that's
        # actually applicable to each record's scope.
        df["progress_pct"] = df.apply(progress_pct, axis=1)

        col1, col2, col3 = st.columns(3)
        col1.metric("Systems Tracked", len(df[df["scope_type"] == "System"]))
        col2.metric("Equipment Tracked", len(df[df["scope_type"] == "Equipment"]))
        col3.metric("Overall Progress", f"{df['progress_pct'].mean():.1f}%")

        st.markdown("###")
        chart_col, matrix_col = st.tabs(["📈 Milestone Distribution", "🧩 Status Matrix"])

        with chart_col:
            melted = df.melt(
                id_vars=["system", "component", "scope_type"],
                value_vars=[f"{m}_status" for m in MILESTONES],
                var_name="milestone", value_name="status",
            )
            melted["milestone"] = melted["milestone"].str.replace("_status", "", regex=False).str.upper()
            fig = px.histogram(
                melted, x="milestone", color="status", barmode="stack",
                category_orders={"milestone": [m.upper() for m in MILESTONES]},
                title="Milestone Status Distribution (all records)",
            )
            st.plotly_chart(fig, use_container_width=True)

        with matrix_col:
            # The badge-verified/progress/pending/failed CSS classes in config.py
            # were defined but never used anywhere — this is what they were for.
            search = st.text_input("🔍 Filter by system or component", "")
            view = df.copy()
            if search.strip():
                s = search.strip().lower()
                view = view[
                    view["system"].str.lower().str.contains(s) |
                    view["component"].str.lower().str.contains(s)
                ]
            rows_html = []
            for _, r in view.sort_values(["system", "component"]).iterrows():
                cells = "".join(f"<td>{badge_html(r[f'{m}_status'])}</td>" for m in MILESTONES)
                rows_html.append(f"""
                <tr>
                    <td><b>{r['system']}</b><br><span style="color:#94a3b8;font-size:0.75rem;">{r['system_kks']}</span></td>
                    <td>{r['component']}</td>
                    <td>{r['scope_type']}</td>
                    {cells}
                    <td><b>{r['progress_pct']:.0f}%</b></td>
                </tr>""")
            header_cells = "".join(f"<th>{m.upper()}</th>" for m in MILESTONES)
            st.markdown(f"""
            <table class="status-table">
                <thead><tr><th>System</th><th>Component</th><th>Scope</th>{header_cells}<th>Progress</th></tr></thead>
                <tbody>{''.join(rows_html)}</tbody>
            </table>
            """, unsafe_allow_html=True)

        with st.expander("ℹ️ Milestone abbreviations"):
            for m in MILESTONES:
                st.markdown(f"- **{m.upper()}** — {MILESTONE_LABELS[m].split('–')[1].strip()}")

# =============================================================================
# TAB 2 — DATA IMPORT & SYNC
# =============================================================================
with tab2:
    st.subheader("Upload & Intelligent Import")
    st.caption("Files are stored in Supabase Storage and parsed by the AI engine (Groq). "
               "Re-uploading the same file skips chunks already processed.")

    uploaded = st.file_uploader("Upload Registry (.csv/.xlsx)", type=["csv", "xlsx"])
    if uploaded and st.button("Run Token-Efficient Sync"):
        with st.spinner("Processing file..."):
            result = process_file_smart(uploaded.getvalue(), uploaded.name)

        if result["records_saved"]:
            st.success(f"✅ Sync complete — {result['records_saved']} records saved "
                       f"({result['chunks_skipped']} chunks already up to date).")
        else:
            st.warning("No records were saved. See details below if any.")

        for alert in result["alerts"]:
            st.warning(alert)

    files_df = load_uploaded_files()
    if not files_df.empty:
        st.markdown("**Previously uploaded files**")
        for _, f in files_df.iterrows():
            url = get_file_download_url(f["storage_path"])
            label = f"{f['file_name']} — {f['rows_imported']} rows ({str(f['uploaded_at'])[:16]})"
            st.markdown(f"[{label}]({url})" if url else label)

# =============================================================================
# TAB 3 — MANUAL / FIELD UPDATES
# =============================================================================
with tab3:
    reg_for_edit = load_registry()

    edit_mode, bulk_mode, delete_mode = st.tabs(["✏️ Add / Edit One Record", "📋 Bulk Edit Table", "🗑️ Delete a Record"])

    # --- Add / edit a single record, with an option to load an existing one ---
    with edit_mode:
        st.caption("Pick an existing record to edit it, or leave as 'New record' to add one. "
                   "Scope is auto-detected from the KKS code but you can override it.")

        existing_keys = []
        if not reg_for_edit.empty:
            existing_keys = (reg_for_edit["system"] + " — " + reg_for_edit["component"]).tolist()
        pick = st.selectbox("Record", ["— New record —"] + existing_keys, key="edit_pick")

        sel_row = None
        if pick != "— New record —":
            sel_row = reg_for_edit.iloc[existing_keys.index(pick)]

        sys_kks_preview = st.text_input("KKS Code", value=sel_row["system_kks"] if sel_row is not None else "", key="kks_preview")
        detected_scope = get_kks_scope(sys_kks_preview) if sys_kks_preview else "Equipment"

        with st.form("manual_update"):
            sys_name = st.text_input("System Name", value=sel_row["system"] if sel_row is not None else "")
            comp = st.text_input("Component Tag", value=sel_row["component"] if sel_row is not None else "")
            default_scope = sel_row["scope_type"] if sel_row is not None else detected_scope
            scope = st.selectbox("Scope", ["System", "Equipment"],
                                  index=0 if default_scope == "System" else 1,
                                  help="Auto-detected from the KKS code above; change if needed.")

            applicable = SCOPE_MILESTONES[scope]
            status_vals = {}
            cols = st.columns(len(MILESTONES))
            for i, m in enumerate(MILESTONES):
                with cols[i]:
                    if m in applicable:
                        default_status = sel_row[f"{m}_status"] if sel_row is not None and sel_row[f"{m}_status"] in STATUS_OPTIONS else "Pending"
                        status_vals[m] = st.selectbox(m.upper(), STATUS_OPTIONS, index=STATUS_OPTIONS.index(default_status), key=f"man_{m}")
                    else:
                        st.selectbox(m.upper(), ["N/A"], index=0, disabled=True, key=f"man_{m}_na")
                        status_vals[m] = "N/A"

            comments = st.text_area("Comments", value=sel_row["comments"] if sel_row is not None else "")

            if st.form_submit_button("Save Record"):
                if not sys_name or not comp:
                    st.error("System Name and Component Tag are required (they're the upsert key).")
                else:
                    row = {
                        "system": sys_name, "system_kks": sys_kks_preview, "scope_type": scope,
                        "component": comp, "comments": comments,
                        "source": sel_row["source"] if sel_row is not None else "Manual Entry",
                    }
                    for m in MILESTONES:
                        row[f"{m}_status"] = status_vals[m]
                    upsert_registry_row(row)
                    st.success("Saved.")
                    st.rerun()

    # --- Bulk inline grid edit ---
    with bulk_mode:
        st.caption("Edit statuses/comments directly in the table, then save. System, KKS, Component, and "
                   "Scope are locked here to protect the record key — use 'Add / Edit One Record' to change those.")
        if reg_for_edit.empty:
            st.info("Registry is empty.")
        else:
            editable_cols = [f"{m}_status" for m in MILESTONES] + ["comments"]
            locked_cols = ["system", "system_kks", "scope_type", "component", "milestone_id", "source", "last_updated"]
            display_cols = ["system", "system_kks", "scope_type", "component"] + editable_cols

            column_config = {f"{m}_status": st.column_config.SelectboxColumn(m.upper(), options=STATUS_OPTIONS) for m in MILESTONES}
            for c in ["system", "system_kks", "scope_type", "component"]:
                column_config[c] = st.column_config.TextColumn(c, disabled=True)

            edited = st.data_editor(
                reg_for_edit[display_cols], use_container_width=True, hide_index=True,
                num_rows="fixed", column_config=column_config, key="bulk_editor",
            )

            if st.button("💾 Save Changes"):
                changed = 0
                for i in range(len(reg_for_edit)):
                    orig = reg_for_edit.iloc[i]
                    new = edited.iloc[i]
                    if any(orig[c] != new[c] for c in editable_cols):
                        row = {c: orig[c] for c in locked_cols if c in orig}
                        row["system"] = orig["system"]
                        row["component"] = orig["component"]
                        row["system_kks"] = orig["system_kks"]
                        row["scope_type"] = orig["scope_type"]
                        for c in editable_cols:
                            row[c] = new[c]
                        upsert_registry_row(row)
                        changed += 1
                if changed:
                    st.success(f"Saved {changed} changed record(s).")
                    st.rerun()
                else:
                    st.info("No changes detected.")

    # --- Delete ---
    with delete_mode:
        st.caption("Deletes a record permanently — this can't be undone.")
        if reg_for_edit.empty:
            st.info("Registry is empty.")
        else:
            del_keys = (reg_for_edit["system"] + " — " + reg_for_edit["component"]).tolist()
            del_pick = st.selectbox("Record to delete", del_keys, key="del_pick")
            confirm = st.checkbox("I understand this permanently deletes the record.")
            if st.button("🗑️ Delete Record", disabled=not confirm):
                del_row = reg_for_edit.iloc[del_keys.index(del_pick)]
                delete_registry_row(del_row["system"], del_row["component"])
                st.success(f"Deleted '{del_pick}'.")
                st.rerun()

# =============================================================================
# TAB 4 — SHIFT NOTE PARSER
# =============================================================================
with tab4:
    st.subheader("Parse a Shift/Field Note")
    st.caption("Paste a free-text note — in English, Russian, or mixed. The AI extracts a "
               "structured update, but nothing saves until you review and confirm it below.")

    note_text = st.text_area(
        "Shift note",
        placeholder="e.g., JAA reactor vessel: flushing complete, hydro test in progress today. "
                    "Выполнено индивидуальное испытание клапана 12KAA20AA801.",
        height=120,
    )

    if st.button("Parse Note") and note_text.strip():
        with st.spinner("Parsing..."):
            result = parse_shift_note(note_text)
        st.session_state["staged_note_records"] = result["records"]
        st.session_state["staged_note_alerts"] = result["alerts"]

    if "staged_note_records" in st.session_state:
        for alert in st.session_state.get("staged_note_alerts", []):
            st.warning(alert)

        records = st.session_state["staged_note_records"]
        if not records:
            st.info("Nothing was extracted from that note. Try rephrasing, or use the Manual tab instead.")
        else:
            st.markdown(f"#### Review {len(records)} extracted record(s)")
            for idx, rec in enumerate(records):
                with st.form(f"confirm_note_{idx}"):
                    st.markdown(f"**Record {idx + 1}**")
                    c1, c2 = st.columns(2)
                    with c1:
                        r_sys = st.text_input("System", value=rec.get("system", ""), key=f"note_sys_{idx}")
                        r_kks = st.text_input("KKS Code", value=rec.get("system_kks", ""), key=f"note_kks_{idx}")
                    with c2:
                        r_comp = st.text_input("Component", value=rec.get("component", ""), key=f"note_comp_{idx}")
                        r_scope = st.selectbox("Scope", ["System", "Equipment"],
                                                index=0 if rec.get("scope_type") == "System" else 1,
                                                key=f"note_scope_{idx}")

                    applicable = SCOPE_MILESTONES[r_scope]
                    m_cols = st.columns(len(MILESTONES))
                    m_vals = {}
                    for i, m in enumerate(MILESTONES):
                        with m_cols[i]:
                            if m in applicable:
                                default = rec.get(f"{m}_status") if rec.get(f"{m}_status") in STATUS_OPTIONS else "Pending"
                                m_vals[m] = st.selectbox(m.upper(), STATUS_OPTIONS, index=STATUS_OPTIONS.index(default), key=f"note_{m}_{idx}")
                            else:
                                st.selectbox(m.upper(), ["N/A"], index=0, disabled=True, key=f"note_{m}_na_{idx}")
                                m_vals[m] = "N/A"

                    r_comments = st.text_area("Comments", value=rec.get("comments", ""), key=f"note_comm_{idx}")

                    if st.form_submit_button("Confirm & Save This Record"):
                        row = {
                            "system": r_sys, "system_kks": r_kks, "scope_type": r_scope,
                            "component": r_comp, "comments": r_comments, "source": "Shift Note Parser",
                        }
                        for m in MILESTONES:
                            row[f"{m}_status"] = m_vals[m]
                        upsert_registry_row(row)
                        st.success(f"Saved record {idx + 1}.")

            if st.button("Discard All"):
                del st.session_state["staged_note_records"]
                st.session_state.pop("staged_note_alerts", None)
                st.rerun()

# =============================================================================
# TAB 5 — KKS REFERENCE
# =============================================================================
with tab5:
    st.subheader("KKS Code Reference")
    st.caption("The 'In Your Registry' table below is derived directly from records you've already "
               "imported or entered — nothing here is AI-guessed. The glossary underneath is yours to "
               "fill in and correct against your plant's official KKS documentation.")

    reg_df = load_registry()
    if not reg_df.empty:
        seen = reg_df[["system_kks", "system", "scope_type"]].drop_duplicates()
        seen = seen[seen["system_kks"] != ""]
        st.markdown("#### KKS Codes In Your Registry")
        if seen.empty:
            st.info("No KKS codes recorded yet.")
        else:
            st.dataframe(seen.sort_values("system_kks"), use_container_width=True, hide_index=True)
    else:
        st.info("Registry is empty — import or add records first to see codes here.")

    st.markdown("---")
    st.markdown("#### Editable Glossary")
    glossary_df = load_kks_glossary()

    search_g = st.text_input("🔍 Search glossary", "")
    view_g = glossary_df.copy()
    if search_g.strip() and not view_g.empty:
        s = search_g.strip().lower()
        view_g = view_g[
            view_g["kks_code"].str.lower().str.contains(s) |
            view_g["description"].fillna("").str.lower().str.contains(s)
        ]
    if not view_g.empty:
        st.dataframe(view_g[["kks_code", "description", "category"]], use_container_width=True, hide_index=True)
    else:
        st.caption("No glossary entries yet — add the first one below.")

    with st.form("kks_glossary_form"):
        st.markdown("**Add / Update a code**")
        g1, g2, g3 = st.columns([1, 2, 1])
        with g1:
            g_code = st.text_input("KKS Code", placeholder="e.g. JAA")
        with g2:
            g_desc = st.text_input("Description", placeholder="e.g. Reactor pressure vessel and reactor cavity")
        with g3:
            g_cat = st.selectbox("Category", ["System", "Equipment Function", "Building", "Other"])
        if st.form_submit_button("Save to Glossary"):
            if g_code.strip():
                upsert_kks_glossary_row(g_code, g_desc, g_cat)
                st.success(f"Saved '{g_code.upper()}' to glossary.")
                st.rerun()
            else:
                st.error("KKS Code is required.")
