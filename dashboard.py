import streamlit as st
import pandas as pd
import plotly.express as px
from database import load_registry, upsert_registry_row
from ai_engine import process_file_smart

st.set_page_config(page_title="Reactor Shop Commissioning", layout="wide")

st.markdown("# ⚛️ Reactor Shop Commissioning Management")

# Tabs for workflow organization
tab1, tab2, tab3 = st.tabs(["📊 Analytics Dashboard", "📥 Data Import & Sync", "🛠️ Manual/Field Updates"])

with tab1:
    df = load_registry()
    if not df.empty:
        col1, col2, col3 = st.columns(3)
        col1.metric("Systems Tracked", len(df[df['scope_type']=='System']))
        col2.metric("Overall Progress", f"{df['it_status'].eq('Completed').mean()*100:.1f}%")
        
        st.subheader("Milestone Status Distribution")
        fig = px.histogram(df, x="it_status", color="scope_type", title="IT Status by Scope")
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Upload & Intelligent Import")
    uploaded = st.file_uploader("Upload Registry (.csv/.xlsx)", type=["csv", "xlsx"])
    if uploaded and st.button("Run Token-Efficient Sync"):
        with st.spinner("Processing file..."):
            process_file_smart(uploaded.getvalue(), uploaded.name)
            st.success("Sync Complete!")

with tab3:
    with st.form("manual_update"):
        st.subheader("Manual Record Update")
        sys = st.text_input("System Name")
        kks = st.text_input("KKS Code")
        comp = st.text_input("Component Tag")
        stat = st.selectbox("Status", ["Pending", "In Progress", "Completed", "Failed"])
        if st.form_submit_button("Submit"):
            upsert_registry_row({"system": sys, "system_kks": kks, "component": comp, "it_status": stat})
            st.success("Registry Updated")
