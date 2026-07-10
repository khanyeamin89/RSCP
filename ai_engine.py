"""
Reactor Shop Commissioning - AI Processing Engine
==================================================
Natural language parsing, KKS classification, and intelligent data extraction.

KKS Coding based on the Rooppur NPP Reactor Shop KKS Code Master List
(hard-coded in config.py — see config.py header for source documents).
"""

import json
import hashlib
import time
import streamlit as st
import pandas as pd
from io import BytesIO
from typing import Dict, List, Any, Tuple, Optional

from database import upsert_registry_row, check_chunk_exists, mark_chunk_done
from config import (
    get_kks_scope,
    parse_kks,
    validate_milestone_dependencies,
    ScopeType,
    UNIT_CODES,
    FUNCTION_KEY_LEGEND,
    EQUIPMENT_TYPE_LEGEND,
    MILESTONES,
    MILESTONE_LABELS,
    VALID_STATUSES,
)


# =============================================================================
# AI (MISTRAL) API INTEGRATION
# =============================================================================

def _build_system_prompt() -> str:
    """Builds the extraction system prompt using the real, hard-coded KKS
    reference tables from config.py so the model is grounded in actual
    Rooppur codes rather than a guessed scheme."""

    unit_lines = "\n".join(f"  {k} = {v}" for k, v in UNIT_CODES.items())
    fkey_lines = ", ".join(f"{k}={v}" for k, v in FUNCTION_KEY_LEGEND.items())
    common_types = ", ".join(
        f"{k}={v.split(' — ')[-1] if ' — ' in v else v}"
        for k, v in list(EQUIPMENT_TYPE_LEGEND.items())[:15]
    )

    return f"""You are a nuclear commissioning data extraction expert for the Rooppur NPP project.

Extract commissioning registry data from the provided shift notes into valid JSON.

KKS CODING RULES (Rooppur NPP Reactor Shop KKS Code Master List):
- KKS = Kraftwerk-Kennzeichensystem, the German-origin power-plant identification standard.
- There are three real code shapes, all starting with a mandatory 2-digit Unit code:
    Equipment: [Unit-2][System-2to4 letters][Subsystem-2digit][Type-2letter][Seq-3digit]  e.g. 10JAA10BB001
    Building : [Unit-2]U[2 letters]                                                       e.g. 10UJA
    System   : [Unit-2][System-2to4 letters]                                              e.g. 10JAA
- Known unit codes:
{unit_lines}
  (other 2-digit unit codes exist for shared/auxiliary facility zones)
- System code function keys (1st letter of the system code): {fkey_lines}
- Common equipment type codes (2 letters, precede the 3-digit sequence number): {common_types}
- Milestones (COMMISSIONING TESTS - apply to ALL scope types): IT=Individual Test, PIC=Post-Install Cleaning, HT=Hydro Test, PT=Pneumatic Test, SAW=Start-up & Adjustment

OUTPUT FORMAT:
{{
    "records": [
        {{
            "system": "System Name",
            "system_kks": "Full KKS code including the mandatory 2-digit Unit prefix",
            "scope_type": "System|Equipment|Building",
            "component": "Component Tag",
            "it_status": "Pending|In Progress|Completed|Failed|N/A",
            "it_date": "YYYY-MM-DD or empty string if not found",
            "pic_status": "Pending|In Progress|Completed|Failed|N/A",
            "pic_date": "YYYY-MM-DD or empty string if not found",
            "ht_status": "Pending|In Progress|Completed|Failed|N/A",
            "ht_date": "YYYY-MM-DD or empty string if not found",
            "pt_status": "Pending|In Progress|Completed|Failed|N/A",
            "pt_date": "YYYY-MM-DD or empty string if not found",
            "saw_status": "Pending|In Progress|Completed|Failed|N/A",
            "saw_date": "YYYY-MM-DD or empty string if not found",
            "comments": "Any relevant notes including KKS context"
        }}
    ]
}}

RULES:
1. Identify KKS codes first. The 2-digit Unit prefix is MANDATORY.
2. System KKS: Unit + 2-4 letter system code (JAA, KBA, etc.).
3. Equipment KKS: Unit + system code + 2-digit subsystem + 2-letter type + 3-digit sequence.
4. Building KKS: Unit + "U" + 2 letters.
5. Status keywords: "done", "complete", "finished", "passed" -> "Completed"
6. Status keywords: "ongoing", "in progress", "started" -> "In Progress"
7. Status keywords: "failed", "rejected", "issue" -> "Failed"
8. Status keywords: "pending", "not started", "awaiting" -> "Pending"
9. If a milestone is not mentioned, default to "Pending".
10. All 5 milestones (IT, PIC, HT, PT, SAW) apply to ALL scope types. They are commissioning tests.
11. PIC (Post Installation Cleaning) must precede HT (Hydro Test).
12. Include any anomalies, KKS code issues, or special notes in "comments".
13. If scope cannot be determined from KKS, infer from context ("system" vs "equipment" vs "building").
14. Never invent a Unit code — if the shift note doesn't specify one, use "00" (common/shared) and note the assumption in "comments".
15. For each milestone's companion "_date" field: extract an actual calendar date ONLY if one is explicitly present near that milestone in the source (a completion date, target date, or logged date). Normalize any date format found (DD/MM/YYYY, "5 July 2026", etc.) to YYYY-MM-DD. NEVER invent, guess, or infer a date — if no explicit date is present for that milestone, output an empty string "".
"""


