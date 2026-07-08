import json
import requests
import streamlit as st

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# Using a blazing fast, context-optimized open weights model on Groq
MODEL_NAME = "llama-3.1-8b-instant"


def ask_cloud_ai_to_parse_chunk(prompt_content: str) -> list:
    """Sends raw log block chunks directly to Groq API using JSON constraints."""
    api_key = st.secrets.get("GROQ_API_KEY")
    if not api_key:
        st.error("Missing GROQ_API_KEY inside Streamlit Secrets panel.")
        return []

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    system_instruction = """
    You are an expert system extraction assistant specialized in nuclear power plant commissioning logs, loops, design checkpoints, and mechanical verification protocols.
    Analyze the raw input text logs provided by the user and convert them into a structured JSON array of records.
    
    Each record inside the JSON array MUST strictly utilize these exact JSON keys:
    - "tag_id": The precise structural tag identifier code of the equipment or milestone (e.g., '10UJA-10-AA001', 'LOOP-102'). If not found, use "".
    - "system": The parent technical loop abbreviation or system unit descriptor (e.g., 'Primary Circuit', 'Ventilation', 'UJA System'). If unknown, default to "General".
    - "loop_number": The index loop integer or reference code if called out. If not explicitly found, use "".
    - "description": A concise, clear summary detailing the engineering status, telemetry metrics, or physical test milestones documented.
    - "status": Must strictly map to one of these four explicit validation values: "Pending", "In Progress", "Verified", or "Failed".

    CRITICAL: Output ONLY a valid JSON object containing a root key named "records" whose value is a list of these objects. 
    Do not add markdown formatting, code block fences, preambles, or conversational commentary.
    """

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt_content},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},  # Native hardware JSON enforcement
    }

    try:
        response = requests.post(
            GROQ_API_URL, json=payload, headers=headers, timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            raw_content = result["choices"][0]["message"]["content"]
            parsed_data = json.loads(raw_content)

            if "records" in parsed_data:
                return parsed_data["records"]
            if isinstance(parsed_data, list):
                return parsed_data
            return [parsed_data]
        else:
            st.error(
                f"Groq API Execution Failure: {response.status_code} - {response.text}"
            )

    except Exception as e:
        st.error(f"Cloud AI engine failed processing pipeline chunk: {e}")

    return []


def universal_ai_file_parser(file_bytes: bytes, file_name: str) -> list:
    """Decodes documents, handles string token constraints, and batches traffic to Groq."""
    try:
        raw_text = file_bytes.decode("utf-8", errors="ignore")
    except Exception as err:
        st.error(f"Character decoding routine failed: {err}")
        return []

    if not raw_text.strip():
        st.warning("The uploaded telemetry file is empty.")
        return []

    # Safe data parsing batch token length thresholds
    max_chunk_size = 75000
    all_extracted_records = []

    for i in range(0, len(raw_text), max_chunk_size):
        chunk = raw_text[i : i + max_chunk_size]
        with st.spinner(
            f"Parsing system chunk sequence {i//max_chunk_size + 1}..."
        ):
            extracted_chunk = ask_cloud_ai_to_parse_chunk(chunk)
            if extracted_chunk:
                all_extracted_records.extend(extracted_chunk)

    return all_extracted_records
