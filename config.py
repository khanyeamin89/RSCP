"""
Reactor Shop Commissioning - Centralized Configuration
======================================================
Contains all constants, schema definitions, and shared utilities.

KKS Coding extracted from the official Rooppur NPP source document:
    RPR-QM-AEB0001, Revision B05, "Agreement on Using the KKS Coding System"
    (JSC ASE EC / Bangladesh Atomic Energy Commission, 2017)

Scope: Reactor Shop (10UJA/20UJA). The reference tables below cover:
  - Section 3 (functional systems, buildings, structures) narrowed to the J
    and K code groups (reactor plant + reactor plant auxiliary systems),
    plus Q/S-group systems explicitly cross-referenced to the 10UJA building
    (cold supply, heat supply, cranes).
  - Section 4 (equipment unit codes) and Section 5 (component codes) in full,
    since these are universal/plant-wide, not building-specific.
This intentionally does NOT cover the full plant (turbine island, electrical
switchyard, BOP, etc.) — only what Reactor Shop commissioning needs. Function
key letters outside this scope (B,C,D,E,F,G,H,L,M,N,P,R,T,V,W,X,Y,Z) are left
out of FUNCTION_KEY_LEGEND rather than filled with guesses; add them from the
same source document if the dashboard's scope ever expands.

The source PDF is a scanned document with no text layer — all data below was
extracted via OCR at 220 DPI with column-isolated re-reads for accuracy, then
cross-checked against the rendered page images. Recommend spot-checking any
code against the source PDF before relying on it for a safety-relevant
decision.

KKS (Kraftwerk-Kennzeichensystem) is the German-origin power-plant identification
standard. Rooppur NPP documentation (RPR.0534 / RPR.0132 series) follows an
adapted version of it, structured as:

    Building code   : [Unit][U][2 letters]                      e.g. 10UJA
    System code     : [2-4 letters]                              e.g. JAA, KBA
    Equipment code  : [Unit][System][Subsystem-2digit][Type-2letter][Seq-3digit]
                       e.g. 10JAA10BB001 = Unit 10, System JAA, Subsystem 10,
                       Type BB (vessel/tank), item 001

All reference tables below (function keys, equipment types, systems, buildings)
are hard-coded from the official KKS coding agreement so that validation
and AI-assisted parsing are always checked against real, known-good codes
instead of a guessed/inferred pattern. This removes an entire class of parsing
errors that occurred previously when codes were validated against an
approximate/incorrect scheme.
"""

import re
import streamlit as st
from supabase import create_client
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

# =============================================================================
# PAGE CONFIGURATION
# =============================================================================

PAGE_TITLE = "Reactor Shop Commissioning Dashboard"
PAGE_ICON = "⚛️"

# =============================================================================
# KKS TAXONOMY DEFINITIONS
# Hard-coded from the Reactor Shop (Rooppur NPP) KKS Code Master List
# =============================================================================

class ScopeType(str, Enum):
    SYSTEM = "System"
    EQUIPMENT = "Equipment"
    BUILDING = "Building"
    UNKNOWN = "Unknown"


# -----------------------------------------------------------------------------
# UNIT CODES (first 2 digits of every KKS code)
# -----------------------------------------------------------------------------
# Observed unit codes across the master list: 00, 01-09, 10-15, 17, 20.
# 00 = common/shared across the whole site, 10 = Unit 1, 20 = Unit 2.
# Hyphenated ranges (e.g. "11-14") denote a structure/system shared by several
# units or trains and are handled by UNIT_CODE_RE below.
# -----------------------------------------------------------------------------

UNIT_CODES: Dict[str, str] = {
    "00": "Common-station installations and systems for Units 1 and 2",
    "10": "Unit 1",
    "20": "Unit 2",
    # Note: per Section 2 i.3.2-3.4 of RPR-QM-AEB0001, the RULE is: power
    # units are coded starting from digit 1 (Unit 1), digit 2 (Unit 2);
    # common-station is "0"; temporary installations are "9". The specific
    # second digit (e.g. "01", "11", "21") denotes sub-trains/sub-blocks
    # within that unit and isn't individually enumerated here — describe_unit()
    # below falls back gracefully for any 2-digit prefix not listed above.
}

UNIT_CODE_RE = re.compile(r"^\d{2}(?:-\d{2})?$")

# -----------------------------------------------------------------------------
# FUNCTION KEY LEGEND (1st letter of every System code)
# Only letters actually verified against RPR-QM-AEB0001 B05 within Reactor
# Shop scope are included — see module docstring for why the rest are
# deliberately left out rather than guessed.
# -----------------------------------------------------------------------------

FUNCTION_KEY_LEGEND: Dict[str, str] = {
    'A': 'Networks and switchgears',
    'J': 'Nuclear generation of heat',
    'K': 'Reactor plant auxiliary systems',
    'U': 'Buildings and structures',
}

# -----------------------------------------------------------------------------
# EQUIPMENT UNIT CODES (2-letter code preceding the sequence number)
# Full Section 4 of RPR-QM-AEB0001 B05 ("List of Equipment Unit Codes") —
# universal/plant-wide, not building-specific, extracted in full.
# -----------------------------------------------------------------------------

