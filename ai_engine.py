"""
Reactor Shop Commissioning - AI Processing Engine
==================================================
Natural language parsing, KKS classification, and intelligent data extraction.

KKS Coding based on Rooppur NPP document RPR-QM-AEB0001 Revision B05 (2017)
"Agreement on Using the KKS Coding System" (VGB-B 105 E 2010, VGB-B 106 E 2004)
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
    validate_milestone_dependencies,
    validate_f0,
    validate_room_code,
    validate_a3,
    get_system_family,
    ScopeType,
    SYSTEM_PREFIXES,
    EQUIPMENT_PREFIXES,
    F0_PREFIXES,
    A3_CODES,
    ROOM_SHAFT_CODES,
    SYSTEM_FAMILY_CODES,
    MILESTONES,
    MILESTONE_LABELS,
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

    system_prompt = """You are a nuclear commissioning data extraction expert for the Rooppur NPP project.

Extract commissioning registry data from the provided shift notes into valid JSON.

KKS CODING RULES (Rooppur NPP RPR-QM-AEB0001 Rev B05 2017):
- KKS = Kraftwerk-Kennzeichensystem, developed by VGB (German industrialists association)
- Code structure: F0 (MANDATORY prefix) + F1F2F3 (functional system, 3 letters) + Fn (00-99) + A1 (equipment unit letter) + An (001-999) + Bn (01-99 component)
- F0 is MANDATORY: 0=common-station, 1=Unit 1, 2=Unit 2, 9=temporary
- Special F0: 1&2=safety train elements, 0=normal operation, 5=HVAC from NO diesel-generator
- System families: A=Networks/Switchgears, B=Power transmission/Auxiliary supply, C=I&C equipment, E=Fuel/Waste, F=Nuclear fuel handling, G=Water supply/Waste removal
- A3 alphabetic code: P=pulse valve, S=safety valve, D=double drive, M=multiple power supply, L=measurement loop, A/B/C=electrical phases, N=working lighting, E=emergency lighting, F=escape lighting
- Room coding: Cartesian coordinates, A1 contains R, 3-digit numbering, shaft codes: 3NN=transport, 4NN=cable, 5NN=stair, 6NN=elevator, 7NN=reactor cavity, 8NN=process, 9NN=ventilation
- Equipment unit numbering: 001-900 per Appendix B
- Milestones (COMMISSIONING TESTS - apply to ALL scope types): IT=Individual Test, PIC=Post-Install Cleaning, HT=Hydro Test, PT=Pneumatic Test, SAW=Start-up & Adjustment

OUTPUT FORMAT:
{
    "records": [
        {
            "system": "System Name",
            "system_kks": "KKS Code with mandatory F0 prefix",
            "scope_type": "System|Equipment|Room",
            "component": "Component Tag",
            "it_status": "Pending|In Progress|Completed|Failed|N/A",
            "pic_status": "Pending|In Progress|Completed|Failed|N/A",
            "ht_status": "Pending|In Progress|Completed|Failed|N/A",
            "pt_status": "Pending|In Progress|Completed|Failed|N/A",
            "saw_status": "Pending|In Progress|Completed|Failed|N/A",
            "comments": "Any relevant notes including KKS context"
        }
    ]
}

