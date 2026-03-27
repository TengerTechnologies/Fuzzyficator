# Fuzzyficator — Issue Status Report

This document was prepared as part of the GUI community contribution to help the maintainer
review the current state of open issues. Each issue is categorized as **Resolved** (fixed in
this contribution), **Partially Addressed**, or **Outstanding** (needs core engine work).

---

## Resolved in This Contribution

| # | Title | How It Was Addressed |
|---|-------|---------------------|
| **#2** | Can't get it to work with Cura gcode | Added Cura/CuraEngine slicer detection and lookup table to `fuzzyficator_core.py`. Matches `;LAYER:` and `;TYPE:SKIN` patterns. Old CrealitySlicer (Cura fork) also detected. |
| **#3** | Software not running on OrcaSlicer with Bambu Printers | Already working in original code. GUI auto-detects slicer from G-code comments. Improved detection to check 50 lines instead of 10, with fallback pattern matching. |
| **#1** | Modification for BambuStudio | Already supported in original code. GUI includes Bambu Studio post-processing command generator with auto-detected paths. |
| **#32** | POSSIBLE ERRORCODES - READ FIRST | GUI eliminates most error scenarios: file browser validates paths (Error 2), Python path auto-detected (Error 9009), binary G-code now caught with a friendly message explaining how to disable it in slicer settings (from Glitch-2112's comment about UTF-8 codec errors). |
| **#35** | I can't get the script to work | The entire GUI was built to solve this — no command line needed, searchable printer database, one-click processing, clear error messages. |
| **#38** | It worked once, now getting Error Code 2 | Path validation in GUI prevents this. Also added "Keep original file" option so the source file is never modified, eliminating issues from re-processing already-modified files. |
| **#40** | Post Processing Script, Error code: 2 | Same as #38 — GUI validates file exists before processing and auto-detects all paths. |
| **#36** | The script doesn't work in CrealitySlicer | Added Cura lookup table (old CrealitySlicer is a Cura fork). Newer Creality Print 5+ is an OrcaSlicer fork and is now auto-detected and mapped to the OrcaSlicer lookup table. |
| **#43** | Compatibility with Flash Studio (Flashforge) | Flash Studio and Orca-FlashForge are OrcaSlicer forks — now auto-detected. Locked FlashForge models (FlashPrint/.gx format) are shown as "Not Supported" in the GUI with an explanation. |

## Partially Addressed

| # | Title | Status | Notes |
|---|-------|--------|-------|
| **#39** | Script not progressing | Partially | GUI runs processing in a background thread with a progress bar so users can see activity. However, if the core engine itself hangs (infinite loop in processing logic), the GUI would show the progress bar stalled. Root cause in the core engine would need investigation. |
| **#10** | Doesn't work with absolute extrusion mode | Partially | The core already returns an error for M82 (absolute extrusion). The GUI shows this as a clear error dialog explaining the limitation. However, **adding M82 support to the core engine** would be the real fix — see Feature Suggestions below. |
| **#7** | Typo on post script text | Unknown | This is about a typo in the original README or script text. Not investigated as part of GUI work. Maintainer should check the original reporter's comment for specifics. |

## Outstanding — Needs Core Engine Work