EQUIPMENT_TYPE_LEGEND: Dict[str, str] = {
    "AA": "Hatches, manholes, doors",
    "AB": "Heat exchangers, heating surfaces",
    "AC": "Rotating, hoisting, handling mechanisms, manipulators as well",
    "AE": "Conveyors, escalators",
    "AF": "Generator sets",
    "AG": "Space heaters, coolers, air conditioners",
    "AH": "Crushing plants, only used in technological process",
    "AJ": "Presses and stackers, only used in technological process",
    "AK": "Mixers, blenders",
    "AM": "Compressors, fans",
    "AN": "Pump sets",
    "AP": "Controlling devices and tightening devices for nonelectrical quantities (only if actuator constitutes single structural assembly connected with another device)",
    "AS": "Cleaning, drying, filtering and fluid separation devices, excepting \"BT\"",
    "AT": "Brakes, transmission gears, clutches, nonelectrical transducers",
    "AU": "Incineration devices",
    "AV": "Stationary processing machines, maintenance devices, laboratory furniture",
    "AW": "Controlling and checking devices for maintenance of installations, laboratory instruments and equipment",
    "AX": "Valves, including drive, manual drive as well; burst rupture devices",
    "BB": "Storage devices (vessels, reservoirs)",
    "BE": "Shafts (only for erection and service)",
    "BF": "Foundations",
    "BN": "Jet pumps, ejectors, injectors, deflectors, hoods",
    "BP": "Constricting devices, flow limiters, throttle orifices (not for measurements)",
    "BQ": "Supports, load-bearing structures, brackets, piping penetrations",
    "BR": "Pipelines, channels, trays",
    "BS": "Mufflers",
    "BT": "Stack gas catalytic converter",
    "BU": "Insulation, shells",
    "CD": "Density",
    "CE": "Electrical variables (e.g. current, voltage, power, electric frequency)",
    "CF": "Flowrate, mass flowrate",
    "CG": "Distance, length, position, direction of rotation",
    "CH": "Manual entry of information (e.g. fire pushbutton)",
    "CK": "Time",
    "CL": "Level (also media interface boundary)",
    "CM": "Moisture content, humidity",
    "CP": "Pressure",
    "CQ": "Quality indicators (analyses, material properties), other than \"CD\", \"CM\", \"CV\"",
    "CR": "Radiation variables, fire alarm",
    "CS": "Velocity, rotation speed, frequency (mechanical), acceleration",
    "CT": "Temperature",
    "CU": "Combined and other variables",
    "CV": "Viscosity",
    "CW": "Weight, mass, force",
    "CX": "Neutron flux",
    "CY": "Vibration, extensions",
    "DD": "Density",
    "DE": "Electrical variables (e.g. current, voltage, power, electrical frequency)",
    "DF": "Flowrate, mass flowrate",
    "DG": "Distance, length, position, direction of rotation",
    "DK": "Time",
    "DL": "Level (also media interface boundary)",
    "DM": "Moisture content, humidity",
    "DP": "Pressure",
    "DQ": "Quality indicators (analyses, material properties), other than \"DD\", \"DM\", \"DV\"",
    "DR": "Radiation quantity",
    "DS": "Velocity, rotation speed, frequency (mechanical), acceleration",
    "DT": "Temperature",
    "DU": "Combined and other variables",
    "DV": "Viscosity",
    "DW": "Weight, mass, force",
    "DX": "Neutron flux",
    "DY": "Vibration, extensions",
    "EA": "Control (free for use)",
    "EB": "Control (free for use)",
    "EC": "Control (free for use)",
    "ED": "Control (free for use)",
    "EE": "Control (free for use)",
    "EG": "Alarms and messages (free for use)",
    "EH": "Alarms and messages (free for use)",
    "EJ": "Alarms and messages (free for use)",
    "EK": "Alarms and messages (free for use)",
    "EM": "Computer (free for use)",
    "EN": "Computer (free for use)",
    "EP": "Computer (free for use)",
    "EQ": "Computer (free for use)",
    "ER": "Reactor protection",
    "EU": "Combined processing of binary and analog signals",
    "EW": "Protection (free for use)",
    "EX": "Protection (free for use)",
    "EY": "Protection (free for use)",
    "EZ": "Protection (free for use)",
    "FD": "Density",
    "FE": "Electrical variables (current, voltage, power, electrical frequency)",
    "FF": "Flowrate, mass flowrate",
    "FG": "Distance, length, position, direction of rotation",
    "FK": "Time",
    "FL": "Level (also media interface boundary)",
    "FM": "Moisture content, humidity",
    "FP": "Pressure",
    "FQ": "Quality indicators (analyses, material properties), other than \"FD\", \"FM\", \"FV\"",
    "FR": "Radiation quantity",
    "FS": "Velocity, rotation speed, frequency (mechanical), acceleration",
    "FT": "Temperature",
    "FU": "Combined and other variables",
    "FV": "Viscosity",
    "FW": "Weight, mass, force",
    "FX": "Neutron flux",
    "FY": "Vibration, extensions",
    "GA": "Junction or distribution boxes and cable penetrations (free for use)",
    "GB": "I&C junction boxes",
    "GC": "Junction or distribution boxes and cable penetrations (free for use)",
    "GD": "Junction or distribution boxes and cable penetrations (free for use)",
    "GE": "Junction or distribution boxes and cable penetrations (free for use)",
    "GF": "Junction or distribution boxes and cable penetrations (free for use)",
    "GG": "Junction or distribution boxes and cable penetrations (free for use)",
    "GH": "Independently mounted electrical devices (cabinets, boxes), control and measurement units coded according to the process diagram",
    "GK": "Devices for presenting information and operative control in automation systems (keyboards, displays, printers, etc.)",
    "GM": "Junction or distribution boxes for low-current open remote communication system",
    "GP": "Junction or distribution boxes and distribution for lighting",
    "GQ": "Junction or distribution boxes and distribution for power receptacles",
    "GR": "DC power supplies, batteries",
    "GS": "Switching devices if not identified by process codes",
    "GT": "Transformer devices",
    "GU": "Converter devices",
    "GV": "Lightning protection and grounding devices",
    "GW": "Cabinet power supply devices",
    "GX": "Actuating equipment for electrical variables",
    "GY": "Junction or distribution boxes for low current systems (not for open telecommunication services)",
    "GZ": "Supports, hangers, and bearing structures for electrical and I&C equipment",
    "HA": "Parts of machine casings",
    "HB": "Parts of moving machinery components",
    "HD": "Structures of bearings",
    "JA": "Absorber elements",
    "JB": "Fuel assemblies",
    "JC": "Breeding elements",
    "JD": "Throttle grills (elements)",
    "JE": "Burnable absorber elements",
    "JF": "Reflecting elements",
    "JG": "Elements of volume, collection",
    "JM": "Moderating elements",
    "JN": "Neutron sources",
    "JS": "Shielding elements",
    "JZ": "Special elements",
}

