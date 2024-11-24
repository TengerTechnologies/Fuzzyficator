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

log_file_path = os.path.join(os.path.expanduser('~'), 'fuzzy_skin_script.log')
try:
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.FileHandler(log_file_path), logging.StreamHandler()])
except Exception as e:
    print(f"Failed to create log file: {e}")

# Function to calculate Euclidean distance between two 3D points
def calculate_distance(point1, point2):
    distance = math.sqrt((point2[0] - point1[0]) ** 2 + (point2[1] - point1[1]) ** 2 + (point2[2] - point1[2]) ** 2)
    logging.debug(f"Calculated distance between {point1} and {point2}: {distance}")
    return distance

# Function to linearly interpolate between two points with a constant segment size
def interpolate_with_constant_resolution(start_point, end_point, segment_length, current_layer_height, total_extrusion):
    distance = calculate_distance(start_point, end_point)
    if distance == 0:
        logging.debug(f"No interpolation needed for identical points: {start_point}")
        return []
    
    num_segments = max(1, int(distance / segment_length))  # Ensure at least one segment
    logging.debug(f"Interpolating between {start_point} and {end_point} with {num_segments} segments")
    points = []
    extrusion_per_segment = total_extrusion / num_segments  # Divide total extrusion evenly among segments
    
    for i in range(num_segments + 1):
        t = i / num_segments
        x_new = start_point[0] + (end_point[0] - start_point[0]) * t
        y_new = start_point[1] + (end_point[1] - start_point[1]) * t
        z_new = start_point[2] + (end_point[2] - start_point[2]) * t

        # Apply controlled fuzzy displacement within a smaller, safer range, keeping Z at least the current layer height
        z_displacement = 0 if (i == 0 or i == num_segments) and ensure_first_z_zero else random.uniform(z_displacement_min, z_displacement_max)  # No displacement for the first segment to ensure connection to walls
        z_new = max(current_layer_height, z_new + z_displacement)  

        original_distance = calculate_distance(start_point, end_point)
        distance = math.sqrt(segment_length ** 2 + z_displacement ** 2)
        compensation_factor = distance / segment_length if segment_length != 0 else 1
        compensated_extrusion = extrusion_per_segment * compensation_factor if args.compensateExtrusion == 1 else extrusion_per_segment
        points.append((x_new, y_new, z_new, compensated_extrusion))
        logging.debug(f"Generated interpolated point: ({x_new}, {y_new}, {z_new}, {extrusion_per_segment})")
    
    return points