# Minimum spacing (seconds) enforced between consecutive Mistral calls. Their
# free "Experiment" tier is rate-limited (roughly 1 request/second-ish,
# providers don't always publish exact figures), so this stays comfortably
# above that. Module-level so it persists across Streamlit reruns within the
# same server process.
_MIN_CALL_INTERVAL_SECONDS = 3.5

_last_ai_call_time: float = 0.0

# Mistral Small via the "-latest" alias, which Mistral keeps pointed at their
# current small model rather than a specific dated snapshot — this avoids the
# stale-model-slug 404s hit with OpenRouter's hardcoded model names.
_MISTRAL_MODEL = "mistral-small-latest"


def _wait_for_rate_limit_slot() -> None:
    """Sleeps just long enough to keep consecutive AI calls spaced apart."""
    global _last_ai_call_time
    now = time.monotonic()
    elapsed = now - _last_ai_call_time
    if elapsed < _MIN_CALL_INTERVAL_SECONDS:
        time.sleep(_MIN_CALL_INTERVAL_SECONDS - elapsed)
    _last_ai_call_time = time.monotonic()


def _salvage_truncated_json(content: str) -> Optional[Dict[str, Any]]:
    """
    Attempts to recover a usable {"records": [...]} dict from a response that
    got cut off mid-record (hit the output token limit before finishing).
    Works backward from the end of the string, trying to close the JSON right
    after each complete '}' — the first one that parses cleanly means
    everything up to (and including) that record is intact; whatever was
    being written after it gets dropped.

    Returns None if no valid "records" array can be recovered at all.
    """
    import re

    idx_records = content.find('"records"')
    if idx_records == -1:
        return None
    idx_bracket = content.find('[', idx_records)
    if idx_bracket == -1:
        return None

    candidate_positions = [m.start() for m in re.finditer(r'\}', content) if m.start() > idx_bracket]
    for pos in reversed(candidate_positions):
        truncated = content[:pos + 1] + ']}'
        try:
            return json.loads(truncated)
        except json.JSONDecodeError:
            continue
    return None


