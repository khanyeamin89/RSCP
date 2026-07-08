import json, requests, hashlib, streamlit as st
from database import upsert_registry_row, check_chunk_exists, mark_chunk_done

def get_kks_scope(kks_code):
    """Advanced KKS Mapping Engine"""
    kks_code = str(kks_code).upper()
    system_prefixes = ('JEA', 'JAA', 'JEB', 'JAB')
    equipment_prefixes = ('AA', 'AP', 'AH', 'AT', 'AN')
    
    if kks_code.startswith(system_prefixes): return "System"
    if kks_code.startswith(equipment_prefixes): return "Equipment"
    return "Equipment" 

def ask_groq(prompt):
    """Groq API wrapper with JSON enforcement"""
    api_key = st.secrets["GROQ_API_KEY"]
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "You are a commissioning expert. Extract data to JSON format with keys: system, system_kks, scope_type, component, it_status, pic_status, ht_status, pt_status, saw_status, comments."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"}
    }
    response = requests.post("https://api.groq.com/openai/v1/chat/completions", 
                             json=payload, headers={"Authorization": f"Bearer {api_key}"})
    return json.loads(response.json()['choices'][0]['message']['content'])

def process_file_smart(file_bytes, file_name):
    """Incremental Processing Engine"""
    file_hash = hashlib.md5(file_bytes).hexdigest()
    # Simple chunking logic (splitting by newline for text or row-count for CSV)
    raw_text = file_bytes.decode('utf-8', errors='ignore')
    chunks = [raw_text[i:i+30000] for i in range(0, len(raw_text), 30000)]
    
    for i, chunk in enumerate(chunks):
        if check_chunk_exists(file_hash, i): continue
        
        data = ask_groq(chunk)
        records = data.get("records", []) if "records" in data else [data]
        
        for record in records:
            # Apply KKS-based Milestone logic
            scope = get_kks_scope(record.get('system_kks', ''))
            record['scope_type'] = scope
            if scope == 'Equipment':
                record['pt_status'] = 'N/A'
                record['saw_status'] = 'N/A'
            
            upsert_registry_row(record)
        
        mark_chunk_done(file_hash, i)