# Example usage
if __name__ == "__main__":
    

    parser = argparse.ArgumentParser(description='Postprocess G-code to add fuzzy skin on top solid infill layers.')
    parser.add_argument('--set-resolution', action='store_true', help='Indicate if -resolution was explicitly set')
    parser.add_argument('--set-zMax', action='store_true', help='Indicate if -zMax was explicitly set')
    parser.add_argument('input_gcode', type=str, help='Path to the input G-code file')
    parser.add_argument('-resolution', type=float, help='Resolution for fuzzy skin interpolation')
    parser.add_argument('-zMin', type=float, default=0.0, help='Minimum Z displacement for fuzzy skin (default: 0.0)')
    parser.add_argument('-zMax', type=float, help='Maximum Z displacement for fuzzy skin')
    parser.add_argument('-ConnectWalls', type=int, choices=[0, 1], default=1, help='Ensure first Z remains at wall height (default: 1)')
    parser.add_argument('-run', type=int, choices=[0, 1], help='Run the script or not')
    parser.add_argument('--set-run', action='store_true', help='Indicate if -run was explicitly set')
    parser.add_argument('-compensateExtrusion', type=int, choices=[0, 1], default=0, help='Compensate extrusion for fuzzy skin segments (default: 0)')

    args = parser.parse_args()

    


    inFile = args.input_gcode
    fuzzy_resolution = args.resolution if args.resolution is not None else 0.3
    z_displacement_min = args.zMin
    z_displacement_max = args.zMax if args.zMax is not None else 0.3
    ensure_first_z_zero = bool(args.ConnectWalls)  # Desired fuzzy resolution, adjust for finer or coarser fuzziness

    try:
        with open(inFile, "r", encoding="utf-8") as f:
            logging.info("Reading input G-code file")
            gcode_lines = f.readlines()

        # Look for fuzzy_skin settings in the G-code file
        fuzzy_skin_enabled = False
        fuzzy_skin_point_dist = None
        fuzzy_skin_thickness = None

        for line in reversed(gcode_lines):
            if line.startswith('; fuzzy_skin ='):
                fuzzy_skin_value = line.split('=')[-1].strip().lower()
                if fuzzy_skin_value in ['external', 'all']:
                    fuzzy_skin_enabled = True
                break

        if fuzzy_skin_enabled:
            for line in reversed(gcode_lines):
                if line.startswith('; fuzzy_skin_point_dist ='):
                    try:
                        fuzzy_skin_point_dist = float(line.split('=')[-1].strip())
                    except ValueError:
                        logging.warning("Invalid value for fuzzy_skin_point_dist. Using default.")
                        fuzzy_skin_point_dist = None
                elif line.startswith('; fuzzy_skin_thickness ='):
                    try:
                        fuzzy_skin_thickness = float(line.split('=')[-1].strip())
                    except ValueError:
                        logging.warning("Invalid value for fuzzy_skin_thickness. Using default.")
                        fuzzy_skin_thickness = None
                if fuzzy_skin_point_dist is not None and fuzzy_skin_thickness is not None:
                    break

        if fuzzy_skin_enabled and fuzzy_skin_point_dist is not None and fuzzy_skin_thickness is not None:
            logging.info("Fuzzy skin setting is enabled. Updating parameters, unless overridden by command line arguments.")
            if args.resolution is None:
                fuzzy_resolution = fuzzy_skin_point_dist
            if args.zMax is None:
                z_displacement_max = fuzzy_skin_thickness
        else:
            fuzzy_resolution = 0.3
            z_displacement_max = 0.3
            logging.info("Fuzzy skin setting is disabled or incomplete in the G-code file. Proceeding with default parameters.")

        # Check if the script should run
        run_script = 1 if fuzzy_skin_enabled else 0
      
        run_script = args.run if args.run is not None else run_script
        
        if run_script == 0:
            logging.info("Run parameter is set to 0 or fuzzy skin is not enabled. Exiting without processing.")
            sys.exit(0)

        in_top_solid_infill = False
        new_gcode = []
        previous_point = None
        previous_extrusion = 0.0
        current_layer_height = 0.0
        extruder_relative_mode = True  # Assume extruder is in relative mode for this scenario

        for line in gcode_lines:
            if line.startswith(';TYPE:Top solid infill'):
                in_top_solid_infill = True
                logging.info("Entering top solid infill section")
                previous_point = None  # Reset previous point at the start of a new top solid infill section
                previous_extrusion = 0.0  # Reset previous extrusion
                new_gcode.append(line)
            elif line.startswith(';TYPE:'):
                if in_top_solid_infill:
                    logging.info("Exiting top solid infill section")
                in_top_solid_infill = False
                new_gcode.append(line)
            elif line.startswith(';LAYER:'):
                new_gcode.append(line)
            elif 'G1' in line and 'Z' in line:
                # Update the current layer height based on the Z value in the G1 command
                z_match = re.search(r'Z([-+]?[0-9]*\.?[0-9]+)', line)
                if z_match:
                    current_layer_height = float(z_match.group(1))
                    logging.debug(f"Updated current layer height to: {current_layer_height}")
                new_gcode.append(line)
            elif in_top_solid_infill and line.startswith('G1') and 'X' in line and 'Y' in line and 'E' in line:
                # Extract X, Y, Z, E coordinates
                coordinates = {param[0]: float(param[1:]) for param in line.split() if param[0] in 'XYZE'}
                logging.debug(f"Extracted coordinates: {coordinates}")
                
                current_point = (
                    coordinates.get('X', previous_point[0] if previous_point else 0),
                    coordinates.get('Y', previous_point[1] if previous_point else 0),
                    coordinates.get('Z', coordinates.get('Z', current_layer_height))
                )
                total_extrusion = coordinates.get('E', 0.0)  # In relative mode, E is the increment
                logging.debug(f"Current point: {current_point}, Total extrusion: {total_extrusion}")
                
                if previous_point:
                    # Calculate the distance and apply fuzzy skin based on the constant resolution
                    in_between_points = interpolate_with_constant_resolution(previous_point, current_point, fuzzy_resolution, current_layer_height, total_extrusion)
                    
                    for point in in_between_points:
                        x_new, y_new, z_new, e_new = point
                        new_gcode.append(f'G1 X{x_new:.4f} Y{y_new:.4f} Z{z_new:.4f} E{e_new:.4f}\n')
                        logging.debug(f"Added interpolated G1 command: G1 X{x_new:.4f} Y{y_new:.4f} Z{z_new:.4f} E{e_new:.4f}")
                
                if not previous_point:
                    new_gcode.append(line)  # Add the original G1 command if it was not processed
                else:
                    new_gcode.append(f'; {line.strip()}\n')  # Add the original G1 command as a comment
                logging.debug(f"Added original G1 command: {line.strip()}")
                # Update previous point after adding the original G-code line
                previous_point = current_point
            elif in_top_solid_infill and line.startswith('G1') and 'X' in line and 'Y' in line and 'F' in line:
                # Extract X, Y, Z coordinates for travel moves
                coordinates = {param[0]: float(param[1:]) for param in line.split() if param[0] in 'XYZ'}
                logging.debug(f"Extracted coordinates for travel move: {coordinates}")
                
                current_point = (
                    coordinates.get('X', previous_point[0] if previous_point else 0),
                    coordinates.get('Y', previous_point[1] if previous_point else 0),
                    coordinates.get('Z', coordinates.get('Z', current_layer_height))
                )
                logging.debug(f"Current point for travel move: {current_point}")
                previous_point = current_point  # Update previous point after travel move
                new_gcode.append(line)
            else:
                new_gcode.append(line)  # Add non-movement commands as is

        # Overwrite the original G-code file with modified content
        with open(inFile, "w", encoding="utf-8") as out:
            logging.info("Saving modified G-code to output file")
            out.writelines(new_gcode)

        print("Fuzzy skin G-code generated successfully with constant resolution!")
        logging.info("Fuzzy skin G-code generation completed successfully")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
