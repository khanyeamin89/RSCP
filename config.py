"""
Reactor Shop Commissioning - Centralized Configuration
======================================================
Contains all constants, schema definitions, and shared utilities.

KKS Coding based on Rooppur NPP document RPR-QM-AEB0001 Revision B05 (2017)
"Agreement on Using the KKS Coding System" (VGB-B 105 E 2010, VGB-B 106 E 2004)

Bilingual support: Russian (original document language) -> English translations
for all KKS terminology, system families, and coding elements.
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
# BILINGUAL KKS TAXONOMY DEFINITIONS
# Rooppur NPP RPR-QM-AEB0001 Rev B05 (2017)
# =============================================================================

class ScopeType(str, Enum):
    SYSTEM = "System"
    EQUIPMENT = "Equipment"
    ROOM = "Room"
    UNKNOWN = "Unknown"

# -----------------------------------------------------------------------------
# F0 PREFIX (Mandatory per Rooppur agreement) - Bilingual
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
#   5 = HVAC from NO diesel-generator
# -----------------------------------------------------------------------------

F0_PREFIXES: Dict[str, Dict[str, str]] = {
    "0": {
        "en": "Common station (shared)",
        "ru": "Общестанционные (общие для всех блоков)",
    },
    "1": {
        "en": "Unit 1 / Safety train elements",
        "ru": "Блок 1 / Элементы системы безопасности",
    },
    "2": {
        "en": "Unit 2 / Safety train elements",
        "ru": "Блок 2 / Элементы системы безопасности",
    },
    "5": {
        "en": "HVAC from NO diesel-generator",
        "ru": "ОВиК от дизель-генератора нормальной эксплуатации",
    },
    "9": {
        "en": "Temporary installations",
        "ru": "Временные установки",
    },
}

F0_SAFETY_TRAINS: Set[str] = {"1", "2"}  # Safety train elements
F0_NORMAL_OPERATION: Set[str] = {"0"}       # Normal operation
F0_HVAC_DIESEL: Set[str] = {"5"}            # HVAC from NO diesel-generator

# -----------------------------------------------------------------------------
# F1F2F3 FUNCTIONAL SYSTEM CODES (3 letters) - Bilingual
# -----------------------------------------------------------------------------
# Major system families per Rooppur NPP agreement:
#   A = Networks / Switchgears
#   B = Power transmission / Auxiliary supply
#   C = I&C equipment
#   E = Fuel / Waste
#   F = Nuclear fuel handling
#   G = Water supply / Waste removal
# -----------------------------------------------------------------------------

SYSTEM_FAMILY_CODES: Dict[str, Dict[str, str]] = {
    "A": {
        "en": "Networks / Switchgears",
        "ru": "Сети / Распределительные устройства",
    },
    "B": {
        "en": "Power transmission / Auxiliary supply",
        "ru": "Передача энергии / Вспомогательное питание",
    },
    "C": {
        "en": "I&C equipment",
        "ru": "Оборудование КИПиА",
    },
    "D": {
        "en": "Diesel generator / Emergency power",
        "ru": "Дизель-генератор / Аварийное питание",
    },
    "E": {
        "en": "Fuel / Waste",
        "ru": "Топливо / Отходы",
    },
    "F": {
        "en": "Nuclear fuel handling",
        "ru": "Обращение с ядерным топливом",
    },
    "G": {
        "en": "Water supply / Waste removal",
        "ru": "Водоснабжение / Удаление отходов",
    },
    "H": {
        "en": "Heating / Thermal engineering",
        "ru": "Отопление / Теплотехника",
    },
    "I": {
        "en": "Instrumentation / Internal systems",
        "ru": "Приборы / Внутренние системы",
    },
    "J": {
        "en": "Process systems (VVER typical)",
        "ru": "Технологические системы (типичные для ВВЭР)",
    },
    "K": {
        "en": "HVAC / Ventilation",
        "ru": "ОВиК / Вентиляция",
    },
    "L": {
        "en": "Lifting / Handling equipment",
        "ru": "Подъемно-транспортное оборудование",
    },
    "M": {
        "en": "Machine shop / Workshop equipment",
        "ru": "Механический цех / Слесарное оборудование",
    },
    "N": {
        "en": "Nuclear island auxiliary systems",
        "ru": "Вспомогательные системы ядерного острова",
    },
    "O": {
        "en": "Oil / Lubrication systems",
        "ru": "Маслосистемы / Смазка",
    },
    "P": {
        "en": "Process auxiliary systems",
        "ru": "Вспомогательные технологические системы",
    },
    "Q": {
        "en": "Quality assurance / Testing",
        "ru": "Обеспечение качества / Испытания",
    },
    "R": {
        "en": "Reactor systems",
        "ru": "Реакторные системы",
    },
    "S": {
        "en": "Safety systems",
        "ru": "Системы безопасности",
    },
    "T": {
        "en": "Turbine / Steam systems",
        "ru": "Турбина / Паровые системы",
    },
    "U": {
        "en": "Utilities / General services",
        "ru": "Коммунальные системы / Общие службы",
    },
    "V": {
        "en": "Vibration / Monitoring",
        "ru": "Вибрация / Мониторинг",
    },
    "W": {
        "en": "Water treatment / Chemistry",
        "ru": "Водоподготовка / Химия",
    },
    "X": {
        "en": "Special systems / Spare",
        "ru": "Специальные системы / Резерв",
    },
    "Y": {
        "en": "Spare / Reserve",
        "ru": "Резерв",
    },
    "Z": {
        "en": "Spare / Reserve",
        "ru": "Резерв",
    },
}}

# Valid system prefixes (F1F2F3) - All A-Z families per VGB KKS
# Generated programmatically: 26 families × 26 subsystems × 26 variants = 17,576 codes
# Covers all possible 3-letter functional system codes

SYSTEM_PREFIXES: Set[str] = set(
    f"{f1}{f2}{f3}"
    for f1 in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for f2 in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for f3 in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
)

# Equipment prefixes (2-letter, A1 position in equipment code)
# Equipment prefixes (2-letter, A1 position in equipment code)
# All A-Z combinations per VGB KKS Appendix B
# Covers all possible 2-letter equipment unit codes: 26 × 26 = 676 combinations

EQUIPMENT_PREFIXES: Set[str] = set(
    f"{a1}{a2}"
    for a1 in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for a2 in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
)

# -----------------------------------------------------------------------------
# A3 ALPHABETIC CODES (Rooppur NPP specific) - Bilingual
# -----------------------------------------------------------------------------
# Per RPR-QM-AEB0001 Rev B05, A3 is used for:
#   - Pulse valves
#   - Safety valves
#   - Double drives
#   - Multiple power supply
#   - Measurement loops
#   - Electrical phases (A, B, C)
#   - Lighting subsystems (N=working, E=emergency, F=escape)
# -----------------------------------------------------------------------------

A3_CODES: Dict[str, Dict[str, str]] = {
    # Electrical phases
    "A": {
        "en": "Electrical phase A",
        "ru": "Электрическая фаза A",
    },
    "B": {
        "en": "Electrical phase B",
        "ru": "Электрическая фаза B",
    },
    "C": {
        "en": "Electrical phase C",
        "ru": "Электрическая фаза C",
    },
    # Lighting subsystems
    "N": {
        "en": "Lighting - Working (Normal)",
        "ru": "Освещение - Рабочее (Нормальное)",
    },
    "E": {
        "en": "Lighting - Emergency",
        "ru": "Освещение - Аварийное",
    },
    "F": {
        "en": "Lighting - Escape route",
        "ru": "Освещение - Эвакуационное",
    },
    # Valve types
    "P": {
        "en": "Pulse valve",
        "ru": "Импульсный клапан",
    },
    "S": {
        "en": "Safety valve",
        "ru": "Предохранительный клапан",
    },
    # Drive types
    "D": {
        "en": "Double drive",
        "ru": "Двойной привод",
    },
    # Power supply
    "M": {
        "en": "Multiple power supply",
        "ru": "Множественное питание",
    },
    # Measurement loops
    "L": {
        "en": "Measurement loop",
        "ru": "Измерительный контур",
    },
    # Additional common codes
    "X": {
        "en": "Spare / Reserve",
        "ru": "Резерв",
    },
    "Y": {
        "en": "Spare / Reserve",
        "ru": "Резерв",
    },
    "Z": {
        "en": "Spare / Reserve",
        "ru": "Резерв",
    },
}

# -----------------------------------------------------------------------------
# ROOM CODING (Rooppur NPP specific) - Bilingual
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

ROOM_SHAFT_CODES: Dict[str, Dict[str, str]] = {
    "3": {
        "en": "Transport shaft",
        "ru": "Транспортный шахтный ствол",
    },
    "4": {
        "en": "Cable shaft",
        "ru": "Кабельный шахтный ствол",
    },
    "5": {
        "en": "Stair shaft",
        "ru": "Лестничный шахтный ствол",
    },
    "6": {
        "en": "Elevator shaft",
        "ru": "Лифтовой шахтный ствол",
    },
    "7": {
        "en": "Reactor cavity",
        "ru": "Реакторный колодец",
    },
    "8": {
        "en": "Process shaft",
        "ru": "Технологический шахтный ствол",
    },
    "9": {
        "en": "Ventilation shaft",
        "ru": "Вентиляционный шахтный ствол",
    },
}

# -----------------------------------------------------------------------------
# MILESTONE DEFINITIONS - Bilingual
# -----------------------------------------------------------------------------

MILESTONE_LABELS: Dict[str, Dict[str, str]] = {
    "it_status": {
        "en": "IT (Individual Test)",
        "ru": "ИО (Индивидуальные испытания)",
    },
    "pic_status": {
        "en": "PIC (Post-Install Cleaning)",
        "ru": "ПОМ (Послеустановочная мойка)",
    },
    "ht_status": {
        "en": "HT (Hydro Test)",
        "ru": "ГИ (Гидравлические испытания)",
    },
    "pt_status": {
        "en": "PT (Pneumatic Test)",
        "ru": "ПН (Пневматические испытания)",
    },
    "saw_status": {
        "en": "SAW (Start-up & Adjustment)",
        "ru": "ПНР (Пусконаладочные работы)",
    },
}

MILESTONES: List[str] = ["it_status", "pic_status", "ht_status", "pt_status", "saw_status"]

# Milestones that are N/A for Equipment scope
EQUIPMENT_NA_MILESTONES: Set[str] = {"pt_status", "saw_status"}

# Valid status values for any milestone - Bilingual
VALID_STATUSES: Set[str] = {"Pending", "In Progress", "Completed", "Failed", "N/A", "Not Applicable"}

STATUS_LABELS: Dict[str, Dict[str, str]] = {
    "Pending": {"en": "Pending", "ru": "В ожидании"},
    "In Progress": {"en": "In Progress", "ru": "В работе"},
    "Completed": {"en": "Completed", "ru": "Выполнено"},
    "Failed": {"en": "Failed", "ru": "Не пройдено"},
    "N/A": {"en": "N/A", "ru": "Н/П"},
    "Not Applicable": {"en": "Not Applicable", "ru": "Не применимо"},
}

# Milestone dependency chain: prerequisite -> dependent
MILESTONE_DEPENDENCIES: Dict[str, str] = {
    "pic_status": "ht_status",   # PIC must be Completed before HT can be Completed
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
# BILINGUAL HELPER FUNCTIONS
# =============================================================================

def get_bilingual_label(data_dict: Dict[str, Dict[str, str]], key: str, lang: str = "en") -> str:
    """Returns a label in the specified language from a bilingual dictionary."""
    if key in data_dict and lang in data_dict[key]:
        return data_dict[key][lang]
    return key


def get_bilingual_display(data_dict: Dict[str, Dict[str, str]], key: str) -> str:
    """Returns a bilingual display string: English (Russian)."""
    if key in data_dict:
        en = data_dict[key].get("en", "")
        ru = data_dict[key].get("ru", "")
        if en and ru:
            return f"{en} ({ru})"
        return en or ru or key
    return key


def sort_by_russian(data_dict: Dict[str, Dict[str, str]]) -> List[Tuple[str, Dict[str, str]]]:
    """Sorts a bilingual dictionary by Russian label."""
    return sorted(data_dict.items(), key=lambda x: x[1].get("ru", x[0]))


def sort_by_english(data_dict: Dict[str, Dict[str, str]]) -> List[Tuple[str, Dict[str, str]]]:
    """Sorts a bilingual dictionary by English label."""
    return sorted(data_dict.items(), key=lambda x: x[1].get("en", x[0]))

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
        valid_f0s = ", ".join([f"{k}={v['en']}" for k, v in F0_PREFIXES.items()])
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

    valid_systems = ", ".join([f"{k}={v['en']}" for k, v in SYSTEM_FAMILY_CODES.items()])
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
        valid_f0s = ", ".join([f"{k}={v['en']}" for k, v in F0_PREFIXES.items()])
        return False, (
            f"Invalid F0 '{f0}'. Valid: {valid_f0s}. "
            f"F0 defines: 0=common-station, 1/2=units, 9=temporary"
        )
    f0_data = F0_PREFIXES[f0]
    return True, f"Valid F0={f0}: {f0_data['en']} ({f0_data['ru']})"


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
        "shaft_type_ru": None,
    }

    # Check for special shaft codes (first digit 3-9 with NN pattern)
    if len(digits) >= 3:
        first_digit = digits[0]
        if first_digit in ROOM_SHAFT_CODES:
            shaft_data = ROOM_SHAFT_CODES[first_digit]
            details["is_shaft"] = True
            details["shaft_type"] = shaft_data["en"]
            details["shaft_type_ru"] = shaft_data["ru"]
            return (
                True,
                f"Valid shaft code: {shaft_data['en']} ({shaft_data['ru']}) ({digits})",
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
      - Pulse valves (P)
      - Safety valves (S)
      - Double drives (D)
      - Multiple power supply (M)
      - Measurement loops (L)
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
        return True, f"Valid A3 code '{a3_upper}': {a3_data['en']} ({a3_data['ru']})"

    valid_a3s = ", ".join([f"{k}={v['en']}" for k, v in A3_CODES.items()])
    return False, (
        f"Unknown A3 code '{a3_upper}'. "
        f"Valid A3 per Rooppur: {valid_a3s}"
    )


def get_kks_scope(kks_code: str) -> Optional[ScopeType]:
    """Returns the scope type for a given KKS code, or None if invalid."""
    valid, _, scope = validate_kks(kks_code)
    return scope if valid else None


def get_system_family(f1f2f3: str) -> Optional[str]:
    """Returns the English system family description for a given F1F2F3 code."""
    if not f1f2f3 or len(f1f2f3) < 1:
        return None
    first_char = f1f2f3[0].upper()
    if first_char in SYSTEM_FAMILY_CODES:
        return SYSTEM_FAMILY_CODES[first_char]["en"]
    return None


def get_system_family_ru(f1f2f3: str) -> Optional[str]:
    """Returns the Russian system family description for a given F1F2F3 code."""
    if not f1f2f3 or len(f1f2f3) < 1:
        return None
    first_char = f1f2f3[0].upper()
    if first_char in SYSTEM_FAMILY_CODES:
        return SYSTEM_FAMILY_CODES[first_char]["ru"]
    return None


def get_bilingual_system_family(f1f2f3: str) -> str:
    """Returns bilingual system family: English (Russian)."""
    if not f1f2f3 or len(f1f2f3) < 1:
        return "Unknown"
    first_char = f1f2f3[0].upper()
    if first_char in SYSTEM_FAMILY_CODES:
        en = SYSTEM_FAMILY_CODES[first_char]["en"]
        ru = SYSTEM_FAMILY_CODES[first_char]["ru"]
        return f"{en} ({ru})"
    return "Unknown"


def enforce_scope_milestones(record: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Enforces milestone rules based on KKS scope per Rooppur NPP.
    - System: all milestones active
    - Equipment: PT and SAW set to 'N/A'
    - Room: all milestones N/A (room coding has no commissioning milestones)

    Returns:
        (enriched_record, alerts)
    """
    alerts = []
    kks = record.get("system_kks", "")
    scope = get_kks_scope(kks)

    if scope is None:
        alerts.append(
            f"WARNING: Could not determine scope for KKS '{kks}'. "
            f"Verify F0 prefix is present (mandatory per Rooppur NPP)."
        )
        return record, alerts

    record["scope_type"] = scope.value

    if scope == ScopeType.EQUIPMENT:
        for ms in EQUIPMENT_NA_MILESTONES:
            current = record.get(ms, "")
            if current and current not in ("N/A", "Not Applicable", ""):
                ms_label_en = MILESTONE_LABELS.get(ms, {}).get("en", ms)
                ms_label_ru = MILESTONE_LABELS.get(ms, {}).get("ru", "")
                alerts.append(
                    f"ALERT: KKS '{kks}' (Equipment scope) has non-N/A value '{current}' for '{ms}'. "
                    f"Auto-corrected to 'N/A'. Equipment does not require {ms_label_en}"
                    f"{' / ' + ms_label_ru if ms_label_ru else ''}."
                )
            record[ms] = "N/A"

    elif scope == ScopeType.ROOM:
        # Room coding has no commissioning milestones per se
        for ms in MILESTONES:
            current = record.get(ms, "")
            if current and current not in ("N/A", "Not Applicable", ""):
                ms_label_en = MILESTONE_LABELS.get(ms, {}).get("en", ms)
                ms_label_ru = MILESTONE_LABELS.get(ms, {}).get("ru", "")
                alerts.append(
                    f"ALERT: KKS '{kks}' (Room coding) has milestone value '{current}' for '{ms}'. "
                    f"Room codes do not have commissioning milestones. Auto-corrected to 'N/A'. "
                    f"{ms_label_en}{' / ' + ms_label_ru if ms_label_ru else ''}"
                )
            record[ms] = "N/A"

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
        prereq_val = record.get(prereq, "").strip().lower()
        dependent_val = record.get(dependent, "").strip().lower()

        if dependent_val == "completed" and prereq_val != "completed":
            prereq_label_en = MILESTONE_LABELS.get(prereq, {}).get("en", prereq)
            prereq_label_ru = MILESTONE_LABELS.get(prereq, {}).get("ru", "")
            dependent_label_en = MILESTONE_LABELS.get(dependent, {}).get("en", dependent)
            dependent_label_ru = MILESTONE_LABELS.get(dependent, {}).get("ru", "")

            prereq_full = f"{prereq_label_en}{' / ' + prereq_label_ru if prereq_label_ru else ''}"
            dependent_full = f"{dependent_label_en}{' / ' + dependent_label_ru if dependent_label_ru else ''}"

            violations.append(
                f"DEPENDENCY VIOLATION: '{dependent}' ({dependent_full}) is marked 'Completed' but prerequisite "
                f"'{prereq}' ({prereq_full}) is '{record.get(prereq, 'N/A')}'. "
                f"{prereq_label_en} must be Completed before {dependent_label_en}."
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
