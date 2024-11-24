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
# Copyright (c) [2024] [Roman Tenger]

import random
import math
import logging
import re
import sys
import argparse
import os

# Configuration and constants
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
        "external_perimeter": ";TYPE:External perimeter",
    },
    "orcaslicer": {
        "fuzzy_skin": "; fuzzy_skin =",
        "fuzzy_skin_values": ["allwalls", "external", "all"],
        "fuzzy_skin_point_dist": "; fuzzy_skin_point_distance =",
        "fuzzy_skin_thickness": "; fuzzy_skin_thickness =",
        "top_solid_infill": ";TYPE:Top surface",
        "type": ";TYPE:",
        "layer": ";LAYER_CHANGE",  ##----< verify
        "bridge": ";TYPE:Bridge",   ##----< verify
        "supportContact": "; support_bottom_z_distance",   ##----< verify
        "overhang": ";TYPE:Overhang wall",   ##----< verify
        "external_perimeter": ";TYPE:Outer wall",
    },
    "bambustudio": {
        "fuzzy_skin": "; fuzzy_skin =",
        "fuzzy_skin_values": ["allwalls", "external", "all"],
        "fuzzy_skin_point_dist": "; fuzzy_skin_point_dist =",
        "fuzzy_skin_thickness": "; fuzzy_skin_thickness =",
        "top_solid_infill": "; FEATURE: Top surface",
        "type": "; FEATURE:",
        "layer": "; CHANGE_LAYER:",   ##----< verify
        "bridge": ";TYPE:Bridge",   ##----< verify
        "supportContact": "; support_top_z_distance",   ##----< verify
        "overhang": "; FEATURE: Overhang wall",   ##----< verify
        "external_perimeter": "; FEATURE: Outer wall",
    }
}

class FuzzySkinConfig:
    def __init__(self, args):
        self.input_file = args.input_gcode
        self.resolution = args.resolution if args.resolution is not None else 0.3
        self.z_min = args.zMin
        self.z_max = args.zMax if args.zMax is not None else 0.3
        self.connect_walls = bool(args.connectWalls)
        self.fuzzy_speed = args.fuzzySpeed
        self.run = args.run
        self.compensate_extrusion = args.compensateExtrusion
        self.lower_surface = bool(args.lowerSurface)
        self.support_contact_dist = None
        self.xy_point_dist = args.xy_point_dist if args.xy_point_dist is not None else 0.3
        self.xy_thickness = args.xy_thickness if args.xy_thickness is not None else 0.3
        self.top_surface = bool(args.topSurface)
        self.bridge_compensation_multiplier = float(args.bridgeCompensationMultiplier)
        self.min_support_distance = float(args.minSupportDistance)

    def apply_gcode_settings(self, fuzzy_enabled, point_dist, thickness, support_contact_dist):
        """Apply G-code settings if command line args weren't specified"""
        if self.resolution is None and point_dist is not None:
            self.resolution = point_dist
        if self.z_max is None and thickness is not None:
            self.z_max = thickness
        if self.run is None:
            self.run = 1 if fuzzy_enabled else 0
        if support_contact_dist is not None:
            self.support_contact_dist = support_contact_dist