def ask_mistral(prompt: str, max_retries: int = 5) -> Optional[Dict[str, Any]]:
    """
    Mistral La Plateforme API wrapper with JSON enforcement, retry logic, and
    error handling. Uses the free "Experiment" tier (~1B tokens/month, no
    credit card required) via the OpenAI-compatible /v1/chat/completions
    endpoint.

    Rate-limit handling:
    - Paces calls so they're at least _MIN_CALL_INTERVAL_SECONDS apart,
      proactively avoiding many 429s rather than only reacting to them.
    - On a 429, honors the `Retry-After` response header when present.
      Falls back to exponential backoff with jitter if the header is missing.
    - Defaults to 5 retries since 429s can happen under load on a free tier,
      not exceptional failures.

    Args:
        prompt: The text to send to the LLM
        max_retries: Number of retry attempts on failure

    Returns:
        Parsed JSON dict or None on failure
    """
    import requests
    import random

    api_key = st.secrets.get("MISTRAL_API_KEY")
    if not api_key:
        st.error("MISTRAL_API_KEY not found in Streamlit secrets.")
        return None

    payload = {
        "model": _MISTRAL_MODEL,
        "messages": [
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 8000
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = None
    for attempt in range(max_retries + 1):
        _wait_for_rate_limit_slot()
        try:
            response = requests.post(
                "https://api.mistral.ai/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=60
            )
            response.raise_for_status()

            result = response.json()
            content = result['choices'][0]['message']['content']
            return json.loads(content)

        except requests.exceptions.HTTPError as e:
            status = response.status_code if response is not None else None

            if status == 429:
                if attempt < max_retries:
                    retry_after = response.headers.get("Retry-After") or response.headers.get("retry-after")
                    if retry_after:
                        try:
                            wait_time = float(retry_after)
                        except ValueError:
                            wait_time = (2 ** attempt) + random.uniform(0, 1)
                    else:
                        wait_time = (2 ** attempt) + random.uniform(0, 1)
                    st.warning(
                        f"Mistral rate limit hit (attempt {attempt + 1}/{max_retries + 1}). "
                        f"Waiting {wait_time:.1f}s before retrying..."
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    st.error(
                        "Mistral API HTTP Error (429): rate limit exceeded and retries exhausted. "
                        "The free Experiment tier allows roughly 1B tokens/month with a tight "
                        "per-request rate cap. Check your usage at https://console.mistral.ai "
                        "under Limits — wait a bit before trying again, or process fewer chunks "
                        "at once."
                    )
                    return None

            if status == 404:
                st.error(
                    f"Mistral API HTTP Error (404): model '{_MISTRAL_MODEL}' not found. "
                    "Mistral's model lineup changes over time; check "
                    "https://docs.mistral.ai/getting-started/models/ for the current model "
                    "names and update _MISTRAL_MODEL in ai_engine.py if needed."
                )
                return None

            if status == 401:
                st.error(
                    "Mistral API HTTP Error (401): invalid or missing API key. Double-check "
                    "MISTRAL_API_KEY in Streamlit secrets matches the key from "
                    "https://console.mistral.ai/api-keys."
                )
                return None

            st.error(f"Mistral API HTTP Error ({status}): {str(e)}")
            return None
        except json.JSONDecodeError as e:
            salvaged = _salvage_truncated_json(content) if 'content' in locals() else None
            if salvaged is not None:
                st.warning(
                    "Mistral's response was cut off (likely hit the output token limit "
                    "before finishing). Recovered the complete records before the cutoff — "
                    "the last, incomplete record in this chunk was dropped. If this happens "
                    "often, the file may need smaller chunks."
                )
                return salvaged
            st.error(f"Mistral returned invalid JSON: {str(e)}")
            return None
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                st.warning(f"Request failed ({str(e)}). Retrying in {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
            st.error(f"Mistral API call failed: {str(e)}")
            return None

    return None


# =============================================================================
# FILE PARSING
# =============================================================================

def extract_text_from_file(file_bytes: bytes, file_name: str) -> str:
    """
    Extracts text content from CSV, XLSX, or plain text files.
    """
    file_lower = file_name.lower()

    if file_lower.endswith('.csv'):
        try:
            df = pd.read_csv(BytesIO(file_bytes))
            return df.to_string(index=False)
        except Exception:
            return file_bytes.decode('utf-8', errors='ignore')

    elif file_lower.endswith('.xlsx') or file_lower.endswith('.xls'):
        try:
            df = pd.read_excel(BytesIO(file_bytes))
            return df.to_string(index=False)
        except Exception as e:
            st.error(f"Failed to parse Excel file: {str(e)}")
            return ""

    else:
        return file_bytes.decode('utf-8', errors='ignore')


def smart_chunk_text(text: str, max_chunk_size: int = 8000) -> List[str]:
    """
    Chunks text intelligently by trying to preserve record boundaries.
    Falls back to character-based chunking if no clear boundaries found.
    """
    if not text:
        return []

    records = text.split('\n\n')

    chunks = []
    current_chunk = ""

    for record in records:
        if len(current_chunk) + len(record) + 2 > max_chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = record
        else:
            current_chunk += "\n\n" + record if current_chunk else record

    if current_chunk:
        chunks.append(current_chunk.strip())

    final_chunks = []
    for chunk in chunks:
        if len(chunk) > max_chunk_size:
            lines = chunk.split('\n')
            current = ""
            for line in lines:
                if len(current) + len(line) + 1 > max_chunk_size:
                    if current:
                        final_chunks.append(current.strip())
                    current = line
                else:
                    current += "\n" + line if current else line
            if current:
                final_chunks.append(current.strip())
        else:
            final_chunks.append(chunk)

    return final_chunks if final_chunks else [text[:max_chunk_size]]


# =============================================================================
# KKS POST-PROCESSING VALIDATION
# =============================================================================

def post_process_kks_record(record: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Post-processes an AI-extracted record by running it through the single,
    centralized KKS parser in config.py (previously this duplicated the
    parsing logic with hard-coded string slices that assumed a 1-digit unit
    prefix, which no longer matches the real 2-digit Rooppur unit codes and
    caused incorrect/failed validation).

    Returns:
        (record, alerts)
    """
    alerts: List[str] = []
    kks = record.get("system_kks", "")

    if not kks:
        alerts.append("WARNING: No KKS code found in extracted record")
        return record, alerts

    parsed = parse_kks(kks)
    if not parsed.valid:
        alerts.append(f"KKS ERROR: {parsed.message}")
        return record, alerts

    alerts.append(f"KKS INFO: {parsed.message}")
    alerts.extend(f"KKS WARNING: {a}" for a in parsed.alerts)

    if parsed.scope:
        record["scope_type"] = parsed.scope.value

    return record, alerts


# =============================================================================
# MAIN PROCESSING PIPELINE
# =============================================================================

def process_file_smart(file_bytes: bytes, file_name: str, force_reprocess: bool = False) -> Tuple[int, List[str]]:
    """
    Incremental, idempotent file processing pipeline with real Rooppur NPP KKS validation.

    Args:
        file_bytes: Raw file bytes
        file_name: Original filename
        force_reprocess: If True, ignores the processed_chunks cache and
            re-sends every chunk to the AI, re-marking them done afterward.
            Use this when the registry was cleared/reset but the same file
            is being re-uploaded — otherwise check_chunk_exists() will still
            report every chunk as already-processed and skip all of them,
            silently producing 0 new records.

    Returns:
        (records_processed, list of all alert messages)
    """
    all_alerts: List[str] = []
    total_processed = 0

    file_hash = hashlib.md5(file_bytes).hexdigest()

    raw_text = extract_text_from_file(file_bytes, file_name)
    if not raw_text.strip():
        st.error("Could not extract any text from the uploaded file.")
        return 0, ["ERROR: Empty or unreadable file"]

    chunks = smart_chunk_text(raw_text)
    st.info(f"File split into {len(chunks)} chunk(s) for processing.")

    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, chunk in enumerate(chunks):
        status_text.text(f"Processing chunk {i+1}/{len(chunks)}...")

        if not force_reprocess and check_chunk_exists(file_hash, i):
            st.info(f"Chunk {i+1} already processed (skipping).")
            progress_bar.progress((i + 1) / len(chunks))
            continue

        data = ask_mistral(chunk)
        if data is None:
            all_alerts.append(f"ERROR: Failed to process chunk {i+1}")
            progress_bar.progress((i + 1) / len(chunks))
            continue

        records = data.get("records", [])
        if not records and all(k in data for k in ('system', 'system_kks', 'component')):
            records = [data]

        st.info(f"Chunk {i+1}: Extracted {len(records)} record(s).")

        for record in records:
            record, kks_alerts = post_process_kks_record(record)
            all_alerts.extend(kks_alerts)

            dep_issues = validate_milestone_dependencies(record)
            all_alerts.extend(dep_issues)

            ok, msgs = upsert_registry_row(record)
            all_alerts.extend(msgs)
            if ok:
                total_processed += 1

        mark_chunk_done(file_hash, i)
        progress_bar.progress((i + 1) / len(chunks))

    progress_bar.empty()
    status_text.empty()

    return total_processed, all_alerts


# =============================================================================
# NATURAL LANGUAGE SHIFT NOTE PARSER (Direct API)
# =============================================================================

def parse_shift_notes(notes_text: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parses natural language shift notes directly into structured records
    with real Rooppur NPP KKS validation.

    Returns:
        (list of parsed records, list of alerts/warnings)
    """
    if not notes_text or not notes_text.strip():
        return [], ["ERROR: Empty shift notes provided"]

    data = ask_mistral(notes_text)
    if data is None:
        return [], ["ERROR: AI extraction failed"]

    records = data.get("records", [])
    if not records and all(k in data for k in ('system', 'system_kks', 'component')):
        records = [data]

    alerts: List[str] = []
    validated_records: List[Dict[str, Any]] = []

    for record in records:
        kks = record.get('system_kks', '')

        record, kks_alerts = post_process_kks_record(record)
        alerts.extend(kks_alerts)

        scope = get_kks_scope(kks)
        if scope is None:
            alerts.append(
                f"WARNING: Unrecognized KKS '{kks}' in extracted record. "
                f"Verify the 2-digit Unit prefix is present (mandatory). Manual review required."
            )
        else:
            record['scope_type'] = scope.value

        dep_issues = validate_milestone_dependencies(record)
        alerts.extend(dep_issues)
        validated_records.append(record)

    return validated_records, alerts
