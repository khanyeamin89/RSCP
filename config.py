"""
Reactor Shop Commissioning - Centralized Configuration
======================================================
Contains all constants, schema definitions, and shared utilities.
"""

import streamlit as st
from supabase import create_client
from functools import lru_cache
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum

# =============================================================================
# PAGE CONFIGURATION
# =============================================================================

PAGE_TITLE = "Reactor Shop Commissioning Dashboard"
PAGE_ICON = "⚛️"

# =============================================================================
# KKS TAXONOMY DEFINITIONS
# =============================================================================

class ScopeType(str, Enum):
    SYSTEM = "System"
    EQUIPMENT = "Equipment"

# Valid KKS prefixes by scope
SYSTEM_PREFIXES: Set[str] = {'JEA', 'JAA', 'JEB', 'JAB', 'JEC', 'JAC', 'JED', 'JAD'}
EQUIPMENT_PREFIXES: Set[str] = {'AA', 'AP', 'AH', 'AT', 'AN', 'AB', 'AC', 'AD', 'AE'}

# Milestone field names
MILESTONES: List[str] = ['it_status', 'pic_status', 'ht_status', 'pt_status', 'saw_status']

# Milestones that are N/A for Equipment scope
EQUIPMENT_NA_MILESTONES: Set[str] = {'pt_status', 'saw_status'}

# Valid status values for any milestone
VALID_STATUSES: Set[str] = {"Pending", "In Progress", "Completed", "Failed", "N/A", "Not Applicable"}

# Milestone dependency chain: prerequisite -> dependent
MILESTONE_DEPENDENCIES: Dict[str, str] = {
    'pic_status': 'ht_status',   # PIC must be Completed before HT can be Completed
}

# =============================================================================
# DATABASE SCHEMA (Registry Table)
# =============================================================================

REGISTRY_SCHEMA: Dict[str, type] = {
    "system": str,
    "system_kks": str,
    "scope_type": str,
    "component": str,
    "it_status": str,
    "pic_status": str,
    "ht_status": str,
    "pt_status": str,
    "saw_status": str,
    "comments": str,
}

REGISTRY_REQUIRED_FIELDS: Set[str] = {"system", "component", "system_kks"}
REGISTRY_UNIQUE_KEYS: List[str] = ["system", "component"]

# =============================================================================
# SUPABASE CLIENT (Single Source of Truth)
# =============================================================================

@st.cache_resource(show_spinner=False)
def get_supabase_client():
    """
    Initializes and caches the connection to the Supabase backend.
    Enforces strict verification of environment variables before allowing execution.
    """
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")

    if not url or not key:
        st.error(
            "CRITICAL ERROR: Supabase connection parameters ('SUPABASE_URL' and 'SUPABASE_KEY') "
            "are missing from the Streamlit Secrets environment. Application execution halted."
        )
        st.stop()

    try:
        client = create_client(url, key)
        # Verify connection with a lightweight ping
        client.table("registry").select("count", count="exact").limit(0).execute()
        return client
    except Exception as initialization_error:
        st.error(f"Failed to establish Supabase Client core interface: {str(initialization_error)}")
        st.stop()

# =============================================================================
# KKS VALIDATION ENGINE
# =============================================================================

def validate_kks(kks_code: str) -> Tuple[bool, str, Optional[ScopeType]]:
    """
    Validates a KKS code and determines its scope.

    Returns:
        (is_valid: bool, message: str, scope: ScopeType|None)
    """
    if not kks_code or not isinstance(kks_code, str):
        return False, "KKS code must be a non-empty string", None

    kks_upper = kks_code.upper().strip()
    prefix = ''.join(c for c in kks_upper if c.isalpha())[:3]  # Extract leading letters

    if prefix in SYSTEM_PREFIXES:
        return True, f"Valid System KKS: {prefix}", ScopeType.SYSTEM
    elif prefix[:2] in EQUIPMENT_PREFIXES:
        return True, f"Valid Equipment KKS: {prefix[:2]}", ScopeType.EQUIPMENT
    else:
        return False, f"Unknown KKS prefix '{prefix}'. Expected System: {SYSTEM_PREFIXES} or Equipment: {EQUIPMENT_PREFIXES}", None


def get_kks_scope(kks_code: str) -> Optional[ScopeType]:
    """Returns the scope type for a given KKS code, or None if invalid."""
    valid, _, scope = validate_kks(kks_code)
    return scope if valid else None