class GCodeProcessor:
    def __init__(self, config):
        self.config = config
        self.lookup = None
        self.current_layer_height = 0.0
        self.previous_point = None
        self.in_top_solid_infill = False
        self.in_bridge = False
        self.in_external_perimeter = False
        self.current_speed = None
        self.has_overhang_in_layer = False
        self.current_layer = None
        self.accumulated_distance = 0.0  # Track distance along perimeter
        self.last_wobble_point = None   # Last point where we applied wobble
        self.in_fuzzy_section = False

    @staticmethod
    def calculate_distance(point1, point2):
        distance = math.sqrt(
            (point2[0] - point1[0]) ** 2 + 
            (point2[1] - point1[1]) ** 2 + 
            (point2[2] - point1[2]) ** 2
        )
        logging.debug(f"Calculated distance between {point1} and {point2}: {distance}")
        return distance

    def interpolate_with_constant_resolution(self, start_point, end_point, segment_length, total_extrusion):
        distance = self.calculate_distance(start_point, end_point)
        if distance == 0:
            logging.debug(f"No interpolation needed for identical points: {start_point}")
            return []
        
        num_segments = max(1, int(distance / segment_length))
        points = []
        extrusion_per_segment = total_extrusion / num_segments
        
        for i in range(num_segments + 1):
            t = i / num_segments
            x_new = start_point[0] + (end_point[0] - start_point[0]) * t
            y_new = start_point[1] + (end_point[1] - start_point[1]) * t
            z_new = start_point[2] + (end_point[2] - start_point[2]) * t

            # Debug print to check values
            logging.debug(f"Bridge layer: {self.in_bridge}, Before z_displacement: {z_new}")

            if self.in_bridge:
                bridge_z_min = self.config.z_min - self.config.z_max
                bridge_z_max = self.config.support_contact_dist - self.config.min_support_distance

                z_displacement = (0 if (i == 0 or i == num_segments) and self.config.connect_walls 
                                else -random.uniform(bridge_z_min, bridge_z_max))
                # Force the displacement to be applied
                z_new = z_new + z_displacement
            else:
                z_displacement = (0 if (i == 0 or i == num_segments) and self.config.connect_walls 
                                else random.uniform(self.config.z_min, self.config.z_max))
                z_new = z_new + z_displacement

            # Debug print after modification
            logging.debug(f"z_displacement: {z_displacement}, After z_displacement: {z_new}")

            # Remove the max check for bridge layers to allow lower z values
            if not self.in_bridge:
                z_new = max(self.current_layer_height, z_new)   

            distance = math.sqrt(segment_length ** 2 + z_displacement ** 2)
            compensation_factor = distance / segment_length if segment_length != 0 else 1
            compensation_factor = compensation_factor ** self.config.bridge_compensation_multiplier
            compensated_extrusion = (extrusion_per_segment * compensation_factor 
                                   if self.config.compensate_extrusion else extrusion_per_segment)
            
            points.append((x_new, y_new, z_new, compensated_extrusion))
        
        return points

    def interpolate_with_constant_resolution_XY(self, start_point, end_point, total_extrusion):
        """Apply fuzzy skin effect along the perimeter."""
        original_distance = self.calculate_distance(start_point, end_point)
        if original_distance == 0:
            return [end_point + (total_extrusion,)]

        num_points = max(2, int(original_distance / self.config.xy_point_dist))
        points = []
        last_e = start_point[3] if len(start_point) > 3 else 0
        
        for i in range(num_points + 1):
            t = i / num_points
            # Base position
            x = start_point[0] + (end_point[0] - start_point[0]) * t
            y = start_point[1] + (end_point[1] - start_point[1]) * t
            
            # Add wobble to all points except start and end
            if 0 < i < num_points:
                wobble = random.uniform(-self.config.xy_thickness, self.config.xy_thickness)
                # Apply wobble perpendicular to movement direction
                dx = end_point[0] - start_point[0]
                dy = end_point[1] - start_point[1]
                length = math.sqrt(dx*dx + dy*dy)
                if length > 0:
                    x += wobble * (-dy/length)
                    y += wobble * (dx/length)
            
            # Calculate extrusion for this segment
            e = start_point[3] + (total_extrusion * t) if len(start_point) > 3 else total_extrusion * t
            
            # For all points except the first one, store the delta E
            if i > 0:
                e_delta = e - last_e
                points.append((x, y, start_point[2], e_delta))
            else:
                # First point uses absolute E
                points.append((x, y, start_point[2], e))
            
            last_e = e

        return points

    def detect_slicer(self, gcode_lines):
        for line in gcode_lines[:10]:
            if 'PrusaSlicer' in line: return 'prusaslicer'
            elif 'OrcaSlicer' in line: return 'orcaslicer'
            elif 'BambuStudio' in line: return 'bambustudio'
        return None

    def detect_gcode_flavor(self, gcode_lines):
        for line in gcode_lines:
            if line.startswith('; gcode_flavor ='):
                return line.split('=')[-1].strip()
        return None

    def process_fuzzy_skin_settings(self, gcode_lines):
        fuzzy_enabled, point_dist, thickness, support_contact_dist = (
            self._process_basic_fuzzy_settings(gcode_lines)
        )
        
        # Apply settings to config if not set by command line
        if self.config.xy_point_dist is None and point_dist is not None:
            self.config.xy_point_dist = point_dist
        if self.config.xy_thickness is None and thickness is not None:
            self.config.xy_thickness = thickness
        
        return fuzzy_enabled, point_dist, thickness, support_contact_dist

    def _process_basic_fuzzy_settings(self, gcode_lines):
        """Original fuzzy settings processing logic"""
        fuzzy_enabled = False
        point_dist = None
        thickness = None
        support_contact_dist = None
        
        # First check if fuzzy skin is enabled
        for line in reversed(gcode_lines):
            if line.startswith(self.lookup["fuzzy_skin"]):
                fuzzy_skin_value = line.split('=')[-1].strip().lower()
                if fuzzy_skin_value in self.lookup["fuzzy_skin_values"]:
                    fuzzy_enabled = True
                break
         
        if fuzzy_enabled:
            logging.error("Paint-On Fuzzyskin requires to turn off normal fuzzyskin in the slicer.")  #-->Exit if fuzzy skin is enabled
            sys.exit(1)
            
        
        # Look for fuzzy skin settings if enabled
        if fuzzy_enabled:
            for line in reversed(gcode_lines):
                if line.startswith(self.lookup["fuzzy_skin_point_dist"]):
                    try:
                        point_dist = float(line.split('=')[-1].strip())
                    except ValueError:
                        logging.warning("Invalid value for fuzzy_skin_point_dist")
                elif line.startswith(self.lookup["fuzzy_skin_thickness"]):
                    try:
                        thickness = float(line.split('=')[-1].strip())
                    except ValueError:
                        logging.warning("Invalid value for fuzzy_skin_thickness")
                if point_dist is not None and thickness is not None:
                    break

        # Always look for support contact distance, regardless of fuzzy skin state
        for line in reversed(gcode_lines):
            if line.startswith(self.lookup["supportContact"]):
                try:
                    support_contact_dist = float(line.split('=')[-1].strip())
                    logging.debug(f"Support contact distance: {support_contact_dist}")
                except ValueError:
                    logging.warning("Invalid value for support_material_contact_distance")
                break

        return fuzzy_enabled, point_dist, thickness, support_contact_dist

    def process_movement_line(self, line):
        """Process a G1 movement line and extract coordinates"""
        try:
            coordinates = {param[0]: float(param[1:]) 
                          for param in line.split() 
                          if param[0] in 'XYZE'}
            
            if 'X' in coordinates or 'Y' in coordinates:
                current_point = (
                    coordinates.get('X', self.previous_point[0] if self.previous_point else 0),
                    coordinates.get('Y', self.previous_point[1] if self.previous_point else 0),
                    coordinates.get('Z', self.current_layer_height)
                )
                return current_point, coordinates.get('E', 0.0)
            
            return None, coordinates.get('E', 0.0)
        except Exception as e:
            logging.debug(f"Error processing movement line: {line.strip()} - {e}")
            return None, 0.0

    def process_file(self):
        with open(self.config.input_file, "r", encoding="utf-8") as f:
            gcode_lines = f.readlines()
        
        
        
        gcode_lines = self.mark_fuzzy_sections(gcode_lines) 
        # Check for absolute extrusion mode
        for line in gcode_lines:
            if line.strip().startswith('M82'):
                logging.error("Absolute extrusion mode (M82) detected. This script only works with relative extrusion mode (M83).")
                return
        
        slicer = self.detect_slicer(gcode_lines)
        gcode_flavor = self.detect_gcode_flavor(gcode_lines)
        
        # Set lookup table based on slicer
        if slicer and slicer.lower() in LOOKUP_TABLES:
            self.lookup = LOOKUP_TABLES[slicer.lower()]
            if slicer == 'orcaslicer' and gcode_flavor == 'marlin':
                self.lookup = LOOKUP_TABLES['bambustudio']
        else:
            self.lookup = LOOKUP_TABLES["prusaslicer"]

        fuzzy_enabled, point_dist, thickness, support_contact_dist = self.process_fuzzy_skin_settings(gcode_lines)
        
        # Apply G-code settings where command line args weren't specified
        self.config.apply_gcode_settings(fuzzy_enabled, point_dist, thickness, support_contact_dist)
        
        # Exit early if fuzzy processing isn't needed
        if not self.config.run:
            logging.info("Fuzzy skin not enabled. No processing needed.")
            return

        # Process file only if fuzzy skin is enabled
        new_gcode = []
        for line in gcode_lines:
            processed_line = self.process_line(line)
            new_gcode.extend(processed_line)

        with open(self.config.input_file, "w", encoding="utf-8") as out:
            out.writelines(new_gcode)

    def process_line(self, line):
        # Check for fuzzy section markers
        if line.startswith(';FuzzySectionStart'):
            self.in_fuzzy_section = True
            return [line]
        elif line.startswith(';FuzzySectionEnd'):
            self.in_fuzzy_section = False
            return [line]

        # Check for layer change
        if line.startswith(self.lookup["layer"]):
            self.current_layer = line
            self.has_overhang_in_layer = False
            return [line]
        
        # Check for external perimeter
        elif line.startswith(self.lookup["external_perimeter"]):
            logging.debug("Starting external perimeter section")
            self.in_external_perimeter = True
            self.in_top_solid_infill = False
            self.in_bridge = False
            return [line]
        
        # Check for overhang perimeter
        elif line.startswith(self.lookup["overhang"]):
            self.has_overhang_in_layer = True
            self.in_external_perimeter = False
            return [line]
        
        # Check for bridge infill
        elif line.startswith(self.lookup["bridge"]) and self.config.lower_surface and self.has_overhang_in_layer and self.in_fuzzy_section:
            self.in_external_perimeter = False
            return self.handle_bridge_infill(line)
        
        # Check for top solid infill
        elif line.startswith(self.lookup["top_solid_infill"]) and self.in_fuzzy_section and self.config.top_surface:
            self.in_external_perimeter = False
            return self.handle_top_solid_infill(line)
        
        # Handle all type changes
        elif line.startswith(self.lookup["type"]):
            return self.handle_type_change(line)
        
        # Handle Z movements
        elif 'G1' in line and 'Z' in line:
            return self.handle_z_movement(line)
        
        # Handle movement commands based on current section
        elif line.startswith('G1'):
            if self.in_external_perimeter and self.in_fuzzy_section:
                if 'E' not in line:  # This is the positioning move
                    result = self.process_movement_line(line)
                    if result and result[0]:  # Check if we got a valid point
                        current_point = result[0]
                        logging.debug(f"Setting initial perimeter position: {current_point}")
                        self.previous_point = current_point
                    return [line]
                return self.handle_external_perimeter_movement(line)
            elif self.in_top_solid_infill or (self.in_bridge and self.config.lower_surface):
                return self.handle_movement_in_infill(line)
            else:
                # Track position for all other moves
                result = self.process_movement_line(line)
                if result and result[0]:  # Check if we got a valid point
                    self.previous_point = result[0]
        
        return [line]

    def handle_top_solid_infill(self, line):
        self.in_top_solid_infill = True
        self.previous_point = None
        result = [line]
        if self.config.fuzzy_speed is not None:
            current_speed_match = re.search(r'F([-+]?[0-9]*\.?[0-9]+)', line)
            if current_speed_match:
                self.current_speed = float(current_speed_match.group(1))
            result.append(f'G1 F{self.config.fuzzy_speed}\n')
        return result

    def handle_bridge_infill(self, line):
        self.in_bridge = True
        self.previous_point = None
        result = [line]
        if self.config.fuzzy_speed is not None:
            current_speed_match = re.search(r'F([-+]?[0-9]*\.?[0-9]+)', line)
            if current_speed_match:
                self.current_speed = float(current_speed_match.group(1))
            result.append(f'G1 F{self.config.fuzzy_speed}\n')
        return result

    def handle_type_change(self, line):
        """Handle type changes in the G-code"""
        logging.debug(f"Type change: {line.strip()}")
        
        # Reset all section flags unless explicitly entering that section
        if not line.startswith(self.lookup["external_perimeter"]):
            self.in_external_perimeter = False
        
        if not line.startswith(self.lookup["top_solid_infill"]):
            self.in_top_solid_infill = False
        
        if not line.startswith(self.lookup["bridge"]):
            self.in_bridge = False
        
        return [line]

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
        elif all(param in line for param in ['X', 'Y']): #bambu
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

    def handle_external_perimeter_movement(self, line):
        """Handle movement commands for external perimeter"""
        if not 'E' in line:  # This is the positioning move
            current_point = self.process_movement_line(line)[0]
            if current_point:
                self.previous_point = current_point
            return [line]

        current_point, e_value = self.process_movement_line(line)
        if not current_point or not self.previous_point:
            return [line]

        points = self.interpolate_with_constant_resolution_XY(
            self.previous_point,
            current_point,
            e_value
        )
        
        result = []
        for i, point in enumerate(points):
            x, y, z, e = point
            if i == 0:
                # First point uses absolute E position
                new_line = f'G1 X{x:.4f} Y{y:.4f} E{e:.5f}\n'
            else:
                # Subsequent points use relative E movements
                new_line = f'G1 X{x:.4f} Y{y:.4f} E{e:.5f}\n'
            result.append(new_line)
        
        self.previous_point = current_point
        return result

    def format_point_to_gcode(self, point):
        """Format a point into a G-code command"""
        x, y, z, e = point
        # Format with 4 decimal places and ensure we're using the same format as original G-code
        return f"G1 X{x:.4f} Y{y:.4f} E{e:.5f}\n"

    def parse_point(self, line):
        """Parse X, Y, Z, E coordinates from a G-code line"""
        try:
            # Initialize coordinates
            coords = {'X': None, 'Y': None, 'Z': None, 'E': None}
            
            # Split line into parts
            parts = line.split()
            logging.debug(f"Parsing line parts: {parts}")
            
            # Parse each part
            for part in parts:
                if part[0] in coords:
                    coords[part[0]] = float(part[1:])
            
            logging.debug(f"Parsed coordinates: {coords}")
            
            # If we don't have at least X and Y coordinates, return None
            if coords['X'] is None or coords['Y'] is None:
                logging.debug("Missing X or Y coordinates")
                return None
            
            # Use previous Z if not specified
            if coords['Z'] is None and hasattr(self, 'previous_point') and self.previous_point:
                coords['Z'] = self.previous_point[2]
            elif coords['Z'] is None:
                coords['Z'] = 0
            
            # Use previous E if not specified
            if coords['E'] is None and hasattr(self, 'previous_point') and self.previous_point:
                coords['E'] = self.previous_point[3]
            elif coords['E'] is None:
                coords['E'] = 0
            
            point = (coords['X'], coords['Y'], coords['Z'], coords['E'])
            logging.debug(f"Created point: {point}")
            return point
            
        except Exception as e:
            logging.error(f"Error parsing line '{line}': {str(e)}")
            return None

    def mark_fuzzy_sections(self, gcode_lines):
        """Pre-process G-code to mark fuzzy sections based on tool changes"""
        logging.debug("Marking fuzzy sections in G-code")
        
        # Check if gcode_lines is None or empty
        if not gcode_lines:
            logging.error("Received empty or None gcode_lines")
            return []
            
        # Determine which logic to use based on the lookup table
        try:
            if self.lookup == LOOKUP_TABLES["prusaslicer"]:
                return self._mark_fuzzy_sections_prusa(gcode_lines)
            elif self.lookup == LOOKUP_TABLES["orcaslicer"]:
                gcode_lines = self._remove_preheat_commands(gcode_lines)
                return self._mark_fuzzy_sections_orca(gcode_lines)
            else:  # BambuStudio
                return self._mark_fuzzy_sections_bambu(gcode_lines)
        except Exception as e:
            logging.error(f"Error processing G-code: {str(e)}")
            return []

    def _remove_preheat_commands(self, gcode_lines):
        """Remove all preheating commands for T0 and T1 (OrcaSlicer specific)"""
        filtered_lines = []
        for line in gcode_lines:
            # Skip lines containing M104 and (T0 or T1)
            if 'M104' in line and ('T0' in line or 'T1' in line):
                logging.debug(f"Removing OrcaSlicer preheat command: {line.strip()}")
                continue
            filtered_lines.append(line)
        return filtered_lines

    def _mark_fuzzy_sections_prusa(self, gcode_lines):
        """Original PrusaSlicer logic for marking fuzzy sections"""
        i = 0
        while i < len(gcode_lines) - 1:
            current_line = gcode_lines[i].strip()
            next_line = gcode_lines[i + 1].strip()
            
            if current_line == ';FuzzyTool':
                if next_line == 'T1':
                    gcode_lines[i] = ';FuzzySectionStart\n'
                    gcode_lines[i + 1] = ''
                    logging.debug(f"Marked fuzzy section start at line {i}")
                elif next_line == 'T0':
                    gcode_lines[i] = ';FuzzySectionEnd\n'
                    gcode_lines[i + 1] = ''
                    logging.debug(f"Marked fuzzy section end at line {i}")
                i += 2
            else:
                i += 1
                
        return [line for line in gcode_lines if line.strip()]

    def _mark_fuzzy_sections_orca(self, gcode_lines):
        """OrcaSlicer/BambuStudio logic for marking fuzzy sections"""
        i = 0
        first_fuzzy_tool = True  # Flag to track first occurrence
        
        while i < len(gcode_lines) - 1:
            current_line = gcode_lines[i].strip()
            
            if current_line == ';FuzzyTool':
                if first_fuzzy_tool:
                    # Skip the first occurrence - keep it and its configuration
                    first_fuzzy_tool = False
                    i += 1
                    continue
                
                # Process subsequent tool changes as before
                tool_config_end = i + 1
                while tool_config_end < len(gcode_lines):
                    line = gcode_lines[tool_config_end].strip()
                    if line.startswith('G1') and ('X' in line or 'Y' in line):
                        break
                    tool_config_end += 1
                
                for j in range(i + 1, tool_config_end):
                    if gcode_lines[j].strip() == 'T1':
                        gcode_lines[i] = ';FuzzySectionStart\n'
                        for k in range(i + 1, tool_config_end):
                            gcode_lines[k] = ''
                        logging.debug(f"Marked fuzzy section start at line {i} and cleared config block")
                        i = tool_config_end
                        break
                    elif gcode_lines[j].strip() == 'T0':
                        gcode_lines[i] = ';FuzzySectionEnd\n'
                        for k in range(i + 1, tool_config_end):
                            gcode_lines[k] = ''
                        logging.debug(f"Marked fuzzy section end at line {i} and cleared config block")
                        i = tool_config_end
                        break
            else:
                i += 1
                
        return [line for line in gcode_lines if line.strip()]

    def _mark_fuzzy_sections_bambu(self, gcode_lines):
        """BambuStudio logic for marking fuzzy sections"""
        i = 0
        first_fuzzy_tool = True
        first_filament_section = True
        last_end_section = None  # Store the last end section to keep it
        
        # First pass: find the last end section
        for idx, line in enumerate(gcode_lines):
            if line.strip() in [';FuzzyFilamentEnd', ';NonFuzzyFilamentEnd']:
                last_end_section = idx
        
        while i < len(gcode_lines):
            current_line = gcode_lines[i].strip()
            
            if current_line == ';FuzzyTool':
                logging.debug(f"Found FuzzyTool at line {i}: {current_line}")
                # Find the end marker
                end_index = i + 1
                found_end = False
                while end_index < len(gcode_lines):
                    if gcode_lines[end_index].strip() == ';FuzzyToolEnd':
                        found_end = True
                        break
                    end_index += 1
                
                if not found_end:
                    logging.debug(f"No FuzzyToolEnd found after line {i}")
                    i += 1
                    continue
                
                if first_fuzzy_tool:
                    logging.debug(f"Keeping first tool block from line {i} to {end_index}")
                    first_fuzzy_tool = False
                    i = end_index + 1
                    continue
                
                # Clear all lines between markers
                logging.debug(f"Clearing tool block from line {i} to {end_index}")
                for j in range(i, end_index + 1):
                    gcode_lines[j] = ''
                i = end_index + 1
                
            elif current_line in [';FuzzyFilament', ';NonFuzzyFilament']:
                logging.debug(f"Found {'Fuzzy' if 'Fuzzy' in current_line else 'NonFuzzy'}Filament at line {i}")
                eos_marker = ';FuzzyFilamentEOS' if current_line == ';FuzzyFilament' else ';NonFuzzyFilamentEOS'
                eos_index = i + 1
                found_eos = False
                while eos_index < len(gcode_lines):
                    if gcode_lines[eos_index].strip() == eos_marker:
                        found_eos = True
                        break
                    eos_index += 1
                
                if not found_eos:
                    logging.debug(f"No {eos_marker} found after line {i}")
                    i += 1
                    continue
                
                if first_filament_section:
                    logging.debug(f"Keeping first filament section from line {i} to {eos_index}")
                    first_filament_section = False
                    if current_line == ';FuzzyFilament':
                        gcode_lines[i] = ';FuzzySectionStart\n'
                else:
                    logging.debug(f"Processing subsequent filament section from line {i} to {eos_index}")
                    if current_line == ';FuzzyFilament':
                        gcode_lines[i] = ';FuzzySectionStart\n'
                        # Clear lines between start and EOS
                        for j in range(i + 1, eos_index + 1):
                            logging.debug(f"Clearing line {j}: {gcode_lines[j].strip()}")
                            gcode_lines[j] = ''
                    else:  # NonFuzzy
                        # Clear everything including the marker
                        for j in range(i, eos_index + 1):
                            gcode_lines[j] = ''
                
                i = eos_index + 1
                
            elif current_line in [';FuzzyFilamentEnd', ';NonFuzzyFilamentEnd']:
                eos_marker = ';FuzzyFilamentEndEOS' if current_line == ';FuzzyFilamentEnd' else ';NonFuzzyFilamentEndEOS'
                eos_index = i + 1
                while eos_index < len(gcode_lines):
                    if gcode_lines[eos_index].strip() == eos_marker:
                        break
                    eos_index += 1
                
                if i == last_end_section:
                    # Keep the last end section as is
                    if current_line == ';FuzzyFilamentEnd':
                        gcode_lines[i] = ';FuzzySectionEnd\n'
                else:
                    # For all other end sections
                    if current_line == ';FuzzyFilamentEnd':
                        gcode_lines[i] = ';FuzzySectionEnd\n'
                        # Clear lines between end and EOS
                        for j in range(i + 1, eos_index + 1):
                            gcode_lines[j] = ''
                    else:  # NonFuzzy
                        # Clear everything including the marker
                        for j in range(i, eos_index + 1):
                            gcode_lines[j] = ''
                
                i = eos_index + 1
                
            else:
                i += 1
        
        # Debug: Print final state
        filtered_lines = [line for line in gcode_lines if line.strip()]
        logging.debug(f"Final number of lines: {len(filtered_lines)}")
        return filtered_lines