# -----------------------------------------------------------------------------
# COMPONENT CODES (component-level detail code, distinct namespace from
# EQUIPMENT_TYPE_LEGEND above — KKS reuses the same letters at different
# code "sectors" with different meanings, e.g. equipment-level "K" is a
# 2-letter equipment-unit code while component-level "K" is a top-level
# group for mechanical components; keeping these as separate dicts avoids
# collisions).
# Full Section 5 of RPR-QM-AEB0001 B05 ("Component Codes") — universal/
# plant-wide, extracted in full.
# -----------------------------------------------------------------------------

COMPONENT_TYPE_LEGEND: Dict[str, str] = {
    "-A": "Self-contained devices, complex devices, units, functional modules, microprocessor devices for control, monitoring, and relay protection",
    "-B": "Converters of nonelectrical quantities into electrical ones and vice versa",
    "-C": "Capacitive elements (capacitors)",
    "-D": "Logic elements, delay and memory devices",
    "-E": "Special elements for which no special alphabetic codes are established, special equipment",
    "-F": "Protection devices (fuses, surge arresters, automatic (non-power) switches)",
    "-G": "Power supplies",
    "-H": "Indication and alarm devices",
    "-K": "Relays, contactors, starters",
    "-L": "Inductances (coils and chokes)",
    "-M": "Electric motors",
    "-N": "Amplifiers and controllers",
    "-P": "Measurement equipment, counters",
    "-Q": "Power circuit breakers, disconnector switches",
    "-R": "Resistors",
    "-S": "Switching devices (selector switches, knife switches)",
    "-T": "Transformers (non-power)",
    "-U": "Converters of electrical quantities into other electrical quantities",
    "-V": "Radio valves, electronic valves, semiconductors",
    "-W": "Data transmission channels between computers, aerials, high-frequency equipment",
    "-X": "Connection devices (terminals, receptacles, plugs, clamps)",
    "-Y": "Electric drives (not electric motors); solenoids (electromagnets)",
    "-Z": "Smoothing devices; filters; limiters; compensators",
    "KA": "Gate valves, cocks, valves, taps, bursting disks, throttling orifices, end plates",
    "KB": "Gates, doors, partition walls",
    "KC": "Heat exchangers, coolers",
    "KD": "Reservoirs, vessels, level (process) vessels",
    "KE": "Turning, handling, hoisting and rotating mechanisms",
    "KF": "Conveyers, feeders",
    "KJ": "Crushing machines",
    "KK": "Pressing and stacking machines",
    "KM": "Mixers",
    "KN": "Compressors, air blowers, fans",
    "KP": "Pumps",
    "KT": "Cleaning machines, dryers, separators, filters",
    "KV": "Burners, fire bars",
    "KW": "Stationary machines and processing machines for maintenance",
    "MB": "Brakes",
    "MF": "Foundations",
    "MG": "Reducing gears",
    "MK": "Clutches",
    "MM": "Engines (non-electric)",
    "MR": "Piping parts, parts of technical channels, sockets",
    "MS": "Drives, non-electric",
    "MT": "Turbines",
    "MU": "Transmission components, non-electric converters and amplifiers, except for clutches and reducing gears",
    "QB": "Measurement sensors if not structurally integral with \"QP\"",
    "QH": "Signalling devices",
    "QN": "Controllers, centrifugal governors",
    "QP": "Measurement instruments, testing equipment, filter holders",
    "QR": "Instrument piping",
    "QS": "Level vessels in measurement circuits",
    "QT": "Protecting tubes and sleeves for protection of vulnerable sensors",
}


# -----------------------------------------------------------------------------
# SYSTEM CODES (2-4 letters). Value = (description, function key letter).
# Reactor Shop scope: full J group (reactor plant) + K group (reactor plant
# auxiliary systems) from Section 3 of RPR-QM-AEB0001 B05, plus Q/S-group
# systems explicitly cross-referenced to the 10UJA building (cold supply,
# heat supply, cranes). Category-header rows (e.g. "JA.", "K..") are excluded
# since they aren't real assignable codes, only section labels.
# -----------------------------------------------------------------------------

