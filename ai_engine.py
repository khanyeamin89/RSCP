import io
import json
from datetime import datetime
import pandas as pd
import requests
import streamlit as st
from config import OLLAMA_URL, MILESTONES_ALL, SCOPE_MILESTONES, STATUS_COLORS

def default_status_for(scope_tier: str, milestone: str) -> str:
    return "Pending" if milestone in SCOPE_MILESTONES.get(scope_tier, []) else "N/A"

def new_registry_row(system, kks, scope_tier, component, milestone_id, comments, source):
    row = {
        "System": system, "System_KKS": kks, "Scope_Type": scope_tier, "Component": component,
        "Milestone_ID": milestone_id if pd.notna(milestone_id) else "",
        "Comments": comments, "Source": source,
        "Last_Updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    for m in MILESTONES_ALL:
        row[f"{m}_Status"] = default_status_for(scope_tier, m)
    return row

def compute_progress(row) -> float:
    applicable = SCOPE_MILESTONES.get(row["Scope_Type"], [])
    if not applicable:
        return 0.0
    completed = sum(1 for m in applicable if row.get(f"{m}_Status") == "Completed")
    return round(100 * completed / len(applicable), 1)

def badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#cbd5e1")
    label = status if status else "N/A"
    return f'<span class="badge" style="background:{color};">{label}</span>'

def find_match(df: pd.DataFrame, system: str, component: str):
    if df.empty or not system or not component:
        return None
    mask = (df["System"].str.strip().str.lower() == str(system).strip().lower()) & \
           (df["Component"].str.strip().str.lower() == str(component).strip().lower())
    matches = df[mask]
    return matches.iloc[0].to_dict() if len(matches) else None

def ask_ollama_to_parse_chunk(prompt_content: str) -> list:
    system_instruction = """
    You are an advanced nuclear commissioning data extractor. Convert input data 
    into a JSON array matching this schema:
    [
      {
        "System": "Name of system",
        "System_KKS": "KKS code or empty string",
        "Scope_Type": "Equipment" or "System",
        "Component": "Tag identifier or name of component",
        "IT_Status": "Pending"|"In Progress"|"Completed"|"Failed"|"N/A",
        "PIC_Status": "Pending"|"In Progress"|"Completed"|"Failed"|"N/A",
        "HT_Status": "Pending"|"In Progress"|"Completed"|"Failed"|"N/A",
        "PT_Status": "Pending"|"In Progress"|"Completed"|"Failed"|"N/A",
        "SAW_Status": "Pending"|"In Progress"|"Completed"|"Failed"|"N/A",
        "Comments": "Reason/remark extracted from text"
      }
    ]
    Rules:
    - Return ONLY a raw JSON array. Do not output markdown code blocks (do not use ```json).
    - If a status is missing, evaluate context or default to "Pending" (or "N/A" if Scope_Type is Equipment and milestone is PT/SAW).
    """
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": "llama3.2", "prompt": f"{system_instruction}\n\nData:\n{prompt_content}", "stream": False, "format": "json"},
            timeout=30
        )
        if response.status_code == 200:
            return json.loads(response.json().get("response", "[]"))
    except Exception as e:
        st.error(f"Ollama error: {e}")
    return []

def parse_commissioning_note_with_ai(user_input_text: str):
    """Parses single free-text shift logs from fields input."""
    records = ask_ollama_to_parse_chunk(user_input_text)
    return records[0] if isinstance(records, list) and len(records) > 0 else None

def ai_process_text_file(file_bytes: bytes) -> list:
    text = file_bytes.decode("utf-8", errors="ignore")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    extracted = []
    chunk = ""
    for p in paragraphs:
        if len(chunk) + len(p) > 2000:
            extracted.extend(ask_ollama_to_parse_chunk(chunk))
            chunk = p
        else:
            chunk += "\n\n" + p
    if chunk:
        extracted.extend(ask_ollama_to_parse_chunk(chunk))
    return extracted

def ai_process_tabular_data(df: pd.DataFrame) -> list:
    extracted = []
    df_clean = df.fillna("").astype(str)
    batch_size = 10
    for i in range(0, len(df_clean), batch_size):
        batch = df_clean.iloc[i:i+batch_size]
        serialized = ""
        for idx, row in batch.iterrows():
            r_str = ", ".join([f"{c}: {v}" for c, v in row.items() if v.strip()])
            serialized += f"[Row {idx}]: {r_str}\n"
        extracted.extend(ask_ollama_to_parse_chunk(serialized))
    return extracted

def universal_ai_file_parser(file_bytes: bytes, file_name: str) -> list:
    name_lower = file_name.lower()
    if name_lower.endswith(".txt"):
        return ai_process_text_file(file_bytes)
    elif name_lower.endswith(".csv"):
        return ai_process_tabular_data(pd.read_csv(io.BytesIO(file_bytes)))
    elif name_lower.endswith((".xlsx", ".xls")):
        xl = pd.ExcelFile(io.BytesIO(file_bytes))
        all_rows = []
        for sheet in xl.sheet_names:
            if not sheet.strip().lower().startswith("report"):
                all_rows.extend(ai_process_tabular_data(xl.parse(sheet)))
        return all_rows
    return []
