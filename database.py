"""
Database layer — the ONLY place that talks to Supabase.
config.py and ai_engine.py both import get_supabase_client from here rather
than creating their own, so the app only ever holds one cached connection.
"""
from datetime import datetime
import pandas as pd
import streamlit as st
from supabase import create_client, Client

from config import MILESTONES, BUCKET_NAME


@st.cache_resource
def get_supabase_client() -> Client:
    """
    Initializes and caches the connection to the Supabase backend.
    Fails loudly and stops the app if secrets are missing, rather than
    letting a cryptic exception surface later.
    """
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")

    if not url or not key:
        st.error(
            "CRITICAL ERROR: 'SUPABASE_URL' and 'SUPABASE_KEY' are missing from "
            "Streamlit Secrets. Application execution halted."
        )
        st.stop()

    try:
        return create_client(url, key)
    except Exception as init_error:
        st.error(f"Failed to establish Supabase client: {init_error}")
        st.stop()


REGISTRY_COLUMNS = (
    ["system", "system_kks", "scope_type", "component", "milestone_id"]
    + [f"{m}_status" for m in MILESTONES]
    + ["comments", "source", "last_updated"]
)

# =============================================================================
# REGISTRY
# =============================================================================
def load_registry() -> pd.DataFrame:
    """Fetches the full commissioning registry. Was missing entirely before —
    dashboard.py imported this and would crash on startup without it."""
    try:
        res = get_supabase_client().table("registry").select("*").order("system").execute()
    except Exception as exc:
        st.error(f"Couldn't load registry from Supabase: {exc}")
        return pd.DataFrame(columns=REGISTRY_COLUMNS)

    if not res.data:
        return pd.DataFrame(columns=REGISTRY_COLUMNS)

    df = pd.DataFrame(res.data)
    for c in REGISTRY_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df.fillna("")


def upsert_registry_row(row: dict):
    """UPSERT on (system, component). Stamps last_updated automatically so
    callers never forget to set it."""
    payload = dict(row)
    payload["last_updated"] = datetime.now().isoformat()
    try:
        get_supabase_client().table("registry").upsert(payload, on_conflict="system,component").execute()
    except Exception as exc:
        st.error(f"Failed to save record to Supabase: {exc}")


def delete_registry_row(system: str, component: str):
    """Deletes a single record identified by its (system, component) key."""
    try:
        get_supabase_client().table("registry").delete() \
            .eq("system", system).eq("component", component).execute()
    except Exception as exc:
        st.error(f"Failed to delete record: {exc}")


# =============================================================================
# TEST LOG
# =============================================================================
def load_test_log() -> pd.DataFrame:
    cols = ["timestamp", "system", "component", "test_type", "test_result", "severity", "resolved", "notes"]
    try:
        res = get_supabase_client().table("test_log").select("*").order("timestamp", desc=True).execute()
    except Exception as exc:
        st.error(f"Couldn't load test log: {exc}")
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(res.data) if res.data else pd.DataFrame(columns=cols)


def insert_test_log_row(row: dict):
    try:
        get_supabase_client().table("test_log").insert(row).execute()
    except Exception as exc:
        st.error(f"Failed to save test log entry: {exc}")


# =============================================================================
# UPLOADED FILES (Supabase Storage + metadata table)
# =============================================================================
def upload_file_to_storage(file_bytes: bytes, file_name: str) -> str | None:
    storage_path = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file_name}"
    try:
        get_supabase_client().storage.from_(BUCKET_NAME).upload(storage_path, file_bytes)
        return storage_path
    except Exception as exc:
        st.warning(f"File was processed but couldn't be saved to Storage: {exc}")
        return None


def record_file_metadata(file_name: str, storage_path: str, rows_imported: int):
    try:
        get_supabase_client().table("uploaded_files").insert({
            "file_name": file_name, "storage_path": storage_path, "rows_imported": rows_imported,
        }).execute()
    except Exception as exc:
        st.warning(f"Couldn't record file metadata: {exc}")


def load_uploaded_files() -> pd.DataFrame:
    try:
        res = get_supabase_client().table("uploaded_files").select("*").order("uploaded_at", desc=True).execute()
    except Exception:
        return pd.DataFrame(columns=["file_name", "storage_path", "uploaded_at", "rows_imported"])
    return pd.DataFrame(res.data) if res.data else pd.DataFrame(
        columns=["file_name", "storage_path", "uploaded_at", "rows_imported"]
    )


def get_file_download_url(storage_path: str) -> str:
    try:
        res = get_supabase_client().storage.from_(BUCKET_NAME).create_signed_url(storage_path, 3600)
        return res.get("signedURL") or res.get("signed_url", "")
    except Exception:
        return ""


# =============================================================================
# KKS GLOSSARY (user-maintained reference — see dashboard.py Tab 5 docstring
# for why this is editable-by-you rather than pre-filled by the AI)
# =============================================================================
def load_kks_glossary() -> pd.DataFrame:
    cols = ["kks_code", "description", "category", "last_updated"]
    try:
        res = get_supabase_client().table("kks_glossary").select("*").order("kks_code").execute()
    except Exception as exc:
        st.error(f"Couldn't load KKS glossary: {exc}")
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(res.data) if res.data else pd.DataFrame(columns=cols)


def upsert_kks_glossary_row(kks_code: str, description: str, category: str):
    payload = {
        "kks_code": kks_code.strip().upper(),
        "description": description,
        "category": category,
        "last_updated": datetime.now().isoformat(),
    }
    try:
        get_supabase_client().table("kks_glossary").upsert(payload, on_conflict="kks_code").execute()
    except Exception as exc:
        st.error(f"Failed to save glossary entry: {exc}")


# =============================================================================
# CHUNK DEDUP (so re-uploading the same file doesn't re-bill the LLM)
# =============================================================================
def check_chunk_exists(file_hash: str, chunk_index: int) -> bool:
    try:
        res = get_supabase_client().table("processed_chunks").select("id") \
            .eq("file_hash", file_hash).eq("chunk_index", chunk_index).execute()
        return len(res.data) > 0
    except Exception:
        # If the check itself fails, don't block processing — fail open.
        return False


def mark_chunk_done(file_hash: str, chunk_index: int):
    try:
        get_supabase_client().table("processed_chunks").insert(
            {"file_hash": file_hash, "chunk_index": chunk_index}
        ).execute()
    except Exception as exc:
        st.warning(f"Couldn't record chunk-processed marker: {exc}")
