from datetime import datetime
import pandas as pd
from config import get_supabase_client, MILESTONES

REGISTRY_COLUMNS = (
    ["system", "system_kks", "scope_type", "component"]
    + [f"{m.lower()}_status" for m in MILESTONES]
    + ["comments", "source", "last_updated"]
)


def load_registry() -> pd.DataFrame:
    """
    Fetch the full commissioning registry from Supabase.

    This function was imported by dashboard.py but never actually defined
    anywhere in the original code — that import would have raised an
    ImportError the moment the app started.
    """
    supabase = get_supabase_client()
    res = supabase.table("registry").select("*").order("system").execute()
    if not res.data:
        return pd.DataFrame(columns=REGISTRY_COLUMNS)
    df = pd.DataFrame(res.data)
    for col in REGISTRY_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df.fillna("")


def upsert_registry_row(row: dict):
    """UPSERT: if system+component exists, it merges automatically."""
    supabase = get_supabase_client()
    payload = dict(row)
    payload.setdefault("last_updated", datetime.now().isoformat())
    supabase.table("registry").upsert(payload, on_conflict="system,component").execute()


def check_chunk_exists(file_hash: str, chunk_index: int) -> bool:
    supabase = get_supabase_client()
    res = (
        supabase.table("processed_chunks")
        .select("id")
        .eq("file_hash", file_hash)
        .eq("chunk_index", chunk_index)
        .execute()
    )
    return len(res.data) > 0


def mark_chunk_done(file_hash: str, chunk_index: int):
    supabase = get_supabase_client()
    supabase.table("processed_chunks").insert(
        {"file_hash": file_hash, "chunk_index": chunk_index}
    ).execute()
