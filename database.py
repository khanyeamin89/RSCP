"""
Reactor Shop Commissioning - Database Operations
=================================================
All Supabase interactions with validation, error handling, and transaction safety.

KKS Coding based on the Rooppur NPP Reactor Shop KKS Code Master List
(hard-coded in config.py — see config.py header for source documents).
"""

import streamlit as st
from typing import Dict, List, Optional, Any, Tuple
from postgrest.exceptions import APIError

# Import from centralized config
from config import (
    get_supabase_client,
    validate_record,
    parse_kks,
    validate_milestone_dependencies,
    REGISTRY_SCHEMA,
    REGISTRY_UNIQUE_KEYS,
    MILESTONES,
    MILESTONE_LABELS,
    MILESTONE_DATE_FIELDS,
    ScopeType,
    PPIA_LOG_SCHEMA,
    validate_ppia_entry,
    MILESTONE_HISTORY_SCHEMA,
    validate_milestone_history_entry,
)


# =============================================================================
# REGISTRY OPERATIONS
# =============================================================================

@st.cache_data(ttl=20, show_spinner=False)
def load_registry() -> List[Dict[str, Any]]:
    """
    Loads all records from the registry table.
    Returns empty list on error (with UI notification).

    Cached for 20s: Streamlit reruns the ENTIRE script (all 9 tabs' code,
    not just the visible tab) on every single interaction anywhere in the
    app. Without caching, load_registry_df() alone was firing 3+ fresh
    Supabase queries per click. Any write function below calls
    load_registry.clear() so edits still show up immediately.
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
        # Delete all records. `neq("system", "")` is used instead of an
        # unconditional delete because Supabase/PostgREST requires a filter
        # on delete; every row has a non-empty "system" value so this
        # matches (and removes) all of them.
        supabase.table("registry").delete().neq("system", "").execute()
        load_registry.clear()
        return True, "Registry cleared successfully. All records removed."
    except APIError as e:
        return False, f"Database error clearing registry: {e.message}"
    except Exception as e:
        return False, f"Unexpected error clearing registry: {str(e)}"


def _today_str() -> str:
    from datetime import date
    return date.today().isoformat()


def _build_history_events(existing_row: Optional[Dict[str, Any]], new_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Compares each milestone's (status, date) in the incoming row against what
    was already stored, and returns one history event per milestone that
    genuinely changed — a new status, a new date, or both. "Pending"/"N/A"/
    empty statuses are skipped since they aren't a completed test attempt,
    just the absence of one.

    If a status changed but no date was supplied, today's date is used as a
    fallback so the change is still placed correctly on the timeline (better
    than silently dropping it).
    """
    events: List[Dict[str, Any]] = []
    old = existing_row or {}

    for ms in MILESTONES:
        new_status = new_row.get(ms, "")
        if not new_status or new_status in ("Pending", "N/A", "Not Applicable"):
            continue

        old_status = old.get(ms, "")
        date_field = MILESTONE_DATE_FIELDS[ms]
        new_date = new_row.get(date_field, "") or ""
        old_date = old.get(date_field, "") or ""

        changed = (new_status != old_status) or (new_date and new_date != old_date)
        if changed:
            events.append({
                "system": new_row.get("system", ""),
                "system_kks": new_row.get("system_kks", ""),
                "component": new_row.get("component", ""),
                "milestone": ms,
                "status": new_status,
                "event_date": new_date or _today_str(),
                "comments": new_row.get("comments", ""),
                "source": "Registry Update",
            })

    return events


