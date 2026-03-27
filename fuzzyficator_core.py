# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
#
# Original Fuzzyficator Copyright (c) [2024] [Roman Tenger]
# GUI extensions and motor-protection features by community contribution

"""
Fuzzyficator Core Engine
========================
Importable module that wraps the original Fuzzyficator G-code processing logic
and adds new features for motor protection, cooling control, and printer profiles.

This module can be used by:
  - The original CLI (Fuzzyficator.py) via backward-compatible interface
  - The GUI app (FuzzyficatorGUI.py)
  - Any other Python script that needs programmatic access
"""

import random
import math
import logging
import re
import os

# ---------------------------------------------------------------------------
# Slicer lookup tables (identical to original Fuzzyficator.py + Cura support)
# ---------------------------------------------------------------------------
LOOKUP_TABLES = {
    "prusaslicer": {
        "fuzzy_skin": "; fuzzy_skin =",
        "fuzzy_skin_values": ["external", "all"],
        "fuzzy_skin_point_dist": "; fuzzy_skin_point_dist =",
        "fuzzy_skin_thickness": "; fuzzy_skin_thickness =",
        "top_solid_infill": ";TYPE:Top solid infill",
        "type": ";TYPE:",
        "layer": ";LAYER_CHANGE",
        "bridge": ";TYPE:Bridge infill",
        "supportContact": "; support_material_contact_distance",
        "overhang": ";TYPE:Overhang perimeter",
    },
    "orcaslicer": {
        "fuzzy_skin": "; fuzzy_skin =",
        "fuzzy_skin_values": ["allwalls", "external", "all"],
        "fuzzy_skin_point_dist": "; fuzzy_skin_point_distance =",
        "fuzzy_skin_thickness": "; fuzzy_skin_thickness =",
        "top_solid_infill": ";TYPE:Top surface",
        "type": ";TYPE:",
        "layer": ";LAYER_CHANGE",
        "bridge": ";TYPE:Bridge",
        "supportContact": "; support_bottom_z_distance",
        "overhang": ";TYPE:Overhang wall",
    },
    "bambustudio": {
        "fuzzy_skin": "; fuzzy_skin =",
        "fuzzy_skin_values": ["allwalls", "external", "all"],
        "fuzzy_skin_point_dist": "; fuzzy_skin_point_dist =",
        "fuzzy_skin_thickness": "; fuzzy_skin_thickness =",
        "top_solid_infill": "; FEATURE: Top surface",
        "type": "; FEATURE:",
        "layer": "; CHANGE_LAYER",
        "bridge": "; FEATURE: Bridge",
        "supportContact": "; support_top_z_distance",
        "overhang": "; FEATURE: Overhang wall",
    },
    # Cura / CrealitySlicer (old) / UltiMaker Cura
    # Note: Cura uses ;TYPE:SKIN for both top and bottom surfaces (no distinction).
    # Bridge/overhang have no distinct TYPE in Cura, so we map them to unlikely
    # strings to effectively disable those features for Cura G-code.
    "cura": {
        "fuzzy_skin": "__CURA_NO_FUZZY_SKIN__",
        "fuzzy_skin_values": [],
        "fuzzy_skin_point_dist": "__CURA_NO_FUZZY_DIST__",
        "fuzzy_skin_thickness": "__CURA_NO_FUZZY_THICK__",
        "top_solid_infill": ";TYPE:SKIN",
        "type": ";TYPE:",
        "layer": ";LAYER:",
        "bridge": "__CURA_NO_BRIDGE__",
        "supportContact": "__CURA_NO_SUPPORT_CONTACT__",
        "overhang": "__CURA_NO_OVERHANG__",
    },
}

