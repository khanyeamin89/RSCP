import io
import json
import requests
import docx
import pandas as pd
import streamlit as st

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "llama-3.3-70b-versatile"


def ask_cloud_ai_to_parse_chunk(prompt_content: str) -> list:
    """Dispatches logs to the Groq API to extract specialized nuclear commissioning parameters."""
    api_key = st.secrets.get("GROQ_API_KEY")
    if not api_key:
        st.error("AI Engine Aborted: 'GROQ_API_KEY' is missing.")
        return []

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    system_instruction = """
    You are an expert automated systems extraction assistant specialized in nuclear power plant commissioning analytics, KKS (Kraftwerk-Kennzeichensystem) parsing formats, and loop testing protocols.
    
    Analyze the raw input text logs, spreadsheet rows, or document sections and convert them cleanly into a structured JSON array of records.
    
    Each record inside the JSON array MUST strictly utilize these exact JSON keys:
    1. "tag_id": General loop code, milestone tag, or reference string if explicitly labeled. If absent, map to "".
    2. "system": The parent physical unit loop designation (e.g., 'Primary Circuit', 'Ventilation System'). Default to 'General' if unclear.
    3. "loop_number": The index identifier string or circuit line index. Map to "" if missing.
    4. "description": A highly focused, professionally written engineering summary of the operational work executed.
    5. "status": Strictly evaluate the text context and map to one of these four string validation parameters: "Pending", "In Progress", "Verified", or "Failed".
    6. "system_kks": The parent system KKS alphanumeric string (e.g., '10UJA', '10YCB', '0XJA'). If missing, map to "".
    7. "equipment_kks": The exact components KKS alphanumeric identifier code (e.g., '10UJA10AA001', '0XJA20AP002'). If missing, map to "".
    8. "commissioning_stage": Identify the active phase or milestone (e.g., 'Phase A - Pre-operational checks', 'Phase B - Hydrostatic Testing', 'Hot Functional Test', 'Pre-commissioning flush').
    9. "test_remarks": Specific diagnostic telemetry values, measurements (e.g., '24.5 MPa', 'vibrations balanced'), or specific observations recorded during the work.
    10. "execution_date": Look for calendar execution timestamps within the log text. Extract and format strictly as an ISO standard date string 'YYYY-MM-DD'. If no concrete date is found inside the text, return an empty string "".

    CRITICAL COMPLIANCE RULES:
    - Output ONLY a valid JSON object containing a root key named "records" whose value is a list of these objects.
    - Example: { "records": [ { "tag_id": "LOOP-101", "system": "UJA System", "loop_number": "1", "description": "Pre-operational visual inspection finalized on the main circuit lines.", "status": "Verified", "system_kks": "10UJA", "equipment_kks": "10UJA10AA001", "commissioning_stage": "Phase A - Pre-operational", "test_remarks": "No cracks detected, welds authenticated.", "execution_date": "2026-07-08" } ] }
    - Do not inject markdown block wraps (e.g. ```json), notes, or conversational text. Returning anything other than raw, compilable JSON will crash the app.
    """

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt_content},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    try:
        response = requests.post(
            GROQ_API_URL, json=payload, headers=headers, timeout=45
        )

        if response.status_code == 200:
            result = response.json()
            raw_content = result["choices"][0]["message"]["content"].strip()

            try:
                parsed_data = json.loads(raw_content)
                if "records" in parsed_data and isinstance(
                    parsed_data["records"], list
                ):
                    return parsed_data["records"]
                elif isinstance(parsed_data, list):
                    return parsed_data
                elif isinstance(parsed_data, dict):
                    return [parsed_data]
            except json.JSONDecodeError:
                st.error(
                    f"JSON Structure Validation Failure. Raw response preview: {raw_content[:200]}"
                )
                return []
        else:
            st.error(
                f"Groq API Cloud Node Rejected Request: Code {response.status_code} - {response.text}"
            )

    except requests.exceptions.Timeout:
        st.error("AI Engine Error: Network connection timed out.")
    except Exception as general_error:
        st.error(
            f"Cloud AI engine encountered an unexpected exception: {str(general_error)}"
        )

    return []


def universal_ai_file_parser(file_bytes: bytes, file_name: str) -> list:
    """Ingests multi-format documents (TXT, LOG, CSV, XLSX, XLS, DOCX) and streams them through the chunking pipeline."""
    file_extension = file_name.split(".")[-1].lower()
    raw_text = ""

    try:
        if file_extension in ["txt", "log", "csv"]:
            raw_text = file_bytes.decode("utf-8", errors="ignore")

        elif file_extension in ["xlsx", "xls"]:
            excel_stream = io.BytesIO(file_bytes)
            excel_workbook = pd.read_excel(
                excel_stream, sheet_name=None, dtype=str
            )

            text_layers = []
            for sheet_name, dataframe in excel_workbook.items():
                dataframe = dataframe.dropna(how="all")
                if not dataframe.empty:
                    text_layers.append(
                        f"\n--- [EXCEL WORKSHEET: {sheet_name}] ---"
                    )
                    text_layers.append(dataframe.to_csv(index=False))
            raw_text = "\n".join(text_layers)

        elif file_extension == "docx":
            word_stream = io.BytesIO(file_bytes)
            doc_object = docx.Document(word_stream)
            text_layers = []

            for paragraph in doc_object.paragraphs:
                if paragraph.text.strip():
                    text_layers.append(paragraph.text)

            for table in doc_object.tables:
                text_layers.append("\n[EMBEDDED TABLE CONTEXT]")
                for row in table.rows:
                    row_cells = [
                        cell.text.strip()
                        for cell in row.cells
                        if cell.text.strip()
                    ]
                    if row_cells:
                        text_layers.append(" | ".join(row_cells))

            raw_text = "\n".join(text_layers)

        else:
            st.error(
                f"Unsupported file format extension profile detected: .{file_extension}"
            )
            return []

    except Exception as parsing_exception:
        st.error(
            f"Core Data Extraction framework failed compiling file contents: {str(parsing_exception)}"
        )
        return []

    clean_text = raw_text.strip()
    if not clean_text:
        st.warning(
            f"Aborted execution: '{file_name}' did not yield any valid text strings."
        )
        return []

    max_chunk_size = 65000
    all_extracted_records = []
    total_chars = len(clean_text)
    total_chunks = (total_chars // max_chunk_size) + (
        1 if total_chars % max_chunk_size > 0 else 0
    )

    for chunk_index in range(total_chunks):
        start_pos = chunk_index * max_chunk_size
        end_pos = min(start_pos + max_chunk_size, total_chars)
        text_chunk = clean_text[start_pos:end_pos]

        with st.spinner(
            f"AI engine evaluating processing layer {chunk_index + 1} of {total_chunks}..."
        ):
            extracted_chunk = ask_cloud_ai_to_parse_chunk(text_chunk)
            if extracted_chunk:
                all_extracted_records.extend(extracted_chunk)

    return all_extracted_records
