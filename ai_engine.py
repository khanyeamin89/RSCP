import json
import io
import requests
import pandas as pd
import docx  # From python-docx library
import streamlit as st

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# Flagship model optimized for high-density industrial and technical nomenclature
MODEL_NAME = "llama-3.3-70b-specdec"

def ask_cloud_ai_to_parse_chunk(prompt_content: str) -> list:
    """
    Dispatches a single block of raw operational logs directly to the Groq LPU cluster.
    Forces JSON compilation constraints and executes rigorous structure schema filtering.
    """
    api_key = st.secrets.get("GROQ_API_KEY")
    if not api_key:
        st.error("AI Engine Aborted: 'GROQ_API_KEY' is missing inside your Streamlit Cloud Settings configuration.")
        return []

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    system_instruction = """
    You are an expert automated data extraction system specialized in processing nuclear power plant commissioning logs, physical loop walkdowns, KKS equipment designations, spreadsheet rows, and component verification telemetry.
    
    Analyze the raw unstructured text input logs or table rows provided by the user and transform them cleanly into a fully structured JSON array of records.
    
    Every item inside the output JSON array MUST strictly utilize these exact structural JSON keys:
    1. "tag_id": The exact technical equipment identification tag or system alphanumeric code (e.g., '10UJA-10-AA001', '0XJA-20-AP002', 'LOOP-102'). Look for pattern sequences typical of industrial or nuclear hardware tagging. If completely absent, map strictly to an empty string "".
    2. "system": The overarching physical system loop abbreviation or unit descriptor (e.g., 'Primary Circuit', 'Ventilation System', 'Emergency Core Cooling', 'UJA System'). If unknown or highly generic, default to "General".
    3. "loop_number": The precise loop reference string, index marker, or circuit index (e.g., '1', 'A', 'Loop 03'). If not explicitly stated, map strictly to an empty string "".
    4. "description": A highly focused, technically accurate summary detailing the operational step, functional diagnostic reading, parameter measurements, or physical milestone status recorded in the entry text.
    5. "status": You must evaluate the context of the entry log and map it strictly to one of these four explicit string validation states:
       - "Pending": Action slated for execution, scheduled, or awaiting preparation.
       - "In Progress": Current physical operations, testing underway, flushing actively running, or measurements being taken.
       - "Verified": Successfully passed validation checkpoints, signed off, criteria satisfied, status green.
       - "Failed": Discovered non-conformance, component leakage, telemetry value out of tolerance bounds, or test rejected.

    CRITICAL COMPLIANCE RULES:
    - Output ONLY a valid, parseable JSON object containing a root key named "records" whose value is a list of these objects.
    - Example Output Format: { "records": [ { "tag_id": "10UJA10AA001", "system": "UJA System", "loop_number": "1", "description": "Hydrostatic pressure testing completed up to 24.5 MPa. No pressure drop observed over hold period.", "status": "Verified" } ] }
    - Do not inject markdown block wraps (e.g. ```json ... ```), preambles, notes, or conversational text. Returning anything other than raw, compilable JSON will break the parsing module pipeline.
    """

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt_content},
        ],
        "temperature": 0.0, # Purely deterministic output
        "response_format": {"type": "json_object"},
    }

    try:
        response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=45)

        if response.status_code == 200:
            result = response.json()
            raw_content = result["choices"][0]["message"]["content"].strip()
            
            try:
                parsed_data = json.loads(raw_content)
                if "records" in parsed_data and isinstance(parsed_data["records"], list):
                    return parsed_data["records"]
                elif isinstance(parsed_data, list):
                    return parsed_data
                elif isinstance(parsed_data, dict):
                    return [parsed_data]
            except json.JSONDecodeError:
                st.error(f"JSON Structure Validation Failure. Raw response preview: {raw_content[:200]}")
                return []
        else:
            st.error(f"Groq API Cloud Node Rejected Request: Code {response.status_code} - {response.text}")
            
    except requests.exceptions.Timeout:
        st.error("AI Engine Error: Network connection timed out while processing text chunk.")
    except Exception as general_error:
        st.error(f"Cloud AI engine encountered an unexpected exception: {str(general_error)}")

    return []

def universal_ai_file_parser(file_bytes: bytes, file_name: str) -> list:
    """
    Ingests raw binary bytes from Streamlit file uploader, detects file profiles 
    (TXT, LOG, CSV, XLSX, XLS, DOCX), translates tables/paragraphs to readable strings, 
    and handles batch chunk transmission workflows smoothly.
    """
    file_extension = file_name.split('.')[-1].lower()
    raw_text = ""

    try:
        # STRATEGY 1: Plain text file profiles
        if file_extension in ["txt", "log", "csv"]:
            raw_text = file_bytes.decode("utf-8", errors="ignore")
            
        # STRATEGY 2: Excel Spreadsheet structures
        elif file_extension in ["xlsx", "xls"]:
            excel_stream = io.BytesIO(file_bytes)
            # Fetch all worksheets inside the document file
            excel_workbook = pd.read_excel(excel_stream, sheet_name=None, dtype=str)
            
            text_layers = []
            for sheet_name, dataframe in excel_workbook.items():
                dataframe = dataframe.dropna(how='all') # Clean completely dead rows
                if not dataframe.empty:
                    text_layers.append(f"\n--- [EXCEL WORKSHEET: {sheet_name}] ---")
                    # Express tables as standard comma separated values for efficient LLM processing
                    text_layers.append(dataframe.to_csv(index=False))
            raw_text = "\n".join(text_layers)

        # STRATEGY 3: Word Document profiles
        elif file_extension == "docx":
            word_stream = io.BytesIO(file_bytes)
            doc_object = docx.Document(word_stream)
            text_layers = []
            
            # Step 1: Ingest text block elements
            for paragraph in doc_object.paragraphs:
                if paragraph.text.strip():
                    text_layers.append(paragraph.text)
                    
            # Step 2: Extract nested matrix tables embedded in document structures
            for table in doc_object.tables:
                text_layers.append("\n[EMBEDDED TABLE CONTEXT]")
                for row in table.rows:
                    row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if row_cells:
                        text_layers.append(" | ".join(row_cells))
                        
            raw_text = "\n".join(text_layers)
            
        else:
            st.error(f"Unsupported file format extension profile detected: .{file_extension}")
            return []

    except Exception as parsing_exception:
        st.error(f"Core Data Extraction framework failed compiling file contents: {str(parsing_exception)}")
        return []

    clean_text = raw_text.strip()
    if not clean_text:
        st.warning(f"Aborted execution: '{file_name}' did not yield any valid text strings.")
        return []

    # Stream batch chunks safely into context windows
    max_chunk_size = 65000
    all_extracted_records = []
    total_chars = len(clean_text)
    total_chunks = (total_chars // max_chunk_size) + (1 if total_chars % max_chunk_size > 0 else 0)

    for chunk_index in range(total_chunks):
        start_pos = chunk_index * max_chunk_size
        end_pos = min(start_pos + max_chunk_size, total_chars)
        text_chunk = clean_text[start_pos:end_pos]
        
        with st.spinner(f"AI engine evaluating processing layer {chunk_index + 1} of {total_chunks}..."):
            extracted_chunk = ask_cloud_ai_to_parse_chunk(text_chunk)
            if extracted_chunk:
                all_extracted_records.extend(extracted_chunk)

    return all_extracted_records
