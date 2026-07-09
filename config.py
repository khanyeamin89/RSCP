"""
Reactor Shop Commissioning - Centralized Configuration
======================================================
Contains all constants, schema definitions, and shared utilities.

KKS Coding based on the Rooppur NPP Reactor Shop KKS Code Master List,
compiled from the project's own commissioning documents:
  1. 1__RS_system_Status__UPDATED.xlsx
  2. Final_Reactor_Shop_Operational_Guiding_Report_09_03_2026.docx
  3. List_of_test_remaining_before_stage_C.xlsx
  4. Overview_of_the_List_of_task___tests_at_B-1_2_and_B-2_with_revised_distribution_list_updated_final_06_07_26.xlsx
  5. RS__Completion_Status__Tests_before_Physical_Start-Up_Progress_on_19_02_2026.xlsx
  6. RS_SAW_works__All_Stages__according_to_RPR_0534_1_0_PN_PC0003.xlsx

KKS (Kraftwerk-Kennzeichensystem) is the German-origin power-plant identification
standard. Rooppur NPP documentation (RPR.0534 / RPR.0132 series) follows an
adapted version of it, structured as:

    Building code   : [Unit][U][2 letters]                      e.g. 10UJA
    System code     : [2-4 letters]                              e.g. JAA, KBA
    Equipment code  : [Unit][System][Subsystem-2digit][Type-2letter][Seq-3digit]
                       e.g. 10JAA10BB001 = Unit 10, System JAA, Subsystem 10,
                       Type BB (vessel/tank), item 001

All reference tables below (function keys, equipment types, systems, buildings)
are hard-coded from the Reactor Shop KKS Code Master List so that validation
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
    "00": "Common station / Balance of Plant (shared across all units)",
    "10": "Unit 1",
    "20": "Unit 2",
}

UNIT_CODE_RE = re.compile(r"^\d{2}(?:-\d{2})?$")

# -----------------------------------------------------------------------------
# FUNCTION KEY LEGEND (1st letter of every System code)
# Hard-coded from the "Function Key Legend" sheet of the KKS Master List.
# -----------------------------------------------------------------------------

FUNCTION_KEY_LEGEND: Dict[str, str] = {
    'A': 'Grid and distribution systems',
    'B': 'Power transmission and auxiliary electrical power supply',
    'C': 'Instrumentation and control systems/equipment',
    'D': 'Control systems',
    'E': 'Conventional fuel supply and residues disposal',
    'F': 'Handling of nuclear equipment / fuel',
    'G': 'Water supply and disposal',
    'H': 'Conventional heat generation',
    'J': 'Nuclear heat generation (reactor systems)',
    'K': 'Nuclear auxiliary systems',
    'L': 'Steam, water, gas cycles',
    'M': 'Main machine sets',
    'N': 'Process energy supply for external users',
    'P': 'Cooling water systems',
    'Q': 'Auxiliary systems',
    'R': 'Gas generation and treatment',
    'S': 'Ancillary systems',
    'U': 'Structures / Buildings',
    'W': 'Solar / renewable energy systems',
    'X': 'Heavy machinery (not main machine sets, e.g. diesel-generator sets)',}

# -----------------------------------------------------------------------------
# EQUIPMENT TYPE LEGEND (2-letter code preceding the sequence number)
# Hard-coded from the "Equipment Type Legend" sheet of the KKS Master List.
# -----------------------------------------------------------------------------

EQUIPMENT_TYPE_LEGEND: Dict[str, str] = {
    'AA': 'Valves, dampers, etc. (incl. actuators, manual, rupture disks) — VALVE',
    'AB': 'Isolating elements, air locks',
    'AC': 'Heat exchangers, heat transfer surfaces — COOLER',
    'AE': 'Turning, driving, lifting and slewing gear (cranes, hoists, manipulators)',
    'AF': 'Continuous conveyors, feeders',
    'AG': 'Generator units',
    'AH': 'Heating, cooling and air-conditioning units',
    'AJ': 'Size reduction equipment (part of process)',
    'AK': 'Compacting and packaging equipment (part of process)',
    'AM': 'Mixers, agitators',
    'AN': 'Compressor units, fans — GAS BLOWER',
    'AP': 'Pump units — PUMP',
    'AS': 'Adjusting and tensioning equipment for non-electrical variables',
    'AT': 'Cleaning, drying, filtering, separating equipment — FILTER',
    'AU': 'Braking, gearbox, coupling equipment, non-electrical converters',
    'AV': 'Combustion equipment',
    'AW': 'Stationary tooling, treatment equipment',
    'AX': 'Test and monitoring equipment for plant maintenance',
    'BB': 'Storage equipment (vessels, tanks)',
    'BE': 'Shafts (erection/maintenance only)',
    'BF': 'Foundations',
    'BN': 'Jet pumps, ejectors, injectors',
    'BP': 'Flow restrictors, limiters, orifices (not metering)',
    'BQ': 'Hangers, supports',
    'BR': 'Supports, structural steel (mechanical)',
    'BS': 'Mechanical equipment (BS group)',
    'BT': 'Mechanical equipment (BT group)',
    'BU': 'Bellows, expansion joints / compensators',
    'CA': 'Direct measuring circuits — general/uncategorized variable',
    'CB': 'Radiation variables (thermal radiation, flame monitoring)',
    'CD': 'Density measurement',
    'CE': 'Electrical variables (current, voltage, power, frequency)',
    'CF': 'Flow, rate measurement',
    'CG': 'Distance, length, position, direction of rotation',
    'CH': 'Manual input (manually operated sensor)',
    'CJ': 'Power measurement (mechanical, thermal)',
    'CK': 'Time',
    'CL': 'Level measurement (incl. dividing line)',
    'CM': 'Moisture, humidity measurement',
    'CP': 'Pressure measurement',
    'CQ': 'Quality variables (analysis, material properties)',
    'CR': 'Radiation variables',
    'CS': 'Velocity, speed, frequency (mechanical), acceleration',
    'CT': 'Temperature measurement',
    'DF': 'Closed-loop control — flow, rate',
    'DL': 'Closed-loop control — level',
    'DP': 'Closed-loop control — pressure',
    'EE': 'Analog/binary signal conditioning equipment',
    'ER': 'Analog/binary signal conditioning — reactor protection',
    'GH': 'Electrical equipment (G group — subtype not confirmed in source docs)',
    'GQ': 'Electrical equipment — power sockets/outlets',
    'ST': 'Ancillary systems equipment (S group — subtype not confirmed in source docs)',}

# -----------------------------------------------------------------------------
# SYSTEM CODES (2-4 letters). Value = (description, function key letter).
# Hard-coded from the "Systems" sheet of the KKS Master List (439 known codes).
# -----------------------------------------------------------------------------

SYSTEM_CODES: Dict[str, Tuple[str, str]] = {
    'AB': ('Program of SAW for the gates of building complex of 00UYP (mechanical part)', 'A'),
    'ACA': ('Program of SAW for the power supply equipment of GIS 400 kV', 'A'),
    'ACM': ('Program of SAW for the 400 kV gas insulated current-conducting wire', 'A'),
    'ACQ': ('Program of SAW for the 400 kV switches of BCA and CBFP', 'A'),
    'ACY': ('Program of SAW for the 400 kV buses of RPA devices', 'A'),
    'ADA': ('Program of SAW for the power supply equipment of GIS 230 kV', 'A'),
    'ADM': ('Program of SAW for the 230 kV gas insulated current-conducting wire', 'A'),
    'ADQ': ('Program of SAW for the 230 kV switches of BCA and CBFP', 'A'),
    'ADY': ('Program of SAW for the RPA devices of 230 kV busbars', 'A'),
    'AN': ('Program of SAW for the 0,4 kV distribution assemblies', 'A'),
    'ARA': ('Program of SAW for the HFC communication channels of 00ACL01 400 kV HVPL', 'A'),
    'AS': ('Program of SAW for the synchronizing circuit of Power Unit No. 1 at 400 kV side', 'A'),
    'ASP': ('Program of SAW for the EER of 230 kV and 400 kV', 'A'),
    'ASQ': ('SAW program for AIEPAS equipment', 'A'),
    'AT': ('0.4 kV', 'A'),
    'ATA': ('0.4 kV power transformers', 'A'),
    'ATT': ('230 kV coupling autotransformers', 'A'),
    'AV': ('Program of SAW for the SPD EP POS', 'A'),
    'AVB': ('Program of SAW for the system of arrangement of channels for communication with NCC', 'A'),
    'AVS': ('Program of SAW for the PICS', 'A'),
    'AYC': ('Program of SAW for the local notification system', 'A'),
    'BA': ('Comprehensive trial program for TC electrical equipment in transient conditions during ...', 'B'),
    'BAA': ('Program of SAW for 24 kV isolated phase busbar', 'B'),
    'BAC': ('Program of SAW for gas-insulated generator switchgears 10BAC01, 10BAC02', 'B'),
    'BAT': ('Program of SAW for power unit transformers 10BAT01A, 10BAT01B, 10BAT01C, 00BAT01R', 'B'),
    'BAY': ('Comprehensive trial program for the generator-transformer unit at the “idle” stage', 'B'),
    'BB': ('Program of SAW for the 10 kV MCSG and power supply cabinets', 'B'),
    'BBG': ('Program of SAW for 10 kV external communication cabinets in the 13UBN building', 'B'),
    'BBT': ('Program of SAW for power auxiliary transformers 10BBT01, 10BBT02', 'B'),
    'BBY': ('Program of SAW for emergency events recording system (EER)', 'B'),
    'BC': ('Program of SAW for the 10 kV MCSG', 'B'),
    'BCS': ('Program of SAW for plantwide auxiliary transformer 10BCS01', 'B'),
    'BCT': ('Program of SAW for plantwide standby auxiliary transformers (10BCT01, 10BCT02)', 'B'),
    'BD': ('Program of SAW for 10 kV switchgears', 'B'),
    'BDB': ('Comprehensive trial program for the group 2 emergency power supply system with design l...', 'B'),
    'BDC': ('Program of SAW for 10 kV switchgears', 'B'),
    'BF': ('Program of SAW for 0.4 kV switchgears', 'B'),
    'BFT': ('0.4 kV power transformers', 'B'),
    'BG': ('Program of SAW for 0.4 kV switchgear assemblies', 'B'),
    'BJ': ('Program of SAW for the 0.4 kV MCSG', 'B'),
    'BJA': ('Program of SAW for the 0,4 kV distribution assemblies', 'B'),
    'BK': ('Program of SAW for the 0,4 kV distribution assemblies', 'B'),
    'BKP': ('0.4 kV power transformers', 'B'),
    'BKT': ('0.4 kV power transformers', 'B'),
    'BL': ('Program of SAW for the 0,4 kV distribution assemblies', 'B'),
    'BLJ': ('Program of SAW for the 0,4 kV distribution assemblies', 'B'),
    'BM': ('Program of SAW for 0.4 kV loads of chilling machines', 'B'),
    'BMT': ('0.4 kV transformer', 'B'),
    'BR': ('Program of comprehensive testing of the system of normal operation reliable power suppl...', 'B'),
    'BRT': ('Program of comprehensive tests of the reliable power supply system of normal operation ...', 'B'),
    'BRU': ('Program of comprehensive testing of emergency power supply system of the first group wh...', 'B'),
    'BT': ('Program of SAW for electric equipment and storage batteries of the first group reliable...', 'B'),
    'BTA': ('Program of SAW for electrical equipment and storage batteries of the emergency power su...', 'B'),
    'BTE': ('Program of SAW for the battery unit of the I group plantwide reliable power supply system', 'B'),
    'BTN': ('Program of SAW for the electric equipment of the plantwide reliable power supply system...', 'B'),
    'BU': ('Program of SAW for the operating DC voltage system for GIS-230 kV and GIS-400 kV', 'B'),
    'BY': ('Program of adjustment for SHC of Unit EP ICS', 'B'),
    'BYA': ('SAW Program for electrical equipment of cabinets of digital and analog information in f...', 'B'),
    'BYC': ('Program of adjustment for remote controls of EP ICS mechanisms and valves', 'B'),
    'BYF': ('Program of SAW for EP ICS FLD cabinets', 'B'),
    'CEJ': ('Testing program for IOPRS acceptance for pilot testing', 'C'),
    'CF': ('Program of adjustment of subsystem for radiation monitoring of premises and operating n...', 'C'),
    'CK': ('Test program for TLS-U acceptance for pilot testing', 'C'),
    'CKU': ('Program autonomous adjustment for SHC of CSS LCP MCS of fire-fighting and service pump ...', 'C'),
    'CKX': ('Program of adjustment for automation tools in the 00UGD demineralizer building', 'C'),
    'CKY': ('Program of autonomous adjustment for set of special equipment of central control post 0...', 'C'),
    'CL': ('Setup program for EP-PP executive part', 'C'),
    'CLP': ('Setup program for ADPS process protections, interlocks and alarms', 'C'),
    'CLR': ('Setup program for CPS electric power supply equipment', 'C'),
    'CM': ('Program of SAW for the FS ICS in the part of fire-fighting valves', 'C'),
    'CMA': ('Program of adjustment for SHC automation tools of essential loads pump station (ELPS-1 ...', 'C'),
    'CMB': ('Program of adjustment for SHC automation tools of essential loads pump station (ELPS-2 ...', 'C'),
    'CMH': ('Setup program for the water chemistry control and monitoring system', 'C'),
    'CMM': ('Test program for biological protection of elements of localizing safety systems', 'C'),
    'CMR': ('Program for calculating the scales of tank level gauges, process tanks and vessels of t...', 'C'),
    'CMS': ('Program of SAW for the FS ICS', 'C'),
    'CMT': ('Program of adjustment for TC ICS measuring channels', 'C'),
    'CMV': ('Setup program for ICS-V measuring channels', 'C'),
    'CMW': ('Program for adjustment of remote control of mechanisms and valves of AWT MCS', 'C'),
    'CMX': ('Program of adjustment for process safeguards, interlocks and alarms (PSIA) of TG proces...', 'C'),
    'CMY': ('Program of adjustment for EPCS measuring channels', 'C'),
    'CN': ('', 'C'),
    'CND': ('Setup program for the RCP technical diagnostics systems', 'C'),
    'CNL': ('', 'C'),
    'CNN': ('Setup program for the secondary coolant leakage detection system (CLDS-2)', 'C'),
    'CNR': ('Program for monitoring of cooling conditions of reactor upper unit equipment (including...', 'C'),
    'CNW': ('Setup program for ICIS measuring channels', 'C'),
    'CNX': ('Program for adjustment of the hardware and software measuring complex (HSMC)', 'C'),
    'CNY': ('Program for adjustment of the automated residual life monitoring system (ARLMS)', 'C'),
    'CNZ': ('Program for adjustment of the integrated diagnostics system (IDS)', 'C'),
    'CX': ('Setup program for LS V ICS, automation equipment of the DM water plant in 10UMX building', 'C'),
    'CXB': ('Setup program for the automation equipment and local control panels (LCP) of the liquid...', 'C'),
    'CXD': ('Program for adjustment of remote controls of doors in 10UJA, 10UKC buildings', 'C'),
    'CXK': ('Program of adjustment for measurement channels of ICS CWT', 'C'),
    'CXM': ('Calibration program for measuring channels of ELCSC MCS CAS', 'C'),
    'CXQ': ('Program of adjustment for automation tools in the storm water treatment structures 00UGH', 'C'),
    'CXS': ('Program autonomous adjustment for MC of CSS LCP MCS of make-up pump station 01UGA', 'C'),
    'CXT': ('Setup program for automation equipment and local control panels of the reactor auxiliar...', 'C'),
    'CXU': ('Setup program for the automation equipment of the evaporating cooling water tower (11-1...', 'C'),
    'CXV': ('Setup program for LS V ICS, automation equipment of the turbine compartment, implemente...', 'C'),
    'CYA': ('Program of SAW for the plant CYA telephone communication', 'C'),
    'CYB': ('Program of SAW for the CYB system of operational loudspeaker and telephone communication', 'C'),
    'CYC': ('Program of SAW for CYC system of personnel annunciation and search', 'C'),
    'CYE': ('Program of SAW for the FS ICS', 'C'),
    'CYF': ('Program of SAW for the CYF clock system', 'C'),
    'CYH': ('Program of SAW for the RNPP-1 operational personnel video recording system (CYH)', 'C'),
    'CYK': ('Program of SAW for the telecommunication transport network system', 'C'),
    'CYL': ('Program of SAW for security alarm', 'C'),
    'CYN': ('Program of SAW for the CYN wire radio translation broadcast system', 'C'),
    'CYP': ('Program of SAW for the CYP01 CCTV system', 'C'),
    'CYQ': ('Program of SAW for the CYQ integrated monitoring system of the internal communication s...', 'C'),
    'CYS': ('Program of SAW for the radio communication system', 'C'),
    'CYV': ('Program of SAW for the TV broadcasting system', 'C'),
    'CYX': ('Program of SAW for LAN', 'C'),
    'CYY': ('Program of SAW for the CYY operational radio telephones operational system', 'C'),
    'CYZ': ('Program of SAW for the CYZ operational speaking document management system', 'C'),
    'DC': ('', 'D'),
    'FAA': ('Program of SAW for the fresh fuel transport and storage system', 'F'),
    'FAB': ('Spent Fuel Storage System', 'F'),
    'FAC': ('Program of SAW for the equipment of the spent fuel transportation and storage system', 'F'),
    'FAK': ('SAW program for fuel pool cooling system (10FAK10-20)', 'F'),
    'FAL': ('Fuel Pool Water Purification System', 'F'),
    'FBA': ('Setup program for automation equipment of the failed fuel detection system', 'F'),
    'FBB': ('Program of SAW for the FA test and repair bench (mechanical part)', 'F'),
    'FCA': ('Program of SAW for the bridge circular electric crane of the reactor compartment (mecha...', 'F'),
    'FCB': ('Program of SAW for Refueling machine (mechanical part)', 'F'),
    'FCC': ('Program of SAW for skip transfer trolley (mechanical part)', 'F'),
    'FCD': ('Program of SAW for the tilter electric equipment', 'F'),
    'FCF': ('Program of SAW for the FFS transport lock equipment', 'F'),
    'FCJ': ('32+5t (mechanical part)', 'F'),
    'FJA': ('Program of SAW for the nuclear reactor cavity equipment', 'F'),
    'FJB': ('Program of SAW for equipment of inspection shafts', 'F'),
    'FJE': ('Program of SAW for the in-core detectors assembly extractor (mechanical part)', 'F'),
    'FJF': ('Program of SAW for the control system of heat exchange pipes, cross pipes and welded jo...', 'F'),
    'FKA': ('Setup program for the automation equipment of decontamination baths', 'F'),
    'FKC': ('Program of SAW for the system of workshops (00FKC) deactivation within 00UKU building', 'F'),
    'FKJ': ('Program of SAW for the system of chemicals preparation and supply (00FKJ)', 'F'),
    'FKT': ('Program of SAW for the decontamination solutions preparation and supply system (10FKT10...', 'F'),
    'GAA': ('Program of SAW for the make-up water mechanical treatment system (01UGA)', 'G'),
    'GAC': ('Program of SAW for the 0.4 kV consumers within 00GAA system', 'G'),
    'GAF': ('Program of SAW for the 10 kV consumers within 00GAF system', 'G'),
    'GC': ('Program of SAW for the 0.4 kV consumers within 00GCR, 00GCF, 00GCB system', 'G'),
    'GCB': ('Program of SAW for the feedwater mechanical treatment system (00GCB)', 'G'),
    'GCF': ('Program of SAW for feed system of cooling water towers', 'G'),
    'GCR': ('Program of SAW for the system for neutralizing effluent water from the water treatment ...', 'G'),
    'GDE': ('Program of SAW for preparation and supply of chemicals to indirect cooling tower system...', 'G'),
    'GHA': ('Program of SAW for the servo cooling system (10GHA)', 'G'),
    'GHC': ('Program for adjustment control cabinets for fine filters of the 02UGA building.', 'G'),
    'GHD': ('', 'G'),
    'GK': ('SAW Program for the hot water supply system of 10UKC, 10UMA, 00UST, 00USV, 00UYB, 00UYC...', 'G'),
    'GKC': ('Program of SAW for the hot water supply system of 00URG building', 'G'),
    'GKD': ('Program of SAW for domestic water supply system', 'G'),
    'GKE': ('SAW Program for Protected-waterhole supply system of 03UYX building', 'G'),
    'GKF': ('Program of SAW for the hot water supply system of 00UAC building', 'G'),
    'GL': ('SAW program for electrical equipment of the RCPS power supply system', 'G'),
    'GM': ('GMM) in 10UKC building', 'G'),
    'GMA': ('Program of SAW for the system of drains accumulations and oily waters removal in 00UTF ...', 'G'),
    'GMB': ('Program of SAW for the system of drain water transfer to sludge disposal site (00GMB)', 'G'),
    'GMC': ('Program of post-install cleaning for the system of pump plants for pumping of domestic ...', 'G'),
    'GMF': ('Program of SAW for the system of clarified water return (00GMF)', 'G'),
    'GML': ('Program of SAW for post-fire-fighting water pumping out system in 00UCB building', 'G'),
    'GMM': ('Program of SAW for the fire water pumping out system of premises 11-14UBZ', 'G'),
    'GMP': ('Program of SAW for the oily water drainage system (GMP) of 11UBN building', 'G'),
    'GND': ('', 'G'),
    'GNR': ('Program of SAW for the system for neutralizing waste water after chemical washing and e...', 'G'),
    'GP': ('Program of SAW for lighting system and welding network', 'G'),
    'GQ': ('SAW Program for domestic sewerage system of 10UBA, 03UYX, 00UYC buildings', 'G'),
    'GQA': ('Program of SAW for the equipment of sewerage pump house', 'G'),
    'GQB': ('Program of SAW for pump station of domestic waste water within the free access zone in ...', 'G'),
    'GQC': ('Program of SAW for the pump plants of 00GQC controlled access zone', 'G'),
    'GQD': ('Program of SAW for protected sewerage pump station for collection and pumping radiactiv...', 'G'),
    'GQF': ('Program of SAW for the household sewage within the controlled access zone (pressure par...', 'G'),
    'GR': ('Program of SAW for the 0.4 kV consumers within 00GRB, 00GRU, 00GRV, 00GRW, 00GRY systems', 'G'),
    'GRB': ('Program of SAW for the system of biological, integrated sewage treatment in the control...', 'G'),
    'GUD': ('SAW program for fire-fighting water system pump station drains', 'G'),
    'GUH': ('Program of SAW for the 0.4 kV loads within process equipment', 'G'),
    'GUS': ('Program of SAW for the systems of rain water treatment facilities in 00UGH building', 'G'),
    'GV': ('Program of SAW for the grounding devices and lighting system', 'G'),
    'JAA': ('Reactor pressure vessel and Reactor Cavity', 'J'),
    'JAB': ('Reactor pressure vessel and Reactor Cavity', 'J'),
    'JAH': ('', 'J'),
    'JAT': ('Setup program for the acoustic leakage monitoring subsystem (ALMS)', 'J'),
    'JBA': ('', 'J'),
    'JBB': ('Program for measuring lengths of channels for installation of in-core detector assemblies', 'J'),
    'JD': ('Setup program for the industrial seismic protection system (ISPS)', 'J'),
    'JDA': ('Program and procedure for SAW of CPS drives (mechanical part) on test bench', 'J'),
    'JEA': ('Program of SAW for monitoring level in steam generators and steam moisture in steam lin...', 'J'),
    'JEB': ('SAW program for reactor coolant pumps (10JEB)', 'J'),
    'JEC': ('Reactor coolant piping system', 'J'),
    'JEF': ('Pressurization system', 'J'),
    'JEV': ('SAW program for the RCPS motor lubrication system (10JEV)', 'J'),
    'JK': ('', 'J'),
    'JKA': ('Program for loading the simulation zone into the reactor', 'J'),
    'JKM': ('Molten Core Catcher', 'J'),
    'JKS': ('Program of SAW for the refueling monitoring system (mechanical part)', 'J'),
    'JKT': ('Setup program for the refueling monitoring system (RMS) and the reactor FAC equipment', 'J'),
    'JKU': ('', 'J'),
    'JM': ('SAW program for the main and emergency locks (mechanical part)', 'J'),
    'JMA': ('UJA Building Confining System', 'J'),
    'JME': ('Program of SAW for the transport lock (mechanical part)', 'J'),
    'JMF': ('Program of SAW for electrical equipment of the main personnel lock 10JMF10AB001', 'J'),
    'JMG': ('Program of SAW for electrical equipment of the emergency personnel lock 10JMG10AB001', 'J'),
    'JMN': ('Sprinkler system', 'J'),
    'JMT': ('Containment Emergency Hydrogen Removal System', 'J'),
    'JMU': ('Setup program for the containment hydrogen concentration monitoring equipment', 'J'),
    'JMY': ('Setup program for the containment reinforcement tension monitoring system АМЦ11830 (10J...', 'J'),
    'JNA': ('Primary Circuit Emergency and Planned Cooldown And Fuel Pool Cooling System', 'J'),
    'JNB': ('Program of SAW for the passive heat removal system (10JNB 50-80)', 'J'),
    'JND': ('Emergency Boron Injection System', 'J'),
    'JNG': ('SAW program for the second stage hydroaccumulator system (passive part of the emergency...', 'J'),
    'JYF': ('Setup program for the loose part detection system (LPDS)', 'J'),
    'JYG': ('Setup program for the vibration monitoring system (VMS)', 'J'),
    'KAA': ('Component Cooling Circuit of Essential Loads', 'K'),
    'KB': ('Program of SAW for the gates 10UKC04AB501 and 10UKC04AB502 of 10UKC building (mechanica...', 'K'),
    'KBA': ('Primary circuit blowdown and feed water system', 'K'),
    'KBB': ('Operating grade coolant storage system', 'K'),
    'KBC': ('SAW program for distillate water system (10KBC10-30)', 'K'),
    'KBD': ('Program of SAW for the system for supplying reagents to the primary coolant (10KBD)', 'K'),
    'KBE': ('Program of SAW for the coolant low temperature purification system (10KBE50-60)', 'K'),
    'KBF': ('Program of SAW for the coolant treatment system (10KBF)', 'K'),
    'KBH': ('Program of SAW for the spent fuel pool and refueling pool water treatment system (10KBH)', 'K'),
    'KL': ('Program for checking the efficiency of aerosol filters of filtering plants of ventilati...', 'K'),
    'KLA': ('Program of SAW for the indoor and outdoor containment ventilation systems of 10UJA buil...', 'K'),
    'KLB': ('Program of SAW for 0.4 kV loads of systems 11,12KLB', 'K'),
    'KLC': ('Program of SAW for the CAA rooms ventilation systems of 10UJA building', 'K'),
    'KLE': ('Individual test programs for ventilation system equipment of the building 10UKC', 'K'),
    'KLF': ('Program of SAW for the 0.4 kV consumers within 00KLF ventilation system', 'K'),
    'KLP': ('Program of SAW for the 0.4 kV consumers within 00KLP ventilation system', 'K'),
    'KLS': ('Program of SAW for the 0.4 kV consumers within 00KLS ventilation system', 'K'),
    'KP': ('Program of SAW for 0.4 kV loads of systems 10KPF20-60, 10KPM, 10KPL, 10KP', 'K'),
    'KPA': ('Program of SAW for the SRW sorting system (KPA10)', 'K'),
    'KPC': ('Program of SAW for cementation system', 'K'),
    'KPE': ('Program of SAW for the set of equipment for arranged storage of highly radioactive SRW ...', 'K'),
    'KPF': ('Program of SAW for the drain water treatment system (unit for collecting and supplying ...', 'K'),
    'KPH': ('Program of SAW for the SRW burning system (KPH20)', 'K'),
    'KPJ': ('Program of SAW for the reagents preparation and supply system (10KPJ)', 'K'),
    'KPK': ('Program of SAW for the liquid radioactive waste intermediate storage system (10KPK)', 'K'),
    'KPL': ('Process Blowoff Hydrogen Burning System', 'K'),
    'KPM': ('Radioactive Blowoffs Treatment System', 'K'),
    'KPN': ('Program of SAW for the cementing plant of 10UKC building (KPN)', 'K'),
    'KPP': ('Program of SAW for the SRW grinding plant (00КРP10)', 'K'),
    'KRA': ('SAW program for the system of nitrogen supply to equipment (10KRA20)', 'K'),
    'KT': ('Program of SAW for 0.4 kV loads of systems 10KTA, 10KTH, 10KTC', 'K'),
    'KTA': ('Primary Circuit Drainage and Controlled Leaks System', 'K'),
    'KTB': ('Reactor Equipment Gas Blow-Off System', 'K'),
    'KTC': ('Borated Drains Collection System', 'K'),
    'KTH': ('Special Sewage System', 'K'),
    'KTK': ('SAW program for active drain system of 00UFC building (10KTK)', 'K'),
    'KTN': ('Program of SAW for the 10UKC building special sewerage system (free flow part) (10KTN)', 'K'),
    'KTP': ('Emergency Gas Removal System', 'K'),
    'KTQ': ('Fuel Pool Liner Leak Tightness Control System', 'K'),
    'KTR': ('Program of SAW for the special sewerage system of amenities building within controlled ...', 'K'),
    'KUA': ('SAW program for the sample selection system from reactor building equipment', 'K'),
    'KUB': ('Program of SAW for sampling system from equipment of 00SRP50 system in 00UKS building', 'K'),
    'KUD': ('Program of SAW for the system of sampling from equipment of 00UYB building', 'K'),
    'KUE': ('Program of SAW for the sampling system from purification plants (10KUE)', 'K'),
    'KUJ': ('Program of SSAW for sampling system for gaseous radioactive media from buildings 10UKA,...', 'K'),
    'KUK': ('Program of SAW for air bleed system to the plant gas aerosol radiation meters', 'K'),
    'KW': ('Program of SAW for 0.4 kV loads of systems 10KWA, 10KWB, 10KWC, 10KUJ', 'K'),
    'KWA': ('Hydrotests and I&C Sensors Blowdown System', 'K'),
    'KWB': ('Program of SAW for the Inst. sensor blowdown system (10KWB)', 'K'),
    'KWC': ('Hydrotests and I&C Sensors Blowdown System', 'K'),
    'LA': ('Program of SAW for the auxiliary feedwater system (10LAH) and SFWP (10LAJ)', 'L'),
    'LAA': ('Program of SAW for the feedwater collecting and deaeration system, including BRU-D (10LAA)', 'L'),
    'LAB': ('Vibration survey program for the steam and feedwater pipelines of the steam chamber', 'L'),
    'LAC': ('Vibration survey and vibration alignment program for electric feed pump units', 'L'),
    'LAD': ('Program of SAW for the high pressure regeneration system (10LAD, 10LBQ, 10LCH)', 'L'),
    'LAV': ('Program of SAW for the EFP lubricating oil system (10LAV)', 'L'),
    'LB': ('Program of SAW for the separation and reheating system (10LBJ, 10LBB)', 'L'),
    'LBA': ('Main Steamlines System (Reactor Shop, Including UJE Chambers)', 'L'),
    'LBG': ('Program of SAW for the system of steam supply to consumers (10LBG)', 'L'),
    'LBW': ('Program of SAW for the turbine sealing system (10LBW, 10MAM)', 'L'),
    'LC': ('Program of SAW for 0.4 kV loads of systems 10LCP, 10LCM', 'L'),
    'LCA': ('Program of SAW for the 1st stage full-flow condensate system (10LCA10)', 'L'),
    'LCB': ('Vibration survey and vibration alignment program for pump units up to 1000 kW in 10UMA ...', 'L'),
    'LCC': ('Program of SAW for the low pressure regeneration system (10LСС, 10LBS, 10LCJ)', 'L'),
    'LCE': ('Program of SAW for the full-flow condensate injection system for cooling low-pressure c...', 'L'),
    'LCM': ('Program of SAW for the condensate return system (LCM) within 00UKU building', 'L'),
    'LCP': ('SAW program for demineralized water system in UMA building (10LCP10)', 'L'),
    'LCQ': ('SAW program for SG blowdown and drainage system (10LCQ10)', 'L'),
    'LCS': ('Program of SAW for the MSR heating steam condensate removal system (LCS);', 'L'),
    'LCT': ('Program of SAW for the MSR separation system (10LCT)', 'L'),
    'LCW': ('Program of SAW for the system for supplying condensate to the seals of vacuum valves (1...', 'L'),
    'LCX': ('Program of SAW for the system of condensate supply to control SCV valves (10LCX)', 'L'),
    'LD': ('Program of SAW for 0.4 kV loads of systems LDB, LDF, LFN', 'L'),
    'LDB': ('Program of SAW for the stand-alone demineralizer (10LDB)', 'L'),
    'LDF': ('Program of SAW for the turbine condensate demineralization and deironing system (DM plant)', 'L'),
    'LDP': ('SAW program for the reprocessing and flushing of spent resins of CPS (10LDP) of the bui...', 'L'),
    'LDR': ('SAW program for the removal of washing and regeneration media of CPS (10LDR) of the bui...', 'L'),
    'LFG': ('Program of SAW for the SG chemical flushing system (10LFG)', 'L'),
    'LFN': ('Program of SAW for the secondary circuit working medium conditioning system (10LFN)', 'L'),
    'LWB': ('SAW program for hydraulic testing of equipment and pipelines of secondary circuit in UM...', 'L'),
    'MA': ('Program of SAW for 0.4 kV loads of systems 10MAK, 10MAV, 10MAN, 10MAX, 10MVL', 'M'),
    'MAG': ('Program of SAW for the main condenser system (10MAG)', 'M'),
    'MAJ': ('Program of SAW for the condenser steam part evacuation system (10MAJ10.20)', 'M'),
    'MAL': ('Program of SAW for the high and low pressure turbine drainage system (10MAL10.20)', 'M'),
    'MAM': ('Vibration survey and vibration alignment program for exhausters in 10UMA building', 'M'),
    'MAN': ('Program of SAW for the turbine bypass system (BRU-K) (10MAN)', 'M'),
    'MAV': ('SAW program for turbine generator and turbine lubrication system (10MAV, 10MVB, 10MVA50...', 'M'),
    'MAX': ('Program of SAW for the turbine control system (10MAX10, 10MAX50, 10MAQ10, 10MXC)', 'M'),
    'MKA': ('Program of SAW for electrical equipment of turbogenerator 10MKA01', 'M'),
    'MKF': ('Program of SAW for the generator stator and pressing ring water cooling system (10MKF01)', 'M'),
    'MKG': ('Program of SAW for the generator housing ventilation system (10MKG)', 'M'),
    'MKY': ('Program of SAW for the generator overhang vibration control system', 'M'),
    'MVA': ('Program of SAW for the system of oil supply to feedwater pumps, steam dump device BRU-K...', 'M'),
    'MVL': ('Program of SAW for the oil jacking system of rotors and shaft-turning gear (10MVL10, 10...', 'M'),
    'MVU': ('Post-installation cleaning program for the oil drain system of turbine building equipme...', 'M'),
    'MXA': ('SAW program for I&C sensors purge system in 10UMA building', 'M'),
    'MXN': ('Program of SAW for the BRU-K regulation (control) oil supply system (10MXN, 10MXN13, 10...', 'M'),
    'NAA': ('Program of SAW for the delivery-water heater system (10NAA, 10NDA10-30, 10NAB)', 'N'),
    'NAB': ('', 'N'),
    'NDE': ('Program of SAW for the system of make-up water for heating network', 'N'),
    'NDF': ('Program of SAW for the system of heat line water supply and return to on-site heating n...', 'N'),
    'PA': ('Program of SAW for 10 kV loads of systems 10PAC, 10PCC', 'P'),
    'PAA': ('Program of SAW for water purification plant flushing water system (10PAA)', 'P'),
    'PAB': ('Program of SAW for the main cooling water system in the turbine building (10PAB10-70) a...', 'P'),
    'PAC': ('', 'P'),
    'PAD': ('Program of SAW for 0.4 kV loads of 10PAD system', 'P'),
    'PAH': ("Program of SAW for automation equipment of 'Taprogge' ball cleaning unit", 'P'),
    'PCB': ('Program of SAW for the chill supply system (PCB) for ventilation systems of 13UBN building', 'P'),
    'PCC': ('Program of SAW for feedwater supply system (PCC05) for the 00UGD building', 'P'),
    'PCD': ('Program of SAW for service water supply system (00PCD01)', 'P'),
    'PE': ('Program of SAW for 0.4 kV loads of systems 11PEA, 10PEC', 'P'),
    'PEB': ('Cooling Water Pipelines Systems', 'P'),
    'PEC': ('Program of SAW for drainage system of cooling water towers (10PEС50)', 'P'),
    'PED': ('', 'P'),
    'PGB': ('SAW program for the normal operation closed cooling water system of 10UJA building (10P...', 'P'),
    'PHN': ('', 'P'),
    'PUA': ('Program of SAW for the oil supply and pumping out system (10PUA)', 'P'),
    'PUE': ('Program of SAW for system of pumps for the removal fish fry (00PUE) in 01UGA building', 'P'),
    'QC': ('Program of SAW for the flocculent reception, preparation and transfer system (1QCJ)', 'Q'),
    'QCB': ('Program of SAW for the nitric acid reception, preparation and transfer system (00QCB)', 'Q'),
    'QCD': ('Program of SAW for the sodium hydroxide reception, preparation and transfer system (00QCD)', 'Q'),
    'QCE': ('Program of SAW for the hydrazine reception, preparation and transfer system (00QCE)', 'Q'),
    'QCF': ('Program of SAW for the ammonia reception, preparation and transfer system (00QCF)', 'Q'),
    'QCJ': ('Program of SAW for the installed equipment and pipelines within the flocculent receptio...', 'Q'),
    'QCQ': ('Program of SAW for the sulfuric acid reception, preparation and transfer system (00QCQ)', 'Q'),
    'QCR': ('Program of SAW for the trisodium phosphate reception, preparation and transfer system (...', 'Q'),
    'QCS': ('Program of SAW for the coagulant reception, preparation and transfer system (00QCS)', 'Q'),
    'QEB': ('Program of SAW for system of process compressed air supply 00QEB', 'Q'),
    'QFA': ('Compressed Air System for Valve Pneumatic Drives', 'Q'),
    'QHA': ('Program of SAW for drain water pipelines (QHA70)', 'Q'),
    'QHC': ('Program of SAW for the system of feedwater', 'Q'),
    'QHG': ('Individual test program of installed equipment and pipelines for makeup water system', 'Q'),
    'QHL': ('Program of SAW for the system of blast air', 'Q'),
    'QHN': ('Program of SAW for the fume-collecting chimney', 'Q'),
    'QJA': ('Program of SAW for the oxygen storage and supply system (QJA)', 'Q'),
    'QJB': ('Program of SAW for nitrogen storage and supply system (QJB)', 'Q'),
    'QJD': ('Program of SAW for oxygen and nitrogen making system (QJD)', 'Q'),
    'QK': ('Program of SAW for the chill supply system for essential loads 11QK&', 'Q'),
    'QKA': ('Program of SAW for the chill supply system for non-essential loads (10QKA)', 'Q'),
    'QKB': ('Program of SAW for the refrigerant storage and charging system 11QKB of the chill suppl...', 'Q'),
    'QKC': ('Program of SAW for supports and suspensions of equipment and pipelines in 00UTH building.', 'Q'),
    'QKD': ('Program of SAW for coolant-supply pipelines of ventilation system of 00UEL building', 'Q'),
    'QKF': ('Program of SAW for the cold supply system of 00UFC building ventilation', 'Q'),
    'QKH': ('Program of SAW for systems of ventilation heating and hot water supply of 00UYD building', 'Q'),
    'QKJ': ('Individual test programs of installed equipment and pipelines for refrigeration supply ...', 'Q'),
    'QKK': ('Individual test programs of installed equipment and pipelines of refrigeration supply s...', 'Q'),
    'QKM': ('', 'Q'),
    'QKQ': ('SAW program for ventilation cold supply system', 'Q'),
    'QKR': ('Program of SAW for system of ventilation cold supply of 00USV building', 'Q'),
    'QKS': ('Program of SAW for the cold supply system of 00UEL building ventilation', 'Q'),
    'QKT': ('Program of SAW for ventilation heating system and hot water supply system of 00USF buil...', 'Q'),
    'QSA': ('Program of SAW for the storage and supply system of transformer oil (00QSA10)', 'Q'),
    'QSB': ('SAW program for OMTI oil storage and supply system (00QSВ10)', 'Q'),
    'QU': ('Setup program for ICS of TC automated chemical monitoring systems (TC ACM)', 'Q'),
    'QUA': ('Program of SAW for the automatic chemical monitoring system of the feedwater system (10...', 'Q'),
    'QUB': ('Program of SAW for the automatic chemical monitoring system of the steam system (proces...', 'Q'),
    'QUC': ('Program of SAW for the automatic chemical monitoring system of the condensate system (p...', 'Q'),
    'QUG': ('Program of SAW for the automatic chemical monitoring system of the DM water plant syste...', 'Q'),
    'QUH': ('Program for the SAW of the circuit 2 sampling system and CPP(10QUH)', 'Q'),
    'QUK': ('Program of SAW for automated chemical monitoring system for steam generator blowdown sy...', 'Q'),
    'QUL': ('Program of SAW for sampling system in 00UTH building', 'Q'),
    'QXJ': ('Program of SAW for the 0.4 kV consumers within 00QXJ system', 'Q'),
    'SA': ('Program of SAW for 0.4 kV loads of SAE, SAC ventilation systems', 'S'),
    'SAB': ('Program for individual tests of equipment of ventilation systems of building 00UYB', 'S'),
    'SAC': ('Program for individual tests of equipment of ventilation systems of building 02UBG', 'S'),
    'SAD': ('Program of SAW for ventilation systems of the emergency power supply system SDPP buildi...', 'S'),
    'SAE': ('Program of SAW for the 0.4 kV consumers within 00SAE ventilation system', 'S'),
    'SAF': ('Program of SAW for the ventilation systems of 00UFC fresh fuel storage premises', 'S'),
    'SAH': ('Program of SAW for the 0.4 kV consumers within 00SAH ventilation system', 'S'),
    'SAJ': ('Program of SAW for 0.4 kV loads of the 00SAJ ventilation system', 'S'),
    'SAK': ('Program of SAW for systems of ventilation heating and hot water supply of 00USV building', 'S'),
    'SAM': ('Individual test programs for ventilation system equipment of building 10UMA', 'S'),
    'SAN': ('SAW Program for ventilation system at 01-05UYP', 'S'),
    'SAP': ('Program of SAW for the ventilation systems of oil-polluted water drains treatment facil...', 'S'),
    'SAQ': ('Individual test program for ventilation system equipment of building 11-12URF', 'S'),
    'SAR': ('Program of SAW for the 0.4 kV consumers', 'S'),
    'SAS': ('Program for SAW of 0.4 kV load of 00SAS ventilation system', 'S'),
    'SAT': ('Program of SAW for ventilation heating system and hot water supply of 00UST building', 'S'),
    'SAU': ('Program of SAW for systems of SAU ventilation in 03UYX building. Aerodynamic test proce...', 'S'),
    'SB': ('SAW program for ventilation heat supply system', 'S'),
    'SBC': ('Program of SAW for heat supply system of ventilation system of 10UBA building', 'S'),
    'SBD': ('Program of SAW for heat-supply pipelines of ventilation system of 00UEL building', 'S'),
    'SBH': ('Program of SAW for heat supply systems of ventilation system of 10UMA building', 'S'),
    'SBJ': ('Program of SAW for heat supply system of ventilation and hot water supply system of 10U...', 'S'),
    'SBP': ('Program of SAW for 01UYP,02UYP,04UYP building heat supply systems', 'S'),
    'SBQ': ('Program of SAW for heat supply systems for ventilation systems of 10URS building', 'S'),
    'SBS': ('Program of SAW for heat-supply pipelines of ventilation system of 00UGD building', 'S'),
    'SBT': ('Program of SAW for SBT heating system of 00USJ building', 'S'),
    'SBU': ('Program of SAW for ventilation heating system, hot water supply system of 00UKS building', 'S'),
    'SCA': ('Program of SAW for the system of compressed air supply for pneumatically driven equipme...', 'S'),
    'SCB': ('Program of SAW for the compressed air supply system for process requirements (10SCB)', 'S'),
    'SCC': ('Compressed Air Supply System for Containment Test', 'S'),
    'SCD': ('', 'S'),
    'SG': ('Program of SAW for the FS ICS', 'S'),
    'SGA': ('Program of SAW for water fire-fighting systems (SGA) in 11UBN building', 'S'),
    'SGC': ('Program of SAW for the automatic water fire-fighting system (SGC) in 11URZ tunnel', 'S'),
    'SGK': ('SAW program for the automatic fire extinguishing systems with mist water SGK in the bui...', 'S'),
    'SMA': ('Program for SAW of 00SMA20AE001 bridge electrical single-beam suspended crane with lift...', 'S'),
    'SMB': ('Program of SAW for electrical equipment of electric traveling hoists', 'S'),
    'SMD': ('Program of SAW for the electric equipment of electric hoist', 'S'),
    'SME': ('c gantry crane (mechanical part)', 'S'),
    'SMF': ('c special electric cranes (mechanical part)', 'S'),
    'SMG': ('Program of SAW for 00SMG20AE100,101,102 bridge electric single-beam suspended cranes (m...', 'S'),
    'SMJ': ('Program of SAW for electrical equipment of the single-girder suspended traveling crane ...', 'S'),
    'SMK': ('Program of SAW for the electric equipment of electric hoist', 'S'),
    'SMM': ('Program of SAW for electrical equipment of the electric hoist', 'S'),
    'SMQ': ('Program of SAW for electric single-girder suspended single-span traveling crane 10SMQ20...', 'S'),
    'SMR': ('Program of SAW for the electric single-girder suspended traveling cranes (mechanical part)', 'S'),
    'SMS': ('Program of SAW for the 00SMS20AE100 suspended electric single-beam crane (hardware)', 'S'),
    'SMT': ('Program of SAW for the 00SMT20AE401 bridge electric single-beam suspended single-span c...', 'S'),
    'SMY': ('Program of SAW for load lifting cranes of 00UYH building (mechanical part)', 'S'),
    'SNA': ('Program of SAW for the electric equipment of passenger elevator', 'S'),
    'SNB': ('Program of SAW for the electric equipment of cargo elevator', 'S'),
    'SRP': ('Program of SAW for the water treatment system within active laundry system (00SRP50)', 'S'),
    'STA': ('Program of SAW for the 0.4 kV consumers within 00STA20 system', 'S'),
    'STP': ("Program of SAW for the 'clean' compartment within active laundry system (00STP)", 'S'),
    'WB': ('Program of SAW for electrical equipment of process loads', 'W'),
    'XJ': ('XJR20)', 'X'),
    'XJA': ('Program of SAW for diesel-electric station', 'X'),
    'XJG': ('SAW program for the DG cooling system (11XJG10)', 'X'),
    'XJN': ('SAW program for the DG fuel system (11XJN10)', 'X'),
    'XJV': ('SAW program for the DG oil system (11XJV10)', 'X'),
    'XJX': ('SAW program for the DG starting air system (12XJX20)', 'X'),
    'XK': ('Program of SAW for diesel generator units', 'X'),
    'XKA': ('Program of SAW for the electrical equipment of diesel generator unit 10XKA30, UPS and a...', 'X'),
    'XKV': ('Program of SAW for the generator lubrication system (11XKV10)', 'X'),
    'XLA': ('Setup program for DGU ICS of 11UBN building', 'X'),}

# -----------------------------------------------------------------------------
# BUILDING CODES ([Unit]U[2 letters]).
# Hard-coded from the "Buildings" sheet of the KKS Master List (257 known codes).
# -----------------------------------------------------------------------------

BUILDING_CODES: Dict[str, str] = {
    '00UAB': 'Program for individual tests of equipment of ventilation systems of building 00UAB',
    '00UAC': 'Program for individual tests of equipment of ventilation systems of building 00UAC',
    '00UAD': 'SAW program for grounding devices and lighting system',
    '00UAG': 'Program of SAW for the SGC31) automated water fire-fighting units within 00UAG structure',
    '00UAX': 'Program of SAW for the 0,4 kV distribution assemblies',
    '00UAZ': 'Program of SAW for the 0.4 kV distribution assemblies',
    '00UBG': 'Program of SAW for the ventilation systems of 00UBG building',
    '00UBH': 'Program of SAW for the grounding devices',
    '00UCB': 'Program of SAW for the grounding devices and lighting system',
    '00UCX': 'Program of preliminary test for AERMS',
    '00UEK': 'Program of SAW for the diesel oil storage and transfer system for ABH and BDGEPS',
    '00UEL': 'Program of SAW for the 0,4 kV distribution assemblies',
    '00UFC': 'Program of SAW for the ventilation systems of 00UFC fresh fuel storage premises',
    '00UGA': '',
    '00UGD': 'Program of SAW for the coagulant reception, preparation and transfer system (00QCS)',
    '00UGG': 'Program of SAW for the SAQ ventilation system of 00UGG buildings',
    '00UGH': 'Program of SAW for the systems of rain water treatment facilities in 00UGH building',
    '00UGM': 'Program of SAW for the systems of oil-polluted water drains treatment facilities in 00U...',
    '00UGR': 'Program of SAW for the system of drain water transfer to sludge disposal site (00GMB)',
    '00UGV': 'Program of SAW for the 0.4 kV loads within process equipment',
    '00UGW': 'Program of SAW for the system of biological, integrated sewage treatment in the control...',
    '00UJY': '',
    '00UKB': '',
    '00UKR': 'Program for SAW of 00SMK20AE001 bridge electrical crane with lifting capacity of 60 t i...',
    '00UKS': 'Program of SAW for the water treatment system within active laundry system (00SRP50)',
    '00UKU': 'Program of SAW for the condensate return system (LCM) within 00UKU building',
    '00UKX': 'Program of SAW for the SGA water fire-fighting systems in 00UKX building',
    '00UMA': '',
    '00UNA': 'Program of SAW for the SAM ventilation system of 00UNA building',
    '00UPX': 'Program of SAW for the 0.4 kV consumers within process equipment',
    '00UQR': '',
    '00URG': '',
    '00URT': 'Program of SAW for the ventilation systems of 00URT building',
    '00URX': 'Program of SAW for the system of ventilator cooling towers filling',
    '00USF': 'Program of adjustment for supports and suspensions of equipment and pipelines in 00USF ...',
    '00USJ': 'Program of SAW for SBT heating system of 00USJ building',
    '00UST': '0.4 kV power transformers',
    '00USV': 'Program of SAW for the SGC, SGA water fire-fighting systems in 00USV building',
    '00USY': 'Program of adjustment for supports and suspensions of equipment and pipelines of pile t...',
    '00UTF': 'Program of SAW for the system of compressed air supply for pneumatically driven equipme...',
    '00UTH': 'Program of SAW for the fume-collecting chimney',
    '00UXD': 'Program of SAW for the 0,4 kV distribution assemblies',
    '00UXG': 'Program of SAW for the grounding devices and lighting system',
    '00UYB': 'Program for individual tests of equipment of ventilation systems of building 00UYB',
    '00UYC': 'Program for SAW of SGA water fire-fighting system in 00UYC building',
    '00UYD': 'Program of SAW for the SGA water fire-fighting systems in 00UYD building',
    '00UYE': '',
    '00UYH': 'Program of SAW for systems of ventilation in 00UYH building. Aerodynamic test procedure',
    '00UYP': '0.4 kV power transformers',
    '00UYQ': 'Program of SAW for systems of ventilation in 00UYQ building',
    '00UZF': 'c gantry crane (mechanical part)',
    '00UZR': 'SAW program for the ventilation systems of the Administrative-customs building facilities',
    '01-02UGF': '',
    '01-02USZ': 'Program of SAW for the grounding devices and lighting system',
    '01-03UGJ': 'Program of SAW for the installed equipment and pipelines of rain water treatment facili...',
    '01-03UXX': '',
    '01-03UYF': 'Program of SAW for the grounding devices and lighting system',
    '01-03UYY': '',
    '01-04UGV': '',
    '01-04UGW': '',
    '01-04UJY': 'Program of SAW for the 0.4 kV consumers within ventilation system',
    '01-04USZ': '',
    '01-05UGG': '',
    '01-05UGU': 'Program of SAW for system of treated rain water within 01-05UGU sewerage pump house',
    '01-05UYP': '',
    '01-06UGM': '',
    '01-07UYP': '',
    '01-08UGH': '',
    '01-08UXD': '',
    '01-09UBZ': 'Program of SAW for the grounding devices and lighting system',
    '01-09UKZ': 'Program of SAW for the grounding devices and lighting system',
    '01-09UTZ': 'Program of SAW for the grounding devices and lighting system',
    '01-09UXG': '',
    '01UBG': 'Program of SAW for the grounding devices and lighting system',
    '01UBY': 'Program of SAW for the grounding devices, lightning protection and lighting system',
    '01UBZ': 'Program of SAW for the grounding devices and lighting system',
    '01UEH': '',
    '01UEL': '',
    '01UGA': 'SAW Program for ventilation system of 01UGA makeup water pump station',
    '01UGD': '',
    '01UGG': 'Program of SAW for domestic water supply system',
    '01UGH': 'Program of SAW for the storm water drainage system of 01UGH building',
    '01UGJ': 'Program of SAW for the installed equipment and pipelines of rain water treatment facili...',
    '01UGU': 'Program of SAW for system of treated rain water within 01-05UGU sewerage pump house',
    '01UGV': '',
    '01UJY': 'Program of SAW for ventilation systems of common-access area 01UJY gallery',
    '01UKH': 'Program of SAW for the grounding devices and lighting system',
    '01UKZ': 'Program of SAW for the grounding devices and lighting system',
    '01URG': 'Program of SAW for the hot water supply system of 00URG building',
    '01USK': 'Program of SAW for the 00SMS20AE200 suspended electric single-beam crane (hardware)',
    '01USY': '',
    '01USZ': 'Program of SAW for the grounding devices and lighting system',
    '01UTZ': 'Program of SAW for the grounding devices and lighting system',
    '01UXC': 'Program of SAW for the 0.4 kV consumers within ventilation system',
    '01UXG': 'Program of SAW for the grounding devices and lighting system',
    '01UXV': 'Program of SAW for enclosed sewage pump station for collection and pumping of sanitary ...',
    '01UXW': 'Program of SAW for protected sewerage pump station for collection and pumping radiactiv...',
    '01UXX': 'Individual test program of installed equipment and pipelines for automatic water fire s...',
    '01UYC': '',
    '01UYE': 'Program of SAW for the fire-fighting water supply system from utility and drinking wate...',
    '01UYP': 'SAW Program for ventilation system at 01-05UYP',
    '01UYX': 'Program of SAW for QKC cold supply system for 01UYX building',
    '01UYY': 'Program of SAW for the ventilation systems of 01UYY building',
    '01UZC': 'Program of SAW for the grounding devices and lighting system',
    '02-03UGG': '',
    '02UAC': '',
    '02UBG': 'Program for individual tests of equipment of ventilation systems of building 02UBG',
    '02UBY': 'Program of SAW for the grounding devices, lightning protection and lighting system',
    '02UEH': '',
    '02UGA': 'Program of SAW for equipment and pipelines of system of drains and discharge for water ...',
    '02UGG': 'Program of individual tests for auxiliary tank and pipelines 02-03UGG',
    '02UJY': 'Program of SAW for ventilation systems of common-access area 02UJY gallery',
    '02UKH': 'Program of SAW for the grounding devices and lighting system',
    '02URG': 'Program of SAW for ventilation systems within warehouse for preparation and supply of c...',
    '02USK': 'Program of SAW for 00SMS20AE201 suspended electric single-beam crane (hardware)',
    '02UXC': 'Program of SAW for the grounding devices and lighting system',
    '02UXD': '0.4 kV power transformers',
    '02UXV': 'Program of SAW for enclosed sewage pump station for collection and pumping of sanitary ...',
    '02UXW': 'Program of SAW for protected sewerage pump station for collection and pumping radiactiv...',
    '02UXX': 'Program of SAW for the SGA water fire-fighting system in 02UXX building',
    '02UYE': 'Program of SAW for the 0.4 kV consumers within ventilation system',
    '02UYP': 'Program of SAW for the grounding devices and lighting system',
    '02UYX': 'Program of SAW for QKC cold supply system for 02UYX building',
    '02UYY': 'Program of SAW for the ventilation systems of 02UYY building',
    '02UZC': 'Program of SAW for the grounding devices and lighting system',
    '03-04USZ': 'Program of SAW for the grounding devices and lighting system',
    '03-05UBY': 'Program of SAW for the grounding devices',
    '03UBG': 'Program of comprehensive tests of the reliable power supply system of normal operation ...',
    '03UBW': '',
    '03UBY': 'Program of SAW for the grounding devices',
    '03UGF': 'Program of SAW for the fire-fighting water supply system (00SGA)',
    '03UGW': 'Program of SAW for the ventilation systems of 03UBW building',
    '03UJY': 'Program of SAW for ventilation systems of common-access area 03UJY gallery',
    '03UKH': 'Program of SAW for the grounding devices and lighting system',
    '03USK': 'Program of SAW for the ventilation systems of 03USK building',
    '03USZ': 'Program of SAW for the grounding devices and lighting system',
    '03UXC': 'Program of SAW for the water supply system (from well) of 03UXC building',
    '03UXV': 'Program of SAW enclosed sewage pump station for collection and pumping of sanitary effl...',
    '03UXW': 'Program of SAW for protected sewerage pump station for collection and pumping radiactiv...',
    '03UXX': 'Program of SAW for the SGA water fire-fighting systems in 03UXX building',
    '03UYP': 'SAW program for water fire-fighting system (SGA83) of 03UYP building',
    '03UYX': 'Program of SAW for systems of SAU ventilation in 03UYX building. Aerodynamic test proce...',
    '04-05UGG': 'Program of SAW for the grounding devices and lighting system',
    '04-07UEH': '',
    '04-09UTZ': '',
    '04UBG': 'Program of SAW for plantwide standby auxiliary transformers (10BCT01, 10BCT02)',
    '04UEH': 'Program of SAW for the grounding devices and lighting system',
    '04UGG': 'Program of SAW for the grounding devices and lighting system',
    '04UGH': 'Program of SAW for the installed equipment and pipelines of rain water treatment facili...',
    '04UGM': '',
    '04UGV': '',
    '04UGW': 'Program of SAW for the grounding devices and lighting system',
    '04UXC': 'Program of SAW for the cold supply system of 04UXC building',
    '04UXV': 'Program of SAW enclosed sewage pump station for collection and pumping of sanitary effl...',
    '04UXW': 'Program of SAW for protected sewerage pump station for collection and pumping radiactiv...',
    '04UYP': 'Program of SAW for the FS ICS',
    '04UYX': 'Program of SAW for the SGA water fire-fighting system in 04UYX building',
    '04UZJ': '',
    '04UZK': '',
    '05-09UBG': 'SAW program for grounding devices and lighting system',
    '05UBG': '0.4 kV power transformers',
    '05UEH': '',
    '05USZ': 'Program of SAW for the grounding devices and lighting system',
    '05UXC': 'Program of SAW for the cold supply system of 05UXC building',
    '05UYP': '',
    '06-07USZ': 'Program of SAW for the grounding devices and lighting system',
    '06UBG': '',
    '06UEH': '',
    '06UGV': '',
    '06USZ': 'Program of SAW for the grounding devices and lighting system',
    '06UXC': 'Program of SAW for diesel generator unit (XJA)',
    '06UYP': 'SAW program for grounding devices and lighting system',
    '07UEH': '',
    '07UXC': 'Program of SAW for XJN50 fuel system in 06,07UXC buildings',
    '08-09USZ': 'Program of SAW for the grounding devices and lighting system',
    '08UGH': 'Program of SAW for 0.4 kV consumers of process equipment of treated waste water pump house',
    '08USZ': 'Program of SAW for the grounding devices and lighting system',
    '08UYP': '',
    '09USY': '',
    '10UAC': '',
    '10UAY': 'Program of SAW for the 400 kV gas insulated current-conducting wire, power unit No.1',
    '10UAZ': 'Program of SAW for automatic water fire-fighting systems SGC',
    '10UBA': 'Program of SAW for electric equipment and storage batteries of the first group reliable...',
    '10UBB': '',
    '10UBF': 'SAW program for grounding devices and lighting system',
    '10UBP': '',
    '10UGB': 'Program of SAW for grounding devices and lighting system',
    '10UGF': '',
    '10UJA': 'Reactor pressure vessel and Reactor Cavity area',
    '10UJB': '',
    '10UJG': 'Program of SAW for the sliding gates of the transport portal (mechanical part)',
    '10UKA': '',
    '10UKC': 'Low temperature purification system of primary coolant area',
    '10UKD': 'Portable DG area',
    '10UKH': 'Program of SAW for grounding devices and lighting system',
    '10UKR': '',
    '10UKS': '',
    '10UMA': 'Individual test programs for ventilation system equipment of building 10UMA',
    '10UMX': 'Setup program for LS V ICS, automation equipment of the DM water plant in 10UMX building',
    '10UQR': '0.4 kV power transformers',
    '10UQX': 'Program of SAW for the grounding devices and lighting system',
    '10URS': 'Individual test programs for ventilation system equipment of building 10URS',
    '10URT': 'Program of SAW for the grounding devices and lighting system',
    '10URW': 'Program of SAW for non-essential loads cooling water system in 10URW building',
    '11-12UBN': '',
    '11-12UEJ': '',
    '11-12UJY': 'Program of SAW for the grounding devices, lightning protection and lighting system',
    '11-12UKZ': 'Program of SAW for grounding devices and lighting system',
    '11-12UPZ': 'Program of SAW for the automatic fire-fighting units of thinly sprayed water (SGK) in c...',
    '11-12URA': 'Program of SAW for the evaporating cooling water tower (11-12URA)',
    '11-12URE': 'Program of SAW for feed system of cooling water towers',
    '11-12URF': '',
    '11-12URR': '',
    '11-12URZ': '',
    '11-12USZ': 'Program of SAW for the grounding devices and lighting system',
    '11-14UBZ': 'Program of SAW for the automatic fire-fighting units of thinly sprayed water (SGK) in c...',
    '11-14URB': 'Program of SAW for distribution cabinets',
    '11-18UPZ': '',
    '11UBN': 'DG system of 11UBN area',
    '11UBP': '',
    '11UBZ': 'Program of SAW for the fire water pumping out system of premises 11-14UBZ',
    '11UEJ': 'Program of SAW for the diesel fuel storage and pumping systems (XJN10)',
    '11UJY': 'Program of SAW for the grounding devices, lightning protection and lighting system',
    '11UKZ': 'Program of SAW for grounding devices and lighting system',
    '11UPZ': 'Program of SAW for the automatic fire-fighting units of thinly sprayed water (SGK) in c...',
    '11URA': 'Setup program for the automation equipment of the evaporating cooling water tower (11-1...',
    '11URB': 'Program of SAW for electric motors of cooling tower fans',
    '11URE': 'Program of SAW for feed system of cooling water towers',
    '11URF': 'Individual test program for ventilation system equipment of building 11-12URF',
    '11URR': 'Program of SAW for the essential loads cooling water indoor drainage system (10PEB60)',
    '11URZ': 'Program of SAW for the automatic water fire-fighting system (SGC) in 11URZ tunnel',
    '11USZ': 'Program of SAW for the grounding devices and lighting system',
    '12UBN': 'DG system of 12UBN area',
    '12UBP': '',
    '12UEJ': 'Program of SAW for the diesel fuel storage and pumping systems (XJN20)',
    '12UKZ': 'Program of SAW for heating, ventilation and air conditioning system of cable tunnel of ...',
    '12URF': 'Program of SAW for the cooling water piping system (10PEB)',
    '12URG': '',
    '12URR': 'Program of SAW for the essential loads cooling water indoor drainage system (10PEB60)',
    '12URZ': 'Program of SAW for the automatic water fire-fighting system (SGC) in 12URZ tunnel',
    '13-14UPZ': 'Program of SAW for the automatic fire-fighting units of thinly sprayed water (SGK) in c...',
    '13-16UPZ': '',
    '13UBN': 'DG system of 13UBN area',
    '13UEJ': 'Program of SAW for the diesel fuel storage and pumping systems (XJN30)',
    '13UPZ': 'Program of SAW for the automatic fire-fighting units of thinly sprayed water (SGK) in c...',
    '13URR': 'Program of SAW for the essential loads cooling water indoor drainage system (10PEB60)',
    '14URR': 'Program of SAW for the essential loads cooling water indoor drainage system (10PEB60)',
    '15-16UBZ': '',
    '15-16UPZ': 'Program of SAW for the automatic fire-fighting units of thinly sprayed water (SGK) in c...',
    '15-16URZ': 'Program of SAW for grounding devices and lighting system',
    '15UPZ': 'Program of SAW for the automatic fire-fighting units of thinly sprayed water (SGK) in c...',
    '15URZ': 'Program of SAW for the ventilation systems of 15-16URZ building',
    '17-18UPZ': 'Program of SAW for grounding devices and lighting system',
    '17UPZ': 'SAW program for the system of automatic water fire-fighting plants SGC in cable tunnels...',
    '20UBA': '',
    '20UJA': '',
    '20UMA': '',}

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
