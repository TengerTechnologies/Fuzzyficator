# Fuzzyficator GUI - Community Contribution

A graphical interface for the Fuzzyficator G-code post-processor, aimed at making
the tool accessible to users who aren't comfortable with command-line usage.

## What This Adds

### New Files (original Fuzzyficator.py is NOT modified)

| File | Purpose |
|------|---------|
| `fuzzyficator_core.py` | Importable engine extracted from original logic + new features |
| `FuzzyficatorGUI.py` | Tkinter GUI application |
| `build.bat` | One-click PyInstaller build to create a standalone .exe |
| `GUI_README.md` | This file |

### New Features

**Motor Protection (G-code injection)**
- **Z Max Feedrate** (`M203 Z`) - Limits how fast the Z axis moves during fuzzy hops
- **Z Acceleration** (`M201 Z`) - Limits Z acceleration to prevent slamming on bed slingers
- **Z Jerk** (`M205 Z`) - Smooths Z direction changes to reduce vibration
- Values are injected before fuzzy sections and restored to defaults afterward

**Cooling Control**
- **Fan Speed Override** (`M106 S`) - Override part fan speed during fuzzy sections

**Printer Profiles**
- Bed Slinger Conservative (safe for P1S, Ender 3, etc.)
- Bed Slinger Balanced
- CoreXY Balanced
- CoreXY Aggressive
- Custom (manual settings)

**Preset System**
- Save/load named presets as JSON files in a `presets/` folder
- Share presets between users

**Slicer Command Generator**
- Shows the equivalent CLI command for the current settings
- Copy to clipboard for pasting into Bambu Studio / OrcaSlicer post-processing field

### Why Motor Protection Matters

The original Fuzzyficator adds Z-axis movements (hops) during top surface printing.
On **bed slinger** printers (P1S, Ender 3, Prusa MK3, etc.), the Z axis moves the
entire heavy print bed. Without limiting Z speed and acceleration, the bed can slam
up and down rapidly, causing:
- Excessive vibration and noise
- Stepper motor overload or missed steps
- Poor print quality from the bed oscillating
- Premature wear on Z lead screws

On **CoreXY** printers, only the lightweight hotend (or a light bed on a cantilevered
Z) moves, so they can handle much more aggressive Z speeds.

The built-in profiles provide safe defaults for each printer type.

## How to Use

### Run directly (Python required)
```bash
pip install tk  # usually included with Python
python FuzzyficatorGUI.py
```

### Build standalone .exe (Windows)
```bash
pip install pyinstaller
build.bat
# Output: dist/FuzzyficatorGUI.exe
```

## Architecture Notes for the Developer

- `fuzzyficator_core.py` re-implements the same G-code processing logic from
  `Fuzzyficator.py` but with a `FuzzyConfig` class that doesn't depend on argparse.
  This makes it callable from both CLI and GUI contexts.
- The original `Fuzzyficator.py` is **completely untouched** so existing CLI users
  are not affected.
- Motor protection G-code is injected via `_build_enter_fuzzy_gcode()` and
  `_build_exit_fuzzy_gcode()` in the processor class. The restore commands use
  typical Bambu defaults (Z feedrate 12mm/s, Z accel 500mm/s^2, Z jerk 0.4mm/s).
  These could be made configurable if needed.
- The GUI runs processing in a background thread so the UI doesn't freeze.
- Presets are stored as simple JSON files in a `presets/` folder next to the exe.

## License

GPL-3.0, same as the original Fuzzyficator. Original work by Roman Tenger.
