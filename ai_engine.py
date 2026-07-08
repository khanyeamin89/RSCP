import io
import json
import hashlib
import pandas as pd
import requests
import streamlit as st

from database import upsert_registry_row, check_chunk_exists, mark_chunk_done
from config import get_kks_scope, MILESTONES, SCOPE_MILESTONES

ROWS_PER_CHUNK = 20        # chunk by logical rows, not raw characters
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_TIMEOUT_SECONDS = 30

# =============================================================================
# System prompt — encodes the Lead Reactor Shop Commissioning AI Assistant
# ROLE spec (KKS taxonomy, milestone definitions, scope enforcement).
# =============================================================================
SYSTEM_PROMPT = """You are the Lead Reactor Shop Commissioning AI Assistant for a nuclear power plant.

KKS Taxonomy:
- System KKS: 3-letter prefix (e.g. JEA, JAA, JEC).
- Equipment KKS: 2-letter prefix (e.g. AA, AP).

Commissioning Milestones:
- IT: Individual Test
- PIC: Post Installation Cleaning / Flushing
- HT: Hydro Test
- PT: Pneumatic Test
- SAW: Start-up and Adjustment Work

Rules:
1. Identify the KKS code for each row/record before anything else.
2. Only set a milestone status field if the input actually addresses that milestone.
   If a milestone isn't mentioned, omit that key entirely — never guess or default it.
3. Valid status values: "Pending", "In Progress", "Completed", "Failed", "N/A".
4. Output strict JSON only. No markdown, no commentary, no code fences.

The input you receive may describe MANY rows/records at once (e.g. rows from a
spreadsheet). You MUST return every one of them, not just one. Always respond
with exactly this structure, wrapping even a single record in the array:

{"records": [
  {
    "system": "...",
    "system_kks": "...",
    "component": "...",
    "it_status": "..."   ,
    "pic_status": "...",
    "ht_status": "...",
    "pt_status": "...",
    "saw_status": "...",
    "comments": "..."
  }
]}
Omit any status key not addressed by the input for that record, rather than guessing.
"""


def ask_groq(prompt: str):
    """Groq API wrapper with JSON enforcement, timeout, and error handling."""
    api_key = st.secrets.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing from Streamlit secrets.")

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=GROQ_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Groq request failed: {exc}") from exc

    try:
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Groq returned an unexpected response shape: {exc}") from exc


def apply_scope_rules(record: dict) -> tuple[dict, list[str]]:
    """
    Enforces KKS-based scope rules on a parsed record and returns any warnings
    that should be surfaced to the user (per the ROLE spec's alerting requirement).
    """
    warnings = []
    kks = record.get("system_kks", "") or ""
    component = record.get("component", "?")
    system = record.get("system", "?")

    scope = get_kks_scope(kks)
    record["scope_type"] = scope
    applicable = SCOPE_MILESTONES[scope]

    for m in MILESTONES:
        key = f"{m.lower()}_status"
        if m not in applicable:
            existing = record.get(key)
            if existing and existing != "N/A":
                warnings.append(
                    f"'{m}' is not applicable for {scope}-scope KKS '{kks}' "
                    f"({system} / {component}) — value '{existing}' was overridden to N/A."
                )
            record[key] = "N/A"
        elif key not in record:
            # Not mentioned in this note — don't overwrite an existing DB value.
            # upsert_registry_row will merge, so we simply don't set it here.
            pass

    # Dependency check: PIC should precede HT.
    if "PIC" in applicable and "HT" in applicable:
        ht_status = record.get("ht_status")
        pic_status = record.get("pic_status")
        if ht_status in ("In Progress", "Completed") and pic_status != "Completed":
            warnings.append(
                f"{system} / {component}: HT is reported as '{ht_status}' but PIC (flushing) "
                f"is not confirmed Completed. PIC should normally precede HT — please verify."
            )

    return record, warnings


def _read_rows(file_bytes: bytes, file_name: str) -> pd.DataFrame:
    """
    Parses the uploaded file into a DataFrame based on its actual type.
    The original code decoded every file — including binary .xlsx archives —
    as UTF-8 text, which produced garbage for anything but plain .csv.
    """
    lower = file_name.lower()
    if lower.endswith(".csv"):
        return pd.read_csv(io.BytesIO(file_bytes))
    elif lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(file_bytes))
    else:
        raise ValueError(f"Unsupported file type: {file_name}")


def process_file_smart(file_bytes: bytes, file_name: str) -> dict:
    """
    Incremental, resumable, row-aligned processing engine.

    Returns a summary dict: {"records_written": int, "chunks_skipped": int, "warnings": [...]}
    so the caller (dashboard.py) can surface alerts to the user instead of them
    being silently swallowed.
    """
    file_hash = hashlib.md5(file_bytes).hexdigest()
    df = _read_rows(file_bytes, file_name)

    chunks = [df.iloc[i:i + ROWS_PER_CHUNK] for i in range(0, len(df), ROWS_PER_CHUNK)]

    records_written = 0
    chunks_skipped = 0
    all_warnings = []

    for i, chunk_df in enumerate(chunks):
        if check_chunk_exists(file_hash, i):
            chunks_skipped += 1
            continue

        chunk_text = chunk_df.to_csv(index=False)

        try:
            data = ask_groq(chunk_text)
        except RuntimeError as exc:
            all_warnings.append(f"Chunk {i}: {exc}")
            continue

        records = data.get("records", [data])

        for record in records:
            record, warnings = apply_scope_rules(record)
            all_warnings.extend(warnings)
            upsert_registry_row(record)
            records_written += 1

        mark_chunk_done(file_hash, i)

    return {
        "records_written": records_written,
        "chunks_skipped": chunks_skipped,
        "warnings": all_warnings,
    }