def upsert_registry_row(row: Dict[str, Any], skip_validation: bool = False) -> Tuple[bool, List[str]]:
    """
    Upserts a single row into the registry table with real Rooppur NPP KKS validation.

    Args:
        row: The record dictionary to upsert
        skip_validation: If True, bypasses validation (use with caution)

    Returns:
        (success: bool, messages: list of info/warning/error strings)
    """
    messages: List[str] = []

    # --- Step 1: Validate record structure (required fields, KKS, statuses, deps) ---
    if not skip_validation:
        is_valid, issues = validate_record(row)
        if not is_valid:
            for issue in issues:
                messages.append(f"VALIDATION ERROR: {issue}")
            st.error("Record validation failed. See details below.")
            for msg in messages:
                st.markdown(f'<div class="alert-box alert-error">{msg}</div>', unsafe_allow_html=True)
            return False, messages

    # --- Step 2: KKS detail parsing (single source of truth — config.parse_kks) ---
    kks = row.get("system_kks", "")
    if kks:
        parsed = parse_kks(kks)
        if parsed.valid:
            messages.append(f"KKS INFO: {parsed.message}")
            for alert in parsed.alerts:
                messages.append(f"KKS WARNING: {alert}")
            # Keep scope_type in sync with what was actually parsed.
            if parsed.scope:
                row["scope_type"] = parsed.scope.value
        else:
            # validate_record() above already caught truly invalid KKS codes
            # (skip_validation=False path); this branch only matters when
            # skip_validation=True was requested by the caller.
            messages.append(f"KKS ERROR: {parsed.message}")

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
            clean_row[field] = "" if field_type == str else None
        else:
            clean_row[field] = str(val) if field_type == str else val

    # --- Step 4.5: Diff against the existing row (if any) BEFORE overwriting,
    # so every genuine milestone change gets logged to history. Without this,
    # a retest simply overwrites the previous status+date and that attempt's
    # record is lost forever — see MILESTONE_HISTORY_SCHEMA in config.py.
    existing_row = get_registry_row(clean_row.get("system", ""), clean_row.get("component", ""))
    history_events = _build_history_events(existing_row, clean_row)

    # --- Step 5: Execute upsert ---
    try:
        supabase = get_supabase_client()
        supabase.table("registry").upsert(
            clean_row,
            on_conflict=",".join(REGISTRY_UNIQUE_KEYS)
        ).execute()

        messages.append(f"SUCCESS: Record upserted for '{row.get('system', 'Unknown')}' / '{row.get('component', 'Unknown')}'")
        load_registry.clear()

        # Log any milestone changes to history AFTER the upsert succeeds, so
        # we never record a history event for a save that didn't actually go through.
        for event in history_events:
            ok, hist_msgs = insert_milestone_history_entry(event)
            if ok:
                messages.append(
                    f"HISTORY: Logged {MILESTONE_LABELS.get(event['milestone'], event['milestone'])} "
                    f"= {event['status']} on {event['event_date'] or 'unknown date'}"
                )
            else:
                messages.extend(hist_msgs)

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
        return res.count > 0 if hasattr(res, 'count') and res.count is not None else len(res.data) > 0
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


def clear_processed_chunks(file_hash: Optional[str] = None) -> Tuple[bool, str]:
    """
    Clears chunk-tracking records so files can be re-imported from scratch.

    This is the missing piece behind "I cleared the registry but re-uploading
    the same file processes 0 records": clear_registry() only empties the
    `registry` table, not `processed_chunks`, so check_chunk_exists() keeps
    reporting every chunk of that file as already-done and skips it.

    Args:
        file_hash: If given, only clears chunks for that specific file
                   (its MD5 — the same value process_file_smart computes
                   internally via hashlib.md5(file_bytes).hexdigest()).
                   If None, clears the ENTIRE processed_chunks table.

    Returns:
        (success: bool, message: str)
    """
    try:
        supabase = get_supabase_client()
        if file_hash:
            supabase.table("processed_chunks").delete().eq("file_hash", file_hash).execute()
            return True, f"Cleared chunk cache for file hash '{file_hash}'. It can now be re-imported."
        else:
            # Same "match everything" trick as clear_registry(): PostgREST
            # requires a delete filter, and every row has a non-empty
            # file_hash, so neq("file_hash", "") matches (and removes) all.
            supabase.table("processed_chunks").delete().neq("file_hash", "").execute()
            return True, "Chunk cache cleared entirely. All previously-uploaded files can now be re-imported."
    except APIError as e:
        return False, f"Database error clearing chunk cache: {e.message}"
    except Exception as e:
        return False, f"Unexpected error clearing chunk cache: {str(e)}"


# =============================================================================
# BATCH OPERATIONS
# =============================================================================

def upsert_registry_batch(records: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
    """
    Batch upsert with per-record validation.
    Returns (success_count, list of all messages).
    """
    success_count = 0
    all_messages: List[str] = []

    if not records:
        return 0, ["INFO: No records to process."]

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


# =============================================================================
# PPIA LOG (Process Protection and Interlock Actuation)
# =============================================================================
# An append-only event log — separate table from `registry`, no unique-key
# upsert. Each protection/interlock actuation reported gets its own row.

@st.cache_data(ttl=20, show_spinner=False)
def load_ppia_log() -> List[Dict[str, Any]]:
    """Loads all records from the ppia_log table, most recent first."""
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("ppia_log")
            .select("*")
            .order("event_date", desc=True)
            .execute()
        )
        return response.data if response.data else []
    except APIError as e:
        st.error(f"Database Error loading PPIA log: {e.message}")
        return []
    except Exception as e:
        st.error(f"Unexpected error loading PPIA log: {str(e)}")
        return []


