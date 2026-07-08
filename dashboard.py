import altair as alt
from ai_engine import universal_ai_file_parser
from config import PAGE_ICON, PAGE_TITLE, apply_custom_css
from database import fetch_all_records_from_supabase, insert_records_to_supabase
import pandas as pd
import streamlit as st

# Initialize Page Environment Profile parameters
st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
apply_custom_css()

st.title("⚛️ Reactor Shop Commissioning & Loop Tracking Dashboard")
st.markdown(
    "Automated Nuclear KKS Parsing and Commissioning Telemetry Monitoring Framework"
)
st.markdown("---")

tab1, tab2 = st.tabs(
    [
        "🚀 Process New Logs / Documentation",
        "📊 Live Database Analytics & Monitoring",
    ]
)

# All columns now being managed inside our views
columns_order = [
    "tag_id",
    "system",
    "system_kks",
    "equipment_kks",
    "loop_number",
    "commissioning_stage",
    "description",
    "status",
    "test_remarks",
    "execution_date",
]

with tab1:
    st.subheader("Data Extraction Engine")
    st.markdown(
        "Upload system checklists, loop sheets, engineering printouts, or operational reports. "
        "System will extract KKS structures, commissioning stages, remarks, and execution dates automatically."
    )

    uploaded_file = st.file_uploader(
        "Drop operational file here",
        type=["txt", "log", "csv", "xlsx", "xls", "docx"],
        help="Supports logs, spreadsheets, and word formats.",
    )

    if uploaded_file is not None:
        st.success(
            f"File successfully loaded: **{uploaded_file.name}** ({len(uploaded_file.getvalue())} bytes)"
        )

        if st.button("🚀 Execute Cloud Extraction & DB Sync", type="primary"):
            file_bytes = uploaded_file.getvalue()
            file_name = uploaded_file.name

            # Core Ingestion Run
            extracted_data = universal_ai_file_parser(file_bytes, file_name)

            if extracted_data:
                st.markdown("### Previewing Processed Records Output")
                st.success(
                    f"Successfully processed {len(extracted_data)} structured database items!"
                )

                df_preview = pd.DataFrame(extracted_data)

                for col in columns_order:
                    if col not in df_preview.columns:
                        df_preview[col] = ""
                df_preview = df_preview[columns_order]

                st.dataframe(df_preview, use_container_width=True)

                with st.spinner(
                    "Executing transactional database sync to Supabase..."
                ):
                    db_success = insert_records_to_supabase(extracted_data)
                    if db_success:
                        st.success(
                            "Production database tables successfully updated and synchronized!"
                        )
                        if hasattr(st, "cache_data"):
                            st.cache_data.clear()
            else:
                st.error(
                    "AI parsing process completed but generated zero records. Verify data alignments inside your document."
                )

with tab2:
    st.subheader("Live Plant Component Status Tracking")

    raw_db_rows = fetch_all_records_from_supabase()

    if raw_db_rows:
        df_master = pd.DataFrame(raw_db_rows)
        for col in columns_order:
            if col not in df_master.columns:
                df_master[col] = ""

        # Analytical KPI block
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        total_items = len(df_master)
        verified_count = len(df_master[df_master["status"] == "Verified"])
        progress_count = len(df_master[df_master["status"] == "In Progress"])
        failed_count = len(df_master[df_master["status"] == "Failed精密"])

        m_col1.metric("Total Tracked Items", total_items)
        m_col2.metric(
            "Verified Checkpoints ✅",
            verified_count,
            delta=f"{int((verified_count/total_items)*100) if total_items else 0}% of total",
        )
        m_col3.metric("Operations In Progress ⏳", progress_count)
        m_col4.metric(
            "Non-Conformance/Failed ❌",
            len(df_master[df_master["status"] == "Failed"]),
            delta_color="inverse",
        )

        st.markdown("---")
        graph_col, filter_col = st.columns([2, 1])

        with graph_col:
            st.markdown("#### System Validation Distribution Status")
            status_counts = df_master["status"].value_counts().reset_index()
            status_counts.columns = ["Status", "Count"]

            status_chart = (
                alt.Chart(status_counts)
                .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                .encode(
                    x=alt.X(
                        "Status:N",
                        sort=["Verified", "In Progress", "Pending", "Failed"],
                        title="Validation State",
                    ),
                    y=alt.Y("Count:Q", title="Number of Equipment Components"),
                    color=alt.Color(
                        "Status:N",
                        scale=alt.Scale(
                            domain=[
                                "Verified",
                                "In Progress",
                                "Pending",
                                "Failed",
                            ],
                            range=["#10B981", "#EAB308", "#64748B", "#EF4444"],
                        ),
                        legend=None,
                    ),
                )
                .properties(height=260)
            )
            st.altair_chart(status_chart, use_container_width=True)

        with filter_col:
            st.markdown("#### Database View Search Filters")
            available_systems = sorted(list(df_master["system"].unique()))
            system_selection = st.multiselect(
                "Filter Display by Systems:",
                options=available_systems,
                default=available_systems,
            )
            search_query = st.text_input(
                "Search Component via Tag or KKS ID:",
                value="",
                placeholder="e.g. 10UJA",
            ).strip()

        # Filtering parameters check
        filtered_df = df_master[df_master["system"].isin(system_selection)]
        if search_query:
            filtered_df = filtered_df[
                filtered_df["tag_id"].str.contains(
                    search_query, case=False, na=False
                )
                | filtered_df["equipment_kks"].str.contains(
                    search_query, case=False, na=False
                )
                | filtered_df["system_kks"].str.contains(
                    search_query, case=False, na=False
                )
            ]

        st.markdown("---")
        st.markdown(f"Showing **{len(filtered_df)}** filtered record listings:")

        # Render complete layout table
        st.dataframe(filtered_df[columns_order], use_container_width=True)

        csv_data = filtered_df[columns_order].to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Export Current Filtered Table view to CSV",
            data=csv_data,
            file_name="rscp_commissioning_filtered_report.csv",
            mime="text/csv",
        )
    else:
        st.info(
            "No logs are currently stored in the Supabase database. Head over to the extraction tab to upload data sheets."
        )
