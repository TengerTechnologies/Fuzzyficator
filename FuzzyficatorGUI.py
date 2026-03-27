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
Fuzzyficator GUI
================
Bambu Studio-styled graphical interface for the Fuzzyficator G-code post-processor.

Can be compiled to a standalone .exe with PyInstaller:
    pyinstaller --onefile --windowed --collect-all customtkinter FuzzyficatorGUI.py
"""

import customtkinter as ctk
from tkinter import filedialog, messagebox
import json
import os
import sys
import glob
import threading
import subprocess

from fuzzyficator_core import FuzzyConfig, GCodeProcessor, PRINTER_PROFILES, PRINTER_DATABASE, UNSUPPORTED_PRINTERS, get_profile_for_printer

# ---------------------------------------------------------------------------
# Bambu Studio color palette
# ---------------------------------------------------------------------------
COLORS = {
    "bg_dark": "#1A1A2E",
    "bg_card": "#222238",
    "bg_input": "#2A2A45",
    "accent": "#00AE42",
    "accent_hover": "#00C94B",
    "accent_dim": "#007A2F",
    "text": "#EAEAEA",
    "text_dim": "#8888AA",
    "text_value": "#00D4FF",
    "warning": "#FF6B35",
    "error": "#FF4444",
    "success": "#00AE42",
    "border": "#333355",
    "slider_track": "#444466",
}

# ---------------------------------------------------------------------------
# Slicer & G-code auto-detection helpers
# ---------------------------------------------------------------------------
SLICER_SEARCH_PATHS = {
    "Bambu Studio": [
        os.path.expandvars(r"%ProgramFiles%\Bambu Studio"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Bambu Studio"),
        os.path.expandvars(r"%LOCALAPPDATA%\BambuStudio"),
        os.path.expandvars(r"%APPDATA%\BambuStudio"),
        r"C:\Program Files\Bambu Studio",
        r"D:\Program Files\Bambu Studio",
    ],
    "OrcaSlicer": [
        os.path.expandvars(r"%ProgramFiles%\OrcaSlicer"),
        os.path.expandvars(r"%ProgramFiles(x86)%\OrcaSlicer"),
        os.path.expandvars(r"%LOCALAPPDATA%\OrcaSlicer"),
        os.path.expandvars(r"%APPDATA%\OrcaSlicer"),
        r"C:\Program Files\OrcaSlicer",
        r"D:\Program Files\OrcaSlicer",
    ],
    "PrusaSlicer": [
        os.path.expandvars(r"%ProgramFiles%\Prusa3D\PrusaSlicer"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Prusa3D\PrusaSlicer"),
        os.path.expandvars(r"%LOCALAPPDATA%\PrusaSlicer"),
        os.path.expandvars(r"%APPDATA%\PrusaSlicer"),
        r"C:\Program Files\Prusa3D\PrusaSlicer",
    ],
}

GCODE_SEARCH_DIRS = [
    os.path.expanduser("~/Desktop"),
    os.path.expanduser("~/Downloads"),
    os.path.expanduser("~/Documents"),
    os.path.expandvars(r"%USERPROFILE%\3D Objects"),
]
# NOTE: We intentionally do NOT search slicer install/data directories —
# those contain internal system G-code (AMS calibration, cache, etc.), not user prints.


def find_slicers():
    """Search for installed slicers and return {name: install_path}."""
    found = {}
    for name, paths in SLICER_SEARCH_PATHS.items():
        for p in paths:
            if os.path.isdir(p):
                found[name] = p
                break
    return found


def find_python():
    """Find the Python executable path."""
    return sys.executable


def find_recent_gcode(extra_dirs=None, max_files=20):
    """Find recent .gcode files in common locations."""
    search_dirs = list(GCODE_SEARCH_DIRS)
    if extra_dirs:
        search_dirs.extend(extra_dirs)

    gcode_files = []
    seen = set()
    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        # Search top level and one level deep
        for pattern in ["*.gcode", "*.g", "*/*.gcode", "*/*.g"]:
            for f in glob.glob(os.path.join(search_dir, pattern)):
                real = os.path.realpath(f)
                if real not in seen and os.path.isfile(real):
                    seen.add(real)
                    gcode_files.append(real)

    # Sort by modification time, newest first
    gcode_files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return gcode_files[:max_files]


# ---------------------------------------------------------------------------
# Tooltip class
# ---------------------------------------------------------------------------
class ToolTip:
    def __init__(self, widget, text, wrap_length=350):
        self.widget = widget
        self.text = text
        self.wrap_length = wrap_length
        self.tip_window = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule_show)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)
        # Also bind leave on all children so moving to a child doesn't orphan the tip
        for child in widget.winfo_children():
            child.bind("<Leave>", self._hide)
            child.bind("<Enter>", self._schedule_show)

    def _schedule_show(self, event=None):
        self._cancel_scheduled()
        self._after_id = self.widget.after(400, self._show)

    def _cancel_scheduled(self):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self, event=None):
        self._after_id = None
        if self.tip_window:
            return
        # Verify mouse is actually over the widget before showing
        try:
            mx = self.widget.winfo_pointerx()
            my = self.widget.winfo_pointery()
            wx = self.widget.winfo_rootx()
            wy = self.widget.winfo_rooty()
            ww = self.widget.winfo_width()
            wh = self.widget.winfo_height()
            if not (wx <= mx <= wx + ww and wy <= my <= wy + wh):
                return
        except Exception:
            return

        # Create tooltip off-screen first to measure its size
        self.tip_window = tw = ctk.CTkToplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry("+0+0")
        tw.attributes("-topmost", True)
        frame = ctk.CTkFrame(tw, fg_color="#0A0A0A", corner_radius=8,
                             border_width=1, border_color=COLORS["accent"])
        frame.pack()
        ctk.CTkLabel(frame, text=self.text, wraplength=self.wrap_length,
                     text_color=COLORS["accent"], font=("Segoe UI", 12),
                     padx=12, pady=8, justify="left").pack()

        # Force geometry calculation
        tw.update_idletasks()
        tip_w = tw.winfo_reqwidth()
        tip_h = tw.winfo_reqheight()

        # Get screen dimensions
        screen_w = self.widget.winfo_screenwidth()
        screen_h = self.widget.winfo_screenheight()

        # Default position: below and right of widget
        x = wx + 20
        y = wy + wh + 5

        # Clamp to stay within screen bounds
        if x + tip_w > screen_w:
            x = screen_w - tip_w - 10
        if x < 0:
            x = 10
        if y + tip_h > screen_h:
            # Show above the widget instead
            y = wy - tip_h - 5
        if y < 0:
            y = 10

        tw.wm_geometry(f"+{x}+{y}")

        # Safety: auto-hide after 5 seconds in case Leave event is missed
        self._auto_hide_id = self.widget.after(5000, self._hide)

    def _hide(self, event=None):
        self._cancel_scheduled()
        if hasattr(self, '_auto_hide_id') and self._auto_hide_id:
            try:
                self.widget.after_cancel(self._auto_hide_id)
            except Exception:
                pass
            self._auto_hide_id = None
        if self.tip_window:
            try:
                self.tip_window.destroy()
            except Exception:
                pass
            self.tip_window = None


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def get_app_data_dir():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    presets_dir = os.path.join(base, "presets")
    os.makedirs(presets_dir, exist_ok=True)
    return presets_dir


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------
class FuzzyficatorApp:
    # Scroll speed multiplier (default CTkScrollableFrame is very slow)
    SCROLL_SPEED = 8

    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")

        self.root = ctk.CTk()
        self.root.title("Fuzzyficator")
        self.root.geometry("800x920")
        self.root.minsize(740, 700)
        self.root.configure(fg_color=COLORS["bg_dark"])

        # --- Variables ---
        self.gcode_path = ctk.StringVar()
        self.printer_profile = ctk.StringVar(value="bed_slinger_conservative")

        # Fuzzy skin
        self.resolution = ctk.DoubleVar(value=0.3)
        self.z_min = ctk.DoubleVar(value=0.0)
        self.z_max = ctk.DoubleVar(value=0.3)
        self.connect_walls = ctk.BooleanVar(value=True)
        self.compensate_extrusion = ctk.BooleanVar(value=True)
        self.top_surface = ctk.BooleanVar(value=True)
        self.lower_surface = ctk.BooleanVar(value=True)
        self.bridge_comp_mult = ctk.DoubleVar(value=3.0)
        self.min_support_dist = ctk.DoubleVar(value=0.1)

        # Speed
        self.fuzzy_speed = ctk.DoubleVar(value=600.0)
        self.fuzzy_speed_enabled = ctk.BooleanVar(value=True)

        # Motor protection
        self.z_max_feedrate = ctk.DoubleVar(value=5.0)
        self.z_max_feedrate_enabled = ctk.BooleanVar(value=True)
        self.z_acceleration = ctk.DoubleVar(value=100.0)
        self.z_acceleration_enabled = ctk.BooleanVar(value=True)
        self.z_jerk = ctk.DoubleVar(value=0.4)
        self.z_jerk_enabled = ctk.BooleanVar(value=True)

        # Cooling
        self.fan_speed = ctk.DoubleVar(value=100.0)
        self.fan_speed_enabled = ctk.BooleanVar(value=False)

        # Preset
        self.preset_name = ctk.StringVar()

        # Detected slicers cache
        self._detected_slicers = find_slicers()
        self._recent_gcode = []
        self._custom_gcode_dirs = []  # User-added search folders

        # Show welcome screen first
        self._build_welcome_screen()

    def run(self):
        self.root.mainloop()

    # ======================================================================
    # Welcome / Printer Selection Screen
    # ======================================================================
    def _build_welcome_screen(self):
        """First screen — search for your printer or pick a profile."""
        self.welcome_frame = ctk.CTkFrame(self.root, fg_color=COLORS["bg_dark"])
        self.welcome_frame.pack(fill="both", expand=True)

        # Header
        header = ctk.CTkFrame(self.welcome_frame, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(30, 0))

        ctk.CTkLabel(header, text="Welcome to Fuzzyficator",
                     font=("Segoe UI", 32, "bold"), text_color=COLORS["accent"]).pack(anchor="w")
        ctk.CTkLabel(header, text="Add fuzzy texture to top surfaces and overhangs of your 3D prints",
                     font=("Segoe UI", 14), text_color=COLORS["text_dim"]).pack(anchor="w", pady=(2, 0))

        # --- Search for your printer ---
        search_card = ctk.CTkFrame(self.welcome_frame, fg_color=COLORS["bg_card"],
                                   corner_radius=12, border_width=1, border_color=COLORS["border"])
        search_card.pack(fill="x", padx=30, pady=(20, 0))

        ctk.CTkLabel(search_card, text="Find Your Printer",
                     font=("Segoe UI", 16, "bold"), text_color=COLORS["text"]).pack(
                         anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(search_card, text="Start typing your printer name and we'll automatically pick the right settings:",
                     font=("Segoe UI", 12), text_color=COLORS["text_dim"]).pack(
                         anchor="w", padx=16, pady=(0, 8))

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._update_printer_search())

        search_entry = ctk.CTkEntry(search_card, textvariable=self._search_var, height=40,
                                    fg_color=COLORS["bg_input"], border_color=COLORS["border"],
                                    text_color=COLORS["text"],
                                    placeholder_text="Type your printer name... (e.g. P1S, Ender 3, Voron)",
                                    font=("Segoe UI", 14), width=500)
        search_entry.pack(fill="x", padx=16, pady=(0, 4))
        search_entry.focus()

        # Selected printer display
        self._selected_printer_label = ctk.CTkLabel(
            search_card, text="", font=("Segoe UI", 13, "bold"), text_color=COLORS["success"])
        self._selected_printer_label.pack(anchor="w", padx=16, pady=(4, 0))

        # Brand filter dropdown
        self._brand_filter_var = ctk.StringVar(value="All")
        brand_frame = ctk.CTkFrame(search_card, fg_color="transparent")
        brand_frame.pack(fill="x", padx=16, pady=(4, 0))

        # Extract unique brands from database
        all_printers = list(PRINTER_DATABASE.keys()) + list(UNSUPPORTED_PRINTERS.keys())
        brands = sorted(set(name.split()[0] for name in all_printers))
        brand_counts = {}
        for name in all_printers:
            b = name.split()[0]
            brand_counts[b] = brand_counts.get(b, 0) + 1
        major_brands = [b for b in brands if brand_counts.get(b, 0) >= 3]
        has_other = any(brand_counts.get(b, 0) < 3 for b in brands)

        # Build dropdown values with printer counts
        dropdown_values = ["All"]
        for b in major_brands:
            dropdown_values.append(f"{b} ({brand_counts[b]})")
        if has_other:
            other_count = sum(c for b, c in brand_counts.items() if b not in major_brands)
            dropdown_values.append(f"Other ({other_count})")

        self._brand_dropdown_map = {}
        for val in dropdown_values:
            key = val.split(" (")[0] if " (" in val else val
            self._brand_dropdown_map[val] = key

        ctk.CTkLabel(brand_frame, text="Brand:", font=("Segoe UI", 12),
                     text_color=COLORS["text_dim"]).pack(side="left", padx=(0, 8))

        self._brand_dropdown_btn = ctk.CTkButton(
            brand_frame, text="All  \u25BE", width=220, height=32,
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            text_color=COLORS["text"], font=("Segoe UI", 12),
            border_width=1, border_color=COLORS["border"],
            corner_radius=8, anchor="w",
            command=self._toggle_brand_dropdown)
        self._brand_dropdown_btn.pack(side="left")
        self._brand_dropdown_values = dropdown_values
        self._brand_dropdown_open = False
        self._brand_dropdown_popup = None

        self._major_brands = major_brands

        # Search results (scrollable)
        self._search_results_frame = ctk.CTkScrollableFrame(
            search_card, fg_color=COLORS["bg_input"], corner_radius=8, height=200,
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"])
        self._search_results_frame.pack(fill="x", padx=16, pady=(4, 14))

        # Pre-populate with all printers grouped by category
        self._populate_all_printers()

        # --- OR pick a profile manually ---
        ctk.CTkLabel(self.welcome_frame, text="— or choose a profile directly —",
                     font=("Segoe UI", 12), text_color=COLORS["text_dim"]).pack(pady=(12, 8))

        profile_row = ctk.CTkFrame(self.welcome_frame, fg_color="transparent")
        profile_row.pack(fill="x", padx=30)

        for key, profile in PRINTER_PROFILES.items():
            btn = ctk.CTkButton(
                profile_row, text=profile["label"], height=36,
                fg_color=COLORS["bg_card"], hover_color=COLORS["border"],
                text_color=COLORS["text"], border_width=1, border_color=COLORS["border"],
                font=("Segoe UI", 12),
                command=lambda k=key: self._select_profile_and_continue(k))
            btn.pack(side="left", padx=4, expand=True, fill="x")
            ToolTip(btn, profile["description"])

        # Continue button
        self._welcome_continue_btn = ctk.CTkButton(
            self.welcome_frame, text="Continue with Selected Printer", width=300, height=48,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color="white", font=("Segoe UI", 15, "bold"),
            corner_radius=10, command=self._close_welcome)
        self._welcome_continue_btn.pack(pady=(16, 0))

        ctk.CTkLabel(self.welcome_frame, text="You can always change your printer and settings later",
                     font=("Segoe UI", 11), text_color=COLORS["text_dim"]).pack(pady=(6, 20))

    def _scroll_results_to_top(self):
        """Scroll the printer search results back to the top."""
        try:
            self._search_results_frame._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

    def _toggle_brand_dropdown(self):
        """Open or close the custom scrollable brand dropdown."""
        if self._brand_dropdown_open and self._brand_dropdown_popup:
            self._close_brand_dropdown()
            return

        btn = self._brand_dropdown_btn
        x = btn.winfo_rootx()
        y = btn.winfo_rooty() + btn.winfo_height() + 2
        item_height = 30
        visible_items = 8.5
        popup_height = int(item_height * visible_items)

        self._brand_dropdown_popup = popup = ctk.CTkToplevel(self.root)
        popup.wm_overrideredirect(True)
        popup.wm_geometry(f"{btn.winfo_width()}x{popup_height}+{x}+{y}")
        popup.attributes("-topmost", True)
        popup.configure(fg_color=COLORS["bg_card"])

        scroll = ctk.CTkScrollableFrame(
            popup, fg_color=COLORS["bg_card"], corner_radius=0,
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"])
        scroll.pack(fill="both", expand=True)

        for val in self._brand_dropdown_values:
            item_btn = ctk.CTkButton(
                scroll, text=val, anchor="w", height=item_height - 4,
                fg_color="transparent", hover_color=COLORS["accent"],
                text_color=COLORS["text"], font=("Segoe UI", 12),
                corner_radius=4,
                command=lambda v=val: self._select_brand_dropdown(v))
            item_btn.pack(fill="x", padx=2, pady=1)

        self._brand_dropdown_open = True
        # Close if user clicks elsewhere
        popup.bind("<FocusOut>", lambda e: self.root.after(100, self._close_brand_dropdown))
        self.root.bind("<Button-1>", self._check_brand_dropdown_click, add="+")

    def _check_brand_dropdown_click(self, event):
        """Close dropdown if click is outside it."""
        if not self._brand_dropdown_popup:
            return
        try:
            px = self._brand_dropdown_popup.winfo_rootx()
            py = self._brand_dropdown_popup.winfo_rooty()
            pw = self._brand_dropdown_popup.winfo_width()
            ph = self._brand_dropdown_popup.winfo_height()
            bx = self._brand_dropdown_btn.winfo_rootx()
            by = self._brand_dropdown_btn.winfo_rooty()
            bw = self._brand_dropdown_btn.winfo_width()
            bh = self._brand_dropdown_btn.winfo_height()
            # Check if click is inside popup or button
            in_popup = px <= event.x_root <= px + pw and py <= event.y_root <= py + ph
            in_btn = bx <= event.x_root <= bx + bw and by <= event.y_root <= by + bh
            if not in_popup and not in_btn:
                self._close_brand_dropdown()
        except Exception:
            pass

    def _select_brand_dropdown(self, selection):
        """Handle brand selection from custom dropdown."""
        brand = self._brand_dropdown_map.get(selection, "All")
        self._brand_filter_var.set(brand)
        self._brand_dropdown_btn.configure(text=f"{selection}  \u25BE")
        self._close_brand_dropdown()
        self._update_printer_search()

    def _close_brand_dropdown(self):
        """Close the custom brand dropdown popup."""
        if self._brand_dropdown_popup:
            try:
                self._brand_dropdown_popup.destroy()
            except Exception:
                pass
            self._brand_dropdown_popup = None
        self._brand_dropdown_open = False
        try:
            self.root.unbind("<Button-1>")
        except Exception:
            pass

    def _get_brand_filtered_printers(self):
        """Return printer database filtered by current brand selection."""
        brand = self._brand_filter_var.get()
        if brand == "All":
            return dict(PRINTER_DATABASE)
        elif brand == "Other":
            return {n: t for n, t in PRINTER_DATABASE.items()
                    if n.split()[0] not in self._major_brands}
        else:
            return {n: t for n, t in PRINTER_DATABASE.items()
                    if n.split()[0] == brand}

    def _get_brand_filtered_unsupported(self):
        """Return unsupported printers filtered by current brand selection."""
        brand = self._brand_filter_var.get()
        if brand == "All":
            return dict(UNSUPPORTED_PRINTERS)
        elif brand == "Other":
            return {n: v for n, v in UNSUPPORTED_PRINTERS.items()
                    if n.split()[0] not in self._major_brands}
        else:
            return {n: v for n, v in UNSUPPORTED_PRINTERS.items()
                    if n.split()[0] == brand}

    def _populate_all_printers(self):
        """Show all printers grouped by type, with unsupported in a separate section."""
        for w in self._search_results_frame.winfo_children():
            w.destroy()

        db = self._get_brand_filtered_printers()
        bed_slingers = sorted([name for name, t in db.items() if t == "bed_slinger"])
        corexy = sorted([name for name, t in db.items() if t in ("corexy", "delta")])

        if bed_slingers:
            ctk.CTkLabel(self._search_results_frame,
                         text=f"BED SLINGERS ({len(bed_slingers)}) — bed moves in Y, needs gentle Z settings",
                         font=("Segoe UI", 11, "bold"), text_color=COLORS["warning"]).pack(
                             anchor="w", padx=8, pady=(6, 2))
            for name in bed_slingers:
                self._add_printer_button(name, "bed_slinger")

        if corexy:
            ctk.CTkLabel(self._search_results_frame,
                         text=f"\nCOREXY / FIXED BED ({len(corexy)}) — bed only moves in Z, can handle faster",
                         font=("Segoe UI", 11, "bold"), text_color=COLORS["text_value"]).pack(
                             anchor="w", padx=8, pady=(6, 2))
            for name in corexy:
                self._add_printer_button(name, "corexy")

        # Unsupported printers section
        unsupported = self._get_brand_filtered_unsupported()
        if unsupported:
            ctk.CTkLabel(self._search_results_frame,
                         text=f"\nNOT SUPPORTED ({len(unsupported)}) — locked to proprietary slicer, cannot use Fuzzyficator",
                         font=("Segoe UI", 11, "bold"), text_color=COLORS["error"]).pack(
                             anchor="w", padx=8, pady=(6, 2))
            for name in sorted(unsupported.keys()):
                reason = unsupported[name]["reason"]
                self._add_unsupported_printer_label(name, reason)

        if not bed_slingers and not corexy and not unsupported:
            ctk.CTkLabel(self._search_results_frame,
                         text="No printers in this category.",
                         font=("Segoe UI", 12), text_color=COLORS["text_dim"]).pack(padx=12, pady=10)

        self._search_results_frame.after(50, self._scroll_results_to_top)

    def _add_unsupported_printer_label(self, name, reason):
        """Add a non-clickable printer entry with reason why it's unsupported."""
        frame = ctk.CTkFrame(self._search_results_frame, fg_color="transparent")
        frame.pack(fill="x", padx=4, pady=0)
        ctk.CTkLabel(frame, text=f"  {name}", font=("Segoe UI", 12),
                     text_color=COLORS["text_dim"], anchor="w").pack(side="left")
        ctk.CTkLabel(frame, text=f"  — {reason}", font=("Segoe UI", 10),
                     text_color=COLORS["error"], anchor="w").pack(side="left")

    def _add_printer_button(self, name, motion_type):
        """Add a clickable printer name to the search results."""
        color = COLORS["warning"] if motion_type == "bed_slinger" else COLORS["text_value"]
        tag = "Bed Slinger" if motion_type == "bed_slinger" else "CoreXY"

        btn = ctk.CTkButton(
            self._search_results_frame, text=f"  {name}", anchor="w",
            fg_color="transparent", hover_color=COLORS["border"],
            text_color=color, font=("Segoe UI", 12),
            height=26, command=lambda n=name, t=motion_type: self._select_printer(n, t))
        btn.pack(fill="x", padx=4, pady=0)

    def _update_printer_search(self):
        """Filter the printer list based on search text and brand filter."""
        query = self._search_var.get().strip().lower()

        for w in self._search_results_frame.winfo_children():
            w.destroy()

        if not query:
            self._populate_all_printers()
            return

        # Search within brand-filtered set (supported)
        db = self._get_brand_filtered_printers()
        matches = []
        for name, motion in db.items():
            if query in name.lower():
                matches.append((name, motion))

        # Also search unsupported printers
        unsupported_db = self._get_brand_filtered_unsupported()
        unsupported_matches = []
        for name, info in unsupported_db.items():
            if query in name.lower():
                unsupported_matches.append((name, info))

        # Sort: exact brand/model matches first, then alphabetical
        matches.sort(key=lambda x: (query not in x[0].lower().split()[0] if x[0].lower().split() else True, x[0]))

        if not matches and not unsupported_matches:
            ctk.CTkLabel(self._search_results_frame,
                         text=f"No printers found matching '{query}'.\n"
                              "If your printer isn't listed, choose a profile below based on your printer type:\n"
                              "- Does your bed move forward/backward while printing? → Bed Slinger\n"
                              "- Does your bed only move up/down (or not at all)? → CoreXY",
                         font=("Segoe UI", 12), text_color=COLORS["text_dim"],
                         wraplength=500, justify="left").pack(padx=12, pady=10)
            return

        if matches:
            ctk.CTkLabel(self._search_results_frame,
                         text=f"{len(matches)} printer(s) found — click yours:",
                         font=("Segoe UI", 11, "bold"), text_color=COLORS["text"]).pack(
                             anchor="w", padx=8, pady=(6, 2))
            for name, motion in matches:
                self._add_printer_button(name, motion)

        if unsupported_matches:
            ctk.CTkLabel(self._search_results_frame,
                         text=f"\nNOT SUPPORTED ({len(unsupported_matches)}) — locked to proprietary slicer",
                         font=("Segoe UI", 11, "bold"), text_color=COLORS["error"]).pack(
                             anchor="w", padx=8, pady=(6, 2))
            for name, info in sorted(unsupported_matches, key=lambda x: x[0]):
                self._add_unsupported_printer_label(name, info["reason"])

        # Auto-scroll to top so results are visible
        self._search_results_frame.after(50, self._scroll_results_to_top)

    def _select_printer(self, name, motion_type):
        """User clicked a printer — set the right profile."""
        if motion_type in ("corexy", "delta"):
            self.printer_profile.set("corexy_balanced")
            profile_label = "CoreXY Balanced"
        else:
            self.printer_profile.set("bed_slinger_conservative")
            profile_label = "Bed Slinger Conservative"

        type_label = "CoreXY / Fixed Bed" if motion_type in ("corexy", "delta") else "Bed Slinger"
        self._selected_printer_label.configure(
            text=f"Selected: {name}  —  Type: {type_label}  —  Profile: {profile_label}")

    def _select_profile_and_continue(self, profile_key):
        """Shortcut: pick a profile directly and go to main UI."""
        self.printer_profile.set(profile_key)
        self._close_welcome()

    def _close_welcome(self):
        """Close welcome screen, build main UI with selected profile."""
        self.welcome_frame.destroy()
        self._build_ui()
        self._apply_profile()
        self._fix_scroll_speed()

    # ======================================================================
    # Fix scroll speed
    # ======================================================================
    def _fix_scroll_speed(self):
        """Override the default mouse wheel binding to scroll much faster."""
        canvas = self.main_scroll._parent_canvas

        # Unbind ALL existing mousewheel bindings so CTk's slow default is gone
        self.root.unbind_all("<MouseWheel>")
        self.root.unbind_all("<Button-4>")
        self.root.unbind_all("<Button-5>")
        try:
            canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass

        # Set a large scroll increment so each "unit" is bigger
        canvas.configure(yscrollincrement=20)

        def _fast_scroll(event):
            # event.delta is 120 or -120 per notch on Windows
            # With yscrollincrement=20 and multiplier=8, each notch scrolls 160px
            if event.delta:
                canvas.yview_scroll(int(-self.SCROLL_SPEED * (event.delta / 120)), "units")
            return "break"

        self.root.bind_all("<MouseWheel>", _fast_scroll, add=False)

    # ======================================================================
    # UI
    # ======================================================================
    def _build_ui(self):
        self.main_scroll = ctk.CTkScrollableFrame(
            self.root, fg_color=COLORS["bg_dark"],
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent"]
        )
        self.main_scroll.pack(fill="both", expand=True, padx=0, pady=0)

        # Header
        header = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 5))
        ctk.CTkLabel(header, text="Fuzzyficator",
                     font=("Segoe UI", 28, "bold"), text_color=COLORS["accent"]).pack(anchor="w")
        ctk.CTkLabel(header, text="Add fuzzy texture to top surfaces and overhangs of your 3D prints",
                     font=("Segoe UI", 13), text_color=COLORS["text_dim"]).pack(anchor="w", pady=(2, 0))

        self._build_info_section()
        self._build_file_section()
        self._build_profile_section()
        self._build_fuzzy_section()
        self._build_motor_section()
        self._build_cooling_section()
        self._build_preset_section()
        self._build_command_section()
        self._build_process_section()

        # Footer
        ctk.CTkLabel(self.main_scroll,
                     text="Fuzzyficator by Roman Tenger (TengerTechnologies)  |  "
                          "GUI & motor protection by community contribution  |  GPL-3.0",
                     font=("Segoe UI", 10), text_color=COLORS["text_dim"]).pack(pady=(5, 20))

    # -- Helpers ------------------------------------------------------------

    def _make_card(self, title, parent=None):
        if parent is None:
            parent = self.main_scroll
        card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12,
                            border_width=1, border_color=COLORS["border"])
        card.pack(fill="x", padx=20, pady=(10, 0))
        if title:
            ctk.CTkLabel(card, text=title, font=("Segoe UI", 15, "bold"),
                         text_color=COLORS["text"]).pack(anchor="w", padx=16, pady=(12, 2))
        return card

    def _make_help_text(self, parent, text):
        lbl = ctk.CTkLabel(parent, text=text, font=("Segoe UI", 11),
                           text_color=COLORS["text_dim"], wraplength=720, justify="left")
        lbl.pack(anchor="w", padx=16, pady=(0, 8))
        return lbl

    # -- Sections -----------------------------------------------------------

    def _build_info_section(self):
        card = self._make_card("Getting Started")
        self._make_help_text(card,
            "There are two ways to use Fuzzyficator:\n\n"
            "METHOD 1 — Manual (process one file at a time):\n"
            "  1. In your slicer, enable 'Fuzzy Skin' in print settings\n"
            "  2. Slice your model, then export the G-code:\n"
            "       Bambu Studio:  File > Export > Export G-code\n"
            "       OrcaSlicer:    File > Export > Export G-code\n"
            "       PrusaSlicer:   File > Export G-code\n"
            "  3. Save the .gcode file somewhere (Desktop is easy)\n"
            "  4. Select that file below, pick your printer profile, and click Process\n"
            "  5. Send the processed file to your printer:\n"
            "       Bambu Studio:  File > Send G-code (or drag file onto the app)\n\n"
            "METHOD 2 — Automatic (runs every time you slice):\n"
            "  1. Scroll down to 'Slicer Post-Processing Setup' and copy the command\n"
            "  2. Paste it into your slicer's post-processing scripts field\n"
            "  3. Now every time you slice, Fuzzyficator runs automatically!\n"
            "  4. To DISABLE it for a print: just turn off 'Fuzzy Skin' in your slicer —\n"
            "       the script detects this and skips processing automatically"
        )

    def _build_file_section(self):
        card = self._make_card("G-code File")
        self._make_help_text(card,
            "Select the .gcode file you exported from your slicer.\n\n"
            "How to export G-code from your slicer:\n"
            "  Bambu Studio:  Slice your model, then File > Export > Export G-code\n"
            "  OrcaSlicer:    Slice your model, then File > Export > Export G-code\n"
            "  PrusaSlicer:   Slice your model, then File > Export G-code\n\n"
            "Save it somewhere easy to find (like your Desktop), then use Browse or Find Recent below.\n"
            "If you always save to the same folder, click 'Add Folder' so Find Recent checks there too.\n\n"
            "Note: This modifies the file in place — keep the original if you want to re-slice later."
        )

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 4))

        entry = ctk.CTkEntry(row, textvariable=self.gcode_path, height=36,
                             fg_color=COLORS["bg_input"], border_color=COLORS["border"],
                             text_color=COLORS["text"],
                             placeholder_text="Select a G-code file below...",
                             font=("Segoe UI", 12))
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_browse = ctk.CTkButton(row, text="Browse...", width=90, height=36,
                                   fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                                   command=self._browse_file, font=("Segoe UI", 12, "bold"))
        btn_browse.pack(side="right", padx=(0, 4))
        ToolTip(btn_browse, "Open a file browser to manually pick your G-code file")

        btn_find = ctk.CTkButton(row, text="Find Recent", width=110, height=36,
                                 fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
                                 text_color=COLORS["text"], border_width=1, border_color=COLORS["border"],
                                 command=self._find_recent_gcode, font=("Segoe UI", 12))
        btn_find.pack(side="right", padx=(0, 4))
        ToolTip(btn_find, "Search Desktop, Downloads, Documents, and any folders you've added "
                          "for recently exported .gcode files")

        btn_add_folder = ctk.CTkButton(row, text="Add Folder", width=100, height=36,
                                       fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
                                       text_color=COLORS["text"], border_width=1, border_color=COLORS["border"],
                                       command=self._add_search_folder, font=("Segoe UI", 12))
        btn_add_folder.pack(side="right", padx=(0, 4))
        ToolTip(btn_add_folder, "Add a custom folder where you save your G-code files. "
                                "This folder will be included when you click 'Find Recent'.")

        # Custom folder display
        self.custom_dirs_label = ctk.CTkLabel(card, text="", font=("Segoe UI", 10),
                                              text_color=COLORS["text_dim"])
        # Only shown when there are custom dirs

        # Recent files list (initially hidden)
        self.recent_files_frame = ctk.CTkFrame(card, fg_color=COLORS["bg_input"], corner_radius=8)
        self._recent_files_visible = False

        ctk.CTkFrame(card, fg_color="transparent", height=10).pack()

    def _add_search_folder(self):
        """Let the user pick a custom folder to include in G-code searches."""
        folder = filedialog.askdirectory(title="Select folder where you save G-code files")
        if folder and folder not in self._custom_gcode_dirs:
            self._custom_gcode_dirs.append(folder)
            dirs_text = "Custom search folders: " + ", ".join(
                os.path.basename(d) or d for d in self._custom_gcode_dirs)
            self.custom_dirs_label.configure(text=dirs_text)
            self.custom_dirs_label.pack(anchor="w", padx=16, pady=(0, 4))
            self.status_label.configure(
                text=f"Added folder: {folder} — click 'Find Recent' to search it",
                text_color=COLORS["success"])

    def _find_recent_gcode(self):
        """Search common folders for recent G-code files and show them."""
        self.status_label.configure(text="Searching for G-code files...", text_color=COLORS["text_value"])
        self.root.update()

        self._recent_gcode = find_recent_gcode(extra_dirs=self._custom_gcode_dirs, max_files=15)

        # Clear and rebuild the list
        for w in self.recent_files_frame.winfo_children():
            w.destroy()

        if not self._recent_gcode:
            ctk.CTkLabel(self.recent_files_frame,
                         text="No .gcode files found in Desktop, Downloads, or Documents.\n"
                              "Try exporting from your slicer first, then click Find Recent again.",
                         font=("Segoe UI", 11), text_color=COLORS["text_dim"],
                         wraplength=680).pack(padx=12, pady=10)
        else:
            ctk.CTkLabel(self.recent_files_frame,
                         text=f"Found {len(self._recent_gcode)} recent G-code file(s) — click one to select it:",
                         font=("Segoe UI", 11, "bold"), text_color=COLORS["text"]).pack(
                             anchor="w", padx=12, pady=(8, 4))

            for filepath in self._recent_gcode:
                name = os.path.basename(filepath)
                folder = os.path.dirname(filepath)
                # Shorten the folder path for display
                short_folder = folder
                home = os.path.expanduser("~")
                if short_folder.startswith(home):
                    short_folder = "~" + short_folder[len(home):]

                btn_frame = ctk.CTkFrame(self.recent_files_frame, fg_color="transparent")
                btn_frame.pack(fill="x", padx=8, pady=1)

                btn = ctk.CTkButton(
                    btn_frame, text=f"  {name}", anchor="w",
                    fg_color="transparent", hover_color=COLORS["border"],
                    text_color=COLORS["text_value"], font=("Segoe UI", 12),
                    height=24, command=lambda p=filepath: self._select_gcode(p)
                )
                btn.pack(side="left", fill="x", expand=True)

                loc = ctk.CTkLabel(btn_frame, text=short_folder,
                                   font=("Segoe UI", 10), text_color=COLORS["text_dim"])
                loc.pack(side="right", padx=(4, 12))

        if not self._recent_files_visible:
            self.recent_files_frame.pack(fill="x", padx=16, pady=(0, 10))
            self._recent_files_visible = True

        self.status_label.configure(
            text=f"Found {len(self._recent_gcode)} G-code file(s)" if self._recent_gcode
            else "No G-code files found",
            text_color=COLORS["success"] if self._recent_gcode else COLORS["warning"]
        )

    def _select_gcode(self, path):
        self.gcode_path.set(path)
        self.status_label.configure(text=f"Selected: {os.path.basename(path)}", text_color=COLORS["success"])

    def _build_profile_section(self):
        card = self._make_card("Printer Profile")
        self._make_help_text(card,
            "Select the profile that matches your printer type. If you're unsure, check the "
            "list of common machines under each option. Bed slingers move the heavy print bed "
            "up/down — they need gentle Z settings. CoreXY printers move the lightweight hotend instead."
        )

        profiles_frame = ctk.CTkFrame(card, fg_color="transparent")
        profiles_frame.pack(fill="x", padx=16, pady=(0, 4))

        for key, profile in PRINTER_PROFILES.items():
            row = ctk.CTkFrame(profiles_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            rb = ctk.CTkRadioButton(row, text=profile["label"],
                                    variable=self.printer_profile, value=key,
                                    command=self._apply_profile,
                                    font=("Segoe UI", 12),
                                    fg_color=COLORS["accent"],
                                    hover_color=COLORS["accent_hover"],
                                    border_color=COLORS["border"],
                                    text_color=COLORS["text"])
            rb.pack(anchor="w")

            # Show machine list as tooltip AND as small text
            machines = profile.get("machines", [])
            if machines:
                machine_str = ", ".join(machines[:6])
                if len(machines) > 6:
                    machine_str += f", +{len(machines)-6} more"
                ToolTip(rb, profile["description"] + "\n\nCommon machines:\n" +
                        "\n".join(f"  - {m}" for m in machines))

                ml = ctk.CTkLabel(row, text=machine_str,
                                  font=("Segoe UI", 10), text_color=COLORS["text_dim"],
                                  wraplength=650)
                ml.pack(anchor="w", padx=(28, 0))
            else:
                ToolTip(rb, profile["description"])

        self.profile_desc = ctk.CTkLabel(card, text="", font=("Segoe UI", 11),
                                         text_color=COLORS["text_dim"], wraplength=720, justify="left")
        self.profile_desc.pack(anchor="w", padx=16, pady=(6, 12))

    def _build_fuzzy_section(self):
        card = self._make_card("Fuzzy Skin Settings")
        self._make_help_text(card,
            "These control how the fuzzy texture is generated. "
            "Resolution sets the detail level, Z displacement controls bump height. "
            "Hover over any setting for a detailed explanation."
        )

        self._add_slider(card, "Resolution", self.resolution, 0.05, 2.0,
                         "How finely the G-code is segmented (mm). Smaller = more detail but larger file size. "
                         "0.3mm is a good starting point. Going below 0.1 makes very large files.")

        self._add_slider(card, "Z Min Displacement", self.z_min, 0.0, 1.0,
                         "Minimum height of fuzzy bumps (mm). Usually 0. "
                         "Increase this if you want ALL points to be raised, not just some.")

        self._add_slider(card, "Z Max Displacement", self.z_max, 0.05, 2.0,
                         "Maximum height of fuzzy bumps (mm). This is the tallest a bump can be. "
                         "0.3mm gives a subtle texture, 0.5-1.0mm is more pronounced.")

        self._add_slider(card, "Bridge Compensation", self.bridge_comp_mult, 0.5, 10.0,
                         "How much extra filament to push on overhang/bridge fuzzy sections. "
                         "Higher = more material on overhangs to prevent gaps. Default 3.0.")

        self._add_slider(card, "Min Support Distance", self.min_support_dist, 0.0, 1.0,
                         "Minimum gap between print and support structures (mm). "
                         "Keeps fuzzy bumps from merging into supports. Default 0.1mm.")

        toggle_frame = ctk.CTkFrame(card, fg_color="transparent")
        toggle_frame.pack(fill="x", padx=16, pady=(5, 14))

        toggles = [
            (self.top_surface, "Top Surface",
             "Apply fuzzy texture to flat top surfaces. This is the main feature — "
             "makes horizontal tops rough/textured instead of smooth."),
            (self.lower_surface, "Lower Surface (Overhangs)",
             "Apply fuzzy texture to overhang/bridge areas. "
             "Requires supports enabled in slicer or overhangs may fail."),
            (self.connect_walls, "Connect Walls",
             "Keep the first and last point of each fuzzy line at the original height. "
             "Prevents gaps where fuzzy sections meet walls. Recommended ON."),
            (self.compensate_extrusion, "Compensate Extrusion",
             "Add extra filament to account for the longer path from Z bumps. "
             "Without this, fuzzy areas may be under-extruded. Recommended ON."),
        ]

        for i, (var, label, tip) in enumerate(toggles):
            sw = ctk.CTkSwitch(toggle_frame, text=label, variable=var,
                               font=("Segoe UI", 12), text_color=COLORS["text"],
                               fg_color=COLORS["slider_track"],
                               progress_color=COLORS["accent"],
                               button_color=COLORS["text"],
                               button_hover_color=COLORS["accent_hover"])
            sw.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 30), pady=4)
            ToolTip(sw, tip)

    def _build_motor_section(self):
        card = self._make_card("Speed & Motor Protection")
        self._make_help_text(card,
            "Limit how fast the Z axis moves during fuzzy sections. "
            "Critical for bed slingers where the heavy bed bounces up and down. "
            "Check the box next to each setting to enable it. "
            "Disabled = printer uses its own defaults (no G-code added)."
        )

        self._add_optional_slider(card, "Fuzzy Print Speed", "mm/min",
                                  self.fuzzy_speed, self.fuzzy_speed_enabled, 100, 3000,
                                  "Overall print speed during fuzzy sections. Lower = better quality but slower. "
                                  "600 mm/min is conservative, 1200+ is faster but may reduce quality.")

        self._add_optional_slider(card, "Z Max Feedrate", "mm/s",
                                  self.z_max_feedrate, self.z_max_feedrate_enabled, 1, 30,
                                  "Maximum Z axis speed (mm/s). Injects M203 Z command. "
                                  "On a bed slinger, the Z motor lifts the entire bed + print. "
                                  "5 mm/s = very safe, 8-10 = moderate, 15+ = aggressive.")

        self._add_optional_slider(card, "Z Acceleration", "mm/s\u00B2",
                                  self.z_acceleration, self.z_acceleration_enabled, 50, 2000,
                                  "How quickly Z speeds up/slows down (mm/s\u00B2). Injects M201 Z command. "
                                  "This is the #1 setting for preventing bed slam. "
                                  "100 = very gentle, 200-400 = moderate, 500 = Bambu default.")

        self._add_optional_slider(card, "Z Jerk", "mm/s",
                                  self.z_jerk, self.z_jerk_enabled, 0.1, 5.0,
                                  "Instant speed change on Z direction reversals (mm/s). Injects M205 Z. "
                                  "Lower = smoother bounce. 0.4 = Bambu default.")

        ctk.CTkFrame(card, fg_color="transparent", height=8).pack()

    def _build_cooling_section(self):
        card = self._make_card("Cooling (Fan Override)")
        self._make_help_text(card,
            "Override the part cooling fan during fuzzy sections. "
            "Leave disabled to use your slicer's fan speed."
        )

        self._add_optional_slider(card, "Fan Speed", "%",
                                  self.fan_speed, self.fan_speed_enabled, 0, 100,
                                  "Part cooling fan speed during fuzzy sections (0-100%). "
                                  "Restored by the slicer's next fan command after fuzzy ends.")

        ctk.CTkFrame(card, fg_color="transparent", height=8).pack()

    def _build_preset_section(self):
        card = self._make_card("Presets")
        self._make_help_text(card,
            "Save your settings as a named preset. Presets are stored as .json files "
            "in the 'presets' folder next to this program so you can share them."
        )

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 4))

        entry = ctk.CTkEntry(row, textvariable=self.preset_name, height=32,
                             fg_color=COLORS["bg_input"], border_color=COLORS["border"],
                             text_color=COLORS["text"], placeholder_text="Preset name...",
                             font=("Segoe UI", 12), width=200)
        entry.pack(side="left", padx=(0, 8))
        ToolTip(entry, "Type a name then click Save, or click a preset below to select it")

        for text, cmd, tip in [
            ("Save", self._save_preset, "Save all current settings under this name"),
            ("Load", self._load_preset, "Load the selected preset"),
            ("Delete", self._delete_preset, "Delete the selected preset file"),
        ]:
            b = ctk.CTkButton(row, text=text, width=70, height=32,
                              fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
                              text_color=COLORS["text"], border_width=1, border_color=COLORS["border"],
                              command=cmd, font=("Segoe UI", 12))
            b.pack(side="left", padx=2)
            ToolTip(b, tip)

        self.preset_list_frame = ctk.CTkFrame(card, fg_color=COLORS["bg_input"], corner_radius=8)
        self.preset_list_frame.pack(fill="x", padx=16, pady=(4, 14))
        self._refresh_preset_list()

    def _build_command_section(self):
        card = self._make_card("Slicer Post-Processing Setup (Automatic Mode)")

        # Show detected slicers
        slicer_info = ""
        if self._detected_slicers:
            slicer_names = ", ".join(self._detected_slicers.keys())
            slicer_info = f"Detected installed slicers: {slicer_names}\n\n"

        self._make_help_text(card,
            f"{slicer_info}"
            "This makes Fuzzyficator run automatically every time you slice — no manual export needed.\n\n"
            "Setup (one time only):\n"
            "  1. Copy the command below\n"
            "  2. Open your slicer and paste it into the post-processing scripts field:\n"
            "       Bambu Studio:  Process tab (gear icon) > Others > Post-processing Scripts\n"
            "       OrcaSlicer:    Process tab > Others > Post-processing Scripts\n"
            "       PrusaSlicer:   Print Settings > Output Options > Post-processing Scripts\n"
            "  3. That's it! The script will run after every slice automatically.\n\n"
            "How to turn it ON/OFF per print (no need to remove the command):\n"
            "  ON:   Enable 'Fuzzy Skin' in your slicer's print settings — the script processes the G-code\n"
            "  OFF:  Disable 'Fuzzy Skin' in your slicer — the script detects this and does nothing\n\n"
            "So you control it with the Fuzzy Skin toggle you already have in your slicer. "
            "No need to add or remove the command each time!"
        )

        self.cmd_textbox = ctk.CTkTextbox(card, height=70, fg_color=COLORS["bg_input"],
                                          text_color=COLORS["text_value"],
                                          font=("Consolas", 11), corner_radius=8,
                                          border_width=1, border_color=COLORS["border"])
        self.cmd_textbox.pack(fill="x", padx=16, pady=(0, 4))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))

        btn_copy = ctk.CTkButton(btn_row, text="Copy to Clipboard", width=140, height=30,
                                 fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
                                 text_color=COLORS["text"], border_width=1, border_color=COLORS["border"],
                                 command=self._copy_command, font=("Segoe UI", 11))
        btn_copy.pack(side="right")
        ToolTip(btn_copy, "Copy the command so you can paste it into your slicer")

        self._update_command_preview()

        for var in [self.resolution, self.z_min, self.z_max, self.connect_walls,
                    self.compensate_extrusion, self.top_surface, self.lower_surface,
                    self.fuzzy_speed, self.fuzzy_speed_enabled, self.bridge_comp_mult,
                    self.min_support_dist]:
            var.trace_add("write", lambda *_: self._update_command_preview())

    def _build_process_section(self):
        card = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
        card.pack(fill="x", padx=20, pady=(15, 5))

        self.progress = ctk.CTkProgressBar(card, fg_color=COLORS["slider_track"],
                                           progress_color=COLORS["accent"], height=8, corner_radius=4)
        self.progress.pack(fill="x", pady=(0, 8))
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(card, text="Ready — select a G-code file and click Process",
                                         font=("Segoe UI", 12), text_color=COLORS["text_dim"])
        self.status_label.pack(anchor="w", pady=(0, 8))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x")

        self.process_btn = ctk.CTkButton(
            btn_row, text="Process G-code", width=200, height=44,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color="white", font=("Segoe UI", 14, "bold"),
            corner_radius=10, command=self._process
        )
        self.process_btn.pack(side="left")
        ToolTip(self.process_btn,
                "Process the selected G-code file with your current settings.")

        self.keep_original_var = ctk.BooleanVar(value=True)
        keep_orig_cb = ctk.CTkCheckBox(
            btn_row, text="Keep original file",
            variable=self.keep_original_var,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["text"], font=("Segoe UI", 12),
            border_color=COLORS["border"])
        keep_orig_cb.pack(side="left", padx=(16, 0))
        ToolTip(keep_orig_cb,
                "When enabled, your original G-code file is preserved untouched. "
                "The processed file is saved as a copy with '_Fuzzyficator' added to the name.\n\n"
                "Example: MyPrint.gcode → MyPrint_Fuzzyficator.gcode\n\n"
                "When disabled, the original file is overwritten in place.")

        # Second row: dry run button
        btn_row2 = ctk.CTkFrame(card, fg_color="transparent")
        btn_row2.pack(fill="x", pady=(6, 0))

        self.dryrun_btn = ctk.CTkButton(
            btn_row2, text="Dry Run / Preview", width=180, height=36,
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            text_color=COLORS["text"], font=("Segoe UI", 12),
            border_width=1, border_color=COLORS["border"],
            corner_radius=8, command=self._dry_run
        )
        self.dryrun_btn.pack(side="left")
        ToolTip(self.dryrun_btn,
                "Analyze the G-code file without modifying anything.\n\n"
                "Shows a report with:\n"
                "- How many layers and sections will be fuzzified\n"
                "- Estimated number of fuzzy moves\n"
                "- Estimated extra print time from Z-hops\n"
                "- Motor protection and cooling settings\n"
                "- Any warnings or potential issues\n\n"
                "No files are changed — safe to run anytime.")

    # ======================================================================
    # Widget helpers
    # ======================================================================
    def _add_slider(self, parent, label_text, variable, from_, to, tooltip):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=3)

        lbl = ctk.CTkLabel(row, text=label_text, font=("Segoe UI", 12),
                           text_color=COLORS["text"], width=180, anchor="w")
        lbl.pack(side="left")
        ToolTip(lbl, tooltip)

        slider = ctk.CTkSlider(row, from_=from_, to=to, variable=variable,
                               fg_color=COLORS["slider_track"], progress_color=COLORS["accent"],
                               button_color=COLORS["text"], button_hover_color=COLORS["accent_hover"],
                               width=300)
        slider.pack(side="left", fill="x", expand=True, padx=(5, 10))
        ToolTip(slider, tooltip)

        val_lbl = ctk.CTkLabel(row, text=f"{variable.get():.2f}", font=("Consolas", 12),
                               text_color=COLORS["text_value"], width=60, anchor="e")
        val_lbl.pack(side="right")
        variable.trace_add("write", lambda *_, v=variable, l=val_lbl: l.configure(text=f"{v.get():.2f}"))

    def _add_optional_slider(self, parent, label_text, unit, variable, enabled_var, from_, to, tooltip):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=3)

        cb = ctk.CTkCheckBox(row, text="", variable=enabled_var, width=24,
                             fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                             border_color=COLORS["border"], checkmark_color="white")
        cb.pack(side="left", padx=(0, 4))
        ToolTip(cb, f"Enable/disable {label_text}. When off, the printer uses its own default.")

        lbl = ctk.CTkLabel(row, text=f"{label_text} ({unit})", font=("Segoe UI", 12),
                           text_color=COLORS["text"], width=210, anchor="w")
        lbl.pack(side="left")
        ToolTip(lbl, tooltip)

        slider = ctk.CTkSlider(row, from_=from_, to=to, variable=variable,
                               fg_color=COLORS["slider_track"], progress_color=COLORS["accent"],
                               button_color=COLORS["text"], button_hover_color=COLORS["accent_hover"],
                               width=260)
        slider.pack(side="left", fill="x", expand=True, padx=(5, 10))
        ToolTip(slider, tooltip)

        val_lbl = ctk.CTkLabel(row, text=f"{variable.get():.1f}", font=("Consolas", 12),
                               text_color=COLORS["text_value"], width=60, anchor="e")
        val_lbl.pack(side="right")
        variable.trace_add("write", lambda *_, v=variable, l=val_lbl: l.configure(text=f"{v.get():.1f}"))

        def toggle_state(*_):
            state = "normal" if enabled_var.get() else "disabled"
            slider.configure(state=state)
            alpha = COLORS["text"] if enabled_var.get() else COLORS["text_dim"]
            lbl.configure(text_color=alpha)
            val_color = COLORS["text_value"] if enabled_var.get() else COLORS["text_dim"]
            val_lbl.configure(text_color=val_color)
        enabled_var.trace_add("write", toggle_state)
        toggle_state()

    # ======================================================================
    # Profile handling
    # ======================================================================
    def _apply_profile(self):
        key = self.printer_profile.get()
        profile = PRINTER_PROFILES.get(key, {})
        self.profile_desc.configure(text=profile.get("description", ""))

        if key == "custom":
            return

        for pkey, var in {"resolution": self.resolution, "z_min": self.z_min, "z_max": self.z_max}.items():
            if profile.get(pkey) is not None:
                var.set(profile[pkey])

        for pkey, (var, en_var) in {
            "fuzzy_speed": (self.fuzzy_speed, self.fuzzy_speed_enabled),
            "z_max_feedrate": (self.z_max_feedrate, self.z_max_feedrate_enabled),
            "z_acceleration": (self.z_acceleration, self.z_acceleration_enabled),
            "z_jerk": (self.z_jerk, self.z_jerk_enabled),
            "fan_speed_percent": (self.fan_speed, self.fan_speed_enabled),
        }.items():
            if profile.get(pkey) is not None:
                var.set(profile[pkey])
                en_var.set(True)
            else:
                en_var.set(False)

    # ======================================================================
    # File handling
    # ======================================================================
    def _browse_file(self):
        # Start in a useful directory
        initial_dir = None
        for d in [os.path.expanduser("~/Desktop"), os.path.expanduser("~/Downloads"),
                  os.path.expanduser("~/Documents")]:
            if os.path.isdir(d):
                initial_dir = d
                break

        path = filedialog.askopenfilename(
            title="Select G-code file",
            initialdir=initial_dir,
            filetypes=[("G-code files", "*.gcode *.g"), ("All files", "*.*")]
        )
        if path:
            self.gcode_path.set(path)

    # ======================================================================
    # Build config
    # ======================================================================
    def _build_config(self):
        return FuzzyConfig(
            input_file=self.gcode_path.get(),
            resolution=self.resolution.get(),
            z_min=self.z_min.get(),
            z_max=self.z_max.get(),
            connect_walls=self.connect_walls.get(),
            fuzzy_speed=self.fuzzy_speed.get() if self.fuzzy_speed_enabled.get() else None,
            run=1,
            compensate_extrusion=1 if self.compensate_extrusion.get() else 0,
            lower_surface=self.lower_surface.get(),
            top_surface=self.top_surface.get(),
            bridge_compensation_multiplier=self.bridge_comp_mult.get(),
            min_support_distance=self.min_support_dist.get(),
            z_max_feedrate=self.z_max_feedrate.get() if self.z_max_feedrate_enabled.get() else None,
            z_acceleration=self.z_acceleration.get() if self.z_acceleration_enabled.get() else None,
            z_jerk=self.z_jerk.get() if self.z_jerk_enabled.get() else None,
            fan_speed_percent=self.fan_speed.get() if self.fan_speed_enabled.get() else None,
        )

    # ======================================================================
    # Processing
    # ======================================================================
    def _dry_run(self):
        path = self.gcode_path.get().strip()
        if not path:
            messagebox.showwarning("No file", "Please select a G-code file first.")
            return
        if not os.path.isfile(path):
            messagebox.showerror("File not found", f"Cannot find:\n{path}")
            return

        self.dryrun_btn.configure(state="disabled")
        self.status_label.configure(text="Analyzing...", text_color=COLORS["text_value"])
        self.progress.set(0)

        config = self._build_config()

        def run():
            def progress_cb(pct):
                self.root.after(0, lambda p=pct: self.progress.set(p))
            processor = GCodeProcessor(config, progress_callback=progress_cb)
            success, msg, _ = processor.process_file(dry_run=True)
            def finish():
                self.dryrun_btn.configure(state="normal")
                self.progress.set(1.0)
                if success:
                    self.status_label.configure(text="Dry run complete — no files modified",
                                                text_color=COLORS["success"])
                    # Show report in a dialog
                    report_window = ctk.CTkToplevel(self.root)
                    report_window.title("Dry Run Report")
                    report_window.geometry("520x480")
                    report_window.attributes("-topmost", True)
                    report_window.configure(fg_color=COLORS["bg_dark"])

                    ctk.CTkLabel(report_window, text="Dry Run / Preview Report",
                                 font=("Segoe UI", 18, "bold"),
                                 text_color=COLORS["accent"]).pack(padx=20, pady=(16, 4))

                    text_frame = ctk.CTkTextbox(
                        report_window, fg_color=COLORS["bg_input"],
                        text_color=COLORS["text"], font=("Consolas", 12),
                        corner_radius=8, border_width=1,
                        border_color=COLORS["border"])
                    text_frame.pack(fill="both", expand=True, padx=20, pady=(4, 12))
                    text_frame.insert("1.0", msg)
                    text_frame.configure(state="disabled")

                    ctk.CTkButton(report_window, text="Close", width=100,
                                  fg_color=COLORS["accent"],
                                  hover_color=COLORS["accent_hover"],
                                  command=report_window.destroy).pack(pady=(0, 16))
                else:
                    self.status_label.configure(text=msg, text_color=COLORS["error"])
                    messagebox.showerror("Error", msg)
            self.root.after(0, finish)

        threading.Thread(target=run, daemon=True).start()

    def _process(self):
        path = self.gcode_path.get().strip()
        if not path:
            messagebox.showwarning("No file", "Please select a G-code file first.\n\n"
                                   "Click 'Browse' to pick one manually, or click 'Find Recent' "
                                   "to search your common folders.")
            return
        if not os.path.isfile(path):
            messagebox.showerror("File not found", f"Cannot find:\n{path}\n\n"
                                 "The file may have been moved or deleted. Try browsing again.")
            return

        keep_original = self.keep_original_var.get()

        if keep_original:
            base, ext = os.path.splitext(path)
            out_name = f"{os.path.basename(base)}_Fuzzyficator{ext}"
            confirm_msg = (f"Original file will be kept untouched:\n"
                           f"  {os.path.basename(path)}\n\n"
                           f"Processed copy will be saved as:\n"
                           f"  {out_name}\n\n"
                           f"in {os.path.dirname(path)}\n\nContinue?")
        else:
            confirm_msg = (f"This will OVERWRITE the G-code file:\n\n"
                           f"{os.path.basename(path)}\n"
                           f"in {os.path.dirname(path)}\n\n"
                           "The original will be lost. Continue?")

        if not messagebox.askyesno("Confirm", confirm_msg):
            return

        self.process_btn.configure(state="disabled")
        self.status_label.configure(text="Processing...", text_color=COLORS["text_value"])
        self.progress.set(0)

        config = self._build_config()

        def run():
            def progress_cb(pct):
                self.root.after(0, lambda p=pct: self.progress.set(p))
            processor = GCodeProcessor(config, progress_callback=progress_cb)
            success, msg, output_path = processor.process_file(keep_original=keep_original)
            def finish():
                self.process_btn.configure(state="normal")
                if success:
                    if keep_original and output_path:
                        msg_full = f"{msg}\n\nSaved to: {os.path.basename(output_path)}\nOriginal file unchanged."
                    else:
                        msg_full = msg
                    self.status_label.configure(text=msg, text_color=COLORS["success"])
                    self.progress.set(1.0)
                    messagebox.showinfo("Success", msg_full)
                else:
                    self.status_label.configure(text=msg, text_color=COLORS["error"])
                    messagebox.showerror("Error", msg)
            self.root.after(0, finish)

        threading.Thread(target=run, daemon=True).start()

    # ======================================================================
    # Slicer command
    # ======================================================================
    def _update_command_preview(self):
        try:
            python_path = find_python()
            script_dir = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.join(script_dir, "Fuzzyficator.py")

            parts = [f'"{python_path}" "{script_path}"']
            parts.append("-run 1")
            parts.append(f"-resolution {self.resolution.get():.2f}")
            parts.append(f"-zMin {self.z_min.get():.2f}")
            parts.append(f"-zMax {self.z_max.get():.2f}")
            parts.append(f"-connectWalls {1 if self.connect_walls.get() else 0}")
            parts.append(f"-compensateExtrusion {1 if self.compensate_extrusion.get() else 0}")
            parts.append(f"-topSurface {1 if self.top_surface.get() else 0}")
            parts.append(f"-lowerSurface {1 if self.lower_surface.get() else 0}")
            parts.append(f"-bridgeCompensationMultiplier {self.bridge_comp_mult.get():.1f}")
            parts.append(f"-minSupportDistance {self.min_support_dist.get():.2f}")
            if self.fuzzy_speed_enabled.get():
                parts.append(f"-fuzzySpeed {self.fuzzy_speed.get():.0f}")

            cmd = " ".join(parts)
            self.cmd_textbox.delete("1.0", "end")
            self.cmd_textbox.insert("1.0", cmd)
        except Exception:
            pass

    def _copy_command(self):
        cmd = self.cmd_textbox.get("1.0", "end").strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(cmd)
        self.status_label.configure(text="Command copied to clipboard!", text_color=COLORS["text_value"])

    # ======================================================================
    # Preset system
    # ======================================================================
    def _refresh_preset_list(self):
        for w in self.preset_list_frame.winfo_children():
            w.destroy()

        presets_dir = get_app_data_dir()
        presets = sorted(f[:-5] for f in os.listdir(presets_dir) if f.endswith(".json")) if os.path.isdir(presets_dir) else []

        if not presets:
            ctk.CTkLabel(self.preset_list_frame, text="No saved presets yet",
                         font=("Segoe UI", 11), text_color=COLORS["text_dim"]).pack(pady=8)
            return

        for name in presets:
            btn = ctk.CTkButton(self.preset_list_frame, text=name, anchor="w",
                                fg_color="transparent", hover_color=COLORS["border"],
                                text_color=COLORS["text"], font=("Segoe UI", 12),
                                height=28, command=lambda n=name: self.preset_name.set(n))
            btn.pack(fill="x", padx=4, pady=1)

    def _save_preset(self):
        name = self.preset_name.get().strip()
        if not name:
            messagebox.showwarning("No name", "Enter a preset name first.")
            return
        config = self._build_config()
        data = config.to_dict()
        data["_profile"] = self.printer_profile.get()
        path = os.path.join(get_app_data_dir(), f"{name}.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        self._refresh_preset_list()
        self.status_label.configure(text=f"Preset '{name}' saved.", text_color=COLORS["success"])

    def _load_preset(self):
        name = self.preset_name.get().strip()
        if not name:
            messagebox.showwarning("No name", "Select or type a preset name.")
            return
        path = os.path.join(get_app_data_dir(), f"{name}.json")
        if not os.path.isfile(path):
            messagebox.showerror("Not found", f"Preset '{name}' not found.")
            return
        with open(path, "r") as f:
            data = json.load(f)

        profile = data.pop("_profile", "custom")
        self.printer_profile.set(profile)
        self.resolution.set(data.get("resolution", 0.3))
        self.z_min.set(data.get("z_min", 0.0))
        self.z_max.set(data.get("z_max", 0.3))
        self.connect_walls.set(data.get("connect_walls", True))
        self.compensate_extrusion.set(bool(data.get("compensate_extrusion", 1)))
        self.top_surface.set(data.get("top_surface", True))
        self.lower_surface.set(data.get("lower_surface", True))
        self.bridge_comp_mult.set(data.get("bridge_compensation_multiplier", 3.0))
        self.min_support_dist.set(data.get("min_support_distance", 0.1))

        for key, var, en_var in [
            ("fuzzy_speed", self.fuzzy_speed, self.fuzzy_speed_enabled),
            ("z_max_feedrate", self.z_max_feedrate, self.z_max_feedrate_enabled),
            ("z_acceleration", self.z_acceleration, self.z_acceleration_enabled),
            ("z_jerk", self.z_jerk, self.z_jerk_enabled),
            ("fan_speed_percent", self.fan_speed, self.fan_speed_enabled),
        ]:
            val = data.get(key)
            if val is not None:
                var.set(val)
                en_var.set(True)
            else:
                en_var.set(False)

        self.status_label.configure(text=f"Preset '{name}' loaded.", text_color=COLORS["success"])

    def _delete_preset(self):
        name = self.preset_name.get().strip()
        if not name:
            return
        path = os.path.join(get_app_data_dir(), f"{name}.json")
        if os.path.isfile(path):
            if messagebox.askyesno("Delete", f"Delete preset '{name}'?"):
                os.remove(path)
                self._refresh_preset_list()
                self.status_label.configure(text=f"Preset '{name}' deleted.", text_color=COLORS["text_dim"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    app = FuzzyficatorApp()
    app.run()


if __name__ == "__main__":
    main()
