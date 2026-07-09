"""
Reactor Shop Commissioning - Database Operations
=================================================
All Supabase interactions with validation, error handling, and transaction safety.

KKS Coding based on Rooppur NPP document RPR-QM-AEB0001 Revision B05 (2017)
"Agreement on Using the KKS Coding System" (VGB-B 105 E 2010, VGB-B 106 E 2004)
"""

import streamlit as st
from typing import Dict, List, Optional, Any, Tuple
from postgrest.exceptions import APIError

# Import from centralized config
from config import (
    get_supabase_client,
    validate_record,
    validate_kks,
    validate_f0,
    validate_room_code,
    validate_a3,
    get_kks_scope,
    get_system_family,
    validate_milestone_dependencies,
    REGISTRY_SCHEMA,
    REGISTRY_UNIQUE_KEYS,
    MILESTONES,
    MILESTONE_LABELS,
    F0_PREFIXES,
    A3_CODES,
    ROOM_SHAFT_CODES,
    SYSTEM_FAMILY_CODES,
    ScopeType,
)


# =============================================================================
# REGISTRY OPERATIONS
# =============================================================================

def load_registry() -> List[Dict[str, Any]]:
    """
    Loads all records from the registry table.
    Returns empty list on error (with UI notification).
    """
    try:
        supabase = get_supabase_client()
        response = supabase.table("registry").select("*").execute()
        return response.data if response.data else []
    except APIError as e:
        st.error(f"Database Error loading registry: {e.message}")
        return []
    except Exception as e:
        st.error(f"Unexpected error loading registry: {str(e)}")
        return []


def load_registry_df() -> "pd.DataFrame":
    """Loads registry as a pandas DataFrame for analytics."""
    import pandas as pd
    data = load_registry()
    if not data:
        return pd.DataFrame(columns=list(REGISTRY_SCHEMA.keys()))
    return pd.DataFrame(data)


def clear_registry() -> Tuple[bool, str]:
    """
    Clears ALL records from the registry table.
    Use with extreme caution - this is irreversible.

    Returns:
        (success: bool, message: str)
    """
    try:
        supabase = get_supabase_client()
        # Delete all records from registry table
        result = supabase.table("registry").delete().neq("system", "").execute()
        return True, "Registry cleared successfully. All records removed."
    except APIError as e:
        return False, f"Database error clearing registry: {e.message}"
    except Exception as e:
        return False, f"Unexpected error clearing registry: {str(e)}"