RULES:
1. Identify KKS codes first. F0 prefix is MANDATORY (0,1,2,5,9).
2. System KKS: F0 + 3-letter system code (JEA, JAA, etc.).
3. Equipment KKS: F0 + 2-letter equipment prefix (AA, AP, etc.) + numbering.
4. Room KKS: contains "R" in A1 position, uses Cartesian coordinates.
5. Status keywords: "done", "complete", "finished", "passed" -> "Completed"
6. Status keywords: "ongoing", "in progress", "started" -> "In Progress"
7. Status keywords: "failed", "rejected", "issue" -> "Failed"
8. Status keywords: "pending", "not started", "awaiting" -> "Pending"
9. If a milestone is not mentioned, default to "Pending".
10. All 5 milestones (IT, PIC, HT, PT, SAW) apply to ALL scope types. They are commissioning tests.
11. PIC (Post Installation Cleaning) must precede HT (Hydro Test).
12. Include any anomalies, KKS code issues, or special notes in "comments".
13. If scope cannot be determined from KKS, infer from context ("system" vs "equipment" vs "room").
14. If equipment unit numbering seems outside 001-900 range, note it in comments per Appendix B limitation.
"""

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
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


def smart_chunk_text(text: str, max_chunk_size: int = 15000) -> List[str]:
    """
    Chunks text intelligently by trying to preserve record boundaries.
    Falls back to character-based chunking if no clear boundaries found.
    """
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
    Post-processes an AI-extracted record to enforce Rooppur NPP KKS rules.
    Validates F0, room codes, A3 codes, and system families.

    Returns:
        (enriched_record, alerts)
    """
    alerts = []
    kks = record.get("system_kks", "")

    if not kks:
        alerts.append("WARNING: No KKS code found in extracted record")
        return record, alerts

    kks_upper = kks.upper().strip()

    # Validate F0 (mandatory)
    if len(kks_upper) >= 1:
        f0 = kks_upper[0]
        f0_valid, f0_msg = validate_f0(f0)
        if not f0_valid:
            alerts.append(f"KKS F0 ERROR: {f0_msg}")
        else:
            alerts.append(f"KKS INFO: {f0_msg}")

    # Validate system family
    if len(kks_upper) >= 4:
        f1f2f3 = kks_upper[1:4]
        family = get_system_family(f1f2f3)
        if family:
            alerts.append(f"KKS INFO: System family {f1f2f3[0]} = {family}")
        elif f1f2f3[:2] in EQUIPMENT_PREFIXES:
            alerts.append(f"KKS INFO: Equipment prefix {f1f2f3[:2]} recognized")
        else:
            alerts.append(
                f"KKS WARNING: F1F2F3='{f1f2f3}' not in known system prefixes. "
                f"Verify against Rooppur NPP system index."
            )

    # Check for room code pattern
    if "R" in kks_upper[:6]:
        room_valid, room_msg, room_details = validate_room_code(kks_upper)
        if room_valid and room_details and room_details.get("is_shaft"):
            alerts.append(f"KKS INFO: {room_msg}")
        elif room_valid:
            alerts.append(f"KKS INFO: Valid room code detected - {room_msg}")

    # Check for A3 codes in longer KKS strings
    if len(kks_upper) >= 8:
        for a3_code, a3_data in A3_CODES.items():
            if a3_code in kks_upper[7:]:
                alerts.append(f"KKS INFO: A3 code '{a3_code}' detected: {a3_data}")

    # Check equipment unit numbering (001-900 per Appendix B)
    digits = "".join(c for c in kks_upper if c.isdigit())
    if len(digits) >= 3:
        potential_an = digits[:3]
        if potential_an.isdigit():
            an_val = int(potential_an)
            if an_val > 900:
                alerts.append(
                    f"KKS WARNING: Equipment unit number {an_val} exceeds 900. "
                    f"Per Appendix B, numbering is 001-900. Verify correctness."
                )
            elif an_val == 0:
                alerts.append(
                    f"KKS WARNING: Equipment unit number 000 is invalid. "
                    f"Per Appendix B, numbering starts at 001."
                )

    return record, alerts


# =============================================================================
# MAIN PROCESSING PIPELINE
# =============================================================================

def process_file_smart(file_bytes: bytes, file_name: str) -> Tuple[int, List[str]]:
    """
    Incremental, idempotent file processing pipeline with Rooppur NPP KKS validation.

    Args:
        file_bytes: Raw file bytes
        file_name: Original filename

    Returns:
        (records_processed, list of all alert messages)
    """
    all_alerts = []
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

        if check_chunk_exists(file_hash, i):
            st.info(f"Chunk {i+1} already processed (skipping).")
            progress_bar.progress((i + 1) / len(chunks))
            continue

        data = ask_groq(chunk)
        if data is None:
            all_alerts.append(f"ERROR: Failed to process chunk {i+1}")
            progress_bar.progress((i + 1) / len(chunks))
            continue

        records = data.get("records", [])
        if not records and all(k in data for k in ['system', 'system_kks', 'component']):
            records = [data]

        st.info(f"Chunk {i+1}: Extracted {len(records)} record(s).")

        for record in records:
            record, kks_alerts = post_process_kks_record(record)
            all_alerts.extend(kks_alerts)

            kks = record.get('system_kks', '')
            scope = get_kks_scope(kks)

            if scope:
                record['scope_type'] = scope.value

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
    with Rooppur NPP KKS validation.

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

        record, kks_alerts = post_process_kks_record(record)
        alerts.extend(kks_alerts)

        scope = get_kks_scope(kks)

        if scope is None:
            alerts.append(
                f"WARNING: Unrecognized KKS '{kks}' in extracted record. "
                f"Verify F0 prefix is present (mandatory per Rooppur NPP). Manual review required."
            )
        else:
            record['scope_type'] = scope.value

        dep_issues = validate_milestone_dependencies(record)
        alerts.extend(dep_issues)
        validated_records.append(record)

    return validated_records, alerts
