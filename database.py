"""
Reactor Shop Commissioning - AI Processing Engine
==================================================
Natural language parsing, KKS classification, and intelligent data extraction.
"""

import json
import hashlib
import streamlit as st
import pandas as pd
from io import BytesIO
from typing import Dict, List, Any, Tuple, Optional

from database import upsert_registry_row, check_chunk_exists, mark_chunk_done
from config import (
    get_kks_scope,
    enforce_scope_milestones,
    validate_milestone_dependencies,
    ScopeType,
    SYSTEM_PREFIXES,
    EQUIPMENT_PREFIXES,
    MILESTONES,
    VALID_STATUSES,
)


# =============================================================================
# GROQ API INTEGRATION
# =============================================================================

def ask_groq(prompt: str, max_retries: int = 2) -> Optional[Dict[str, Any]]:
    """
    Groq API wrapper with JSON enforcement, retry logic, and error handling.

    Args:
        prompt: The text to send to the LLM
        max_retries: Number of retry attempts on failure

    Returns:
        Parsed JSON dict or None on failure
    """
    import requests
    import time

    api_key = st.secrets.get("GROQ_API_KEY")
    if not api_key:
        st.error("GROQ_API_KEY not found in Streamlit secrets.")
        return None

    system_prompt = """You are a nuclear commissioning data extraction expert.

    Extract commissioning registry data from the provided shift notes into valid JSON.

    OUTPUT FORMAT:
    {
        "records": [
            {
                "system": "System Name",
                "system_kks": "KKS Code",
                "scope_type": "System|Equipment",
                "component": "Component Tag",
                "it_status": "Pending|In Progress|Completed|Failed|N/A",
                "pic_status": "Pending|In Progress|Completed|Failed|N/A",
                "ht_status": "Pending|In Progress|Completed|Failed|N/A",
                "pt_status": "Pending|In Progress|Completed|Failed|N/A",
                "saw_status": "Pending|In Progress|Completed|Failed|N/A",
                "comments": "Any relevant notes"
            }
        ]
    }

    RULES:
    1. Identify KKS codes first. System KKS = 3-letter prefix (JEA, JAA, etc.). Equipment KKS = 2-letter prefix (AA, AP, etc.).
    2. If scope cannot be determined from KKS, infer from context ("system" vs "equipment").
    3. Status keywords: "done", "complete", "finished", "passed" → "Completed"
    4. Status keywords: "ongoing", "in progress", "started" → "In Progress"
    5. Status keywords: "failed", "rejected", "issue" → "Failed"
    6. Status keywords: "pending", "not started", "awaiting" → "Pending"
    7. If a milestone is not mentioned, default to "Pending".
    8. For Equipment scope, PT and SAW should be "N/A".
    9. PIC (Post Installation Cleaning) must precede HT (Hydro Test).
    10. Include any anomalies or special notes in "comments".
    """

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,  # Low temperature for deterministic extraction
        "max_tokens": 4000
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=60
            )
            response.raise_for_status()

            result = response.json()
            content = result['choices'][0]['message']['content']
            parsed = json.loads(content)
            return parsed

        except requests.exceptions.HTTPError as e:
            if response.status_code == 429 and attempt < max_retries:
                wait_time = 2 ** attempt
                st.warning(f"Rate limited. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            st.error(f"Groq API HTTP Error ({response.status_code}): {str(e)}")
            return None
        except json.JSONDecodeError as e:
            st.error(f"Groq returned invalid JSON: {str(e)}")
            return None
        except Exception as e:
            st.error(f"Groq API call failed: {str(e)}")
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
        except Exception as e:
            # Fallback: try as plain text
            return file_bytes.decode('utf-8', errors='ignore')

    elif file_lower.endswith('.xlsx') or file_lower.endswith('.xls'):
        try:
            df = pd.read_excel(BytesIO(file_bytes))
            return df.to_string(index=False)
        except Exception as e:
            st.error(f"Failed to parse Excel file: {str(e)}")
            return ""

    else:
        # Plain text
        return file_bytes.decode('utf-8', errors='ignore')


def smart_chunk_text(text: str, max_chunk_size: int = 15000) -> List[str]:
    """
    Chunks text intelligently by trying to preserve record boundaries.
    Falls back to character-based chunking if no clear boundaries found.
    """
    # Try to split by double newlines (common record separator)
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

    # If any chunk is still too large, force split by single newlines
    final_chunks = []
    for chunk in chunks:
        if len(chunk) > max_chunk_size:
            lines = chunk.split('\n')
            current = ""
            for line in lines:
                if len(current) + len(line) + 1 > max_chunk_size:
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
# MAIN PROCESSING PIPELINE
# =============================================================================

def process_file_smart(file_bytes: bytes, file_name: str) -> Tuple[int, List[str]]:
    """
    Incremental, idempotent file processing pipeline.

    Args:
        file_bytes: Raw file bytes
        file_name: Original filename

    Returns:
        (records_processed, list of all alert messages)
    """
    all_alerts = []
    total_processed = 0

    # Compute file hash for idempotency
    file_hash = hashlib.md5(file_bytes).hexdigest()

    # Extract text
    raw_text = extract_text_from_file(file_bytes, file_name)
    if not raw_text.strip():
        st.error("Could not extract any text from the uploaded file.")
        return 0, ["ERROR: Empty or unreadable file"]

    # Smart chunking
    chunks = smart_chunk_text(raw_text)
    st.info(f"File split into {len(chunks)} chunk(s) for processing.")

    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, chunk in enumerate(chunks):
        status_text.text(f"Processing chunk {i+1}/{len(chunks)}...")

        # Skip already processed chunks
        if check_chunk_exists(file_hash, i):
            st.info(f"Chunk {i+1} already processed (skipping).")
            progress_bar.progress((i + 1) / len(chunks))
            continue

        # Call AI extraction
        data = ask_groq(chunk)
        if data is None:
            all_alerts.append(f"ERROR: Failed to process chunk {i+1}")
            progress_bar.progress((i + 1) / len(chunks))
            continue

        # Extract records (handle both {records: [...]} and direct dict formats)
        records = data.get("records", [])
        if not records and all(k in data for k in ['system', 'system_kks', 'component']):
            records = [data]

        st.info(f"Chunk {i+1}: Extracted {len(records)} record(s).")

        # Process each record
        for record in records:
            # Ensure KKS scope is correct
            kks = record.get('system_kks', '')
            scope = get_kks_scope(kks)

            if scope:
                record['scope_type'] = scope.value

            # Enforce scope milestones and collect alerts
            record, scope_alerts = enforce_scope_milestones(record)
            all_alerts.extend(scope_alerts)

            # Check for N/A milestone violations in the source text
            if scope == ScopeType.EQUIPMENT:
                for ms in ['pt_status', 'saw_status']:
                    src_val = record.get(ms, '')
                    if src_val not in ('N/A', 'Not Applicable', '', 'Pending'):
                        all_alerts.append(
                            f"ALERT: Source text requested action on '{ms}' for Equipment KKS '{kks}', "
                            f"but this milestone is N/A for Equipment scope. Value corrected to 'N/A'."
                        )

            # Validate dependencies
            dep_issues = validate_milestone_dependencies(record)
            all_alerts.extend(dep_issues)

            # Upsert to database
            ok, msgs = upsert_registry_row(record)
            all_alerts.extend(msgs)
            if ok:
                total_processed += 1

        # Mark chunk as done
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
    Parses natural language shift notes directly into structured records.

    Returns:
        (list of parsed records, list of alerts/warnings)
    """
    if not notes_text or not notes_text.strip():
        return [], ["ERROR: Empty shift notes provided"]

    data = ask_groq(notes_text)
    if data is None:
        return [], ["ERROR: AI extraction failed"]

    records = data.get("records", [])
    if not records and all(k in data for k in ['system', 'system_kks', 'component']):
        records = [data]

    alerts = []
    validated_records = []

    for record in records:
        kks = record.get('system_kks', '')
        scope = get_kks_scope(kks)

        if scope is None:
            alerts.append(f"WARNING: Unrecognized KKS '{kks}' in extracted record. Manual review required.")
        else:
            record['scope_type'] = scope.value
            record, scope_alerts = enforce_scope_milestones(record)
            alerts.extend(scope_alerts)

        dep_issues = validate_milestone_dependencies(record)
        alerts.extend(dep_issues)
        validated_records.append(record)

    return validated_records, alerts
