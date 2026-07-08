import streamlit as st
from config import get_supabase_client


def insert_records_to_supabase(records_list: list) -> bool:
    """Ingests an array of structured dictionary records and performs a bulk insert

    transaction into the target Supabase relational table ('rscp_logs').
    """
    if not records_list:
        st.warning(
            "Database layer execution bypassed: Ingested record array is empty."
        )
        return False

    supabase = get_supabase_client()

    sanitized_records = []
    required_keys = {"tag_id", "system", "loop_number", "description", "status"}

    for idx, record in enumerate(records_list):
        if not isinstance(record, dict):
            continue
        clean_record = {key: record.get(key, "") for key in required_keys}
        if not clean_record["system"]:
            clean_record["system"] = "General"
        if clean_record["status"] not in [
            "Pending",
            "In Progress",
            "Verified",
            "Failed",
        ]:
            clean_record["status"] = "Pending"

        sanitized_records.append(clean_record)

    try:
        response = (
            supabase.table("rscp_logs").insert(sanitized_records).execute()
        )
        if hasattr(response, "data") and response.data:
            return True
        else:
            st.error(
                "Database Transaction Failure: Operation completed but no confirmation rows were generated."
            )
            return False

    except Exception as db_transaction_error:
        st.error(
            f"Critical Database Write Exception Raised: {str(db_transaction_error)}"
        )
        return False


def fetch_all_records_from_supabase() -> list:
    """Queries the master 'rscp_logs' relational table, retrieving the full

    historical sequence of logged entries sorted chronologically.
    """
    supabase = get_supabase_client()
    try:
        response = (
            supabase.table("rscp_logs")
            .select(
                "id, tag_id, system, loop_number, description, status, created_at"
            )
            .order("created_at", descending=True)
            .execute()
        )
        if hasattr(response, "data"):
            return response.data
        return []
    except Exception as db_query_error:
        st.error(
            f"Critical Database Read Exception Raised: {str(db_query_error)}"
        )
        return []