SYSTEM_CODES: Dict[str, Tuple[str, str]] = {
    "JAA": ("Reactor pressure vessel", "J"),
    "JAB": ("Reactor head (upper unit), including flanges, seals, and studs", "J"),
    "JAC": ("Reactor internals", "J"),
    "JAH": ("Reactor external insulation", "J"),
    "JAJ": ("Reactor external cooling system", "J"),
    "JAT": ("Reactor leakage monitoring system", "J"),
    "JBA": ("Reactor pressure vessel surveillance samples", "J"),
    "JDA": ("CPS drive system", "J"),
    "JDK": ("Emergency protection system", "J"),
    "JDY": ("Group and individual control system of CPS control member drives", "J"),
    "JEA": ("Steam generation system", "J"),
    "JEB": ("Reactor coolant pump system", "J"),
    "JEC": ("Reactor coolant piping system", "J"),
    "JEF": ("Pressurizer system, including injection devices", "J"),
    "JEG": ("Steam receipt from pressurizer dumping devices system", "J"),
    "JET": ("Reactor coolant controlled leak-off system", "J"),
    "JEV": ("RCP motor lubrication system", "J"),
    "JEW": ("RCP sealing water system", "J"),
    "JKA": ("Reactor core", "J"),
    "JKM": ("Molten core retaining and cooling system", "J"),
    "JKS": ("In-core instrumentation system (ICIS)", "J"),
    "JKT": ("Ex-core instrumentation system", "J"),
    "JKU": ("Fuel rod cladding monitoring system", "J"),
    "JMA": ("10UJA (20UJA) building containment shells system", "J"),
    "JME": ("Equipment airlock", "J"),
    "JMF": ("Main personnel airlock", "J"),
    "JMG": ("Emergency personnel airlock", "J"),
    "JMJ": ("Structural components inside containment (only for component coding)", "J"),
    "JMK": ("System of pipeline penetrations", "J"),
    "JML": ("System of cable penetrations", "J"),
    "JMN": ("Sprinkler system", "J"),
    "JMP": ("System of relief devices of the reactor building steam chambers", "J"),
    "JMT": ("Hydrogen suppression inside the containment system", "J"),
    "JMU": ("Hydrogen concentration monitoring inside containment system", "J"),
    "JMY": ("Control, regulation and protection devices", "J"),
    "JNA": ("Reactor coolant circuit emergency and planned cooldown and fuel pool cooling system", "J"),
    "JNB": ("Emergency residual heat removal systems from SGs", "J"),
    "JND": ("Emergency boron injection system", "J"),
    "JNG": ("Passive part of the emergency core cooling system", "J"),
    "JNK": ("Borated water storage system", "J"),
    "JYF": ("Loose parts monitoring system", "J"),
    "JYG": ("Vibration monitoring system", "J"),
    "KAA": ("Component cooling system for essential loads of building 10UJA (20UJA)", "K"),
    "KAW": ("Seal water supply system", "K"),
    "KBA": ("Volume and chemical control system", "K"),
    "KBB": ("Operating grade coolant storage system", "K"),
    "KBC": ("Distillate and boron concentrate system", "K"),
    "KBD": ("System for adding chemical reagents to primary coolant", "K"),
    "KBE": ("Coolant purification system", "K"),
    "KBF": ("Coolant treatment system", "K"),
    "KBH": ("Fuel pool water purification system", "K"),
    "LCQ": ("Steam Generator Blowdown Water Purification System", "L"),
    "KLA": ("Ventilation system of the 10UJA (20UJA) buildings", "K"),
    "KLB": ("Ventilation system of the 10UJB (20UJB) buildings", "K"),
    "KLC": ("Ventilation system of the 10UKA (20UKA) buildings", "K"),
    "KLE": ("Ventilation system of the 10UKC (20UKC), 00UKU buildings", "K"),
    "KLF": ("Ventilation system of the 00UKS building", "K"),
    "KLM": ("Annulus space passive filtration system", "K"),
    "KLP": ("Ventilation system of 00UGW building", "K"),
    "KLS": ("Ventilation system of the 01-03UJY, 00UYB buildings", "K"),
    "KPA": ("Solid radwaste processing system", "K"),
    "KPB": ("Incineration system", "K"),
    "KPC": ("Cementation system", "K"),
    "KPE": ("Solid radwaste storage system", "K"),
    "KPF": ("Floor water collection system and radioactive sewerage system", "K"),
    "KPH": ("SRW incineration system", "K"),
    "KPJ": ("Reagent preparation and supply system", "K"),
    "KPK": ("Intermediate liquid radioactive media storage system", "K"),
    "KPL": ("Burning system for hydrogen from radioactive process blow-offs", "K"),
    "KPM": ("Radioactive process blow-offs purification system", "K"),
    "KPN": ("Cementation system", "K"),
    "KPP": ("Shredding system", "K"),
    "KRA": ("Nitrogen supply system", "K"),
    "KTA": ("Primary coolant circuit drains and sampling system", "K"),
    "KTB": ("Gas blow-off system", "K"),
    "KTC": ("Waste collection and removal system from the 10UJA (20UJA) building", "K"),
    "KTF": ("Active drain system of the 10UJA (20UJA) (non-pressure part)", "K"),
    "KTH": ("Active drain system of the 10UJA (20UJA), 10UKC (20UKC) buildings (pressure part)", "K"),
    "KTK": ("Active drain system of building 00UFC", "K"),
    "KTN": ("Active drain system of the 10UKC (20UKC) buildings (non-pressure part)", "K"),
    "KTP": ("Emergency gas removal system", "K"),
    "KTQ": ("Fuel pool lining tightness monitoring system", "K"),
    "KTR": ("Active drain system of building 00UYB", "K"),
    "KUA": ("Sampling system for primary circuit", "K"),
    "KUB": ("System for taking samples from equipment", "K"),
    "KUC": ("High-level sampling system for radiation control", "K"),
    "KUD": ("System for taking samples from equipment of building 00UYB", "K"),
    "PEB": ("Component cooling water piping system for essential loads", "P"),
    "PEC": ("Pump sets for essential loads", "P"),
    "PED": ("Ventilation units of essential-load cooling system", "P"),
    "PGB": ("Component cooling systems for normal operation loads", "P"),
    "KUE": ("System for taking samples from Active Water Treatment plants", "K"),
    "KUJ": ("System of taking air samples for mobile gas-aerosol radiometers", "K"),
    "KUK": ("System of taking air samples for stationary gas-aerosol radiometers", "K"),
    "KWA": ("System of I&C transducers hydraulic testing and flushing by distillate", "K"),
    "KWB": ("Systems for testing the SG secondary side and flushing I&C sensors with secondary coolant circuit blowdown water", "K"),
    "KWC": ("System for hydraulic tests and flushing of I&C transducers with boron-containing water", "K"),
    "QKJ": ("Cold supply system for ventilation systems of the 10UJA (20UJA) building", "Q"),
    "SBJ": ("Heat supply system of the 10UJA (20UJA), 10UBB (20UBB), 11-12UBP (21-22UBP) buildings", "S"),
    "SMJ": ("Cranes, stationary hoisting devices and transport equipment in the 10UJA (20UJA), 10UJB (20UJB), 10UJC (20UJC), 10UJE (20UJE) buildings", "S"),
}


# -----------------------------------------------------------------------------
# BUILDING CODES ([Unit]U[2 letters]).
# Hard-coded from the "Buildings" sheet of the KKS Master List (257 known codes).
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# BUILDING CODES ([Unit]U[2 letters]).
# Reactor Shop scope: the full UJ-series (Reactor building/containment
# complex) and UK-series (reactor plant auxiliary buildings) from Section 3
# of RPR-QM-AEB0001 B05, plus UB-series rooms explicitly located inside the
# 10UJA building (electrical/control equipment rooms).
# -----------------------------------------------------------------------------