| # | Title | Why It's Outstanding | Suggested Fix |
|---|-------|---------------------|---------------|
| **#45** | Does not work with multicolour prints | The core engine doesn't handle tool changes (T0/T1) or filament swap G-code. Multi-color prints insert purge sequences, wipe tower moves, and tool changes that break the line-by-line processing assumptions. | Core engine needs to detect and skip tool-change sequences. When a `T0`/`T1` or `M600` is encountered, pause fuzzy processing until the normal print path resumes. |
| **#44** | paintOn script top surface not affected and weird gCode | This is about `Fuzzyficator_paintOn.py`, a separate script not covered by this GUI contribution. | Needs investigation in the paintOn script's surface detection logic. |
| **#42** | Question regarding PaintOn in Bambu Studio | PaintOn script question, not the standard Fuzzyficator. | May need paintOn-specific documentation for Bambu Studio workflow. |
| **#41** | topSurface param not working in paintOn script | PaintOn script bug. | Needs debugging in `Fuzzyficator_paintOn.py`. |
| **#14** | Different infill patterns in PrusaSlicer | Infill pattern detection is a core engine concern. Different infill patterns may produce G-code move sequences that the interpolation logic doesn't handle well. | Would need testing with various infill patterns (gyroid, lightning, adaptive cubic) to identify which patterns cause issues. |
| **#13** | Standalone script 2.0 | Feature request for an updated standalone version. | This GUI contribution could serve as the basis — it already bundles into a standalone .exe via PyInstaller. |
| **#12** | Did not work with retraction turned on | Retraction G-code (G10/G11 or G1 E-negative) inserted mid-move may interfere with the interpolation and extrusion compensation logic. | Core engine's `process_line()` and `interpolate_with_constant_resolution()` need to handle retraction/unretraction moves within fuzzy sections — either pass them through unchanged or account for the E-axis reset. |
| **#9** | Feature Request: Fuzzy tops while fuzzy is off | User wants fuzzy top surfaces without enabling Fuzzy Skin in the slicer globally. | The `-run 1` flag already forces processing even when fuzzy skin is disabled in the slicer. This may just need better documentation. The GUI exposes this as a simple toggle. |
| **#8** | Idea: Every layer a fuzzy layer | Feature request to apply fuzzy Z-displacement to every layer, not just top surfaces and overhangs. | Would require modifying the core engine to process all `;TYPE:` sections, not just top solid infill and bridge/overhang. Could be a new flag like `-allLayers 1`. |
| **#6** | First extrusion of top surface not fuzzy | The first move after a `;TYPE:Top solid infill` comment may not get fuzzified because processing starts after the type comment is detected, potentially missing the first G1 move. | Core engine should buffer or look-ahead when entering a fuzzy section to ensure the first extrusion move is also processed. |
| **#4** | Wrong movements when having holes in top surface | Holes in top surfaces create travel moves (G0/G1 without extrusion) that interrupt the fuzzy section. The engine may be applying Z-displacement to travel moves or losing track of the Z offset across travel moves. | Core engine should detect non-extruding moves within fuzzy sections and pass them through without Z-displacement, then resume fuzzy processing on the next extruding move. |
| **#34** | Question... | Too vague to assess. | Maintainer should check the original issue for context. |

---

## Files Added by This Contribution

| File | Purpose |
|------|---------|
| `fuzzyficator_core.py` | Importable engine with motor protection, printer database, Cura support |
| `FuzzyficatorGUI.py` | Full GUI application (customtkinter) |
| `build.bat` | One-click PyInstaller build to standalone .exe |
| `GUI_README.md` | Developer documentation for the GUI |
| `ISSUE_STATUS.md` | This file |
| `FUTURE_IDEAS.md` | Possible future upgrades for maintainer to evaluate |

The original `Fuzzyficator.py` is **completely untouched**.

---

## Open Pull Requests — Notes for Maintainer

These PRs were open at the time of this contribution. Notes on how they relate to our work:

### PR #37 — Added Z-Range and Force flag (by dmgualb)
- Adds `-zIni` / `-zEnd` to limit fuzzy skin to a height range, and `-force` to process even with paint-on only
- **Our notes:** The Z-range feature is a great idea. Our GUI currently doesn't expose `-zIni`/`-zEnd` but could easily add sliders for it. The `-force` flag overlaps with our GUI's "run" toggle. If this PR is merged, we can update `fuzzyficator_core.py` to include these parameters in `FuzzyConfig`.

### PR #11 — Bugfix for PrusaSlicer issue 4 (by Art3mis-1)
- Fixes travel move handling in `Fuzzyficator_Prusaslicer.py` — prevents modifying travel moves and ensures first line after travel is processed
- **Our notes:** This is for the standalone PrusaSlicer script, not the main `Fuzzyficator.py`. However, the same travel-move bug likely exists in the main script (see issue #4). Worth reviewing and porting the fix to the main codebase.

### PR #5 — Bugfixes for issue 3+4 (by TimoRaab)
- Changes "TYPE" to "FEATURE" for OrcaSlicer/BambuStudio compatibility, adds `.lower()` for case handling, fixes travel move calculations
- **Our notes:** The maintainer identified the real issue as Marlin flavor detection, not comment changes. Our `fuzzyficator_core.py` already handles this correctly — the `detect_slicer()` function checks for Marlin flavor and remaps OrcaSlicer to BambuStudio lookup table when needed (the same approach the maintainer described in the PR comments). The travel move fix from this PR is worth merging regardless.

---

*Prepared by community contributor, March 2026. Licensed GPL-3.0.*