def enforce_scope_milestones(record: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Enforces milestone rules based on KKS scope.
    - System: all milestones active
    - Equipment: PT and SAW set to 'N/A'

    Returns:
        (enriched_record, alerts)
    """
    alerts = []
    kks = record.get('system_kks', '')
    scope = get_kks_scope(kks)

    if scope is None:
        alerts.append(f"WARNING: Could not determine scope for KKS '{kks}'. Leaving milestones as-is.")
        return record, alerts

    record['scope_type'] = scope.value

    if scope == ScopeType.EQUIPMENT:
        for ms in EQUIPMENT_NA_MILESTONES:
            current = record.get(ms, '')
            if current and current not in ('N/A', 'Not Applicable', ''):
                alerts.append(
                    f"ALERT: KKS '{kks}' (Equipment scope) has non-N/A value '{current}' for '{ms}'. "
                    f"Auto-corrected to 'N/A'. Equipment does not require {ms.replace('_status', '').upper()}."
                )
            record[ms] = 'N/A'

    return record, alerts


# =============================================================================
# MILESTONE DEPENDENCY VALIDATOR
# =============================================================================

def validate_milestone_dependencies(record: Dict[str, Any]) -> List[str]:
    """
    Validates that milestone dependencies are satisfied.
    Currently enforces: PIC must be 'Completed' before HT can be 'Completed'.

    Returns list of violation messages (empty if all valid).
    """
    violations = []

    for prereq, dependent in MILESTONE_DEPENDENCIES.items():
        prereq_val = record.get(prereq, '').strip().lower()
        dependent_val = record.get(dependent, '').strip().lower()

        if dependent_val == 'completed' and prereq_val != 'completed':
            violations.append(
                f"DEPENDENCY VIOLATION: '{dependent}' is marked 'Completed' but prerequisite "
                f"'{prereq}' is '{record.get(prereq, 'N/A')}'. "
                f"{prereq.replace('_status', '').upper()} must be Completed before {dependent.replace('_status', '').upper()}."
            )

    return violations


# =============================================================================
# RECORD VALIDATOR
# =============================================================================

def validate_record(record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Full validation of a registry record.
    Returns (is_valid, list_of_issues).
    """
    issues = []

    # Check required fields
    for field in REGISTRY_REQUIRED_FIELDS:
        if not record.get(field):
            issues.append(f"Missing required field: '{field}'")

    # Validate KKS
    kks = record.get('system_kks', '')
    valid_kks, kks_msg, scope = validate_kks(kks)
    if not valid_kks:
        issues.append(f"KKS Validation Error: {kks_msg}")

    # Validate status values
    for ms in MILESTONES:
        val = record.get(ms, '')
        if val and val not in VALID_STATUSES:
            issues.append(f"Invalid status '{val}' for '{ms}'. Valid: {VALID_STATUSES}")

    # Check dependencies
    dep_issues = validate_milestone_dependencies(record)
    issues.extend(dep_issues)

    return len(issues) == 0, issues


# =============================================================================
# CUSTOM CSS
# =============================================================================

def apply_custom_css():
    """
    Injects custom CSS styling into the Streamlit DOM to optimize workspace layout,
    improve visual hierarchy, and enforce professional engineering aesthetics.
    """
    st.markdown(
        """
        <style>
        /* Optimize viewport real estate */
        .block-container { 
            padding-top: 1.5rem; 
            padding-bottom: 1.5rem; 
            max-width: 95% !important;
        }

        /* Typography Polish */
        h1 { color: #0F172A; font-weight: 800; letter-spacing: -0.05em; }
        h2 { color: #1E3A8A; font-weight: 700; border-bottom: 2px solid #E2E8F0; padding-bottom: 0.25rem; }
        h3 { color: #0369A1; font-weight: 600; }

        /* Metric Box Adjustments */
        [data-testid="stMetricValue"] { font-size: 2.2rem; font-weight: 700; color: #1E293B; }
        [data-testid="stMetricLabel"] { font-weight: 600; color: #64748B; text-transform: uppercase; font-size: 0.8rem; }

        /* Status Badges */
        .badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; }
        .badge-verified { background-color: #DCFCE7; color: #15803D; }
        .badge-progress { background-color: #FEF9C3; color: #A16207; }
        .badge-pending { background-color: #F1F5F9; color: #475569; }
        .badge-failed { background-color: #FEE2E2; color: #B91C1C; }
        .badge-na { background-color: #E2E8F0; color: #475569; font-style: italic; }

        /* Alert Boxes */
        .alert-box {
            padding: 12px 16px;
            border-radius: 8px;
            margin: 8px 0;
            border-left: 4px solid;
        }
        .alert-warning { background-color: #FEF9C3; border-color: #EAB308; color: #854D0E; }
        .alert-error { background-color: #FEE2E2; border-color: #EF4444; color: #991B1B; }
        .alert-info { background-color: #DBEAFE; border-color: #3B82F6; color: #1E40AF; }
        </style>
        """,
        unsafe_allow_html=True,
    )
