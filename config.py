"""
Reactor Shop Commissioning - Centralized Configuration
======================================================
Contains all constants, schema definitions, and shared utilities.

KKS Coding based on Rooppur NPP document RPR-QM-AEB0001 Revision B05 (2017)
"Agreement on Using the KKS Coding System" (VGB-B 105 E 2010, VGB-B 106 E 2004)
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
# Rooppur NPP RPR-QM-AEB0001 Rev B05 (2017)
# =============================================================================

class ScopeType(str, Enum):
    SYSTEM = "System"
    EQUIPMENT = "Equipment"
    ROOM = "Room"
    UNKNOWN = "Unknown"

# -----------------------------------------------------------------------------
# F0 PREFIX (Mandatory per Rooppur agreement)
# -----------------------------------------------------------------------------
# F0 is MANDATORY and defines the scope/ownership:
#   0 = Common station (shared across all units)
#   1 = Unit 1
#   2 = Unit 2
#   9 = Temporary installations
#
# Special F0 usage per Rooppur:
#   1 & 2 = Safety train elements (redundancy separation)
#   0 = Normal operation systems
#   5 = HVAC diesel
# -----------------------------------------------------------------------------

F0_PREFIXES: Dict[str, str] = {
    "0": "Common station (shared)",
    "1": "Unit 1 / Safety train elements",
    "2": "Unit 2 / Safety train elements",
    "5": "HVAC from NO diesel-generator",
    "9": "Temporary installations",
}

F0_SAFETY_TRAINS: Set[str] = {"1", "2"}
F0_NORMAL_OPERATION: Set[str] = {"0"}
F0_HVAC_DIESEL: Set[str] = {"5"}

# -----------------------------------------------------------------------------
# F1F2F3 FUNCTIONAL SYSTEM CODES (3 letters)
# -----------------------------------------------------------------------------
# Major system families per Rooppur NPP agreement
# -----------------------------------------------------------------------------

SYSTEM_FAMILY_CODES: Dict[str, str] = {
    "A": "Networks / Switchgears",
    "B": "Power transmission / Auxiliary supply",
    "C": "I&C equipment",
    "D": "Diesel generator / Emergency power",
    "E": "Fuel / Waste",
    "F": "Nuclear fuel handling",
    "G": "Water supply / Waste removal",
    "H": "Heating / Thermal engineering",
    "I": "Instrumentation / Internal systems",
    "J": "Process systems (VVER typical)",
    "K": "HVAC / Ventilation",
    "L": "Lifting / Handling equipment",
    "M": "Machine shop / Workshop equipment",
    "N": "Nuclear island auxiliary systems",
    "O": "Oil / Lubrication systems",
    "P": "Process auxiliary systems",
    "Q": "Quality assurance / Testing",
    "R": "Reactor systems",
    "S": "Safety systems",
    "T": "Turbine / Steam systems",
    "U": "Utilities / General services",
    "V": "Vibration / Monitoring",
    "W": "Water treatment / Chemistry",
    "X": "Special systems / Spare",
    "Y": "Spare / Reserve",
    "Z": "Spare / Reserve",
}

# Valid system prefixes (F1F2F3) - All A-Z families per VGB KKS
SYSTEM_PREFIXES: Set[str] = set(
    f"{f1}{f2}{f3}"
    for f1 in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for f2 in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for f3 in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
)

# Equipment prefixes (2-letter, A1 position in equipment code)
EQUIPMENT_PREFIXES: Set[str] = set(
    f"{a1}{a2}"
    for a1 in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for a2 in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
)

# -----------------------------------------------------------------------------
# A3 ALPHABETIC CODES (Rooppur NPP specific)
# -----------------------------------------------------------------------------
# Per RPR-QM-AEB0001 Rev B05, A3 is used for:
#   - Pulse valves, Safety valves, Double drives
#   - Multiple power supply, Measurement loops
#   - Electrical phases (A, B, C)
#   - Lighting subsystems (N=working, E=emergency, F=escape)
# -----------------------------------------------------------------------------

A3_CODES: Dict[str, str] = {
    "A": "Electrical phase A",
    "B": "Electrical phase B",
    "C": "Electrical phase C",
    "N": "Lighting - Working (Normal)",
    "E": "Lighting - Emergency",
    "F": "Lighting - Escape route",
    "P": "Pulse valve",
    "S": "Safety valve",
    "D": "Double drive",
    "M": "Multiple power supply",
    "L": "Measurement loop",
    "X": "Spare / Reserve",
    "Y": "Spare / Reserve",
    "Z": "Spare / Reserve",
}

# -----------------------------------------------------------------------------
# ROOM CODING (Rooppur NPP specific)
# -----------------------------------------------------------------------------
# Room coding uses Cartesian coordinates:
#   - A1 must contain "R" (Room indicator)
#   - 3-digit numbering
#   - Special shaft codes:
#       3NN = Transport shaft
#       4NN = Cable shaft
#       5NN = Stair shaft
#       6NN = Elevator shaft
#       7NN = Reactor cavity
#       8NN = Process shaft
#       9NN = Ventilation shaft
# -----------------------------------------------------------------------------

ROOM_SHAFT_CODES: Dict[str, str] = {
    "3": "Transport shaft",
    "4": "Cable shaft",
    "5": "Stair shaft",
    "6": "Elevator shaft",
    "7": "Reactor cavity",
    "8": "Process shaft",
    "9": "Ventilation shaft",
}

# -----------------------------------------------------------------------------
# MILESTONE DEFINITIONS
# -----------------------------------------------------------------------------
# IT, PIC, HT, PT, SAW are COMMISSIONING TESTS performed during the works.
# They are NOT scope types. All tests apply to all scope types.
# -----------------------------------------------------------------------------

MILESTONE_LABELS: Dict[str, str] = {
    "it_status": "IT (Individual Test)",
    "pic_status": "PIC (Post-Install Cleaning)",
    "ht_status": "HT (Hydro Test)",
    "pt_status": "PT (Pneumatic Test)",
    "saw_status": "SAW (Start-up & Adjustment)",
}

MILESTONES: List[str] = ["it_status", "pic_status", "ht_status", "pt_status", "saw_status"]

# Valid status values for any milestone
VALID_STATUSES: Set[str] = {"Pending", "In Progress", "Completed", "Failed", "N/A", "Not Applicable"}

STATUS_LABELS: Dict[str, str] = {
    "Pending": "Pending",
    "In Progress": "In Progress",
    "Completed": "Completed",
    "Failed": "Failed",
    "N/A": "N/A",
    "Not Applicable": "Not Applicable",
}

# Milestone dependency chain: prerequisite -> dependent
# PIC must be Completed before HT can be Completed
MILESTONE_DEPENDENCIES: Dict[str, str] = {
    "pic_status": "ht_status",
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
# HELPER FUNCTIONS
# =============================================================================

def get_label(data_dict: Dict[str, str], key: str) -> str:
    """Returns a label from a dictionary."""
    return data_dict.get(key, key)


def get_display(data_dict: Dict[str, str], key: str) -> str:
    """Returns a display string from a dictionary."""
    return data_dict.get(key, key)


def sort_by_label(data_dict: Dict[str, str]) -> List[Tuple[str, str]]:
    """Sorts a dictionary by its values (labels)."""
    return sorted(data_dict.items(), key=lambda x: x[1])


# =============================================================================
# KKS VALIDATION ENGINE - Rooppur NPP RPR-QM-AEB0001 Rev B05
# =============================================================================

def validate_kks(kks_code: str) -> Tuple[bool, str, Optional[ScopeType]]:
    """
    Validates a KKS code per Rooppur NPP RPR-QM-AEB0001 Rev B05 (2017).

    KKS Structure: F0 + F1F2F3 + Fn + A1 + An + Bn
      F0  = Prefix (0=common, 1/2=units, 9=temp) - MANDATORY
      F1F2F3 = Functional system (3 letters)
      Fn  = 00-99
      A1  = Equipment unit letter
      An  = 001-999 (equipment unit numbering per Appendix B)
      Bn  = 01-99 (component)

    Returns:
        (is_valid: bool, message: str, scope: ScopeType|None)
    """
    if not kks_code or not isinstance(kks_code, str):
        return False, "KKS code must be a non-empty string", None

    kks_upper = kks_code.upper().strip()

    # Check minimum length (F0 + F1F2F3 = 4 chars minimum)
    if len(kks_upper) < 4:
        return False, f"KKS code too short ({len(kks_upper)} chars). Minimum: F0 + F1F2F3 (4 chars)", None

    # Extract F0 (first character) - MANDATORY per Rooppur
    f0 = kks_upper[0]
    if f0 not in F0_PREFIXES:
        valid_f0s = ", ".join([f"{k}={v}" for k, v in F0_PREFIXES.items()])
        return False, (
            f"Invalid F0 prefix '{f0}'. "
            f"Valid F0 per Rooppur NPP: {valid_f0s}. "
            f"F0 is MANDATORY (0=common, 1/2=units, 9=temp)"
        ), None

    # Extract F1F2F3 (next 3 characters)
    f1f2f3 = kks_upper[1:4]
    if not f1f2f3.isalpha() or len(f1f2f3) != 3:
        return False, f"Invalid F1F2F3 functional system code '{f1f2f3}'. Must be exactly 3 letters.", None

    # Determine scope from F1F2F3
    if f1f2f3 in SYSTEM_PREFIXES:
        # Check if it's a room code (contains R in A1 position)
        if len(kks_upper) >= 5 and kks_upper[4] == "R":
            return True, f"Valid Room KKS: F0={f0}, F1F2F3={f1f2f3} (Room coding per Rooppur)", ScopeType.ROOM
        family = get_system_family(f1f2f3)
        family_str = f" ({family})" if family else ""
        return True, f"Valid System KKS: F0={f0}, F1F2F3={f1f2f3}{family_str}", ScopeType.SYSTEM

    # Check for Equipment prefix (2-letter A1 code)
    if f1f2f3[:2] in EQUIPMENT_PREFIXES:
        return True, f"Valid Equipment KKS: F0={f0}, A1={f1f2f3[:2]} (Equipment unit per Appendix B)", ScopeType.EQUIPMENT

    # Check for Room code pattern (A1 contains R)
    if "R" in kks_upper[:6]:
        return True, f"Potential Room KKS: contains R indicator. Verify 3-digit numbering per Rooppur.", ScopeType.ROOM

    valid_systems = ", ".join([f"{k}={v}" for k, v in SYSTEM_FAMILY_CODES.items()])
    return (
        False,
        f"Unknown KKS code '{kks_upper}'. "
        f"F1F2F3='{f1f2f3}' not in system prefixes. "
        f"Expected System families: {valid_systems} or Equipment prefix.",
        None,
    )


def validate_f0(f0: str) -> Tuple[bool, str]:
    """
    Validates F0 prefix per Rooppur NPP specific rules.

    Returns:
        (is_valid: bool, message: str)
    """
    if not f0:
        return False, "F0 prefix is MANDATORY per Rooppur NPP RPR-QM-AEB0001 Rev B05"
    if f0 not in F0_PREFIXES:
        valid_f0s = ", ".join([f"{k}={v}" for k, v in F0_PREFIXES.items()])
        return False, (
            f"Invalid F0 '{f0}'. Valid: {valid_f0s}. "
            f"F0 defines: 0=common-station, 1/2=units, 9=temporary"
        )
    f0_data = F0_PREFIXES[f0]
    return True, f"Valid F0={f0}: {f0_data}"


def validate_room_code(room_code: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Validates room coding per Rooppur NPP Cartesian coordinate system.

    Rules:
      - A1 must contain "R"
      - 3-digit numbering
      - Special shaft codes: 3NN=transport, 4NN=cable, 5NN=stair,
        6NN=elevator, 7NN=reactor cavity, 8NN=process, 9NN=ventilation

    Returns:
        (is_valid: bool, message: str, details: dict|None)
    """
    if not room_code or not isinstance(room_code, str):
        return False, "Room code must be a non-empty string", None

    code_upper = room_code.upper().strip()

    # A1 must contain R
    if "R" not in code_upper:
        return False, "Room code A1 must contain 'R' per Rooppur NPP agreement", None

    # Extract numeric portion for shaft code check
    digits = "".join(c for c in code_upper if c.isdigit())

    if not digits:
        return False, "Room code must contain numeric coordinates (3-digit numbering)", None

    details = {
        "code": code_upper,
        "has_r": True,
        "digits": digits,
        "is_shaft": False,
        "shaft_type": None,
    }

    # Check for special shaft codes (first digit 3-9 with NN pattern)
    if len(digits) >= 3:
        first_digit = digits[0]
        if first_digit in ROOM_SHAFT_CODES:
            shaft_data = ROOM_SHAFT_CODES[first_digit]
            details["is_shaft"] = True
            details["shaft_type"] = shaft_data
            return (
                True,
                f"Valid shaft code: {shaft_data} ({digits})",
                details,
            )

    # Standard room code
    if len(digits) >= 3:
        return True, f"Valid room code with 3-digit numbering: {digits}", details

    return False, f"Room code must use 3-digit numbering. Found: {digits}", details