# ---------------------------------------------------------------------------
# Printer database — maps printer names to their motion type
# "bed_slinger" = bed moves in Y (i3-style) — heavy bed slings back and forth
# "corexy" = bed only moves in Z, toolhead moves XY — gentle Z on leadscrews
# "delta" = delta kinematics, stationary bed — treated as corexy for Z settings
# ---------------------------------------------------------------------------
PRINTER_DATABASE = {
    # --- Anet ---
    "Anet A6": "bed_slinger",
    "Anet A8": "bed_slinger",
    "Anet A8 Plus": "bed_slinger",
    "Anet E10": "bed_slinger",
    "Anet E12": "bed_slinger",
    "Anet E16": "bed_slinger",
    "Anet ET4": "bed_slinger",
    "Anet ET4 Pro": "bed_slinger",
    "Anet ET5": "bed_slinger",
    "Anet ET5 Pro": "bed_slinger",
    # --- AnkerMake ---
    "AnkerMake M5": "bed_slinger",
    "AnkerMake M5C": "bed_slinger",
    # --- Anycubic (i3-style) ---
    "Anycubic Chiron": "bed_slinger",
    "Anycubic i3 Mega": "bed_slinger",
    "Anycubic i3 Mega S": "bed_slinger",
    "Anycubic i3 Mega X": "bed_slinger",
    "Anycubic i3 Mega Zero": "bed_slinger",
    "Anycubic i3 Mega Zero 2.0": "bed_slinger",
    "Anycubic Kobra": "bed_slinger",
    "Anycubic Kobra Go": "bed_slinger",
    "Anycubic Kobra Max": "bed_slinger",
    "Anycubic Kobra Neo": "bed_slinger",
    "Anycubic Kobra Plus": "bed_slinger",
    "Anycubic Vyper": "bed_slinger",
    # --- Anycubic (CoreXY) ---
    "Anycubic Kobra 2": "corexy",
    "Anycubic Kobra 2 Max": "corexy",
    "Anycubic Kobra 2 Plus": "corexy",
    "Anycubic Kobra 2 Pro": "corexy",
    "Anycubic Kobra 3": "corexy",
    "Anycubic Kobra 3 Combo": "corexy",
    "Anycubic Kobra S1": "corexy",
    "Anycubic Kobra S1 Combo": "corexy",
    "Anycubic Kobra S1C": "corexy",
    "Anycubic Kobra S1 Max": "corexy",
    "Anycubic Kobra X": "corexy",
    # --- Artillery ---
    "Artillery Genius": "bed_slinger",
    "Artillery Genius Pro": "bed_slinger",
    "Artillery Hornet": "bed_slinger",
    "Artillery Sidewinder X1": "bed_slinger",
    "Artillery Sidewinder X2": "bed_slinger",
    "Artillery Sidewinder X3 Plus": "bed_slinger",
    "Artillery Sidewinder X3 Pro": "bed_slinger",
    # --- Bambu Lab ---
    "Bambu Lab A1": "bed_slinger",
    "Bambu Lab A1 Combo": "bed_slinger",
    "Bambu Lab A1 Mini": "bed_slinger",
    "Bambu Lab A1 Mini Combo": "bed_slinger",
    "Bambu Lab P1P": "corexy",
    "Bambu Lab P1S": "corexy",
    "Bambu Lab X1": "corexy",
    "Bambu Lab X1 Carbon": "corexy",
    "Bambu Lab X1 Carbon Combo": "corexy",
    "Bambu Lab X1E": "corexy",
    "Bambu Lab P1S Combo": "corexy",
    "Bambu Lab P2S": "corexy",
    "Bambu Lab H2S": "corexy",
    "Bambu Lab H2C": "corexy",
    "Bambu Lab H2D": "corexy",
    # --- BIQU ---
    "BIQU B1": "bed_slinger",
    "BIQU B1 SE Plus": "bed_slinger",
    "BIQU Hurakan": "bed_slinger",
    "BIQU BX Plus": "corexy",
    # --- BLV ---
    "BLV MGN Cube": "corexy",
    # --- Comgrow ---
    "Comgrow T300": "bed_slinger",
    "Comgrow T500": "bed_slinger",
    # --- Creality (bed slingers) ---
    "Creality CR-6 SE": "bed_slinger",
    "Creality CR-6 Max": "bed_slinger",
    "Creality CR-10": "bed_slinger",
    "Creality CR-10 Max": "bed_slinger",
    "Creality CR-10 Mini": "bed_slinger",
    "Creality CR-10 S4": "bed_slinger",
    "Creality CR-10 S5": "bed_slinger",
    "Creality CR-10 SE": "bed_slinger",
    "Creality CR-10 Smart": "bed_slinger",
    "Creality CR-10 Smart Pro": "bed_slinger",
    "Creality CR-10 V2": "bed_slinger",
    "Creality CR-10 V3": "bed_slinger",
    "Creality CR-10S": "bed_slinger",
    "Creality CR-10S Pro": "bed_slinger",
    "Creality CR-10S Pro V2": "bed_slinger",
    "Creality CR-20": "bed_slinger",
    "Creality CR-20 Pro": "bed_slinger",
    "Creality CR-30 (3DPrintMill)": "bed_slinger",
    "Creality CR-200B": "bed_slinger",
    "Creality Ender 2 Pro": "bed_slinger",
    "Creality Ender 3": "bed_slinger",
    "Creality Ender 3 Max": "bed_slinger",
    "Creality Ender 3 Max Neo": "bed_slinger",
    "Creality Ender 3 Neo": "bed_slinger",
    "Creality Ender 3 Pro": "bed_slinger",
    "Creality Ender 3 S1": "bed_slinger",
    "Creality Ender 3 S1 Plus": "bed_slinger",
    "Creality Ender 3 S1 Pro": "bed_slinger",
    "Creality Ender 3 V2": "bed_slinger",
    "Creality Ender 3 V2 Neo": "bed_slinger",
    "Creality Ender 3 V3": "bed_slinger",
    "Creality Ender 3 V3 KE": "bed_slinger",
    "Creality Ender 3 V3 Plus": "bed_slinger",
    "Creality Ender 3 V3 SE": "bed_slinger",
    "Creality Ender 5": "bed_slinger",
    "Creality Ender 5 Plus": "bed_slinger",
    "Creality Ender 5 Pro": "bed_slinger",
    "Creality Sermoon V1": "bed_slinger",
    "Creality Sermoon V1 Pro": "bed_slinger",
    # --- Creality (CoreXY) ---
    "Creality CR-M4": "corexy",
    "Creality Ender 5 S1": "corexy",
    "Creality Ender 6": "corexy",
    "Creality Ender 7": "corexy",
    "Creality K1": "corexy",
    "Creality K1 Max": "corexy",
    "Creality K1C": "corexy",
    "Creality K1 SE": "corexy",
    "Creality K2 Plus": "corexy",
    "Creality K2": "corexy",
    "Creality K2 Pro": "corexy",
    "Creality Hi": "corexy",
    "Creality Ender-3 V4": "bed_slinger",
    "Creality SPARKX i7": "corexy",
    "Creality Sermoon D1": "corexy",
    # --- Dremel --- (MOVED to UNSUPPORTED_PRINTERS — locked to Dremel DigiLab Slicer)
    # --- Elegoo (bed slingers) ---
    "Elegoo Neptune 1": "bed_slinger",
    "Elegoo Neptune 2": "bed_slinger",
    "Elegoo Neptune 2D": "bed_slinger",
    "Elegoo Neptune 2S": "bed_slinger",
    "Elegoo Neptune 3": "bed_slinger",
    "Elegoo Neptune 3 Max": "bed_slinger",
    "Elegoo Neptune 3 Plus": "bed_slinger",
    "Elegoo Neptune 3 Pro": "bed_slinger",
    "Elegoo Neptune X": "bed_slinger",
    # --- Elegoo (CoreXY) ---
    "Elegoo Neptune 4": "corexy",
    "Elegoo Neptune 4 Max": "corexy",
    "Elegoo Neptune 4 Plus": "corexy",
    "Elegoo Neptune 4 Pro": "corexy",
    "Elegoo Centauri Carbon": "corexy",
    "Elegoo Centauri Carbon 2": "corexy",
    "Elegoo OrangeStorm Giga": "corexy",
    # --- FlashForge (open models — Klipper-based, support OrcaSlicer) ---
    "FlashForge Adventurer 5M": "corexy",
    "FlashForge Adventurer 5M Pro": "corexy",
    "FlashForge Creator 5": "corexy",
    "FlashForge AD5X": "corexy",
    # (Locked FlashForge models moved to UNSUPPORTED_PRINTERS)
    # --- Flsun (Delta — treated as CoreXY for Z settings) ---
    "Flsun Q5": "delta",
    "Flsun QQ-S": "delta",
    "Flsun QQ-S Pro": "delta",
    "Flsun SR (Super Racer)": "delta",
    "Flsun V400": "delta",
    "Flsun T1": "delta",
    # --- Geeetech ---
    "Geeetech A10": "bed_slinger",
    "Geeetech A10M": "bed_slinger",
    "Geeetech A10T": "bed_slinger",
    "Geeetech A20": "bed_slinger",
    "Geeetech A20M": "bed_slinger",
    "Geeetech A20T": "bed_slinger",
    "Geeetech A30": "bed_slinger",
    "Geeetech Mizar": "bed_slinger",
    "Geeetech Mizar Pro": "bed_slinger",
    "Geeetech Mizar S": "bed_slinger",
    "Geeetech Thunder": "corexy",
    # --- Kingroon ---
    "Kingroon KP3": "bed_slinger",
    "Kingroon KP3S": "bed_slinger",
    "Kingroon KP3S Pro": "bed_slinger",
    "Kingroon KP3S Pro V2": "bed_slinger",
    "Kingroon KP5L": "bed_slinger",
    "Kingroon KLP1": "corexy",
    # --- Kywoo ---
    "Kywoo Tycoon": "bed_slinger",
    "Kywoo Tycoon Max": "bed_slinger",
    "Kywoo Tycoon Slim": "bed_slinger",
    # --- Longer ---
    "Longer LK4": "bed_slinger",
    "Longer LK4 Pro": "bed_slinger",
    "Longer LK5": "bed_slinger",
    "Longer LK5 Pro": "bed_slinger",
    "Longer Cube 2": "bed_slinger",
    # --- Lotmaxx ---
    "Lotmaxx SC-10 Shark": "bed_slinger",
    "Lotmaxx SC-10 Shark V2": "bed_slinger",
    "Lotmaxx SC-10 Shark V3": "bed_slinger",
    # --- LulzBot ---
    "LulzBot Mini 2": "bed_slinger",
    "LulzBot Mini 3": "bed_slinger",
    "LulzBot TAZ 6": "bed_slinger",
    "LulzBot TAZ Pro": "bed_slinger",
    "LulzBot TAZ Pro XT": "bed_slinger",
    "LulzBot TAZ Workhorse": "bed_slinger",
    "LulzBot TAZ SideKick 289": "bed_slinger",
    "LulzBot TAZ SideKick 747": "bed_slinger",
    # --- MakerBot --- (MOVED to UNSUPPORTED_PRINTERS — locked to MakerBot Print/CloudPrint)
    # --- Mingda ---
    "Mingda D2": "bed_slinger",
    "Mingda D3 Pro": "bed_slinger",
    "Mingda Magician Max": "bed_slinger",
    "Mingda Magician Pro": "bed_slinger",
    "Mingda Magician X": "bed_slinger",
    "Mingda Magician X2": "bed_slinger",
    # --- Monoprice ---
    "Monoprice Maker Select Plus": "bed_slinger",
    "Monoprice Maker Select V2": "bed_slinger",
    "Monoprice Select Mini V2": "bed_slinger",
    # (Monoprice Voxel moved to UNSUPPORTED — FlashForge Adventurer 3 rebrand, locked to FlashPrint)
    # --- Peopoly ---
    "Peopoly Magneto X": "corexy",
    # --- Prusa ---
    "Prusa MK3": "bed_slinger",
    "Prusa MK3S": "bed_slinger",
    "Prusa MK3S+": "bed_slinger",
    "Prusa MK4": "bed_slinger",
    "Prusa MK4S": "bed_slinger",
    "Prusa Mini": "bed_slinger",
    "Prusa Mini+": "bed_slinger",
    "Prusa Core One": "corexy",
    "Prusa Core One L": "corexy",
    "Prusa XL": "corexy",
    # --- QIDI ---
    "QIDI i-Fast": "corexy",
    "QIDI i-Mates": "corexy",
    "QIDI Q1 Pro": "corexy",
    "QIDI Tech X-CF Pro": "corexy",
    "QIDI Tech X-Max": "corexy",
    "QIDI Tech X-Max 3": "corexy",
    "QIDI Tech X-Plus": "corexy",
    "QIDI Tech X-Plus 3": "corexy",
    "QIDI Tech X-Smart 3": "corexy",
    "QIDI X-Smart": "corexy",
    "QIDI Plus 4": "corexy",
    "QIDI Max 4": "corexy",
    # --- Raise3D ---
    "Raise3D E2": "corexy",
    "Raise3D E2CF": "corexy",
    "Raise3D Pro2": "corexy",
    "Raise3D Pro2 Plus": "corexy",
    "Raise3D Pro3": "corexy",
    "Raise3D Pro3 Plus": "corexy",
    "Raise3D Pro3 HS": "corexy",
    # --- RatRig ---
    "RatRig V-Core 3": "corexy",
    "RatRig V-Core 3.1": "corexy",
    "RatRig V-Core 4": "corexy",
    "RatRig V-Minion": "corexy",
    # --- Sindoh --- (MOVED to UNSUPPORTED_PRINTERS — locked to 3DWOX slicer)
    # --- Snapmaker ---
    "Snapmaker Original": "bed_slinger",
    "Snapmaker 2.0 A150": "bed_slinger",
    "Snapmaker 2.0 A250": "bed_slinger",
    "Snapmaker 2.0 A350": "bed_slinger",
    "Snapmaker Artisan": "bed_slinger",
    "Snapmaker J1": "bed_slinger",
    "Snapmaker J1S": "corexy",
    "Snapmaker U1": "corexy",
    # --- Sovol ---
    "Sovol SV01": "bed_slinger",
    "Sovol SV01 Pro": "bed_slinger",
    "Sovol SV02": "bed_slinger",
    "Sovol SV03": "bed_slinger",
    "Sovol SV04": "bed_slinger",
    "Sovol SV05": "bed_slinger",
    "Sovol SV06": "bed_slinger",
    "Sovol SV06 Plus": "bed_slinger",
    "Sovol SV07": "corexy",
    "Sovol SV07 Plus": "corexy",
    "Sovol SV08": "corexy",
    "Sovol SV08 Max": "corexy",
    "Sovol Zero": "corexy",
    # --- Tenlog ---
    "Tenlog TL-D3 Pro": "bed_slinger",
    "Tenlog TL-D3 V2": "bed_slinger",
    "Tenlog TL-D5": "bed_slinger",
    # --- Tronxy (bed slingers) ---
    "Tronxy XY-2": "bed_slinger",
    "Tronxy XY-2 Pro": "bed_slinger",
    "Tronxy XY-3": "bed_slinger",
    "Tronxy XY-3 Pro": "bed_slinger",
    "Tronxy XY-3 SE": "bed_slinger",
    # --- Tronxy (CoreXY) ---
    "Tronxy X5SA": "corexy",
    "Tronxy X5SA Pro": "corexy",
    "Tronxy X5SA-400": "corexy",
    "Tronxy X5SA-500": "corexy",
    "Tronxy Veho 600": "corexy",
    "Tronxy Veho 800": "corexy",
    # --- Two Trees ---
    "Two Trees Bluer": "bed_slinger",
    "Two Trees Bluer Plus": "bed_slinger",
    "Two Trees Sapphire Plus": "corexy",
    "Two Trees Sapphire Pro": "corexy",
    "Two Trees SP-5 V3": "corexy",
    # --- UltiMaker ---
    "UltiMaker 2+ Connect": "corexy",
    "UltiMaker S3": "corexy",
    "UltiMaker S5": "corexy",
    "UltiMaker S7": "corexy",
    "UltiMaker Method": "corexy",
    "UltiMaker Method X": "corexy",
    "UltiMaker Method XL": "corexy",
    "UltiMaker Factor 4": "corexy",
    # --- Voron ---
    "Voron 0 (V0)": "corexy",
    "Voron 0.1": "corexy",
    "Voron 0.2": "corexy",
    "Voron 2.4": "corexy",
    "Voron 2.4 R2": "corexy",
    "Voron Trident": "corexy",
    "Voron Switchwire": "bed_slinger",
    # --- Voxelab ---
    "Voxelab Aquila": "bed_slinger",
    "Voxelab Aquila C2": "bed_slinger",
    "Voxelab Aquila D1": "bed_slinger",
    "Voxelab Aquila Pro": "bed_slinger",
    "Voxelab Aquila S2": "bed_slinger",
    "Voxelab Aquila X2": "bed_slinger",
    # --- Wanhao ---
    "Wanhao Duplicator 6": "bed_slinger",
    "Wanhao Duplicator 9": "bed_slinger",
    "Wanhao Duplicator i3 Plus": "bed_slinger",
    "Wanhao Duplicator i3 Plus Mark 2": "bed_slinger",
    # --- AtomForm ---
    "AtomForm Palette 300": "corexy",
}

