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
    },
    "bambustudio": {
        "fuzzy_skin": "; fuzzy_skin =",
        "fuzzy_skin_values": ["allwalls", "external", "all"],
        "fuzzy_skin_point_dist": "; fuzzy_skin_point_dist =",
        "fuzzy_skin_thickness": "; fuzzy_skin_thickness =",
        "top_solid_infill": "; FEATURE: Top surface",
        "type": "; FEATURE:",
        "layer": "; CHANGE_LAYER",   ##----< verify
        "bridge": "; FEATURE: Bridge",   ##----< verify
        "supportContact": "; support_top_z_distance",   ##----< verify
        "overhang": "; FEATURE: Overhang wall",   ##----< verify
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
        self.top_surface = bool(args.topSurface)
        self.support_contact_dist = None
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
        self.current_speed = None
        self.has_overhang_in_layer = False
        self.current_layer = None

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
            if self.in_bridge: 
                compensation_factor = compensation_factor ** self.config.bridge_compensation_multiplier
            compensated_extrusion = (extrusion_per_segment * compensation_factor 
                                   if self.config.compensate_extrusion else extrusion_per_segment)
            
            points.append((x_new, y_new, z_new, compensated_extrusion))
        
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
        fuzzy_skin_enabled = False
        fuzzy_skin_point_dist = None
        fuzzy_skin_thickness = None
        support_contact_dist = None

        # First check if fuzzy skin is enabled
        for line in reversed(gcode_lines):
            if line.startswith(self.lookup["fuzzy_skin"]):
                fuzzy_skin_value = line.split('=')[-1].strip().lower()
                if fuzzy_skin_value in self.lookup["fuzzy_skin_values"]:
                    fuzzy_skin_enabled = True
                break

        # Look for fuzzy skin settings if enabled
        if fuzzy_skin_enabled:
            for line in reversed(gcode_lines):
                if line.startswith(self.lookup["fuzzy_skin_point_dist"]):
                    try:
                        fuzzy_skin_point_dist = float(line.split('=')[-1].strip())
                    except ValueError:
                        logging.warning("Invalid value for fuzzy_skin_point_dist")
                elif line.startswith(self.lookup["fuzzy_skin_thickness"]):
                    try:
                        fuzzy_skin_thickness = float(line.split('=')[-1].strip())
                    except ValueError:
                        logging.warning("Invalid value for fuzzy_skin_thickness")
                if fuzzy_skin_point_dist is not None and fuzzy_skin_thickness is not None:
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

        return fuzzy_skin_enabled, fuzzy_skin_point_dist, fuzzy_skin_thickness, support_contact_dist

    def process_movement_line(self, line):
        coordinates = {param[0]: float(param[1:]) for param in line.split() if param[0] in 'XYZE'}
        
        current_point = (
            coordinates.get('X', self.previous_point[0] if self.previous_point else 0),
            coordinates.get('Y', self.previous_point[1] if self.previous_point else 0),
            coordinates.get('Z', coordinates.get('Z', self.current_layer_height))
        )
        
        return current_point, coordinates.get('E', 0.0)

    def process_file(self):
        with open(self.config.input_file, "r", encoding="utf-8") as f:
            gcode_lines = f.readlines()

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
        # Check for layer change
        if line.startswith(self.lookup["layer"]):
            self.current_layer = line
            self.has_overhang_in_layer = False
            return [line]
        # Check for overhang perimeter
        elif line.startswith(self.lookup["overhang"]):
            self.has_overhang_in_layer = True
            return [line]
        # Only process bridges if we have an overhang in this layer
        elif line.startswith(self.lookup["bridge"]) and self.config.lower_surface and self.has_overhang_in_layer:
            return self.handle_bridge_infill(line)
        elif line.startswith(self.lookup["top_solid_infill"]) and self.config.top_surface:
            return self.handle_top_solid_infill(line)
        elif line.startswith(self.lookup["type"]):
            return self.handle_type_change(line)
        elif 'G1' in line and 'Z' in line:
            return self.handle_z_movement(line)
        elif (self.in_top_solid_infill or (self.in_bridge and self.config.lower_surface)) and line.startswith('G1'):
            return self.handle_movement_in_infill(line)
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
        result = []
        if (self.in_top_solid_infill or self.in_bridge) and self.current_speed is not None:
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
    parser.add_argument('-zMax', type=float, default=0.3, help='Maximum Z displacement for fuzzy skin')
    parser.add_argument('-connectWalls', type=int, choices=[0, 1], default=1, help='Ensure first Z remains at wall height (default: 1)')
    parser.add_argument('-run', type=int, choices=[0, 1], help='Run the script or not')
    parser.add_argument('--set-run', action='store_true', help='Indicate if -run was explicitly set')
    parser.add_argument('-compensateExtrusion', type=int, choices=[0, 1], default=1, help='Compensate extrusion for fuzzy skin segments (default: 0)')
    parser.add_argument('-fuzzySpeed', type=float, help='Print speed for fuzzy skin sections (in mm/min)')
    parser.add_argument('-lowerSurface', type=int, choices=[0, 1], default=1, help='Apply fuzzy skin to lower surfaces (default: 1)')
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
