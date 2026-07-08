import streamlit as st
from supabase import create_client

@st.cache_resource
def get_supabase_client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

def upsert_registry_row(row: dict):
    supabase = get_supabase_client()
    # UPSERT: If system+component exists, it merges automatically
    supabase.table("registry").upsert(row, on_conflict="system,component").execute()

def check_chunk_exists(file_hash, chunk_index):
    res = get_supabase_client().table("processed_chunks").select("id")\
        .eq("file_hash", file_hash).eq("chunk_index", chunk_index).execute()
    return len(res.data) > 0

def mark_chunk_done(file_hash, chunk_index):
    get_supabase_client().table("processed_chunks").insert(
        {"file_hash": file_hash, "chunk_index": chunk_index}).execute()
