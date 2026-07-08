from datetime import datetime
import pandas as pd
from config import (
    supabase, BUCKET_NAME, REGISTRY_COLUMNS, COLS_DB_TO_PY, COLS_PY_TO_DB,
    TESTLOG_PY_TO_DB, TESTLOG_DB_TO_PY
)

def load_registry() -> pd.DataFrame:
    res = supabase.table("registry").select("*").order("system").execute()
    if not res.data:
        return pd.DataFrame(columns=REGISTRY_COLUMNS)
    df = pd.DataFrame(res.data).rename(columns=COLS_DB_TO_PY)
    for c in REGISTRY_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[REGISTRY_COLUMNS].fillna("")

def upsert_registry_row(py_row: dict):
    payload = {COLS_PY_TO_DB[k]: v for k, v in py_row.items() if k in COLS_PY_TO_DB}
    payload["last_updated"] = datetime.now().isoformat()
    supabase.table("registry").upsert(payload, on_conflict="system,component").execute()

def load_test_log() -> pd.DataFrame:
    res = supabase.table("test_log").select("*").order("timestamp", desc=True).execute()
    cols = list(TESTLOG_PY_TO_DB.keys())
    if not res.data:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(res.data).rename(columns=TESTLOG_DB_TO_PY)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols]

def insert_test_log_row(py_row: dict):
    payload = {TESTLOG_PY_TO_DB[k]: v for k, v in py_row.items() if k in TESTLOG_PY_TO_DB}
    supabase.table("test_log").insert(payload).execute()

def upload_file_to_storage(file_bytes: bytes, file_name: str) -> str:
    storage_path = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file_name}"
    supabase.storage.from_(BUCKET_NAME).upload(storage_path, file_bytes)
    return storage_path

def record_file_metadata(file_name: str, storage_path: str, rows_imported: int):
    supabase.table("uploaded_files").insert({
        "file_name": file_name, "storage_path": storage_path, "rows_imported": rows_imported,
    }).execute()

def load_uploaded_files() -> pd.DataFrame:
    res = supabase.table("uploaded_files").select("*").order("uploaded_at", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame(columns=["file_name", "storage_path", "uploaded_at", "rows_imported"])

def get_file_download_url(storage_path: str) -> str:
    res = supabase.storage.from_(BUCKET_NAME).create_signed_url(storage_path, 3600)
    return res.get("signedURL") or res.get("signed_url", "")