def validate_a3(a3_code: str) -> Tuple[bool, str]:
    """
    Validates A3 alphabetic code per Rooppur NPP specific usage.

    A3 is used for:
      - Pulse valves (P), Safety valves (S), Double drives (D)
      - Multiple power supply (M), Measurement loops (L)
      - Electrical phases (A, B, C)
      - Lighting subsystems (N=working, E=emergency, F=escape)

    Returns:
        (is_valid: bool, message: str)
    """
    if not a3_code:
        return False, "A3 code is empty"

    a3_upper = a3_code.upper().strip()

    if a3_upper in A3_CODES:
        a3_data = A3_CODES[a3_upper]
        return True, f"Valid A3 code '{a3_upper}': {a3_data}"

    valid_a3s = ", ".join([f"{k}={v}" for k, v in A3_CODES.items()])
    return False, (
        f"Unknown A3 code '{a3_upper}'. "
        f"Valid A3 per Rooppur: {valid_a3s}"
    )


def get_kks_scope(kks_code: str) -> Optional[ScopeType]:
    """Returns the scope type for a given KKS code, or None if invalid."""
    valid, _, scope = validate_kks(kks_code)
    return scope if valid else None


def get_system_family(f1f2f3: str) -> Optional[str]:
    """Returns the system family description for a given F1F2F3 code."""
    if not f1f2f3 or len(f1f2f3) < 1:
        return None
    first_char = f1f2f3[0].upper()
    return SYSTEM_FAMILY_CODES.get(first_char)


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
        prereq_val = record.get(prereq, "").strip().lower()
        dependent_val = record.get(dependent, "").strip().lower()

        if dependent_val == "completed" and prereq_val != "completed":
            prereq_label = MILESTONE_LABELS.get(prereq, prereq)
            dependent_label = MILESTONE_LABELS.get(dependent, dependent)

            violations.append(
                f"DEPENDENCY VIOLATION: '{dependent}' ({dependent_label}) is marked 'Completed' but prerequisite "
                f"'{prereq}' ({prereq_label}) is '{record.get(prereq, 'N/A')}'. "
                f"{prereq_label} must be Completed before {dependent_label}."
            )

    return violations


# =============================================================================
# RECORD VALIDATOR
# =============================================================================

def validate_record(record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Full validation of a registry record per Rooppur NPP KKS rules.
    Returns (is_valid, list_of_issues).
    """
    issues = []

    # Check required fields
    for field in REGISTRY_REQUIRED_FIELDS:
        if not record.get(field):
            issues.append(f"Missing required field: '{field}'")

    # Validate KKS (including mandatory F0)
    kks = record.get("system_kks", "")
    valid_kks, kks_msg, scope = validate_kks(kks)
    if not valid_kks:
        issues.append(f"KKS Validation Error: {kks_msg}")
    else:
        # Additional F0 validation
        if kks:
            f0 = kks[0].upper() if kks else ""
            f0_valid, f0_msg = validate_f0(f0)
            if not f0_valid:
                issues.append(f"F0 Validation Error: {f0_msg}")

    # Validate status values
    for ms in MILESTONES:
        val = record.get(ms, "")
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
