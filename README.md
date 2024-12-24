# Fuzzyficator
(Work In Progress) A Gcode postprocessing script to add non-planar "Fuzzyskin" to top flat surfaces and overhangs.

(Dear Youtubers if you make a Video about this, I would be glad if you could link to my channel <3 https://www.youtube.com/@tengertechnologies ) 

The Fuzzyficator.py works for Bambustudio, Orcaslicer and Prusaslicer. 

Use it at your on risk.

The Fuzzyficator script automatically reads your fuzzyskin settings and applies them to the top and bottom surfaces. 
If you want to use the overhang fuzzyskin, enable supports. Otherwise it will end up in a failed overhang.

You can overite the settings with:

-resolution (use any number)

-zMin (use any number)

-zMax (use any number)

-connectWalls (use 1 or 0)

-run (use 1 or 0)

-compensateExtrusion (use 1 or 0)

-topSurface (use 1 or 0)

-lowerSurface (use 1 or 0)

-fuzzySpeed (use any number)

-minSupportDistance (use any number)

-bridgeCompensationMultiplier(use any number)



Add the script to your slicers postprocessing tab:

`"C:\pathToPython\python.exe" "C:\pathToScript\Fuzzyficator.py"`


The script will use your Fuzzyskin settings if Fuzzyskin is enabled. compensateExtrusion and connectWalls default to ON.

You can use the settings to override it's defaults by adding them after the script:

`"C:\pathToPython\python.exe" "C:\pathToScript\Fuzzyficator.py" -run 1 -zMin 0 -zMax 0.5 -resolution 0.3 -ConnectWalls 1 -compensateExtrusion 1` etc.



# General settings

-resolution sets the size of how to segment the Gcode
![grafik](https://github.com/user-attachments/assets/ec9a2832-ebee-4b15-a821-e848d71073ec)

-zMin and zMax set the minimal and maximal Z displacement of the segments.
![grafik](https://github.com/user-attachments/assets/0e9c0c30-0c61-4df0-ae76-dbe2a4c6e381)

-connectWalls sets wether the first segment should not be displaced. 
![grafik](https://github.com/user-attachments/assets/a2874fcf-e2fa-4440-a6c1-b58d4f6bc080)

-run enables or disables the script

-compensateExtrusion compensates extrusion values for the added distance 

-fuzzySpeed sets the speed for the fuzzy sections in mm/min

-topSurface enables or disables top surface processing

-lowerSurface enables or disables overhang processing 

-bridgeCompensationMultiplier is a factor to multiply the extrusion compensation on overhang layers

-minSupportDistance sets the minimal distance to the support interface 


# Fuzzyficator Paint-On

(experimental) A Gcode postprocessing script to add paint-on "Fuzzyskin" to Prusaslicer Orcaslicer and Bambustudio.



The Fuzzyficator_paintOn.py works for Bambustudio, Orcaslicer and Prusaslicer. 

Use it at your on risk.

The Fuzzyficator script only runs if fuzzyskin is disabled in the slicer. 
You have to set some things up in the slicers first. I'm still working on this page so for now check the video linked below. 

You can overite the settings with:

-resolution (use any number)

-zMin (use any number)

-zMax (use any number)

-connectWalls (use 1 or 0)

-run (use 1 or 0)

-compensateExtrusion (use 1 or 0)

-topSurface (use 1 or 0)

-lowerSurface (use 1 or 0)

-fuzzySpeed (use any number)

-minSupportDistance (use any number)

-bridgeCompensationMultiplier(use any number)


For paint-on only:

-xy_thickness (use any number)

-xy_point_dist (use any number)





# Video Guide



[![Thumnbnail](http://img.youtube.com/vi/cNkHfydnUCI/0.jpg)](http://www.youtube.com/watch?v=cNkHfydnUCI)


# Fuzzyficator Pattern

(experimental) A Gcode postprocessing script to add paint-on Displacement maps to Prusaslicer Orcaslicer and Bambustudio.



The Fuzzyficator_pattern.py works for Bambustudio, Orcaslicer and Prusaslicer. 

Use it at your on risk.

You will need to have a displacement map for it to work.
You have to set some things up in the slicers first. I'm still working on this page so for now check the video linked below. 

You need to set:

-run 1

-displacement_map Path\to\displacementMap.png

# Video Guide

# Old standalone version (Do not use anymore)

Only for Prusaslicer. Left in the repo because of the Youtube tutorial. 

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