BUILDING_CODES: Dict[str, str] = {
    "00UKD": "Area for placing alternative beyond-design accident control facilities",
    "00UKR": "CPS AR storage building",
    "00UKS": "Radioactive waste processing and storage building",
    "00UKU": "Controlled-access area workshops",
    "00UKX": "Special-purpose vehicles garage",
    "01-04UJY": "Gallery of the controlled access area",
    "01-09UKZ": "Cable tunnel of normal operation system",
    "01UKH": "Ventilation stack (to the 00UKS building)",
    "01UKY": "Gallery of the common access area",
    "02UKH": "Ventilation stack (to the 00UKU building)",
    "03UKH": "Ventilation stack (to the 00UYB building)",
    "10UBB": "Rooms for electrical equipment and rooms for normal operation control devices in the 10UJA building",
    "10UJA": "Reactor building/Inner containment (Unit 1)",
    "10UJB": "Outer containment in the 10UJA building",
    "10UJC": "Premise for PHRS heat exchangers in the 10UJA building",
    "10UJE": "Steam chamber in the 10UJA building",
    "10UJG": "Transport portal of the 10UJA building",
    "10UKA": "Extension of the 10UJA building",
    "10UKC": "Reactor auxiliary building (Unit 1)",
    "10UKH": "Ventilation stack (Unit 1)",
    "11-12UBP": "Rooms for electrical equipment and rooms for safety system control devices in the 10UJA building",
    "11-12UJY": "Gallery of the controlled access area",
    "11-12UKZ": "Safety system cable tunnel",
    "11-13UIZ": "Process tunnel",
    "13UJY": "Ventilation gallery",
    "20UBB": "Rooms for electrical equipment and rooms for normal operation control devices in the 20UJA building",
    "20UJA": "Reactor building/Inner containment (Unit 2)",
    "20UJB": "Outer containment in the 20UJA building",
    "20UJC": "Premise for PHRS heat exchangers in the 20UJA building",
    "20UJE": "Steam chamber in the 20UJA building",
    "20UJG": "Transport portal of the 20UJA building",
    "20UKA": "Extension of the 20UJA building",
    "20UKC": "Reactor auxiliary building (Unit 2)",
    "20UKH": "Ventilation stack (Unit 2)",
    "21-22UBP": "Rooms for electrical equipment and rooms for safety system control devices in the 20UJA building",
    "21-22UJY": "Gallery of the controlled access area",
    "21-22UKZ": "Safety system cable tunnel",
    "21-23UIZ": "Process tunnel",
    "23UJY": "Ventilation gallery",
}


# -----------------------------------------------------------------------------
# Regex patterns for the 3 real KKS code shapes
# -----------------------------------------------------------------------------
BUILDING_RE = re.compile(r"^(\d{2}(?:-\d{2})?)U([A-Z]{2})$")
EQUIPMENT_RE = re.compile(r"^(\d{2}(?:-\d{2})?)([A-Z]{2,4})(\d{2})([A-Z]{2})(\d{3})$")
SYSTEM_ONLY_RE = re.compile(r"^(\d{2}(?:-\d{2})?)([A-Z]{2,4})$")

# -----------------------------------------------------------------------------
# Backward-compatible aliases
# -----------------------------------------------------------------------------
# Older parts of this codebase (and the UI legend expander) referred to these
# names. They are kept as aliases so nothing else needs to change, but they
# now point at the REAL hard-coded Rooppur tables above instead of a guessed
# A-Z scheme.
F0_PREFIXES: Dict[str, str] = UNIT_CODES
SYSTEM_FAMILY_CODES: Dict[str, str] = FUNCTION_KEY_LEGEND
A3_CODES: Dict[str, str] = EQUIPMENT_TYPE_LEGEND
ROOM_SHAFT_CODES: Dict[str, str] = BUILDING_CODES

# Valid system code prefixes / equipment prefixes, derived from real data
SYSTEM_PREFIXES: Set[str] = set(SYSTEM_CODES.keys())
EQUIPMENT_PREFIXES: Set[str] = set(EQUIPMENT_TYPE_LEGEND.keys())
COMPONENT_PREFIXES: Set[str] = set(COMPONENT_TYPE_LEGEND.keys())


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

# Each milestone's companion date field (target/completion date for that test).
# Dates are plain "YYYY-MM-DD" strings (or "" if unknown) — kept as str in the
# schema so partial/unknown dates never break validation; parsing to real
# dates happens only where a chart needs it.
MILESTONE_DATE_FIELDS: Dict[str, str] = {
    "it_status": "it_date",
    "pic_status": "pic_date",
    "ht_status": "ht_date",
    "pt_status": "pt_date",
    "saw_status": "saw_date",
}

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
    "commissioning_stage": str,
    "it_status": str,
    "it_date": str,
    "pic_status": str,
    "pic_date": str,
    "ht_status": str,
    "ht_date": str,
    "pt_status": str,
    "pt_date": str,
    "saw_status": str,
    "saw_date": str,
    "comments": str,
}

REGISTRY_REQUIRED_FIELDS: Set[str] = {"system", "component", "system_kks"}
REGISTRY_UNIQUE_KEYS: List[str] = ["system", "component"]

# -----------------------------------------------------------------------------
# Commissioning stage (A, A-1, B, B-1, B-2, ...)
# -----------------------------------------------------------------------------
# Rooppur commissioning works are organized into lettered stages, with
# optional numbered sub-stages (A-1, A-2, B-1, B-2, ...). This is separate
# from the IT/PIC/HT/PT/SAW milestones — a stage is a broader phase of the
# commissioning program that a given piece of equipment/system belongs to.

_STAGE_PATTERN = re.compile(r"^([A-Za-z])(?:-(\d+))?$")


