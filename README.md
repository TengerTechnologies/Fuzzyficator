# Fuzzyficator
(Work In Progress) A Gcode postprocessing script to add non-planar "Fuzzyskin" to top flat surfaces. 

Currently it is tested with Prusaslicer and Marlin Flavour gcode. (More slicers and Klipper will come)

Use it at your on risk.



You can run it with 4 parameters:

1: float:FuzzyResolution

2: float:z_min_displacement

3: float:z_max_displacement

4: bool:ensure_first_z_zero

FuzzyResolution sets the size of how to segment the Gcode
![grafik](https://github.com/user-attachments/assets/ec9a2832-ebee-4b15-a821-e848d71073ec)

z_min_displacement and z_max_displacement set the minimal and maximal Z displacement of the segments.
![grafik](https://github.com/user-attachments/assets/0e9c0c30-0c61-4df0-ae76-dbe2a4c6e381)

ensure_first_z_zero sets wether the first segment should not be displaced
![grafik](https://github.com/user-attachments/assets/a2874fcf-e2fa-4440-a6c1-b58d4f6bc080)

So to run the script with the following settings: FuzzyResolution: 0.3, z_min_displacement 0, z_max_displacement: 0.5, ensure_first_z_zero: 1

Run: `python fuzzyficator.py 0.3 0 0.5 1` in your console.

The gcode file must be in the same directory and must be named input.gcode