# ---------------------------------------------------------------------------
# Unsupported printers — locked to proprietary slicers that Fuzzyficator
# cannot process. Shown separately in the GUI so users know why.
# Format: "Printer Name": {"type": motion_type, "reason": why unsupported}
# ---------------------------------------------------------------------------
UNSUPPORTED_PRINTERS = {
    # --- Dremel (locked to Dremel DigiLab Slicer, .g3drem format) ---
    "Dremel DigiLab 3D20": {"type": "bed_slinger", "reason": "Locked to Dremel DigiLab Slicer (.g3drem format)"},
    "Dremel DigiLab 3D40": {"type": "bed_slinger", "reason": "Locked to Dremel DigiLab Slicer (.g3drem format)"},
    "Dremel DigiLab 3D45": {"type": "bed_slinger", "reason": "Locked to Dremel DigiLab Slicer (.g3drem format)"},
    # --- FlashForge (locked to FlashPrint, proprietary .gx format) ---
    "FlashForge Adventurer 3": {"type": "corexy", "reason": "Locked to FlashPrint (.gx format)"},
    "FlashForge Adventurer 3 Lite": {"type": "corexy", "reason": "Locked to FlashPrint (.gx format)"},
    "FlashForge Adventurer 4": {"type": "corexy", "reason": "Locked to FlashPrint (.gx format)"},
    "FlashForge Creator 3": {"type": "corexy", "reason": "Locked to FlashPrint (.gx format)"},
    "FlashForge Creator 3 Pro": {"type": "corexy", "reason": "Locked to FlashPrint (.gx format)"},
    "FlashForge Creator 4": {"type": "corexy", "reason": "Locked to FlashPrint (.gx format)"},
    "FlashForge Guider 2": {"type": "corexy", "reason": "Locked to FlashPrint (.gx format)"},
    "FlashForge Guider 2S": {"type": "corexy", "reason": "Locked to FlashPrint (.gx format)"},
    "FlashForge Guider 3": {"type": "corexy", "reason": "Locked to FlashPrint (.gx format)"},
    "FlashForge Guider 3 Plus": {"type": "corexy", "reason": "Locked to FlashPrint (.gx format)"},
    # --- MakerBot (locked to MakerBot Print / CloudPrint, .makerbot format) ---
    "MakerBot Method": {"type": "corexy", "reason": "Locked to MakerBot CloudPrint (.makerbot format)"},
    "MakerBot Method X": {"type": "corexy", "reason": "Locked to MakerBot CloudPrint (.makerbot format)"},
    "MakerBot Method XL": {"type": "corexy", "reason": "Locked to MakerBot CloudPrint (.makerbot format)"},
    "MakerBot Replicator+": {"type": "bed_slinger", "reason": "Locked to MakerBot Print (.makerbot format)"},
    "MakerBot Replicator Mini+": {"type": "bed_slinger", "reason": "Locked to MakerBot Print (.makerbot format)"},
    # --- Monoprice (FlashForge rebrands) ---
    "Monoprice Voxel": {"type": "corexy", "reason": "FlashForge Adventurer 3 rebrand — locked to FlashPrint"},
    # --- Sindoh (locked to 3DWOX slicer, proprietary format) ---
    "Sindoh 3DWOX 1": {"type": "bed_slinger", "reason": "Locked to Sindoh 3DWOX slicer (proprietary format)"},
    "Sindoh 3DWOX 2X": {"type": "bed_slinger", "reason": "Locked to Sindoh 3DWOX slicer (proprietary format)"},
    # --- XYZprinting (locked to XYZware, NFC filament cartridges) ---
    "XYZprinting da Vinci 1.0": {"type": "bed_slinger", "reason": "Locked to XYZware slicer (proprietary format, NFC cartridges)"},
    "XYZprinting da Vinci 1.0 Pro": {"type": "bed_slinger", "reason": "Locked to XYZware slicer (proprietary format)"},
    "XYZprinting da Vinci Mini": {"type": "bed_slinger", "reason": "Locked to XYZware slicer (proprietary format, NFC cartridges)"},
    "XYZprinting da Vinci Mini w+": {"type": "bed_slinger", "reason": "Locked to XYZware slicer (proprietary format, NFC cartridges)"},
    "XYZprinting da Vinci Jr. 1.0": {"type": "bed_slinger", "reason": "Locked to XYZware slicer (proprietary format, NFC cartridges)"},
}