def parse_commissioning_stage(raw: str) -> Optional[str]:
    """
    Normalizes a commissioning stage string (e.g. "a1", "A - 1", "b") into the
    canonical "A", "A-1", "B-2" form. Returns None if it doesn't look like a
    valid stage at all, so callers can distinguish "no stage given" from
    "malformed stage".
    """
    if not raw:
        return None
    cleaned = str(raw).strip().upper().replace(" ", "")
    # Tolerate "A-1", "A1", "A_1" as equivalent inputs
    cleaned = cleaned.replace("_", "-")
    if "-" not in cleaned and len(cleaned) > 1 and cleaned[1:].isdigit():
        cleaned = f"{cleaned[0]}-{cleaned[1:]}"

    match = _STAGE_PATTERN.match(cleaned)
    if not match:
        return None
    letter, number = match.groups()
    return f"{letter}-{int(number)}" if number else letter


def commissioning_stage_sort_key(stage: str) -> Tuple[str, int]:
    """
    Sort key so stages order meaningfully: A, A-1, A-2, B, B-1, B-2, ... rather
    than plain alphabetical (which would put "A-1" before "A" as a string).
    Unparseable/empty stages sort last.
    """
    normalized = parse_commissioning_stage(stage)
    if not normalized:
        return ("~", 9999)  # sorts after all real letters
    if "-" in normalized:
        letter, number = normalized.split("-")
        return (letter, int(number))
    return (normalized, 0)

# =============================================================================
# PPIA LOG (Process Protection and Interlock Actuation)
# =============================================================================
# A separate, append-only log of discrete protection/interlock actuation
# EVENTS — a reactor trip, an interlock actuation, a protection system alarm,
# etc. — as distinct from the pass/fail commissioning MILESTONES tracked in
# the main registry above. One shift note can report zero, one, or several
# PPIA events; each becomes its own log row. There is no unique-key upsert
# for this table (unlike the registry): every event is a new row.
# -----------------------------------------------------------------------------

PPIA_LOG_SCHEMA: Dict[str, type] = {
    "system": str,
    "system_kks": str,
    "event_date": str,             # YYYY-MM-DD, "" if unknown
    "event_time": str,             # HH:MM 24h, "" if unknown
    "interlock_description": str,  # what actuated/tripped (e.g. "Reactor trip on low pressurizer level")
    "trigger_cause": str,          # what caused it, if known/stated
    "status": str,
    "comments": str,
    "source": str,                 # e.g. filename or "Manual Entry"
}

PPIA_LOG_REQUIRED_FIELDS: Set[str] = {"interlock_description"}

PPIA_STATUSES: Set[str] = {
    "Confirmed", "False Alarm", "Resolved", "Under Investigation", "Pending Review",
}

PPIA_STATUS_LABELS: Dict[str, str] = {s: s for s in PPIA_STATUSES}


