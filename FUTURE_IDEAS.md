# Fuzzyficator — Possible Future Upgrades

Ideas for the maintainer to consider. These are suggestions only — each would need
evaluation for whether it fits the project's direction and is worth the complexity.

---

### 1. Absolute Extrusion Mode (M82) Support

Many printers and slicer configurations default to absolute extrusion (M82) rather than
relative (M83). Currently the script rejects these files entirely. Supporting M82 would
require tracking the absolute E position and computing deltas for extrusion compensation
rather than relying on relative E values directly.

### 2. Multi-Color / Multi-Tool Print Support

Skip fuzzy processing during tool-change sequences (T0/T1 commands), purge tower sections
(`;TYPE:Prime tower` or `;TYPE:PRIME-TOWER`), and filament swap pauses (M600). Resume normal
fuzzy processing once the printer returns to the active print area. This is critical for AMS
and multi-extruder setups which are increasingly common.

### 3. Retraction-Aware Processing

When retraction G-code appears within a fuzzy section (G10/G11 firmware retraction, or
G1 E-negative for direct retraction), pass those moves through without modification and
without disrupting the Z-offset tracking. Currently retraction moves may get caught in
the interpolation logic and produce corrupted extrusion values.

### 4. Per-Layer Z-Offset Ramping

Instead of applying full Z displacement immediately, ramp the displacement over the first
and last N moves of a fuzzy section. This creates a smooth transition between flat and
textured regions rather than an abrupt edge. Would improve print quality at the boundaries
of fuzzy zones.

### 5. Travel Move Filtering in Fuzzy Sections

Detect non-extruding moves (G0, or G1 without E parameter) within fuzzy sections and
pass them through at the current Z height without displacement. This prevents the toolhead
from doing unnecessary Z-hops during travel moves over holes or gaps in the top surface,
which causes stringing and artifacts.

### 6. Configurable Restore Values for Motor Protection

The motor protection feature (M201/M203/M205 injection) restores to hardcoded defaults
after fuzzy sections. Different printers have different default Z speeds and accelerations.
The restore values could be:
- Auto-detected from the G-code header (many slicers emit M201/M203 at the start)
- User-configurable per printer

### 7. Seed-Based Reproducible Randomness

The fuzzy Z-displacement uses `random.uniform()` which produces different results each run.
An optional seed parameter (`-seed N`) would make output deterministic. Useful for debugging,
batch processing (consistent texture across copies), and quality control.

### 8. Minimum Segment Length Filter

Very short G-code segments (< 0.1mm travel) can receive Z-displacement that creates
extreme angles relative to segment length, producing spiky artifacts. A minimum segment
length filter would skip fuzzy processing on segments below a threshold.

### 9. Adaptive Z-Displacement Based on Speed

Scale the Z-displacement range based on the current feedrate. At lower speeds, the printer
can handle larger Z-hops. At higher speeds, large Z-hops cause ringing and overshoot
(especially on bed slingers). Reducing zMax at high feedrates would produce more consistent
texture quality regardless of print speed.

---

*Suggestions from community contributor, March 2026.*