def get_profile_for_printer(printer_name):
    """Look up which profile category a printer belongs to.
    Returns 'bed_slinger' or 'corexy'. Delta printers return 'corexy'."""
    motion = PRINTER_DATABASE.get(printer_name, None)
    if motion in ("corexy", "delta"):
        return "corexy"
    return "bed_slinger"


# ---------------------------------------------------------------------------
# Built-in printer profiles
# ---------------------------------------------------------------------------
PRINTER_PROFILES = {
    "bed_slinger_conservative": {
        "label": "Bed Slinger - Conservative",
        "description": "Safe settings for i3-style printers where the bed moves in Y. "
                       "The heavy bed slinging back and forth means Z hops need to be "
                       "gentle to avoid vibration and missed steps.",
        "z_max_feedrate": 5.0,
        "z_acceleration": 100.0,
        "z_jerk": 0.4,
        "fan_speed_percent": None,
        "fuzzy_speed": 600.0,
        "resolution": 0.3,
        "z_min": 0.0,
        "z_max": 0.3,
    },
    "bed_slinger_balanced": {
        "label": "Bed Slinger - Balanced",
        "description": "Moderate settings for bed slingers. Good balance between "
                       "texture quality and speed. Use after Conservative works for you.",
        "z_max_feedrate": 8.0,
        "z_acceleration": 200.0,
        "z_jerk": 0.6,
        "fan_speed_percent": None,
        "fuzzy_speed": 900.0,
        "resolution": 0.3,
        "z_min": 0.0,
        "z_max": 0.3,
    },
    "corexy_balanced": {
        "label": "CoreXY / Fixed Bed - Balanced",
        "description": "For CoreXY and enclosed printers where the bed only moves in Z "
                       "on leadscrews (gentle, gravity-assisted). The lightweight toolhead "
                       "does all the fast XY movement, so Z can be faster.",
        "z_max_feedrate": 12.0,
        "z_acceleration": 400.0,
        "z_jerk": 1.0,
        "fan_speed_percent": None,
        "fuzzy_speed": 1200.0,
        "resolution": 0.3,
        "z_min": 0.0,
        "z_max": 0.3,
    },
    "corexy_aggressive": {
        "label": "CoreXY / Fixed Bed - Aggressive",
        "description": "Faster settings for rigid CoreXY frames. More pronounced texture "
                       "at the cost of more vibration and noise. For experienced users.",
        "z_max_feedrate": 20.0,
        "z_acceleration": 800.0,
        "z_jerk": 2.0,
        "fan_speed_percent": None,
        "fuzzy_speed": 1800.0,
        "resolution": 0.2,
        "z_min": 0.0,
        "z_max": 0.5,
    },
    "custom": {
        "label": "Custom",
        "description": "Set all values manually. No values will be changed when you select this.",
        "z_max_feedrate": None,
        "z_acceleration": None,
        "z_jerk": None,
        "fan_speed_percent": None,
        "fuzzy_speed": None,
        "resolution": 0.3,
        "z_min": 0.0,
        "z_max": 0.3,
    },
}


