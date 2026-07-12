"""
Reactor Shop Commissioning - AI Processing Engine
==================================================
Natural language parsing, KKS classification, and intelligent data extraction.

KKS Coding based on the Rooppur NPP Reactor Shop KKS Code Master List
(hard-coded in config.py — see config.py header for source documents).
"""

import json
import re
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
    MILESTONE_DATE_FIELDS,
    VALID_STATUSES,
    parse_commissioning_stage,
    validate_ppia_entry,
)


# =============================================================================
# AI (MISTRAL) API INTEGRATION
# =============================================================================

def _build_system_prompt(include_ppia: bool = True) -> str:
    """Builds the extraction system prompt using the real, hard-coded KKS
    reference tables from config.py so the model is grounded in actual
    Rooppur codes rather than a guessed scheme.

    Args:
        include_ppia: whether to ask the model to also extract PPIA events.
            PPIA extraction is intentionally scoped to the interactive Shift
            Note Parser only (free-form shift-handover text is where PPIA
            events actually get reported) — bulk file imports (structured
            Excel/CSV data) don't ask for it, since those sources are
            commissioning test records, not shift narratives.
    """

    unit_lines = "\n".join(f"  {k} = {v}" for k, v in UNIT_CODES.items())
    fkey_lines = ", ".join(f"{k}={v}" for k, v in FUNCTION_KEY_LEGEND.items())
    common_types = ", ".join(
        f"{k}={v.split(' — ')[-1] if ' — ' in v else v}"
        for k, v in list(EQUIPMENT_TYPE_LEGEND.items())[:15]
    )
    milestone_summary = ", ".join(
        f"{ms.replace('_status', '').upper()}={MILESTONE_LABELS.get(ms, ms).split('(')[-1].rstrip(')')}"
        for ms in MILESTONES
    )
    # Milestone status/date field pairs, generated from config.py's MILESTONES
    # list so this never has to be manually kept in sync again (e.g. if the
    # number of protocol parts changes from P-9 to something else).
    milestone_fields_json = ",\n".join(
        f'            "{ms}": "Pending|In Progress|Completed|Failed|N/A",\n'
        f'            "{MILESTONE_DATE_FIELDS[ms]}": "YYYY-MM-DD or empty string if not found"'
        for ms in MILESTONES
    )

    ppia_intro = ""
    ppia_output_block = ""
    ppia_rules = ""
    if include_ppia:
        ppia_intro = """
- PPIA = Process Protection and Interlock Actuation. This is DIFFERENT from the milestones above:
  a PPIA entry is a discrete EVENT report (a protection system tripped, an interlock actuated, a
  protection alarm occurred) — not a pass/fail commissioning test status. Look for language like
  "interlock actuated", "protection trip", "PPIA", "reactor trip on...", "actuation of...",
  "protection system alarmed", etc. Extract each such event as its own entry."""
        ppia_output_block = """,
    "ppia_events": [
        {
            "system": "System Name",
            "system_kks": "KKS code if stated, else empty string",
            "event_date": "YYYY-MM-DD or empty string if not found",
            "event_time": "HH:MM 24h or empty string if not found",
            "interlock_description": "What actuated/tripped, in plain language (REQUIRED)",
            "trigger_cause": "What caused it, if stated, else empty string",
            "status": "Confirmed|False Alarm|Resolved|Under Investigation|Pending Review",
            "comments": "Any additional notes"
        }
    ]"""
        ppia_rules = """
16. "ppia_events" is a SEPARATE list from "records" — a PPIA event is not a milestone status update. If the source mentions no protection/interlock actuations, output an empty list for "ppia_events".
17. PPIA "status" field: if the shift note doesn't explicitly characterize the event, default to "Pending Review" rather than guessing "Confirmed" or "False Alarm".
18. "interlock_description" is required for every PPIA event — if you cannot state clearly what actuated/tripped, do not create the entry."""

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
- Milestones (apply to ALL scope types): {milestone_summary}. IT/PIC/HT/PT/SAW are physical
  commissioning tests. P1 through P9 track PROTOCOL DOCUMENT sign-off (paperwork, e.g. "P-3 not
  signed", "P-1 is checked") — not physical tests.{ppia_intro}
- MULTIPLE CODES IN ONE CELL/SENTENCE: source text often lists several KKS/equipment codes
  together, comma-separated, e.g. "12KAA20AA801, 802, 12KAA10AA801" or "01UYP, 02UYP, 03UYP".
  Create ONE SEPARATE record per code, not one record covering all of them. When a later code in
  the list is just a short suffix (e.g. "802" or "12" following a full code), it means "same
  prefix as the previous full code, only the trailing part changed" — reconstruct the full code
  by combining it with the immediately preceding full code's prefix. Example: "12KAA20AA801, 802"
  means two equipment codes: 12KAA20AA801 AND 12KAA20AA802 (both get their own record). Example:
  "01UYP, 02UYP, 03UYP" are three already-complete building codes — no reconstruction needed,
  just three separate records.

OUTPUT FORMAT:
{{
    "records": [
        {{
            "system": "System Name",
            "system_kks": "Full KKS code including the mandatory 2-digit Unit prefix",
            "scope_type": "System|Equipment|Building",
            "component": "Component Tag",
            "commissioning_stage": "Stage code if present in source (e.g. A, A-1, A-3.1, B-2), else empty string",
{milestone_fields_json},
            "comments": "Any relevant notes including KKS context"
        }}
    ]{ppia_output_block}
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
10. All milestones (IT, PIC, HT, PT, SAW, P1-P9) apply to ALL scope types.
11. PIC (Post Installation Cleaning) must precede HT (Hydro Test).
12. Include any anomalies, KKS code issues, or special notes in "comments".
13. If scope cannot be determined from KKS, infer from context ("system" vs "equipment" vs "building").
14. Never invent a Unit code — if the shift note doesn't specify one, use "00" (common/shared) and note the assumption in "comments".
15. For each milestone's companion "_date" field: extract an actual calendar date ONLY if one is explicitly present near that milestone in the source (a completion date, target date, or logged date). Normalize any date format found (DD/MM/YYYY, "5 July 2026", etc.) to YYYY-MM-DD. NEVER invent, guess, or infer a date — if no explicit date is present for that milestone, output an empty string "".{ppia_rules}
19. "commissioning_stage": Rooppur commissioning works are organized into lettered stages with optional numbered sub-stages, including decimal ones — A, A-1, A-2, A-3.1, A-3.2, B, B-1, B-2, etc. Look for a column or label in the source explicitly named "Stage", "Commissioning Stage", "Phase", "Stage of performance", or similar, or an inline mention like "Stage A-1" / "Phase B-2" / "on sub-stage A-1". Extract it exactly as given. If no stage is stated anywhere for a record, output an empty string — NEVER guess or infer a stage from context.
20. "p1_status" through "p9_status": these track PROTOCOL DOCUMENT sign-off, distinct from the physical tests. Look for phrases like "Protocol collected", "Protocol submitted", "P-1 signed", "P-3 not signed", "Protocol not submitted", and match to the correct part number. Map: not mentioned/not submitted -> "Pending"; collected but not yet submitted -> "In Progress"; submitted and signed -> "Completed"; rejected/returned -> "Failed".
21. COMMA-SEPARATED CODE LISTS: never merge multiple codes into a single record's system_kks field. Always split into one record per code, applying the suffix-inheritance reconstruction rule described above where applicable.
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


def ask_mistral(prompt: str, max_retries: int = 5, include_ppia: bool = True) -> Optional[Dict[str, Any]]:
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
        include_ppia: whether to ask for PPIA event extraction too (see
            _build_system_prompt docstring — scoped to the Shift Note Parser)

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
            {"role": "system", "content": _build_system_prompt(include_ppia=include_ppia)},
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

_KKS_FULL_CODE_RE = re.compile(r'^\d{2}[A-Z]{2,4}\d{2}[A-Z]{2}\d{3}$')
_KKS_SYSTEM_OR_BUILDING_RE = re.compile(r'^\d{2}(?:U)?[A-Z]{2,4}$')
_SUFFIX_ONLY_RE = re.compile(r'^\d{2,3}$')  # e.g. "802", "12" — a trailing part only


def split_comma_separated_kks(system_kks: str) -> List[str]:
    """
    Deterministic safety net for comma-separated KKS lists — doesn't rely on
    the AI to get this right every time. Real Rooppur source sheets do this
    routinely, e.g. "12KAA20AA801, 802" (second token is just the trailing
    sequence number, inheriting the first token's prefix) or "01UYP, 02UYP,
    03UYP" (already-complete codes, just split on the comma).

    Returns a list of one or more fully-reconstructed KKS codes. If the input
    has no comma, returns a single-element list unchanged.
    """
    if not system_kks or "," not in system_kks:
        return [system_kks] if system_kks else []

    tokens = [t.strip() for t in system_kks.split(",") if t.strip()]
    if not tokens:
        return []

    result: List[str] = []
    last_full_prefix = None  # the "stem" to reuse for abbreviated suffix tokens

    for tok in tokens:
        tok_clean = tok.upper().replace(" ", "")

        if _KKS_FULL_CODE_RE.match(tok_clean):
            result.append(tok_clean)
            # stem = everything except the trailing 3-digit sequence number
            last_full_prefix = tok_clean[:-3]
        elif _KKS_SYSTEM_OR_BUILDING_RE.match(tok_clean):
            # Already a complete system/building code — no reconstruction needed
            result.append(tok_clean)
            last_full_prefix = None
        elif _SUFFIX_ONLY_RE.match(tok_clean) and last_full_prefix:
            # Abbreviated suffix — inherit the previous full code's prefix
            seq_len = len(tok_clean)
            padded = tok_clean.zfill(3) if seq_len <= 3 else tok_clean
            result.append(f"{last_full_prefix}{padded}")
        else:
            # Unrecognized shape — keep as-is rather than silently dropping it;
            # downstream KKS validation will flag it for manual review.
            result.append(tok_clean)
            last_full_prefix = None

    return result


def expand_comma_separated_records(record: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    If a record's system_kks (or component) contains comma-separated codes,
    expands it into multiple independent records — one per code — instead of
    silently treating a multi-code cell as a single record. This is the
    deterministic backstop behind rule #21 in the system prompt; the AI is
    asked to do this splitting itself, but real source sheets are messy
    enough that a Python-level check catches anything the AI merges by mistake.

    Returns:
        (list of one or more records, list of info alerts)
    """
    alerts: List[str] = []
    kks_raw = record.get("system_kks", "")

    if not kks_raw or "," not in kks_raw:
        return [record], alerts

    expanded_codes = split_comma_separated_kks(kks_raw)
    if len(expanded_codes) <= 1:
        return [record], alerts

    alerts.append(
        f"SPLIT: '{kks_raw}' contained {len(expanded_codes)} comma-separated codes — "
        f"expanded into {len(expanded_codes)} separate records: {', '.join(expanded_codes)}"
    )

    expanded_records = []
    for code in expanded_codes:
        new_record = dict(record)
        new_record["system_kks"] = code
        expanded_records.append(new_record)

    return expanded_records, alerts


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

    # Normalize commissioning stage first — independent of KKS validity, so
    # it still gets cleaned up even if the KKS code itself has issues below.
    raw_stage = record.get("commissioning_stage", "")
    if raw_stage:
        normalized_stage = parse_commissioning_stage(raw_stage)
        if normalized_stage:
            record["commissioning_stage"] = normalized_stage
        else:
            alerts.append(
                f"STAGE WARNING: Could not parse commissioning stage '{raw_stage}' "
                f"(expected a letter, optionally with a dash and number, e.g. 'A', 'A-1'). "
                f"Kept as-is for manual review."
            )

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


def post_process_ppia_event(event: Dict[str, Any], source: str = "") -> Tuple[Dict[str, Any], List[str]]:
    """
    Post-processes an AI-extracted PPIA event: normalizes KKS (if given,
    non-fatal if absent/invalid — PPIA events don't require a KKS), defaults
    an unstated status to "Pending Review" rather than trusting a guess, and
    stamps the source file/note.
    """
    alerts: List[str] = []
    event = dict(event)

    kks = event.get("system_kks", "")
    if kks:
        parsed = parse_kks(kks)
        if parsed.valid:
            alerts.append(f"PPIA KKS INFO: {parsed.message}")
        else:
            alerts.append(f"PPIA KKS NOTE: {parsed.message} (non-blocking for PPIA events)")

    if not event.get("status"):
        event["status"] = "Pending Review"

    event["source"] = source

    is_valid, issues = validate_ppia_entry(event)
    if not is_valid:
        alerts.extend(f"PPIA VALIDATION: {i}" for i in issues if not i.startswith("KKS Note:"))

    return event, alerts


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

        data = ask_mistral(chunk, include_ppia=False)
        if data is None:
            all_alerts.append(f"ERROR: Failed to process chunk {i+1}")
            progress_bar.progress((i + 1) / len(chunks))
            continue

        raw_records = data.get("records", [])
        if not raw_records and all(k in data for k in ('system', 'system_kks', 'component')):
            raw_records = [data]

        # Expand any comma-separated multi-code records into individual ones
        # BEFORE counting/processing, so "12KAA20AA801, 802" becomes 2 records.
        records = []
        for raw_record in raw_records:
            expanded, split_alerts = expand_comma_separated_records(raw_record)
            records.extend(expanded)
            all_alerts.extend(split_alerts)

        st.info(f"Chunk {i+1}: Extracted {len(records)} record(s) (after comma-split).")

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

def parse_shift_notes(notes_text: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """
    Parses natural language shift notes directly into structured records
    with real Rooppur NPP KKS validation, plus any PPIA (Process Protection
    and Interlock Actuation) events mentioned. Neither is saved here — the
    caller is expected to let the user review/edit before committing.

    Returns:
        (list of parsed registry records, list of parsed PPIA events, list of alerts/warnings)
    """
    if not notes_text or not notes_text.strip():
        return [], [], ["ERROR: Empty shift notes provided"]

    data = ask_mistral(notes_text)
    if data is None:
        return [], [], ["ERROR: AI extraction failed"]

    raw_records = data.get("records", [])
    if not raw_records and all(k in data for k in ('system', 'system_kks', 'component')):
        raw_records = [data]
    ppia_events_raw = data.get("ppia_events", [])

    alerts: List[str] = []
    validated_records: List[Dict[str, Any]] = []
    validated_ppia_events: List[Dict[str, Any]] = []

    # Expand any comma-separated multi-code records into individual ones
    # BEFORE validation, so "12KAA20AA801, 802" becomes 2 records.
    records = []
    for raw_record in raw_records:
        expanded, split_alerts = expand_comma_separated_records(raw_record)
        records.extend(expanded)
        alerts.extend(split_alerts)

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

    for event in ppia_events_raw:
        event, ppia_alerts = post_process_ppia_event(event, source="Shift Note Parser")
        alerts.extend(ppia_alerts)
        validated_ppia_events.append(event)

    return validated_records, validated_ppia_events, alerts