def validate_ppia_entry(entry: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Lightweight validation for a PPIA log entry — far less strict than the
    main registry validator since this is a free-form incident log, not a
    KKS-keyed commissioning record."""
    issues: List[str] = []
    for field_name in PPIA_LOG_REQUIRED_FIELDS:
        if not entry.get(field_name):
            issues.append(f"Missing required field: '{field_name}'")

    status = entry.get("status", "")
    if status and status not in PPIA_STATUSES:
        issues.append(
            f"Invalid PPIA status '{status}'. Must be one of: {', '.join(sorted(PPIA_STATUSES))}"
        )

    kks = entry.get("system_kks", "")
    if kks:
        result = parse_kks(kks)
        if not result.valid:
            # Non-fatal for PPIA — KKS may be partially known or not stated —
            # surfaced as an issue but doesn't block saving the event.
            issues.append(f"KKS Note: {result.message}")

    return (len([i for i in issues if not i.startswith("KKS Note:")]) == 0), issues

# =============================================================================
# MILESTONE TEST HISTORY (append-only, every test attempt — not just latest)
# =============================================================================
# The `registry` table holds one row per (system, component) — it can only
# ever show the CURRENT/latest status+date for each milestone. If a pump
# fails IT on 01.01.2026, passes a retest on 10.01.2026, then gets a repeat
# verification on 10.12.2026, the registry only ever shows the most recent
# of those. This table keeps every attempt, so the full history is never
# lost and can be plotted on the timeline.

MILESTONE_HISTORY_SCHEMA: Dict[str, type] = {
    "system": str,
    "system_kks": str,
    "component": str,
    "milestone": str,     # one of MILESTONES, e.g. "it_status"
    "status": str,        # the status AT THAT TEST, e.g. "Failed", "Completed"
    "event_date": str,    # YYYY-MM-DD — when that specific test/attempt happened
    "comments": str,
    "source": str,        # e.g. filename, "Shift Note Parser", "Manual Entry"
}

MILESTONE_HISTORY_REQUIRED_FIELDS: Set[str] = {"system_kks", "component", "milestone"}


def validate_milestone_history_entry(entry: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Lightweight validation for a single test-history entry."""
    issues: List[str] = []
    for field_name in MILESTONE_HISTORY_REQUIRED_FIELDS:
        if not entry.get(field_name):
            issues.append(f"Missing required field: '{field_name}'")

    milestone = entry.get("milestone", "")
    if milestone and milestone not in MILESTONES:
        issues.append(f"Invalid milestone '{milestone}'. Must be one of: {', '.join(MILESTONES)}")

    status = entry.get("status", "")
    if status and status not in VALID_STATUSES:
        issues.append(f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}")

    return len(issues) == 0, issues

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


def describe_unit(unit: str) -> str:
    """Returns a human-readable description for a 2-digit (or hyphenated-range) unit code."""
    if unit in UNIT_CODES:
        return UNIT_CODES[unit]
    if "-" in unit:
        return f"Shared structure/system across units {unit.replace('-', '–')}"
    return f"Auxiliary/shared facility zone {unit}"


# =============================================================================
# KKS PARSE RESULT
# =============================================================================

@dataclass
class KKSParseResult:
    """Structured result of parsing a single KKS code. This is the single
    source of truth for KKS parsing — every module (database, ai_engine,
    dashboard) should call parse_kks()/validate_kks() rather than re-slicing
    the raw string themselves, which previously caused index-mismatch bugs."""
    valid: bool
    scope: Optional[ScopeType] = None
    raw: str = ""
    unit: str = ""
    unit_desc: str = ""
    system_code: str = ""
    system_desc: str = ""
    function_key: str = ""
    function_key_desc: str = ""
    subsystem: str = ""
    equip_type: str = ""
    equip_type_desc: str = ""
    sequence: str = ""
    building_code: str = ""
    message: str = ""
    alerts: List[str] = field(default_factory=list)


# =============================================================================
# KKS VALIDATION ENGINE
# =============================================================================
# Real Rooppur NPP KKS code shapes (hard-coded reference tables above):
#   Equipment : [Unit-2][System-2..4][Subsystem-2][Type-2][Seq-3]  e.g. 10JAA10BB001
#   Building  : [Unit-2]U[2 letters]                                e.g. 10UJA
#   System    : [Unit-2][System-2..4]                               e.g. 10JAA
#
# A code is considered *structurally valid* if it matches one of these shapes.
# Whether the system/building/type appears in the hard-coded master tables
# only affects whether we can attach a description, and produces a soft
# warning (not a hard failure) when it doesn't — new equipment legitimately
# appears in shift notes before it exists in any master list, so unknown-but
# well-formed codes must still be accepted for data entry.
# =============================================================================

def parse_kks(kks_code: str) -> KKSParseResult:
    """Parses and validates a KKS code against the real Rooppur NPP structure."""
    if not kks_code or not isinstance(kks_code, str):
        return KKSParseResult(valid=False, message="KKS code must be a non-empty string")

    code = kks_code.upper().strip()

    if len(code) < 4:
        return KKSParseResult(
            valid=False,
            raw=code,
            message=(
                f"KKS code '{code}' is too short ({len(code)} chars). "
                "Expected Unit(2 digits) + System(2-4 letters) at minimum, e.g. '10JAA'."
            ),
        )

    # --- Equipment: Unit + System + Subsystem(2) + Type(2) + Seq(3) ---
    m = EQUIPMENT_RE.match(code)
    if m:
        unit, system, subsystem, etype, seq = m.groups()
        alerts: List[str] = []

        sys_entry = SYSTEM_CODES.get(system)
        if sys_entry:
            sys_desc, fkey = sys_entry
        else:
            fkey = system[0]
            fkey_desc = FUNCTION_KEY_LEGEND.get(fkey)
            if fkey_desc:
                sys_desc = fkey_desc
                alerts.append(
                    f"System code '{system}' not found in KKS master list; "
                    f"function key '{fkey}' = {fkey_desc}. Verify system code against master list."
                )
            else:
                sys_desc = ""
                alerts.append(
                    f"System code '{system}' has an unrecognized function key '{fkey}'. "
                    f"Verify against the KKS master list."
                )

        type_desc = EQUIPMENT_TYPE_LEGEND.get(etype, "")
        if not type_desc:
            alerts.append(f"Equipment type code '{etype}' not found in the Equipment Type Legend.")

        seq_val = int(seq)
        if seq_val == 0:
            alerts.append("Sequence number '000' is invalid; numbering starts at 001.")

        unit_desc = describe_unit(unit)
        message = (
            f"Valid Equipment KKS: Unit={unit} ({unit_desc}), System={system}"
            f"{' (' + sys_desc + ')' if sys_desc else ''}, Subsystem={subsystem}, "
            f"Type={etype}{' (' + type_desc + ')' if type_desc else ''}, Seq={seq}"
        )
        return KKSParseResult(
            valid=True, scope=ScopeType.EQUIPMENT, raw=code, unit=unit, unit_desc=unit_desc,
            system_code=system, system_desc=sys_desc, function_key=fkey,
            function_key_desc=FUNCTION_KEY_LEGEND.get(fkey, ""), subsystem=subsystem,
            equip_type=etype, equip_type_desc=type_desc, sequence=seq, message=message, alerts=alerts,
        )

    # --- Building: Unit + "U" + 2 letters ---
    m = BUILDING_RE.match(code)
    if m:
        unit, suffix = m.groups()
        building_code = f"{unit}U{suffix}"
        alerts = []
        desc = BUILDING_CODES.get(building_code, "")
        if not desc:
            alerts.append(
                f"Building code '{building_code}' not found in the KKS master list. "
                f"Verify against the Buildings sheet."
            )
        unit_desc = describe_unit(unit)
        message = f"Valid Building KKS: {building_code} — Unit={unit} ({unit_desc})"
        if desc:
            message += f", {desc}"
        return KKSParseResult(
            valid=True, scope=ScopeType.BUILDING, raw=code, unit=unit, unit_desc=unit_desc,
            building_code=building_code, system_desc=desc, message=message, alerts=alerts,
        )

    # --- System only: Unit + System(2-4 letters), no subsystem/type/seq ---
    m = SYSTEM_ONLY_RE.match(code)
    if m:
        unit, system = m.groups()
        alerts = []
        sys_entry = SYSTEM_CODES.get(system)
        if sys_entry:
            sys_desc, fkey = sys_entry
        else:
            fkey = system[0]
            fkey_desc = FUNCTION_KEY_LEGEND.get(fkey)
            if not fkey_desc:
                return KKSParseResult(
                    valid=False, raw=code,
                    message=(
                        f"Unknown KKS code '{code}'. System code '{system}' not found in the KKS "
                        f"master list and function key '{fkey}' is not a recognized function key "
                        f"({', '.join(sorted(FUNCTION_KEY_LEGEND.keys()))})."
                    ),
                )
            sys_desc = fkey_desc
            alerts.append(
                f"System code '{system}' not found in KKS master list; "
                f"function key '{fkey}' = {fkey_desc}. Verify system code against master list."
            )
        unit_desc = describe_unit(unit)
        message = f"Valid System KKS: Unit={unit} ({unit_desc}), System={system} ({sys_desc})"
        return KKSParseResult(
            valid=True, scope=ScopeType.SYSTEM, raw=code, unit=unit, unit_desc=unit_desc,
            system_code=system, system_desc=sys_desc, function_key=fkey,
            function_key_desc=FUNCTION_KEY_LEGEND.get(fkey, ""), message=message, alerts=alerts,
        )

    return KKSParseResult(
        valid=False, raw=code,
        message=(
            f"Unrecognized KKS code format '{code}'. Expected one of: "
            f"Equipment 'UUSSSSSSTTNNN' (e.g. 10JAA10BB001), "
            f"Building 'UUU + 2 letters' (e.g. 10UJA), "
            f"or System 'UU + 2-4 letters' (e.g. 10JAA)."
        ),
    )


def validate_kks(kks_code: str) -> Tuple[bool, str, Optional[ScopeType]]:
    """Backward-compatible wrapper around parse_kks()."""
    result = parse_kks(kks_code)
    return result.valid, result.message, result.scope


def get_kks_scope(kks_code: str) -> Optional[ScopeType]:
    """Returns the scope type for a given KKS code, or None if invalid."""
    result = parse_kks(kks_code)
    return result.scope if result.valid else None


def get_system_family(system_or_fragment: str) -> Optional[str]:
    """
    Returns a description for a system code or function-key fragment.
    Looks up the exact system code first (real master-list description),
    falling back to the function-key legend for the first letter.
    """
    if not system_or_fragment:
        return None
    code = system_or_fragment.upper().strip()
    if code in SYSTEM_CODES:
        return SYSTEM_CODES[code][0]
    first_char = code[0]
    return FUNCTION_KEY_LEGEND.get(first_char)


# -----------------------------------------------------------------------------
# Component validators (unit / building / equipment-type)
# -----------------------------------------------------------------------------

def validate_unit(unit: str) -> Tuple[bool, str]:
    """Validates a 2-digit (or hyphenated-range) unit code."""
    if not unit:
        return False, "Unit code is mandatory (first 2 digits of every KKS code)"
    unit = unit.strip()
    if not UNIT_CODE_RE.match(unit):
        return False, f"Invalid unit code '{unit}'. Expected 2 digits, optionally a hyphenated range (e.g. '11-14')."
    return True, f"Valid unit '{unit}': {describe_unit(unit)}"


def validate_building_code(code: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Validates a building KKS code against the real Building code shape/master list."""
    if not code or not isinstance(code, str):
        return False, "Building code must be a non-empty string", None
    result = parse_kks(code)
    if result.scope != ScopeType.BUILDING:
        return False, f"'{code}' is not a valid Building KKS code (expected Unit + 'U' + 2 letters).", None
    details = {
        "code": result.building_code,
        "unit": result.unit,
        "description": result.system_desc,
        "known": bool(result.system_desc),
    }
    return True, result.message, details


def validate_equipment_type(type_code: str) -> Tuple[bool, str]:
    """Validates a 2-letter equipment type code against the Equipment Type Legend."""
    if not type_code:
        return False, "Equipment type code is empty"
    code = type_code.upper().strip()
    if code in EQUIPMENT_TYPE_LEGEND:
        return True, f"Valid equipment type '{code}': {EQUIPMENT_TYPE_LEGEND[code]}"
    valid = ", ".join(f"{k}={v}" for k, v in sorted(EQUIPMENT_TYPE_LEGEND.items()))
    return False, f"Unknown equipment type code '{code}'. Valid types: {valid}"


# -----------------------------------------------------------------------------
# Backward-compatible aliases for the validators above
# -----------------------------------------------------------------------------
validate_f0 = validate_unit
validate_room_code = validate_building_code
validate_a3 = validate_equipment_type


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

    def _safe_str(val: Any) -> str:
        # Handles None, and also pandas NaN (a float that is != itself),
        # which shows up when records come from row.to_dict() on a
        # DataFrame with missing cells. Both previously crashed .strip()
        # with AttributeError since dict.get()'s default only applies
        # when the key is absent, not when its value is None/NaN.
        if val is None:
            return ""
        if isinstance(val, float) and val != val:
            return ""
        return str(val)

    for prereq, dependent in MILESTONE_DEPENDENCIES.items():
        prereq_val = _safe_str(record.get(prereq)).strip().lower()
        dependent_val = _safe_str(record.get(dependent)).strip().lower()

        if dependent_val == "completed" and prereq_val != "completed":
            prereq_label = MILESTONE_LABELS.get(prereq, prereq)
            dependent_label = MILESTONE_LABELS.get(dependent, dependent)

            violations.append(
                f"DEPENDENCY VIOLATION: '{dependent}' ({dependent_label}) is marked 'Completed' but prerequisite "
                f"'{prereq}' ({prereq_label}) is '{_safe_str(record.get(prereq)) or 'N/A'}'. "
                f"{prereq_label} must be Completed before {dependent_label}."
            )

    return violations


# =============================================================================
# RECORD VALIDATOR
# =============================================================================

def validate_record(record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Full validation of a registry record per the real Rooppur NPP KKS rules.
    Returns (is_valid, list_of_issues).
    """
    issues = []

    # Check required fields
    for field_name in REGISTRY_REQUIRED_FIELDS:
        if not record.get(field_name):
            issues.append(f"Missing required field: '{field_name}'")

    # Validate KKS
    kks = record.get("system_kks", "")
    result = parse_kks(kks)
    if not result.valid:
        issues.append(f"KKS Validation Error: {result.message}")

    # Validate status values
    for ms in MILESTONES:
        val = record.get(ms, "")
        if val and val not in VALID_STATUSES:
            issues.append(f"Invalid status '{val}' for '{ms}'. Valid: {sorted(VALID_STATUSES)}")

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