# ---------------------------------------------------------------------------
# Configuration dataclass (replaces argparse-dependent FuzzySkinConfig)
# ---------------------------------------------------------------------------
class FuzzyConfig:
    """All settings for a Fuzzyficator run, buildable from GUI or CLI."""

    def __init__(
        self,
        input_file="",
        resolution=0.3,
        z_min=0.0,
        z_max=0.3,
        connect_walls=True,
        fuzzy_speed=None,
        run=1,
        compensate_extrusion=1,
        lower_surface=True,
        top_surface=True,
        bridge_compensation_multiplier=3.0,
        min_support_distance=0.1,
        # --- New motor-protection settings ---
        z_max_feedrate=None,       # mm/s  - M203 Z
        z_acceleration=None,       # mm/s^2 - M201 Z
        z_jerk=None,               # mm/s  - M205 Z
        # --- New cooling settings ---
        fan_speed_percent=None,    # 0-100  - M106 S(0-255)
    ):
        self.input_file = input_file
        self.resolution = resolution
        self.z_min = z_min
        self.z_max = z_max
        self.connect_walls = connect_walls
        self.fuzzy_speed = fuzzy_speed
        self.run = run
        self.compensate_extrusion = compensate_extrusion
        self.lower_surface = lower_surface
        self.top_surface = top_surface
        self.bridge_compensation_multiplier = bridge_compensation_multiplier
        self.min_support_distance = min_support_distance
        self.support_contact_dist = None

        # Motor protection
        self.z_max_feedrate = z_max_feedrate
        self.z_acceleration = z_acceleration
        self.z_jerk = z_jerk

        # Cooling
        self.fan_speed_percent = fan_speed_percent

    def apply_gcode_settings(self, fuzzy_enabled, point_dist, thickness, support_contact_dist):
        """Apply settings read from G-code comments (slicer defaults)."""
        if self.resolution is None and point_dist is not None:
            self.resolution = point_dist
        if self.z_max is None and thickness is not None:
            self.z_max = thickness
        if self.run is None:
            self.run = 1 if fuzzy_enabled else 0
        if support_contact_dist is not None:
            self.support_contact_dist = support_contact_dist

    def to_dict(self):
        """Serialize to dict for preset saving."""
        return {
            "resolution": self.resolution,
            "z_min": self.z_min,
            "z_max": self.z_max,
            "connect_walls": self.connect_walls,
            "fuzzy_speed": self.fuzzy_speed,
            "compensate_extrusion": self.compensate_extrusion,
            "lower_surface": self.lower_surface,
            "top_surface": self.top_surface,
            "bridge_compensation_multiplier": self.bridge_compensation_multiplier,
            "min_support_distance": self.min_support_distance,
            "z_max_feedrate": self.z_max_feedrate,
            "z_acceleration": self.z_acceleration,
            "z_jerk": self.z_jerk,
            "fan_speed_percent": self.fan_speed_percent,
        }

    @classmethod
    def from_dict(cls, d, input_file=""):
        """Deserialize from dict (preset loading)."""
        return cls(input_file=input_file, **d)