def load_ppia_log_df() -> "pd.DataFrame":
    """Loads the PPIA log as a pandas DataFrame."""
    import pandas as pd
    data = load_ppia_log()
    if not data:
        return pd.DataFrame(columns=list(PPIA_LOG_SCHEMA.keys()))
    return pd.DataFrame(data)


def insert_ppia_entry(entry: Dict[str, Any], skip_validation: bool = False) -> Tuple[bool, List[str]]:
    """
    Inserts a single PPIA log entry. Always inserts a new row (append-only —
    no unique-key upsert, since the same interlock can legitimately actuate
    more than once).

    Returns:
        (success: bool, messages: list of info/warning/error strings)
    """
    messages: List[str] = []

    if not skip_validation:
        is_valid, issues = validate_ppia_entry(entry)
        if not is_valid:
            for issue in issues:
                messages.append(f"VALIDATION ERROR: {issue}")
            return False, messages
        for issue in issues:
            if issue.startswith("KKS Note:"):
                messages.append(issue)

    clean_entry = {}
    for field, field_type in PPIA_LOG_SCHEMA.items():
        val = entry.get(field)
        if val is None:
            clean_entry[field] = "" if field_type == str else None
        else:
            clean_entry[field] = str(val) if field_type == str else val

    try:
        supabase = get_supabase_client()
        supabase.table("ppia_log").insert(clean_entry).execute()
        load_ppia_log.clear()
        messages.append(
            f"SUCCESS: PPIA event logged for '{entry.get('system_kks') or entry.get('system', 'Unknown')}'"
        )
        return True, messages
    except APIError as e:
        err_msg = f"Database insert failed: {e.message}"
        messages.append(f"ERROR: {err_msg}")
        st.error(err_msg)
        return False, messages
    except Exception as e:
        err_msg = f"Unexpected error during PPIA insert: {str(e)}"
        messages.append(f"ERROR: {err_msg}")
        st.error(err_msg)
        return False, messages


