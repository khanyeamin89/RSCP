import json
import requests
import streamlit as st

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# Using the flagship large-context, accurate model for handling technical equipment nomenclature
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
    You are an expert automated systems extraction system specialized in processing nuclear power plant commissioning logs, physical loop walkdowns, KKS equipment designations, and component verification telemetry.
    
    Analyze the raw unstructured text input logs provided by the user and transform them cleanly into a fully structured JSON array of records.
    
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
        "temperature": 0.0, # Complete determinism for rigid engineering classifications
        "response_format": {"type": "json_object"}, # Hardware level JSON validation enforcement
    }

    try:
        response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=45)

        if response.status_code == 200:
            result = response.json()
            raw_content = result["choices"][0]["message"]["content"].strip()
            
            # Robust extraction parsing block
            try:
                parsed_data = json.loads(raw_content)
                if "records" in parsed_data and isinstance(parsed_data["records"], list):
                    return parsed_data["records"]
                elif isinstance(parsed_data, list):
                    return parsed_data
                elif isinstance(parsed_data, dict):
                    return [parsed_data]
            except json.JSONDecodeError as decode_err:
                st.error(f"JSON Structure Validation Failure. Raw response preview: {raw_content[:200]}")
                return []
        else:
            st.error(f"Groq API Cloud Node Rejected Request: Code {response.status_code} - {response.text}")
            
    except requests.exceptions.Timeout:
        st.error("AI Engine Error: Network connection timed out while processing text chunk.")
    except Exception as general_error:
        st.error(f"Cloud AI engine encountered an unexpected processing pipeline exception: {str(general_error)}")

    return []

def universal_ai_file_parser(file_bytes: bytes, file_name: str) -> list:
    """
    Ingests binary input document files from the dashboard, manages safe string conversion,
    implements a rolling buffer chunking mechanism to respect LLM window contexts, and compiles results.
    """
    try:
        raw_text = file_bytes.decode("utf-8", errors="ignore")
    except Exception as decode_error:
        st.error(f"Character decoding routine failed to process input binary payload: {str(decode_error)}")
        return []

    clean_text = raw_text.strip()
    if not clean_text:
        st.warning(f"Aborted file processing execution: '{file_name}' appears to contain no text characters.")
        return []

    # Safe chunk sizing bounds (roughly 15,000 to 20,000 words to safeguard API window ceilings)
    max_chunk_size = 65000
    all_extracted_records = []

    # Calculate total processing load for UI readability
    total_chars = len(clean_text)
    total_chunks = (total_chars // max_chunk_size) + (1 if total_chars % max_chunk_size > 0 else 0)

    for chunk_index in range(total_chunks):
        start_pos = chunk_index * max_chunk_size
        end_pos = min(start_pos + max_chunk_size, total_chars)
        text_chunk = clean_text[start_pos:end_pos]
        
        with st.spinner(f"AI Core processing document chunk batch {chunk_index + 1} of {total_chunks}..."):
            extracted_chunk = ask_cloud_ai_to_parse_chunk(text_chunk)
            if extracted_chunk:
                all_extracted_records.extend(extracted_chunk)

    return all_extracted_records