def upsert_registry_row(row: Dict[str, Any], skip_validation: bool = False) -> Tuple[bool, List[str]]:
    """
    Upserts a single row into the registry table with Rooppur NPP KKS validation.

    Args:
        row: The record dictionary to upsert
        skip_validation: If True, bypasses validation (use with caution)

    Returns:
        (success: bool, messages: list of info/warning/error strings)
    """
    messages = []

    # --- Step 1: Validate record structure ---
    if not skip_validation:
        is_valid, issues = validate_record(row)
        if not is_valid:
            for issue in issues:
                messages.append(f"VALIDATION ERROR: {issue}")
            st.error("Record validation failed. See details below.")
            for msg in messages:
                st.markdown(f'<div class="alert-box alert-error">{msg}</div>', unsafe_allow_html=True)
            return False, messages

    # --- Step 2: Additional Rooppur NPP KKS validation ---
    kks = row.get('system_kks', '')
    if kks:
        # Validate F0 (mandatory per Rooppur)
        if len(kks) >= 1:
            f0 = kks[0].upper()
            f0_valid, f0_msg = validate_f0(f0)
            if not f0_valid:
                messages.append(f"KKS F0 ERROR: {f0_msg}")
                st.error(f"KKS F0 ERROR: {f0_msg}")
                return False, messages
            else:
                messages.append(f"KKS INFO: {f0_msg}")

        # Validate system family
        if len(kks) >= 4:
            f1f2f3 = kks[1:4].upper()
            family = get_system_family(f1f2f3)
            if family:
                messages.append(f"KKS INFO: System family {f1f2f3[0]} = {family}")

        # Check for room code
        if 'R' in kks[:6].upper():
            room_valid, room_msg, _ = validate_room_code(kks)
            if room_valid:
                messages.append(f"KKS INFO: {room_msg}")

        # Check for A3 codes
        if len(kks) >= 8:
            for a3_code, a3_data in A3_CODES.items():
                if a3_code in kks[7:].upper():
                    messages.append(
                        f"KKS INFO: A3 code '{a3_code}' detected: {a3_data}"
                    )

    # --- Step 3: Check milestone dependencies ---
    dep_violations = validate_milestone_dependencies(row)
    if dep_violations:
        for v in dep_violations:
            messages.append(f"DEPENDENCY: {v}")
        st.warning("Milestone dependency warnings detected. Record will be saved, but review required.")
        for v in dep_violations:
            st.markdown(f'<div class="alert-box alert-warning">{v}</div>', unsafe_allow_html=True)

    # --- Step 4: Ensure all schema fields exist (fill missing with defaults) ---
    clean_row = {}
    for field, field_type in REGISTRY_SCHEMA.items():
        val = row.get(field)
        if val is None:
            if field_type == str:
                clean_row[field] = ""
            else:
                clean_row[field] = None
        else:
            clean_row[field] = str(val) if field_type == str else val

    # --- Step 5: Execute upsert ---
    try:
        supabase = get_supabase_client()
        result = supabase.table("registry").upsert(
            clean_row, 
            on_conflict=",".join(REGISTRY_UNIQUE_KEYS)
        ).execute()

        messages.append(f"SUCCESS: Record upserted for '{row.get('system', 'Unknown')}' / '{row.get('component', 'Unknown')}'")
        return True, messages

    except APIError as e:
        err_msg = f"Database upsert failed: {e.message}"
        messages.append(f"ERROR: {err_msg}")
        st.error(err_msg)
        return False, messages
    except Exception as e:
        err_msg = f"Unexpected error during upsert: {str(e)}"
        messages.append(f"ERROR: {err_msg}")
        st.error(err_msg)
        return False, messages


def get_registry_row(system: str, component: str) -> Optional[Dict[str, Any]]:
    """Fetches a single record by system + component composite key."""
    try:
        supabase = get_supabase_client()
        result = supabase.table("registry").select("*").eq("system", system).eq("component", component).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        st.error(f"Error fetching record: {str(e)}")
        return None


# =============================================================================
# CHUNK TRACKING (Idempotent Processing)
# =============================================================================

def check_chunk_exists(file_hash: str, chunk_index: int) -> bool:
    """Checks if a file chunk has already been processed."""
    try:
        supabase = get_supabase_client()
        res = supabase.table("processed_chunks").select("id", count="exact").eq("file_hash", file_hash).eq("chunk_index", chunk_index).execute()
        return res.count > 0 if hasattr(res, 'count') else len(res.data) > 0
    except Exception as e:
        st.warning(f"Chunk check failed (assuming not processed): {str(e)}")
        return False


def mark_chunk_done(file_hash: str, chunk_index: int) -> bool:
    """Marks a file chunk as successfully processed."""
    try:
        supabase = get_supabase_client()
        supabase.table("processed_chunks").insert({
            "file_hash": file_hash,
            "chunk_index": chunk_index
        }).execute()
        return True
    except Exception as e:
        st.warning(f"Failed to mark chunk {chunk_index} as done: {str(e)}")
        return False


# =============================================================================
# BATCH OPERATIONS
# =============================================================================

def upsert_registry_batch(records: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
    """
    Batch upsert with per-record validation.
    Returns (success_count, list of all messages).
    """
    success_count = 0
    all_messages = []

    progress = st.progress(0)
    total = len(records)

    for i, record in enumerate(records):
        ok, msgs = upsert_registry_row(record)
        all_messages.extend(msgs)
        if ok:
            success_count += 1
        progress.progress((i + 1) / total)

    progress.empty()
    return success_count, all_messages