# ---------------------------------------------------------------------------
# G-code Processor (extended from original with motor/cooling injection)
# ---------------------------------------------------------------------------
class GCodeProcessor:
    def __init__(self, config: FuzzyConfig, progress_callback=None):
        self.config = config
        self.lookup = None
        self.current_layer_height = 0.0
        self.previous_point = None
        self.in_top_solid_infill = False
        self.in_bridge = False
        self.current_speed = None
        self.has_overhang_in_layer = False
        self.current_layer = None
        self.progress_callback = progress_callback  # GUI progress updates

        # Track original machine state so we can restore after fuzzy sections
        self._original_z_feedrate = None
        self._original_z_accel = None
        self._original_z_jerk = None
        self._original_fan_speed = None
        self._in_fuzzy_section = False

    # -- Distance calculation --------------------------------------------------

    @staticmethod
    def calculate_distance(point1, point2):
        return math.sqrt(
            (point2[0] - point1[0]) ** 2 +
            (point2[1] - point1[1]) ** 2 +
            (point2[2] - point1[2]) ** 2
        )

    # -- Interpolation (core fuzzy logic, same as original) --------------------

    def interpolate_with_constant_resolution(self, start_point, end_point, segment_length, total_extrusion):
        distance = self.calculate_distance(start_point, end_point)
        if distance == 0:
            return []

        num_segments = max(1, int(distance / segment_length))
        points = []
        extrusion_per_segment = total_extrusion / num_segments

        for i in range(num_segments + 1):
            t = i / num_segments
            x_new = start_point[0] + (end_point[0] - start_point[0]) * t
            y_new = start_point[1] + (end_point[1] - start_point[1]) * t
            z_new = start_point[2] + (end_point[2] - start_point[2]) * t

            if self.in_bridge:
                bridge_z_min = self.config.z_min - self.config.z_max
                bridge_z_max = (self.config.support_contact_dist or 0.2) - self.config.min_support_distance
                z_displacement = (0 if (i == 0 or i == num_segments) and self.config.connect_walls
                                  else -random.uniform(bridge_z_min, bridge_z_max))
                z_new = z_new + z_displacement
            else:
                z_displacement = (0 if (i == 0 or i == num_segments) and self.config.connect_walls
                                  else random.uniform(self.config.z_min, self.config.z_max))
                z_new = z_new + z_displacement

            if not self.in_bridge:
                z_new = max(self.current_layer_height, z_new)

            seg_distance = math.sqrt(segment_length ** 2 + z_displacement ** 2)
            compensation_factor = seg_distance / segment_length if segment_length != 0 else 1
            if self.in_bridge:
                compensation_factor = compensation_factor ** self.config.bridge_compensation_multiplier
            compensated_extrusion = (extrusion_per_segment * compensation_factor
                                     if self.config.compensate_extrusion else extrusion_per_segment)

            points.append((x_new, y_new, z_new, compensated_extrusion))

        return points

    # -- Slicer detection ------------------------------------------------------

    def detect_slicer(self, gcode_lines):
        # Check first 50 lines for slicer identification comments
        for line in gcode_lines[:50]:
            if 'PrusaSlicer' in line:
                return 'prusaslicer'
            elif 'OrcaSlicer' in line:
                return 'orcaslicer'
            elif 'BambuStudio' in line:
                return 'bambustudio'
            # Creality Print 5+ is an OrcaSlicer fork — uses same G-code format
            elif 'CrealityPrint' in line or 'Creality Print' in line:
                return 'orcaslicer'
            # Flash Studio / Orca-FlashForge is an OrcaSlicer fork
            elif 'FlashSlicer' in line or 'Orca-FlashForge' in line or 'Flash Studio' in line:
                return 'orcaslicer'
        # Check for Cura-style G-code (;LAYER:0 pattern, generated_by Cura)
        for line in gcode_lines[:50]:
            if 'Cura_SteamEngine' in line or 'Cura' in line and 'Generated' in line:
                return 'cura'
            # Old CrealitySlicer is a Cura fork
            elif 'CrealitySlicer' in line:
                return 'cura'
        # Last resort: detect by G-code comment style
        for line in gcode_lines[:200]:
            if line.startswith(';LAYER:'):
                return 'cura'
            elif line.startswith(';LAYER_CHANGE'):
                return 'prusaslicer'
            elif line.startswith('; CHANGE_LAYER'):
                return 'bambustudio'
        return None

    def detect_gcode_flavor(self, gcode_lines):
        for line in gcode_lines:
            if line.startswith('; gcode_flavor ='):
                return line.split('=')[-1].strip()
        return None

    # -- Read slicer settings from G-code comments -----------------------------

    def process_fuzzy_skin_settings(self, gcode_lines):
        fuzzy_skin_enabled = False
        fuzzy_skin_point_dist = None
        fuzzy_skin_thickness = None
        support_contact_dist = None

        for line in reversed(gcode_lines):
            if line.startswith(self.lookup["fuzzy_skin"]):
                fuzzy_skin_value = line.split('=')[-1].strip().lower()
                if fuzzy_skin_value in self.lookup["fuzzy_skin_values"]:
                    fuzzy_skin_enabled = True
                break

        if fuzzy_skin_enabled:
            for line in reversed(gcode_lines):
                if line.startswith(self.lookup["fuzzy_skin_point_dist"]):
                    try:
                        fuzzy_skin_point_dist = float(line.split('=')[-1].strip())
                    except ValueError:
                        pass
                elif line.startswith(self.lookup["fuzzy_skin_thickness"]):
                    try:
                        fuzzy_skin_thickness = float(line.split('=')[-1].strip())
                    except ValueError:
                        pass
                if fuzzy_skin_point_dist is not None and fuzzy_skin_thickness is not None:
                    break

        for line in reversed(gcode_lines):
            if line.startswith(self.lookup["supportContact"]):
                try:
                    support_contact_dist = float(line.split('=')[-1].strip())
                except ValueError:
                    pass
                break

        return fuzzy_skin_enabled, fuzzy_skin_point_dist, fuzzy_skin_thickness, support_contact_dist

    # -- Motor protection G-code injection -------------------------------------

    def _build_enter_fuzzy_gcode(self):
        """G-code commands to inject BEFORE a fuzzy section starts."""
        lines = []
        lines.append("; >>> Fuzzyficator: entering fuzzy section (motor protection ON)\n")

        if self.config.z_max_feedrate is not None:
            lines.append(f"M203 Z{self.config.z_max_feedrate:.1f} ; limit Z feedrate (mm/s)\n")

        if self.config.z_acceleration is not None:
            lines.append(f"M201 Z{self.config.z_acceleration:.0f} ; limit Z acceleration (mm/s^2)\n")

        if self.config.z_jerk is not None:
            lines.append(f"M205 Z{self.config.z_jerk:.2f} ; limit Z jerk (mm/s)\n")

        if self.config.fan_speed_percent is not None:
            s_value = int(self.config.fan_speed_percent * 255 / 100)
            lines.append(f"M106 S{s_value} ; fuzzy section fan speed ({self.config.fan_speed_percent}%)\n")

        return lines

    def _build_exit_fuzzy_gcode(self):
        """G-code commands to inject AFTER a fuzzy section ends."""
        lines = []

        # Restore defaults by sending high/normal values
        # Bambu P1S defaults: Z feedrate ~12mm/s, Z accel ~500, Z jerk ~0.4
        if self.config.z_max_feedrate is not None:
            lines.append("M203 Z12.0 ; restore Z feedrate\n")

        if self.config.z_acceleration is not None:
            lines.append("M201 Z500 ; restore Z acceleration\n")

        if self.config.z_jerk is not None:
            lines.append("M205 Z0.40 ; restore Z jerk\n")

        if self.config.fan_speed_percent is not None:
            lines.append("; fan speed will be restored by slicer's next M106 command\n")

        lines.append("; <<< Fuzzyficator: exiting fuzzy section (motor protection OFF)\n")
        return lines

    # -- Movement parsing ------------------------------------------------------

    def process_movement_line(self, line):
        coordinates = {param[0]: float(param[1:]) for param in line.split() if param[0] in 'XYZE'}

        current_point = (
            coordinates.get('X', self.previous_point[0] if self.previous_point else 0),
            coordinates.get('Y', self.previous_point[1] if self.previous_point else 0),
            coordinates.get('Z', coordinates.get('Z', self.current_layer_height))
        )

        return current_point, coordinates.get('E', 0.0)

    # -- Main processing entry point -------------------------------------------

    def process_file(self, keep_original=False, dry_run=False):
        """Process a G-code file.

        Args:
            keep_original: If True, write output to a new file with '_Fuzzyficator'
                          appended to the name, leaving the original untouched.
            dry_run: If True, analyze the file and return stats without modifying anything.

        Returns (success: bool, message: str, output_path: str or None).
        """
        if not self.config.input_file or not os.path.isfile(self.config.input_file):
            return False, f"File not found: {self.config.input_file}", None

        # Check for binary G-code (some slicers export binary .gcode)
        try:
            with open(self.config.input_file, "r", encoding="utf-8") as f:
                gcode_lines = f.readlines()
        except UnicodeDecodeError:
            return False, ("This file appears to be binary G-code, not text.\n\n"
                           "In your slicer, disable binary G-code export:\n"
                           "  PrusaSlicer/OrcaSlicer: Printer Settings > General > "
                           "Supports binary G-code → Off\n"
                           "  Bambu Studio: Already exports text G-code by default.\n\n"
                           "Re-export the file and try again."), None

        # Check for absolute extrusion mode
        for line in gcode_lines:
            if line.strip().startswith('M82'):
                return False, ("Absolute extrusion mode (M82) detected. "
                               "This script only works with relative extrusion mode (M83)."), None

        slicer = self.detect_slicer(gcode_lines)
        gcode_flavor = self.detect_gcode_flavor(gcode_lines)

        if slicer and slicer.lower() in LOOKUP_TABLES:
            self.lookup = LOOKUP_TABLES[slicer.lower()]
            if slicer == 'orcaslicer' and gcode_flavor == 'marlin':
                self.lookup = LOOKUP_TABLES['bambustudio']
        else:
            self.lookup = LOOKUP_TABLES["prusaslicer"]

        fuzzy_enabled, point_dist, thickness, support_contact_dist = self.process_fuzzy_skin_settings(gcode_lines)
        self.config.apply_gcode_settings(fuzzy_enabled, point_dist, thickness, support_contact_dist)

        if not self.config.run:
            return False, "Fuzzy skin not enabled in slicer and -run not set. No processing needed.", None

        # --- Dry run mode: analyze without modifying ---
        if dry_run:
            return self._dry_run_analysis(gcode_lines, slicer)

        total_lines = len(gcode_lines)
        new_gcode = []
        for i, line in enumerate(gcode_lines):
            processed = self.process_line(line)
            new_gcode.extend(processed)
            if self.progress_callback and i % 5000 == 0:
                self.progress_callback(i / total_lines)

        # Determine output path
        if keep_original:
            base, ext = os.path.splitext(self.config.input_file)
            output_path = f"{base}_Fuzzyficator{ext}"
        else:
            output_path = self.config.input_file

        with open(output_path, "w", encoding="utf-8") as out:
            out.writelines(new_gcode)

        if self.progress_callback:
            self.progress_callback(1.0)

        detected = slicer or "unknown"
        return True, f"Done! Slicer detected: {detected}. Processed {total_lines} lines.", output_path

    def _dry_run_analysis(self, gcode_lines, slicer):
        """Analyze G-code without modifying it. Returns stats and warnings."""
        total_lines = len(gcode_lines)
        layer_count = 0
        fuzzy_layers = set()
        current_layer = 0
        in_fuzzy_section = False
        fuzzy_move_count = 0
        top_surface_sections = 0
        bridge_sections = 0
        overhang_sections = 0
        warnings = []

        for i, line in enumerate(gcode_lines):
            stripped = line.strip()
            if stripped.startswith(self.lookup["layer"]):
                current_layer = layer_count
                layer_count += 1
            elif stripped.startswith(self.lookup["top_solid_infill"]) and self.config.top_surface:
                if not in_fuzzy_section:
                    top_surface_sections += 1
                in_fuzzy_section = True
                fuzzy_layers.add(current_layer)
            elif stripped.startswith(self.lookup.get("bridge", "")) and self.config.lower_surface:
                if not in_fuzzy_section:
                    bridge_sections += 1
                in_fuzzy_section = True
                fuzzy_layers.add(current_layer)
            elif stripped.startswith(self.lookup.get("overhang", "")) and self.config.lower_surface:
                if not in_fuzzy_section:
                    overhang_sections += 1
                in_fuzzy_section = True
                fuzzy_layers.add(current_layer)
            elif stripped.startswith(self.lookup["type"]) or stripped.startswith(self.lookup.get("type", ";TYPE:")):
                in_fuzzy_section = False
            elif in_fuzzy_section and (stripped.startswith("G1 ") or stripped.startswith("G0 ")):
                if "E" in stripped:
                    fuzzy_move_count += 1

            if self.progress_callback and i % 5000 == 0:
                self.progress_callback(i / total_lines)

        # Check for potential issues
        if fuzzy_move_count == 0:
            warnings.append("No fuzzy moves detected — the file may not have top surfaces or overhangs matching the settings.")

        # Estimate extra time: each fuzzy move adds ~0.1-0.5mm of Z travel
        avg_z_hop = (abs(self.config.z_min) + abs(self.config.z_max)) / 2
        extra_z_mm = fuzzy_move_count * avg_z_hop * 2  # up and down
        z_feedrate = self.config.z_max_feedrate if self.config.z_max_feedrate else 12.0
        extra_time_sec = extra_z_mm / z_feedrate
        extra_time_min = extra_time_sec / 60.0

        if self.progress_callback:
            self.progress_callback(1.0)

        detected = slicer or "unknown"
        report_lines = [
            f"Dry Run Analysis",
            f"{'=' * 40}",
            f"Slicer detected: {detected}",
            f"Total lines: {total_lines:,}",
            f"Total layers: {layer_count}",
            f"",
            f"Fuzzy Processing Preview",
            f"{'-' * 40}",
            f"Layers with fuzzy sections: {len(fuzzy_layers)} of {layer_count}",
            f"Top surface sections: {top_surface_sections}",
            f"Bridge sections: {bridge_sections}",
            f"Overhang sections: {overhang_sections}",
            f"Estimated fuzzy moves: {fuzzy_move_count:,}",
            f"",
            f"Time Estimate",
            f"{'-' * 40}",
            f"Extra Z travel: ~{extra_z_mm:.1f}mm",
            f"Estimated added time: ~{extra_time_min:.1f} min",
            f"  (at Z feedrate {z_feedrate} mm/s)",
        ]

        if self.config.z_max_feedrate:
            report_lines.append(f"\nMotor Protection: ON")
            report_lines.append(f"  Z max feedrate: {self.config.z_max_feedrate} mm/s")
            if self.config.z_acceleration:
                report_lines.append(f"  Z acceleration: {self.config.z_acceleration} mm/s²")
            if self.config.z_jerk:
                report_lines.append(f"  Z jerk: {self.config.z_jerk} mm/s")
        else:
            report_lines.append(f"\nMotor Protection: OFF")

        if self.config.fan_speed_percent is not None:
            report_lines.append(f"Fan override: {self.config.fan_speed_percent}%")

        if warnings:
            report_lines.append(f"\nWarnings")
            report_lines.append(f"{'-' * 40}")
            for w in warnings:
                report_lines.append(f"  ! {w}")

        report_lines.append(f"\nNo files were modified.")

        report = "\n".join(report_lines)
        return True, report, None

    # -- Line-by-line processing -----------------------------------------------

    def process_line(self, line):
        if line.startswith(self.lookup["layer"]):
            self.current_layer = line
            self.has_overhang_in_layer = False
            return [line]
        elif line.startswith(self.lookup["overhang"]):
            self.has_overhang_in_layer = True
            return [line]
        elif line.startswith(self.lookup["bridge"]) and self.config.lower_surface and self.has_overhang_in_layer:
            return self.handle_bridge_infill(line)
        elif line.startswith(self.lookup["top_solid_infill"]) and self.config.top_surface:
            return self.handle_top_solid_infill(line)
        elif line.startswith(self.lookup["type"]):
            return self.handle_type_change(line)
        elif 'G1' in line and 'Z' in line and 'X' not in line and 'Y' not in line:
            return self.handle_z_movement(line)
        elif (self.in_top_solid_infill or (self.in_bridge and self.config.lower_surface)) and line.startswith('G1'):
            return self.handle_movement_in_infill(line)
        return [line]

    def handle_top_solid_infill(self, line):
        self.in_top_solid_infill = True
        self._in_fuzzy_section = True
        self.previous_point = None
        result = [line]
        # Inject motor protection commands
        result.extend(self._build_enter_fuzzy_gcode())
        if self.config.fuzzy_speed is not None:
            current_speed_match = re.search(r'F([-+]?[0-9]*\.?[0-9]+)', line)
            if current_speed_match:
                self.current_speed = float(current_speed_match.group(1))
            result.append(f'G1 F{self.config.fuzzy_speed}\n')
        return result

    def handle_bridge_infill(self, line):
        self.in_bridge = True
        self._in_fuzzy_section = True
        self.previous_point = None
        result = [line]
        # Inject motor protection commands
        result.extend(self._build_enter_fuzzy_gcode())
        if self.config.fuzzy_speed is not None:
            current_speed_match = re.search(r'F([-+]?[0-9]*\.?[0-9]+)', line)
            if current_speed_match:
                self.current_speed = float(current_speed_match.group(1))
            result.append(f'G1 F{self.config.fuzzy_speed}\n')
        return result

    def handle_type_change(self, line):
        result = []
        if self.in_top_solid_infill or self.in_bridge:
            # Restore motor settings when leaving fuzzy section
            if self._in_fuzzy_section:
                result.extend(self._build_exit_fuzzy_gcode())
                self._in_fuzzy_section = False
            if self.current_speed is not None:
                result.append(f'G1 F{self.current_speed}\n')
        self.in_top_solid_infill = False
        self.in_bridge = False
        result.append(line)
        return result

    def handle_z_movement(self, line):
        z_match = re.search(r'Z([-+]?[0-9]*\.?[0-9]+)', line)
        if z_match:
            self.current_layer_height = float(z_match.group(1))
        return [line]

    def handle_movement_in_infill(self, line):
        if all(param in line for param in ['X', 'Y', 'E']):
            return self.handle_extrusion_movement(line)
        elif all(param in line for param in ['X', 'Y', 'F']):
            return self.handle_travel_movement(line)
        elif all(param in line for param in ['X', 'Y']):  # bambu
            return self.handle_travel_movement(line)
        return [line]

    def handle_extrusion_movement(self, line):
        current_point, total_extrusion = self.process_movement_line(line)
        result = []

        if self.previous_point:
            points = self.interpolate_with_constant_resolution(
                self.previous_point, current_point,
                self.config.resolution, total_extrusion
            )

            for point in points:
                x, y, z, e = point
                result.append(f'G1 X{x:.4f} Y{y:.4f} Z{z:.4f} E{e:.4f}\n')
            result.append(f'; {line.strip()}\n')
        else:
            result.append(line)

        self.previous_point = current_point
        return result

    def handle_travel_movement(self, line):
        current_point, _ = self.process_movement_line(line)
        self.previous_point = current_point
        return [line]