def insert_ppia_batch(entries: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
    """Batch insert of PPIA log entries. Returns (success_count, all_messages)."""
    success_count = 0
    all_messages: List[str] = []

    if not entries:
        return 0, ["INFO: No PPIA events to log."]

    for entry in entries:
        ok, msgs = insert_ppia_entry(entry)
        all_messages.extend(msgs)
        if ok:
            success_count += 1

    return success_count, all_messages


def update_ppia_entry(entry_id: Any, entry: Dict[str, Any], skip_validation: bool = False) -> Tuple[bool, List[str]]:
    """
    Updates an EXISTING PPIA log row by its database id — this is what makes
    the PPIA Log editable rather than append-only-insert-only. Unlike
    insert_ppia_entry, this modifies a specific already-saved row instead of
    always creating a new one.

    Args:
        entry_id: the row's primary key (from the "id" column Supabase
            auto-generates — present in every row load_ppia_log() returns)
        entry: the edited field values to save
        skip_validation: bypass validation (use with caution)

    Returns:
        (success: bool, messages: list of info/warning/error strings)
    """
    messages: List[str] = []

    if entry_id is None or entry_id == "":
        messages.append("ERROR: Cannot update a PPIA entry without its row id.")
        return False, messages

    if not skip_validation:
        is_valid, issues = validate_ppia_entry(entry)
        if not is_valid:
            for issue in issues:
                messages.append(f"VALIDATION ERROR: {issue}")
            return False, messages
        for issue in issues:
            if issue.startswith("KKS Note:"):
                messages.append(issue)

    clean_entry = {}
    for field, field_type in PPIA_LOG_SCHEMA.items():
        val = entry.get(field)
        if val is None:
            clean_entry[field] = "" if field_type == str else None
        else:
            clean_entry[field] = str(val) if field_type == str else val

    try:
        supabase = get_supabase_client()
        supabase.table("ppia_log").update(clean_entry).eq("id", entry_id).execute()
        load_ppia_log.clear()
        messages.append(f"SUCCESS: PPIA event #{entry_id} updated.")
        return True, messages
    except APIError as e:
        err_msg = f"Database update failed: {e.message}"
        messages.append(f"ERROR: {err_msg}")
        st.error(err_msg)
        return False, messages
    except Exception as e:
        err_msg = f"Unexpected error during PPIA update: {str(e)}"
        messages.append(f"ERROR: {err_msg}")
        st.error(err_msg)
        return False, messages


def update_ppia_batch(edited_rows: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
    """
    Batch update of edited PPIA log rows — each dict must include its "id".
    Returns (success_count, all_messages).
    """
    success_count = 0
    all_messages: List[str] = []

    if not edited_rows:
        return 0, ["INFO: No PPIA events to update."]

    for row in edited_rows:
        row_id = row.get("id")
        ok, msgs = update_ppia_entry(row_id, row)
        all_messages.extend(msgs)
        if ok:
            success_count += 1

    return success_count, all_messages


def clear_ppia_log() -> Tuple[bool, str]:
    """
    Clears ALL records from the ppia_log table. Use with extreme caution —
    this is irreversible.

    Returns:
        (success: bool, message: str)
    """
    try:
        supabase = get_supabase_client()
        # Same "match everything" pattern as clear_registry(): PostgREST
        # requires a delete filter, and every row has a non-empty
        # interlock_description, so neq() against it matches (and removes) all.
        supabase.table("ppia_log").delete().neq("interlock_description", "").execute()
        load_ppia_log.clear()
        return True, "PPIA log cleared successfully. All events removed."
    except APIError as e:
        return False, f"Database error clearing PPIA log: {e.message}"
    except Exception as e:
        return False, f"Unexpected error clearing PPIA log: {str(e)}"


# =============================================================================
# MILESTONE TEST HISTORY (append-only — every test attempt, not just latest)
# =============================================================================

def insert_milestone_history_entry(entry: Dict[str, Any], skip_validation: bool = False) -> Tuple[bool, List[str]]:
    """
    Inserts a single milestone test-history event. Always inserts a new row
    (append-only — the whole point is to preserve every attempt, not just
    the latest one).

    Returns:
        (success: bool, messages: list of info/warning/error strings)
    """
    messages: List[str] = []

    if not skip_validation:
        is_valid, issues = validate_milestone_history_entry(entry)
        if not is_valid:
            for issue in issues:
                messages.append(f"VALIDATION ERROR: {issue}")
            return False, messages

    clean_entry = {}
    for field, field_type in MILESTONE_HISTORY_SCHEMA.items():
        val = entry.get(field)
        if val is None:
            clean_entry[field] = "" if field_type == str else None
        else:
            clean_entry[field] = str(val) if field_type == str else val

    try:
        supabase = get_supabase_client()
        supabase.table("milestone_history").insert(clean_entry).execute()
        load_milestone_history.clear()
        return True, messages
    except APIError as e:
        err_msg = f"Database insert failed: {e.message}"
        messages.append(f"ERROR: {err_msg}")
        return False, messages
    except Exception as e:
        err_msg = f"Unexpected error during history insert: {str(e)}"
        messages.append(f"ERROR: {err_msg}")
        return False, messages


@st.cache_data(ttl=20, show_spinner=False)
def load_milestone_history() -> List[Dict[str, Any]]:
    """Loads all milestone test-history events, most recent first."""
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("milestone_history")
            .select("*")
            .order("event_date", desc=True)
            .execute()
        )
        return response.data if response.data else []
    except APIError as e:
        st.error(f"Database Error loading milestone history: {e.message}")
        return []
    except Exception as e:
        st.error(f"Unexpected error loading milestone history: {str(e)}")
        return []


def load_milestone_history_df() -> "pd.DataFrame":
    """Loads the milestone test-history as a pandas DataFrame."""
    import pandas as pd
    data = load_milestone_history()
    if not data:
        return pd.DataFrame(columns=list(MILESTONE_HISTORY_SCHEMA.keys()))
    return pd.DataFrame(data)


def load_milestone_history_for(system_kks: str, component: str) -> List[Dict[str, Any]]:
    """Loads every test-history event for one specific system+component,
    across all 5 milestones — this is what the timeline chart plots."""
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("milestone_history")
            .select("*")
            .eq("system_kks", system_kks)
            .eq("component", component)
            .order("event_date", desc=False)
            .execute()
        )
        return response.data if response.data else []
    except APIError as e:
        st.error(f"Database Error loading test history: {e.message}")
        return []
    except Exception as e:
        st.error(f"Unexpected error loading test history: {str(e)}")
        return []


def clear_milestone_history() -> Tuple[bool, str]:
    """
    Clears ALL records from the milestone_history table. Use with extreme
    caution — this is irreversible and discards all retest history.

    Returns:
        (success: bool, message: str)
    """
    try:
        supabase = get_supabase_client()
        supabase.table("milestone_history").delete().neq("milestone", "").execute()
        load_milestone_history.clear()
        return True, "Milestone test history cleared successfully. All events removed."
    except APIError as e:
        return False, f"Database error clearing milestone history: {e.message}"
    except Exception as e:
        return False, f"Unexpected error clearing milestone history: {str(e)}"
