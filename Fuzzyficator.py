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


logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

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
        z_displacement = 0 if i == 0 and ensure_first_z_zero else random.uniform(z_displacement_min, z_displacement_max)  # No displacement for the first segment to ensure connection to walls
        z_new = max(current_layer_height, z_new + z_displacement)  

        points.append((x_new, y_new, z_new, extrusion_per_segment))
        logging.debug(f"Generated interpolated point: ({x_new}, {y_new}, {z_new}, {extrusion_per_segment})")
    
    return points

# Open the G-code file
with open('input.gcode', 'r') as gcode_file:
    logging.info("Reading input G-code file")
    gcode_lines = gcode_file.readlines()

in_top_solid_infill = False
new_gcode = []
previous_point = None
previous_extrusion = 0.0
import sys

# Parse command-line arguments for parameters
fuzzy_resolution = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3
z_displacement_min = float(sys.argv[2]) if len(sys.argv) > 2 else 0
z_displacement_max = float(sys.argv[3]) if len(sys.argv) > 3 else 0.3
ensure_first_z_zero = bool(int(sys.argv[4])) if len(sys.argv) > 4 else True  # Desired fuzzy resolution, adjust for finer or coarser fuzziness
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
        
        new_gcode.append(line)  # Add the original G1 command
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

# Save the modified G-code to a new file
with open('output_fuzzy_skin.gcode', 'w') as new_gcode_file:
    logging.info("Saving modified G-code to output file")
    new_gcode_file.writelines(new_gcode)

print("Fuzzy skin G-code generated successfully with constant resolution!")
logging.info("Fuzzy skin G-code generation completed successfully")