def setup_logging():
    log_file_path = os.path.join(os.path.expanduser('~'), 'fuzzy_skin_script.log')
    try:
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.FileHandler(log_file_path), logging.StreamHandler()]
        )
    except Exception as e:
        print(f"Failed to create log file: {e}")

def parse_arguments():
    parser = argparse.ArgumentParser(description='Postprocess G-code to add fuzzy skin on top solid infill layers.')
    parser.add_argument('--set-resolution', action='store_true', help='Indicate if -resolution was explicitly set')
    parser.add_argument('--set-zMax', action='store_true', help='Indicate if -zMax was explicitly set')
    parser.add_argument('input_gcode', type=str, help='Path to the input G-code file')
    parser.add_argument('-resolution', type=float, help='Resolution for fuzzy skin interpolation')
    parser.add_argument('-zMin', type=float, default=0.0, help='Minimum Z displacement for fuzzy skin (default: 0.0)')
    parser.add_argument('-zMax', type=float, help='Maximum Z displacement for fuzzy skin')
    parser.add_argument('-connectWalls', type=int, choices=[0, 1], default=1, help='Ensure first Z remains at wall height (default: 1)')
    parser.add_argument('-run', type=int, choices=[0, 1], help='Run the script or not')
    parser.add_argument('--set-run', action='store_true', help='Indicate if -run was explicitly set')
    parser.add_argument('-compensateExtrusion', type=int, choices=[0, 1], default=1, help='Compensate extrusion for fuzzy skin segments (default: 0)')
    parser.add_argument('-fuzzySpeed', type=float, help='Print speed for fuzzy skin sections (in mm/min)')
    parser.add_argument('-lowerSurface', type=int, choices=[0, 1], default=1, help='Apply fuzzy skin to lower surfaces (default: 1)')
    parser.add_argument('-xy_point_dist', type=float, default=0.3,
                       help='Distance between fuzzy points for external perimeters (default: 0.8mm)')
    parser.add_argument('-xy_thickness', type=float, default=0.3,
                       help='Maximum deviation for external perimeter fuzzy skin (default: 0.3mm)')
    parser.add_argument('-topSurface', type=int, choices=[0, 1], default=1, help='Apply fuzzy skin to top surfaces (default: 1)')
    parser.add_argument('-bridgeCompensationMultiplier', type=float, default=3.0, 
                       help='Multiplier for bridge compensation factor (default: 3.0)')
    parser.add_argument('-minSupportDistance', type=float, default=0.1, 
                       help='Minimum distance to maintain from support structure (default: 0.1)')
    
    return parser.parse_args()

def main():
    setup_logging()
    logging.info("Script started")
    print("Script started")
    
    args = parse_arguments()
    config = FuzzySkinConfig(args)
    processor = GCodeProcessor(config)
    
    try:
        processor.process_file()
        print("Fuzzy skin G-code generated successfully with constant resolution!")
        logging.info("Fuzzy skin G-code generation completed successfully")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
