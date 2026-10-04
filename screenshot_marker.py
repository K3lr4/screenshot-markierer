#!/usr/bin/env python3
"""Small native screenshot annotation tool for circles and arrows."""

from __future__ import annotations

import math
import os
import sys
import io
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageOps


Tool = Literal["circle", "arrow", "number", "move", "rotate", "crop"]


@dataclass(frozen=True)
class Annotation:
    kind: Tool
    start: tuple[float, float]
    end: tuple[float, float]
    color: str
    width: int
    number: int | None = None
    perfect_circle: bool = False


def arrow_points(
    start: tuple[float, float],
    end: tuple[float, float],
    width: float,
) -> list[tuple[float, float]]:
    """Return a filled arrow polygon in image coordinates."""
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1:
        return []

    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    head_length = min(max(width * 4.5, 16.0), max(length * 0.48, 1.0))
    head_width = max(width * 3.2, 12.0)
    shaft_half = max(width / 2.0, 1.0)
    neck_x, neck_y = x2 - ux * head_length, y2 - uy * head_length

    return [
        (x1 + px * shaft_half, y1 + py * shaft_half),
        (neck_x + px * shaft_half, neck_y + py * shaft_half),
        (neck_x + px * head_width / 2, neck_y + py * head_width / 2),
        (x2, y2),
        (neck_x - px * head_width / 2, neck_y - py * head_width / 2),
        (neck_x - px * shaft_half, neck_y - py * shaft_half),
        (x1 - px * shaft_half, y1 - py * shaft_half),
    ]


def circle_box(
    start: tuple[float, float],
    end: tuple[float, float],
    image_size: tuple[int, int],
) -> tuple[float, float, float, float]:
    """Build a circular bounding box from a drag, clipped to the image."""
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    step_x = -1 if dx < 0 else 1
    step_y = -1 if dy < 0 else 1
    image_width, image_height = image_size
    room_x = x1 if step_x < 0 else image_width - x1 - 1
    room_y = y1 if step_y < 0 else image_height - y1 - 1
    diameter = min(max(abs(dx), abs(dy)), room_x, room_y)
    x2 = x1 + step_x * diameter
    y2 = y1 + step_y * diameter
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def ellipse_box(
    start: tuple[float, float],
    end: tuple[float, float],
    image_size: tuple[int, int],
) -> tuple[float, float, float, float]:
    """Build a freely sized ellipse bounding box, clipped to the image."""
    width, height = image_size
    x1, x2 = sorted((start[0], end[0]))
    y1, y2 = sorted((start[1], end[1]))
    return (
        min(max(x1, 0), width - 1),
        min(max(y1, 0), height - 1),
        min(max(x2, 0), width - 1),
        min(max(y2, 0), height - 1),
    )


def annotation_box(annotation: Annotation, image_size: tuple[int, int]) -> tuple[float, float, float, float]:
    """Return the visible ellipse bounds for a circle-tool annotation."""
    if annotation.perfect_circle:
        return circle_box(annotation.start, annotation.end, image_size)
    return ellipse_box(annotation.start, annotation.end, image_size)


def rotate_arrow(
    annotation: Annotation,
    angle_radians: float,
    image_size: tuple[int, int],
) -> Annotation:
    """Rotate an arrow around its midpoint and keep it within the image."""
    if annotation.kind != "arrow":
        return annotation
    center_x = (annotation.start[0] + annotation.end[0]) / 2
    center_y = (annotation.start[1] + annotation.end[1]) / 2
    cos_a, sin_a = math.cos(angle_radians), math.sin(angle_radians)

    def rotate(point: tuple[float, float]) -> tuple[float, float]:
        dx, dy = point[0] - center_x, point[1] - center_y
        return center_x + dx * cos_a - dy * sin_a, center_y + dx * sin_a + dy * cos_a

    start, end = rotate(annotation.start), rotate(annotation.end)
    width, height = image_size
    min_x, max_x = sorted((start[0], end[0]))
    min_y, max_y = sorted((start[1], end[1]))
    dx = min(max(0.0, -min_x), width - 1 - max_x)
    dy = min(max(0.0, -min_y), height - 1 - max_y)
    return replace(
        annotation,
        start=(start[0] + dx, start[1] + dy),
        end=(end[0] + dx, end[1] + dy),
    )


def crop_bounds(
    rect: tuple[float, float, float, float],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Convert a crop frame to a valid Pillow box (right/bottom exclusive)."""
    left, top, right, bottom = rect
    width, height = image_size
    x1 = max(0, min(width, math.floor(min(left, right))))
    y1 = max(0, min(height, math.floor(min(top, bottom))))
    x2 = max(0, min(width, math.ceil(max(left, right))))
    y2 = max(0, min(height, math.ceil(max(top, bottom))))
    if x2 <= x1:
        x1, x2 = max(0, min(width - 1, x1)), max(1, min(width, x1 + 1))
    if y2 <= y1:
        y1, y2 = max(0, min(height - 1, y1)), max(1, min(height, y1 + 1))
    return x1, y1, x2, y2


def window_size_for_image(
    image_size: tuple[int, int],
    screen_size: tuple[int, int],
    min_size: tuple[int, int] = (720, 500),
    chrome: tuple[int, int] = (56, 215),
    margin: tuple[int, int] = (40, 80),
) -> tuple[int, int, int, int]:
    """Return centered window geometry sized to an image and available screen."""
    image_width, image_height = image_size
    screen_width, screen_height = screen_size
    available_width = max(1, screen_width - margin[0])
    available_height = max(1, screen_height - margin[1])
    minimum_width = min(min_size[0], available_width)
    minimum_height = min(min_size[1], available_height)
    width = min(available_width, max(minimum_width, image_width + chrome[0]))
    height = min(available_height, max(minimum_height, image_height + chrome[1]))
    return width, height, max(0, (screen_width - width) // 2), max(0, (screen_height - height) // 2)


def number_marker_box(
    center: tuple[float, float],
    image_size: tuple[int, int],
    number: int,
) -> tuple[float, float, float, float]:
    """Return a number badge box whose center and radius stay inside the image."""
    image_width, image_height = image_size
    radius = min(18 + max(0, len(str(number)) - 1) * 4, image_width / 2, image_height / 2)
    cx = min(max(center[0], radius), image_width - radius)
    cy = min(max(center[1], radius), image_height - radius)
    return cx - radius, cy - radius, cx + radius, cy + radius


def marker_text_color(color: str) -> str:
    """Choose a readable number color for a hex badge background."""
    try:
        red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
    except (ValueError, IndexError):
        return "#ffffff"
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    return "#111827" if luminance > 0.58 else "#ffffff"


def next_marker_number(annotations: list[Annotation]) -> int:
    """Return the next sequential number currently unused on the canvas."""
    return max((item.number or 0 for item in annotations if item.kind == "number"), default=0) + 1


def _point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.dist(point, start)
    fraction = min(1, max(0, ((px - x1) * dx + (py - y1) * dy) / length_squared))
    return math.dist(point, (x1 + fraction * dx, y1 + fraction * dy))


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


def arrow_hit_test(
    point: tuple[float, float],
    annotation: Annotation,
    tolerance: float,
) -> bool:
    """Test a point against an arrow polygon, including a forgiving edge margin."""
    if annotation.kind != "arrow":
        return False
    polygon = arrow_points(annotation.start, annotation.end, annotation.width)
    if not polygon:
        return False
    if _point_in_polygon(point, polygon):
        return True
    return any(
        _point_segment_distance(point, polygon[index], polygon[(index + 1) % len(polygon)]) <= tolerance
        for index in range(len(polygon))
    )


def annotation_hit_test(
    point: tuple[float, float],
    annotation: Annotation,
    tolerance: float,
    image_size: tuple[int, int],
) -> bool:
    """Hit-test an arrow, circle outline, or filled numbered marker."""
    if annotation.kind == "arrow":
        return arrow_hit_test(point, annotation, tolerance)
    if annotation.kind == "number":
        box = number_marker_box(annotation.start, image_size, annotation.number or 1)
        center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        return math.dist(point, center) <= (box[2] - box[0]) / 2 + tolerance
    if annotation.kind == "circle":
        box = annotation_box(annotation, image_size)
        center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        radius_x = max((box[2] - box[0]) / 2, 0.5)
        radius_y = max((box[3] - box[1]) / 2, 0.5)
        band = tolerance + annotation.width / 2
        normalized = math.hypot((point[0] - center[0]) / radius_x, (point[1] - center[1]) / radius_y)
        distance = abs(normalized - 1) * min(radius_x, radius_y)
        return distance <= band
    return False


def move_annotation(
    annotation: Annotation,
    delta: tuple[float, float],
    image_size: tuple[int, int],
) -> Annotation:
    """Translate a marker without moving it beyond its image bounds."""
    dx, dy = delta
    width, height = image_size
    if annotation.kind == "number":
        box = number_marker_box(annotation.start, image_size, annotation.number or 1)
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        radius_x, radius_y = (box[2] - box[0]) / 2, (box[3] - box[1]) / 2
        dx = min(max(dx, radius_x - cx), width - radius_x - cx)
        dy = min(max(dy, radius_y - cy), height - radius_y - cy)
        center = (cx + dx, cy + dy)
        return replace(annotation, start=center, end=center)

    min_x, max_x = sorted((annotation.start[0], annotation.end[0]))
    min_y, max_y = sorted((annotation.start[1], annotation.end[1]))
    dx = min(max(dx, -min_x), width - 1 - max_x)
    dy = min(max(dy, -min_y), height - 1 - max_y)
    return replace(
        annotation,
        start=(annotation.start[0] + dx, annotation.start[1] + dy),
        end=(annotation.end[0] + dx, annotation.end[1] + dy),
    )


def render_annotations(image: Image.Image, annotations: list[Annotation]) -> Image.Image:
    """Render vector annotations onto a copy of an image at full resolution."""
    output = image.convert("RGBA").copy()
    draw = ImageDraw.Draw(output)
    for annotation in annotations:
        if annotation.kind == "circle":
            box = annotation_box(annotation, image.size)
            draw.ellipse(box, outline=annotation.color, width=annotation.width)
        elif annotation.kind == "number":
            number = annotation.number or 1
            box = number_marker_box(annotation.start, image.size, number)
            radius = (box[2] - box[0]) / 2
            draw.ellipse(box, fill=annotation.color, outline="#ffffff", width=max(1, round(radius * 0.12)))
            font_size = max(10, min(24, round(radius * 1.05)))
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except OSError:
                font = ImageFont.load_default()
            draw.text(
                ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2),
                str(number),
                fill=marker_text_color(annotation.color),
                font=font,
                anchor="mm",
                stroke_width=max(0, font_size // 12),
                stroke_fill="#111827" if marker_text_color(annotation.color) == "#ffffff" else "#ffffff",
            )
        else:
            points = arrow_points(annotation.start, annotation.end, annotation.width)
            if points:
                draw.polygon(points, fill=annotation.color)
    return output


def render_selection(
    image: Image.Image,
    annotations: list[Annotation],
    crop_rect: tuple[float, float, float, float] | None,
) -> Image.Image:
    """Render all annotation layers, then return the selected region if any."""
    output = render_annotations(image, annotations)
    if crop_rect is not None:
        output = output.crop(crop_bounds(crop_rect, image.size))
    return output


def image_to_ppm_bytes(image: Image.Image) -> bytes:
    """Convert a Pillow image to binary PPM data accepted by Tk PhotoImage."""
    stream = io.BytesIO()
    image.convert("RGB").save(stream, format="PPM")
    return stream.getvalue()


class ScreenshotMarker:
    COLORS = ("#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#a855f7", "#111827")
    IMAGE_TYPES = [
        ("Bilder", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"),
        ("Alle Dateien", "*.*"),
    ]

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Screenshot-Markierer")
        self.root.geometry("1100x760")
        self.root.minsize(720, 500)

        self.image: Image.Image | None = None
        self.image_path: Path | None = None
        self.crop_rect: tuple[float, float, float, float] | None = None
        self.crop_drag_kind: str | None = None
        self.crop_drag_start: tuple[float, float] | None = None
        self.crop_fixed_point: tuple[float, float] | None = None
        self.crop_original_rect: tuple[float, float, float, float] | None = None
        self.annotations: list[Annotation] = []
        self.undo_stack: list[list[Annotation]] = []
        self.redo_stack: list[list[Annotation]] = []
        self.move_index: int | None = None
        self.move_start: tuple[float, float] | None = None
        self.move_original_annotations: list[Annotation] | None = None
        self.rotate_index: int | None = None
        self.rotate_center: tuple[float, float] | None = None
        self.rotate_pointer_angle: float | None = None
        self.rotate_original_annotations: list[Annotation] | None = None
        self.tool: Tool = "circle"
        self.color = self.COLORS[0]
        self.width = tk.IntVar(value=8)
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.start_image: tuple[float, float] | None = None
        self.preview_id: int | None = None
        self.tk_image: tk.PhotoImage | None = None
        self.dirty = False

        self._configure_style()
        self._build_ui()
        self._bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Toolbar.TFrame", background="#f3f4f6")
        style.configure("Title.TLabel", background="#f3f4f6", font=("TkDefaultFont", 10, "bold"))
        style.configure("File.TButton", padding=(12, 8))
        style.configure("Tool.TButton", padding=(3, 6))
        style.configure("ActiveTool.TButton", padding=(3, 6), background="#dbeafe")

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, style="Toolbar.TFrame", padding=10)
        toolbar.pack(fill="x")

        tools_row = ttk.Frame(toolbar, style="Toolbar.TFrame")
        tools_row.pack(fill="x")
        controls_row = ttk.Frame(toolbar, style="Toolbar.TFrame")
        controls_row.pack(fill="x", pady=(6, 0))

        ttk.Button(tools_row, text="Öffnen", command=self.open_image, style="File.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(tools_row, text="Speichern unter", command=self.save_as, style="File.TButton").pack(side="left", padx=(0, 12))

        self.circle_button = ttk.Button(tools_row, text="○ Kreis", command=lambda: self.set_tool("circle"), style="ActiveTool.TButton")
        self.circle_button.pack(side="left", padx=3)
        self.arrow_button = ttk.Button(tools_row, text="➜ Pfeil", command=lambda: self.set_tool("arrow"), style="Tool.TButton")
        self.arrow_button.pack(side="left", padx=3)
        self.number_button = ttk.Button(tools_row, text="① Nummer", command=lambda: self.set_tool("number"), style="Tool.TButton")
        self.number_button.pack(side="left", padx=3)
        self.move_button = ttk.Button(tools_row, text="↔ Bewegen", command=lambda: self.set_tool("move"), style="Tool.TButton")
        self.move_button.pack(side="left", padx=3)
        self.rotate_button = ttk.Button(tools_row, text="⤾ Drehen", command=lambda: self.set_tool("rotate"), style="Tool.TButton")
        self.rotate_button.pack(side="left", padx=3)
        self.crop_button = ttk.Button(tools_row, text="▢ Zuschneiden", command=lambda: self.set_tool("crop"), style="Tool.TButton")
        self.crop_button.pack(side="left", padx=(3, 4))
        self.cut_button = ttk.Button(tools_row, text="✂ Cut", command=self.cut_to_selection, style="Tool.TButton")
        self.cut_button.pack(side="left", padx=3)
        self.cut_button.pack_forget()

        ttk.Label(controls_row, text="Farbe", style="Title.TLabel").pack(side="left", padx=(0, 6))
        self.color_buttons: list[tk.Button] = []
        for color in self.COLORS:
            button = tk.Button(
                controls_row,
                bg=color,
                activebackground=color,
                width=2,
                height=1,
                relief="sunken" if color == self.color else "flat",
                bd=2,
                command=lambda selected=color: self.set_color(selected),
                cursor="hand2",
            )
            button.pack(side="left", padx=2)
            self.color_buttons.append(button)
        ttk.Button(controls_row, text="…", width=3, command=self.choose_color).pack(side="left", padx=(3, 14))

        ttk.Label(controls_row, text="Stärke", style="Title.TLabel").pack(side="left", padx=(0, 5))
        ttk.Spinbox(controls_row, from_=2, to=30, width=4, textvariable=self.width).pack(side="left")

        actions = ttk.Frame(self.root, padding=(10, 6))
        actions.pack(fill="x")
        self.paste_button = ttk.Button(actions, text="Aus Zwischenablage einfügen", command=self.paste_from_clipboard)
        self.paste_button.pack(side="left", padx=(0, 5))
        self.copy_button = ttk.Button(actions, text="In Zwischenablage kopieren", command=self.copy_to_clipboard, state="disabled")
        self.copy_button.pack(side="left", padx=(0, 10))
        self.undo_button = ttk.Button(actions, text="↶ Rückgängig", command=self.undo, state="disabled")
        self.undo_button.pack(side="left", padx=(0, 5))
        self.redo_button = ttk.Button(actions, text="↷ Wiederholen", command=self.redo, state="disabled")
        self.redo_button.pack(side="left", padx=5)
        self.clear_button = ttk.Button(actions, text="Alle Markierungen löschen", command=self.clear_annotations, state="disabled")
        self.clear_button.pack(side="left", padx=5)
        self.status = ttk.Label(actions, text="Öffne einen Screenshot, um zu beginnen.")
        self.status.pack(side="right")

        canvas_frame = ttk.Frame(self.root)
        canvas_frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(canvas_frame, bg="#25282d", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Motion>", self.on_canvas_motion)
        self.canvas.bind("<Configure>", lambda _event: self.redraw())

        self.empty_text = self.canvas.create_text(
            0,
            0,
            text="Bild öffnen oder aus der Zwischenablage einfügen\n\nPNG · JPG · WEBP · BMP · TIFF",
            fill="#d1d5db",
            font=("TkDefaultFont", 16),
            justify="center",
        )

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _event: self.open_image())
        self.root.bind("<Control-v>", lambda _event: self.paste_from_clipboard())
        self.root.bind("<Control-c>", lambda _event: self.copy_to_clipboard())
        self.root.bind("<Control-Shift-S>", lambda _event: self.save_as())
        self.root.bind("<Control-z>", lambda _event: self.undo())
        self.root.bind("<Control-y>", lambda _event: self.redo())
        self.root.bind("<Control-Shift-Z>", lambda _event: self.redo())
        self.root.bind("<Key-1>", lambda _event: self.set_tool("circle"))
        self.root.bind("<Key-2>", lambda _event: self.set_tool("arrow"))
        self.root.bind("<Key-3>", lambda _event: self.set_tool("crop"))
        self.root.bind("<Key-4>", lambda _event: self.set_tool("number"))
        self.root.bind("<Key-v>", lambda _event: self.set_tool("move"))
        self.root.bind("<Key-r>", lambda _event: self.set_tool("rotate"))

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool
        for name, button in (
            ("circle", self.circle_button),
            ("arrow", self.arrow_button),
            ("number", self.number_button),
            ("move", self.move_button),
            ("rotate", self.rotate_button),
            ("crop", self.crop_button),
        ):
            button.configure(style="ActiveTool.TButton" if tool == name else "Tool.TButton")
        if tool == "circle":
            text = "Ellipse frei ziehen · Umschalt+Ziehen auf Markierung verschiebt, im Leeren wird der Kreis rund."
        elif tool == "arrow":
            text = "Pfeil: vom Anfang zur Spitze ziehen · Strg+Ziehen auf einem Pfeil dreht ihn."
        elif tool == "number":
            text = "Nummer: klicken, um den nächsten nummerierten Marker zu setzen."
        elif tool == "move":
            text = "Bewegen: Markierung ziehen · Umschalt+Ziehen funktioniert in jedem Werkzeug."
        elif tool == "rotate":
            text = "Drehen: Pfeil um seine Mitte ziehen · Strg+Ziehen funktioniert in jedem Werkzeug."
        else:
            text = "Zuschnitt: Rahmen ziehen, an Ecken ändern oder innen verschieben."
        self.status.configure(text=text)
        self.canvas.configure(cursor="crosshair")
        self._update_cut_button_visibility()

    def _update_cut_button_visibility(self) -> None:
        if not hasattr(self, "cut_button"):
            return
        show = self.tool == "crop" and self.image is not None and self.crop_rect is not None
        if show:
            left, top, right, bottom = crop_bounds(self.crop_rect, self.image.size)
            show = right - left >= 2 and bottom - top >= 2
        is_visible = bool(self.cut_button.winfo_manager())
        if show and not is_visible:
            self.cut_button.pack(side="left", padx=3)
        elif not show and is_visible:
            self.cut_button.pack_forget()

    def set_color(self, color: str) -> None:
        self.color = color
        for button in self.color_buttons:
            button.configure(relief="sunken" if button.cget("bg") == color else "flat")

    def choose_color(self) -> None:
        selected = colorchooser.askcolor(self.color, title="Farbe auswählen", parent=self.root)[1]
        if selected:
            self.set_color(selected)

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Ungespeicherte Änderungen",
            "Möchtest Du die Markierungen vor dem Fortfahren speichern?",
            parent=self.root,
        )
        if answer is None:
            return False
        if answer:
            return self.save_as()
        return True

    def open_image(self, path: str | None = None) -> None:
        if not self._confirm_discard():
            return
        chosen = path or self._choose_image_file()
        if not chosen:
            return
        try:
            loaded = Image.open(chosen)
            loaded.load()
            self.image = ImageOps.exif_transpose(loaded).convert("RGBA")
        except Exception as exc:
            messagebox.showerror("Bild konnte nicht geöffnet werden", str(exc), parent=self.root)
            return
        self.image_path = Path(chosen)
        self.crop_rect = None
        self.crop_drag_kind = None
        self.annotations.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.dirty = False
        self.root.title(f"Screenshot-Markierer — {self.image_path.name}")
        self.status.configure(text=f"{self.image.width} × {self.image.height} px")
        self._update_actions()
        self.redraw()

    def _gtk_clipboard(self):
        """Return GTK's desktop clipboard and its image-related classes."""
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

        initialized = Gtk.init_check()
        if isinstance(initialized, tuple):
            initialized = initialized[0]
        if not initialized:
            raise RuntimeError("Die GTK-Zwischenablage konnte nicht initialisiert werden.")
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("Es wurde kein grafischer Desktop gefunden.")
        clipboard = Gtk.Clipboard.get_for_display(display, Gdk.SELECTION_CLIPBOARD)
        return clipboard, GdkPixbuf, GLib

    def paste_from_clipboard(self) -> None:
        if not self._confirm_discard():
            return
        try:
            clipboard, _gdk_pixbuf, _glib = self._gtk_clipboard()
            pixbuf = clipboard.wait_for_image()
            if pixbuf is None:
                messagebox.showinfo(
                    "Kein Bild in der Zwischenablage",
                    "Kopiere zuerst einen Screenshot oder ein Bild und versuche es erneut.",
                    parent=self.root,
                )
                return
            width, height = pixbuf.get_width(), pixbuf.get_height()
            mode = "RGBA" if pixbuf.get_has_alpha() else "RGB"
            pixels = pixbuf.get_pixels()
            if isinstance(pixels, str):
                pixels = pixels.encode("latin-1")
            loaded = Image.frombytes(
                mode,
                (width, height),
                bytes(pixels),
                "raw",
                mode,
                pixbuf.get_rowstride(),
                1,
            ).convert("RGBA")
        except Exception as exc:
            messagebox.showerror("Zwischenablage konnte nicht gelesen werden", str(exc), parent=self.root)
            return

        self.image = loaded
        self.image_path = None
        self.crop_rect = None
        self.crop_drag_kind = None
        self.annotations.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.dirty = False
        self.root.title("Screenshot-Markierer — Zwischenablage")
        self.status.configure(text=f"Zwischenablage: {width} × {height} px")
        self._update_actions()
        self._resize_window_to_image()
        self.redraw()

    def _resize_window_to_image(self) -> None:
        if self.image is None:
            return
        try:
            self.root.state("normal")
        except tk.TclError:
            pass
        geometry = window_size_for_image(
            self.image.size,
            (self.root.winfo_screenwidth(), self.root.winfo_screenheight()),
        )
        width, height, x, y = geometry
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def copy_to_clipboard(self) -> None:
        if self.image is None:
            return
        try:
            clipboard, gdk_pixbuf, glib = self._gtk_clipboard()
            output = render_selection(self.image, self.annotations, self.crop_rect).convert("RGBA")
            pixel_bytes = glib.Bytes.new(output.tobytes())
            pixbuf = gdk_pixbuf.Pixbuf.new_from_bytes(
                pixel_bytes,
                gdk_pixbuf.Colorspace.RGB,
                True,
                8,
                output.width,
                output.height,
                output.width * 4,
            )
            clipboard.set_image(pixbuf)
            clipboard.store()
        except Exception as exc:
            messagebox.showerror("Kopieren fehlgeschlagen", str(exc), parent=self.root)
            return
        if self.crop_rect is None:
            self.status.configure(text="Markiertes Bild in die Zwischenablage kopiert")
        else:
            self.status.configure(text=f"Ausschnitt {output.width} × {output.height} px kopiert")

    def cut_to_selection(self) -> None:
        """Commit the current crop, including its rendered annotation layers."""
        if self.image is None or self.crop_rect is None:
            return
        left, top, right, bottom = crop_bounds(self.crop_rect, self.image.size)
        if right - left < 2 or bottom - top < 2:
            return
        output = render_selection(self.image, self.annotations, self.crop_rect).convert("RGBA")
        self.image = output
        self.annotations.clear()
        self.crop_rect = None
        self.crop_drag_kind = None
        self.crop_drag_start = None
        self.crop_fixed_point = None
        self.crop_original_rect = None
        # Annotation snapshots use the old image coordinate space; clear them
        # so Undo cannot restore markers at stale coordinates after the cut.
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.dirty = True
        self._update_actions()
        self._resize_window_to_image()
        self.redraw()
        self.status.configure(text=f"Zugeschnitten: {self.image.width} × {self.image.height} px")

    def _view_transform(self) -> None:
        if self.image is None:
            return
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        margin = 28
        self.zoom = min((cw - margin * 2) / self.image.width, (ch - margin * 2) / self.image.height, 1.0)
        self.zoom = max(self.zoom, 0.02)
        shown_w = self.image.width * self.zoom
        shown_h = self.image.height * self.zoom
        self.offset_x = (cw - shown_w) / 2
        self.offset_y = (ch - shown_h) / 2

    def redraw(self) -> None:
        self._update_cut_button_visibility()
        self.canvas.delete("all")
        if self.image is None:
            self.empty_text = self.canvas.create_text(
                self.canvas.winfo_width() / 2,
                self.canvas.winfo_height() / 2,
                text="Bild öffnen oder aus der Zwischenablage einfügen\n\nPNG · JPG · WEBP · BMP · TIFF",
                fill="#d1d5db",
                font=("TkDefaultFont", 16),
                justify="center",
            )
            return

        self._view_transform()
        shown_size = (
            max(1, round(self.image.width * self.zoom)),
            max(1, round(self.image.height * self.zoom)),
        )
        preview = self.image.resize(shown_size, Image.Resampling.LANCZOS)
        # Use Tk's native PPM loader. This keeps the app independent from the
        # separately packaged PIL.ImageTk bridge on Debian/Ubuntu systems.
        self.tk_image = tk.PhotoImage(data=image_to_ppm_bytes(preview), format="PPM")
        self.canvas.create_image(self.offset_x, self.offset_y, image=self.tk_image, anchor="nw")
        for annotation in self.annotations:
            self._draw_canvas_annotation(annotation)
        if self.crop_rect is not None:
            self._draw_crop_overlay()

    def _to_canvas(self, point: tuple[float, float]) -> tuple[float, float]:
        return self.offset_x + point[0] * self.zoom, self.offset_y + point[1] * self.zoom

    def _to_image(self, x: float, y: float, clamp: bool = True) -> tuple[float, float] | None:
        if self.image is None:
            return None
        ix = (x - self.offset_x) / self.zoom
        iy = (y - self.offset_y) / self.zoom
        if clamp:
            ix = min(max(ix, 0), self.image.width - 1)
            iy = min(max(iy, 0), self.image.height - 1)
        elif not (0 <= ix < self.image.width and 0 <= iy < self.image.height):
            return None
        return ix, iy

    def _to_image_edge(self, x: float, y: float, clamp: bool = False) -> tuple[float, float] | None:
        if self.image is None:
            return None
        ix = (x - self.offset_x) / self.zoom
        iy = (y - self.offset_y) / self.zoom
        if clamp:
            ix = min(max(ix, 0), self.image.width)
            iy = min(max(iy, 0), self.image.height)
        elif not (0 <= ix <= self.image.width and 0 <= iy <= self.image.height):
            return None
        return ix, iy

    def _crop_handles(self, rect: tuple[float, float, float, float]) -> dict[str, tuple[float, float]]:
        left, top, right, bottom = rect
        return {
            "nw": (left, top),
            "ne": (right, top),
            "se": (right, bottom),
            "sw": (left, bottom),
        }

    def _draw_crop_overlay(self) -> None:
        if self.image is None or self.crop_rect is None:
            return
        image_left, image_top = self.offset_x, self.offset_y
        image_right = image_left + self.image.width * self.zoom
        image_bottom = image_top + self.image.height * self.zoom
        top_left, bottom_right = (self._to_canvas(point) for point in (
            (self.crop_rect[0], self.crop_rect[1]),
            (self.crop_rect[2], self.crop_rect[3]),
        ))
        left, top = top_left
        right, bottom = bottom_right
        shade = {"fill": "#000000", "stipple": "gray50", "outline": ""}
        if top > image_top:
            self.canvas.create_rectangle(image_left, image_top, image_right, top, **shade)
        if bottom < image_bottom:
            self.canvas.create_rectangle(image_left, bottom, image_right, image_bottom, **shade)
        if left > image_left:
            self.canvas.create_rectangle(image_left, top, left, bottom, **shade)
        if right < image_right:
            self.canvas.create_rectangle(right, top, image_right, bottom, **shade)

        self.canvas.create_rectangle(left, top, right, bottom, outline="#111827", width=4)
        self.canvas.create_rectangle(left, top, right, bottom, outline="#ffffff", width=2)
        for point in self._crop_handles(self.crop_rect).values():
            x, y = self._to_canvas(point)
            self.canvas.create_rectangle(x - 7, y - 7, x + 7, y + 7, fill="#ffffff", outline="#2563eb", width=2)

    def _crop_press(self, event: tk.Event) -> None:
        point = self._to_image_edge(event.x, event.y)
        if point is None:
            self.crop_drag_kind = None
            return
        self.crop_original_rect = self.crop_rect
        self.crop_drag_start = point
        self.crop_fixed_point = None
        if self.crop_rect is not None:
            handles = self._crop_handles(self.crop_rect)
            canvas_handles = {name: self._to_canvas(pos) for name, pos in handles.items()}
            for name, pos in canvas_handles.items():
                if math.dist((event.x, event.y), pos) <= 11:
                    opposite = {"nw": "se", "ne": "sw", "se": "nw", "sw": "ne"}[name]
                    self.crop_fixed_point = handles[opposite]
                    self.crop_drag_kind = "resize"
                    return
            left, top, right, bottom = self.crop_rect
            if left <= point[0] <= right and top <= point[1] <= bottom:
                self.crop_drag_kind = "move"
                return
        self.crop_drag_kind = "new"
        self.crop_rect = (point[0], point[1], point[0], point[1])
        self.redraw()

    def _crop_drag(self, event: tk.Event) -> None:
        if self.crop_drag_kind is None or self.crop_drag_start is None or self.image is None:
            return
        point = self._to_image_edge(event.x, event.y, clamp=True)
        if point is None:
            return
        if self.crop_drag_kind == "move" and self.crop_original_rect is not None:
            left, top, right, bottom = self.crop_original_rect
            dx = point[0] - self.crop_drag_start[0]
            dy = point[1] - self.crop_drag_start[1]
            dx = min(max(dx, -left), self.image.width - right)
            dy = min(max(dy, -top), self.image.height - bottom)
            self.crop_rect = (left + dx, top + dy, right + dx, bottom + dy)
        elif self.crop_drag_kind == "resize" and self.crop_fixed_point is not None:
            fx, fy = self.crop_fixed_point
            self.crop_rect = (min(fx, point[0]), min(fy, point[1]), max(fx, point[0]), max(fy, point[1]))
        else:
            sx, sy = self.crop_drag_start
            self.crop_rect = (min(sx, point[0]), min(sy, point[1]), max(sx, point[0]), max(sy, point[1]))
        self.redraw()

    def _crop_release(self, event: tk.Event) -> None:
        if self.crop_drag_kind is None:
            return
        self._crop_drag(event)
        if self.crop_rect is not None:
            left, top, right, bottom = self.crop_rect
            if right - left < 2 or bottom - top < 2:
                self.crop_rect = self.crop_original_rect
        self.crop_drag_kind = None
        self.crop_drag_start = None
        self.crop_fixed_point = None
        self.crop_original_rect = None
        if self.crop_rect is not None and self.image is not None:
            x1, y1, x2, y2 = crop_bounds(self.crop_rect, self.image.size)
            self.status.configure(text=f"Zuschnitt: {x2 - x1} × {y2 - y1} px · Ecken ziehen, innen verschieben")
        self.redraw()

    def on_canvas_motion(self, event: tk.Event) -> None:
        if self.tool == "move":
            point = self._to_image(event.x, event.y, clamp=False)
            cursor = "fleur" if point is not None and self._annotation_index_at(point) is not None else "crosshair"
            self.canvas.configure(cursor=cursor)
            return
        if self.tool != "crop" or self.crop_rect is None:
            return
        handles = self._crop_handles(self.crop_rect)
        if any(math.dist((event.x, event.y), self._to_canvas(point)) <= 11 for point in handles.values()):
            self.canvas.configure(cursor="hand2")
            return
        point = self._to_image_edge(event.x, event.y)
        left, top, right, bottom = self.crop_rect
        if point is not None and left <= point[0] <= right and top <= point[1] <= bottom:
            self.canvas.configure(cursor="fleur")
        else:
            self.canvas.configure(cursor="crosshair")

    def _draw_canvas_annotation(self, annotation: Annotation, tag: str | None = None) -> int | None:
        start = self._to_canvas(annotation.start)
        end = self._to_canvas(annotation.end)
        scaled_width = max(2, round(annotation.width * self.zoom))
        tags = (tag,) if tag else ()
        if annotation.kind == "circle":
            x1, y1, x2, y2 = annotation_box(annotation, self.image.size)
            start, end = self._to_canvas((x1, y1)), self._to_canvas((x2, y2))
            return self.canvas.create_oval(
                start[0], start[1], end[0], end[1],
                outline=annotation.color,
                width=scaled_width,
                tags=tags,
            )
        if annotation.kind == "number":
            number = annotation.number or 1
            box = number_marker_box(annotation.start, self.image.size, number)
            center = self._to_canvas(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2))
            shown_radius = max(9, (box[2] - box[0]) * self.zoom / 2)
            left, top = center[0] - shown_radius, center[1] - shown_radius
            right, bottom = center[0] + shown_radius, center[1] + shown_radius
            self.canvas.create_oval(
                left, top, right, bottom,
                fill=annotation.color,
                outline="#ffffff",
                width=max(1, round(2 * self.zoom)),
                tags=tags,
            )
            return self.canvas.create_text(
                (left + right) / 2,
                (top + bottom) / 2,
                text=str(number),
                fill=marker_text_color(annotation.color),
                font=("TkDefaultFont", max(8, round(21 * self.zoom)), "bold"),
                tags=tags,
            )
        return self.canvas.create_line(
            start[0], start[1], end[0], end[1],
            fill=annotation.color,
            width=scaled_width,
            arrow="last",
            arrowshape=(max(12, scaled_width * 5), max(14, scaled_width * 6), max(5, scaled_width * 2)),
            capstyle="round",
            tags=tags,
        )

    def _annotation_index_at(self, point: tuple[float, float]) -> int | None:
        if self.image is None:
            return None
        tolerance = 10 / max(self.zoom, 0.02)
        for index in range(len(self.annotations) - 1, -1, -1):
            if annotation_hit_test(point, self.annotations[index], tolerance, self.image.size):
                return index
        return None

    def _arrow_index_at(self, point: tuple[float, float]) -> int | None:
        if self.image is None:
            return None
        tolerance = 10 / max(self.zoom, 0.02)
        for index in range(len(self.annotations) - 1, -1, -1):
            annotation = self.annotations[index]
            if annotation.kind == "arrow" and arrow_hit_test(point, annotation, tolerance):
                return index
        return None

    def _begin_annotation_move(self, event: tk.Event) -> None:
        point = self._to_image(event.x, event.y, clamp=False)
        if point is None:
            return
        index = self._annotation_index_at(point)
        if index is None:
            self.status.configure(text="Keine Markierung an dieser Stelle · Markierung anklicken und ziehen")
            return
        self.move_index = index
        self.move_start = point
        self.move_original_annotations = self.annotations.copy()

    def _drag_annotation_move(self, event: tk.Event) -> None:
        if self.move_index is None or self.move_start is None or self.move_original_annotations is None:
            return
        if self.image is None:
            return
        point = self._to_image(event.x, event.y)
        if point is None:
            return
        original = self.move_original_annotations[self.move_index]
        self.annotations[self.move_index] = move_annotation(
            original,
            (point[0] - self.move_start[0], point[1] - self.move_start[1]),
            self.image.size,
        )
        self.redraw()

    def _finish_annotation_move(self, event: tk.Event) -> None:
        if self.move_index is None or self.move_original_annotations is None:
            return
        self._drag_annotation_move(event)
        original = self.move_original_annotations
        if self.annotations != original:
            self.undo_stack.append(original)
            if len(self.undo_stack) > 100:
                del self.undo_stack[0]
            self.redo_stack.clear()
            self.dirty = True
            self.status.configure(text="Markierung verschoben")
        self.move_index = None
        self.move_start = None
        self.move_original_annotations = None
        self._update_actions()
        self.redraw()

    def _begin_arrow_rotate(self, event: tk.Event) -> None:
        point = self._to_image(event.x, event.y, clamp=False)
        if point is None or self.image is None:
            return
        index = self._arrow_index_at(point)
        if index is None:
            self.status.configure(text="Kein Pfeil an dieser Stelle · Pfeil anklicken und um seine Mitte drehen")
            return
        annotation = self.annotations[index]
        center = (
            (annotation.start[0] + annotation.end[0]) / 2,
            (annotation.start[1] + annotation.end[1]) / 2,
        )
        pointer_vector = (point[0] - center[0], point[1] - center[1])
        if math.hypot(*pointer_vector) < 2:
            pointer_angle = math.atan2(annotation.end[1] - annotation.start[1], annotation.end[0] - annotation.start[0])
        else:
            pointer_angle = math.atan2(pointer_vector[1], pointer_vector[0])
        self.rotate_index = index
        self.rotate_center = center
        self.rotate_pointer_angle = pointer_angle
        self.rotate_original_annotations = self.annotations.copy()

    def _drag_arrow_rotate(self, event: tk.Event) -> None:
        if (self.rotate_index is None or self.rotate_center is None or self.rotate_pointer_angle is None
                or self.rotate_original_annotations is None or self.image is None):
            return
        point = self._to_image(event.x, event.y)
        if point is None:
            return
        original = self.rotate_original_annotations[self.rotate_index]
        vector = (point[0] - self.rotate_center[0], point[1] - self.rotate_center[1])
        if math.hypot(*vector) < 2:
            return
        pointer_angle = math.atan2(vector[1], vector[0])
        delta = math.atan2(math.sin(pointer_angle - self.rotate_pointer_angle), math.cos(pointer_angle - self.rotate_pointer_angle))
        self.annotations[self.rotate_index] = rotate_arrow(original, delta, self.image.size)
        self.redraw()

    def _finish_arrow_rotate(self, event: tk.Event) -> None:
        if self.rotate_index is None or self.rotate_original_annotations is None:
            return
        self._drag_arrow_rotate(event)
        original = self.rotate_original_annotations
        if self.annotations != original:
            self.undo_stack.append(original)
            if len(self.undo_stack) > 100:
                del self.undo_stack[0]
            self.redo_stack.clear()
            self.dirty = True
            self.status.configure(text="Pfeil gedreht")
        self.rotate_index = None
        self.rotate_center = None
        self.rotate_pointer_angle = None
        self.rotate_original_annotations = None
        self._update_actions()
        self.redraw()

    def _push_undo_state(self) -> None:
        self.undo_stack.append(self.annotations.copy())
        if len(self.undo_stack) > 100:
            del self.undo_stack[0]
        self.redo_stack.clear()

    def on_press(self, event: tk.Event) -> None:
        if self.image is None:
            self.open_image()
            return
        modifier_state = getattr(event, "state", 0)
        if modifier_state & 0x0004:
            self._begin_arrow_rotate(event)
            if self.rotate_index is not None:
                return
        if modifier_state & 0x0001:
            self._begin_annotation_move(event)
            if self.move_index is not None:
                return
        if self.tool == "crop":
            self._crop_press(event)
            return
        if self.tool == "move":
            self._begin_annotation_move(event)
            return
        if self.tool == "rotate":
            self._begin_arrow_rotate(event)
            return
        self.start_image = self._to_image(event.x, event.y, clamp=False)

    def on_drag(self, event: tk.Event) -> None:
        if self.crop_drag_kind is not None:
            self._crop_drag(event)
            return
        if self.move_index is not None:
            self._drag_annotation_move(event)
            return
        if self.rotate_index is not None:
            self._drag_arrow_rotate(event)
            return
        if self.tool == "number":
            return
        if self.start_image is None:
            return
        end = self._to_image(event.x, event.y)
        if end is None:
            return
        self.canvas.delete("preview")
        annotation = Annotation(
            self.tool, self.start_image, end, self.color, max(2, int(self.width.get())),
            perfect_circle=self.tool == "circle" and bool(getattr(event, "state", 0) & 0x0001),
        )
        self.preview_id = self._draw_canvas_annotation(annotation, "preview")

    def on_release(self, event: tk.Event) -> None:
        if self.crop_drag_kind is not None:
            self._crop_release(event)
            return
        if self.move_index is not None:
            self._finish_annotation_move(event)
            return
        if self.rotate_index is not None:
            self._finish_arrow_rotate(event)
            return
        if self.start_image is None:
            return
        end = self._to_image(event.x, event.y)
        start = self.start_image
        self.start_image = None
        self.canvas.delete("preview")
        self.preview_id = None
        if end is None:
            return
        drag_distance = math.dist(start, end)
        if self.tool == "number":
            if drag_distance > 5 / self.zoom:
                return
        elif drag_distance < 3 / self.zoom:
            return
        try:
            width = max(2, min(30, int(self.width.get())))
        except (ValueError, tk.TclError):
            width = 8
            self.width.set(width)
        if self.tool == "number":
            number = next_marker_number(self.annotations)
            self._push_undo_state()
            self.annotations.append(Annotation("number", start, start, self.color, width, number))
        elif self.tool in {"circle", "arrow"}:
            self._push_undo_state()
            self.annotations.append(Annotation(
                self.tool, start, end, self.color, width,
                perfect_circle=self.tool == "circle" and bool(getattr(event, "state", 0) & 0x0001),
            ))
        else:
            return
        self.dirty = True
        self._update_actions()
        self.redraw()

    def undo(self) -> None:
        if not self.undo_stack:
            return
        self.redo_stack.append(self.annotations.copy())
        self.annotations = self.undo_stack.pop()
        self.dirty = True
        self._update_actions()
        self.redraw()

    def redo(self) -> None:
        if not self.redo_stack:
            return
        self.undo_stack.append(self.annotations.copy())
        self.annotations = self.redo_stack.pop()
        self.dirty = True
        self._update_actions()
        self.redraw()

    def clear_annotations(self) -> None:
        if not self.annotations:
            return
        if messagebox.askyesno("Markierungen löschen", "Alle Markierungen aus diesem Bild löschen?", parent=self.root):
            self._push_undo_state()
            self.annotations.clear()
            self.dirty = True
            self._update_actions()
            self.redraw()

    def _update_actions(self) -> None:
        self.copy_button.configure(state="normal" if self.image is not None else "disabled")
        self.undo_button.configure(state="normal" if self.undo_stack else "disabled")
        self.redo_button.configure(state="normal" if self.redo_stack else "disabled")
        self.clear_button.configure(state="normal" if self.annotations else "disabled")

    def save_as(self) -> bool:
        if self.image is None:
            messagebox.showinfo("Kein Bild geöffnet", "Öffne zuerst einen Screenshot.", parent=self.root)
            return False
        default_name = f"{self.image_path.stem}-markiert.png" if self.image_path else "screenshot-markiert.png"
        target = self._choose_output_file(default_name)
        if not target:
            return False
        if not Path(target).suffix:
            target = f"{target}.png"
        try:
            output = render_annotations(self.image, self.annotations)
            suffix = Path(target).suffix.lower()
            if suffix in {".jpg", ".jpeg"}:
                output.convert("RGB").save(target, quality=95)
            else:
                output.save(target)
        except Exception as exc:
            messagebox.showerror("Speichern fehlgeschlagen", str(exc), parent=self.root)
            return False
        self.dirty = False
        self.status.configure(text=f"Gespeichert: {Path(target).name}")
        return True

    def _run_zenity(self, args: list[str]) -> str | None:
        """Show a GTK file chooser so users get desktop previews and sorting."""
        zenity = shutil.which("zenity")
        if zenity is None:
            return None
        try:
            result = subprocess.run(
                [zenity, "--file-selection", "--modal", *args],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            messagebox.showerror("Dateiauswahl fehlgeschlagen", str(exc), parent=self.root)
            return None
        if result.returncode == 1:
            return None
        if result.returncode != 0:
            details = result.stderr.strip() or f"Zenity wurde mit Status {result.returncode} beendet."
            messagebox.showerror("Dateiauswahl fehlgeschlagen", details, parent=self.root)
            return None
        return result.stdout.rstrip("\r\n") or None

    def _choose_flatpak_file(
        self,
        title: str,
        action: str,
        initial_path: Path | None,
        default_name: str | None = None,
        filters: list[tuple[str, tuple[str, ...]]] | None = None,
    ) -> str | None:
        """Use GTK's native chooser so Flatpak routes file access through portals."""
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        initialized = Gtk.init_check()
        if isinstance(initialized, tuple):
            initialized = initialized[0]
        if not initialized:
            raise RuntimeError("Die GTK-Dateiauswahl konnte nicht initialisiert werden.")

        chooser_action = {
            "open": Gtk.FileChooserAction.OPEN,
            "save": Gtk.FileChooserAction.SAVE,
        }[action]
        accept_label = "Öffnen" if action == "open" else "Speichern"
        dialog = Gtk.FileChooserNative.new(title, None, chooser_action, accept_label, "Abbrechen")
        dialog.set_modal(True)
        if action == "save":
            dialog.set_do_overwrite_confirmation(True)
            if default_name:
                dialog.set_current_name(default_name)
        if initial_path is not None:
            try:
                if action == "open" and initial_path.is_file():
                    dialog.set_filename(str(initial_path))
                else:
                    folder = initial_path if initial_path.is_dir() else initial_path.parent
                    dialog.set_current_folder(str(folder))
            except (OSError, TypeError):
                pass
        for label, patterns in filters or []:
            file_filter = Gtk.FileFilter()
            file_filter.set_name(label)
            for pattern in patterns:
                file_filter.add_pattern(pattern)
            dialog.add_filter(file_filter)
        try:
            if dialog.run() == Gtk.ResponseType.ACCEPT:
                return dialog.get_filename() or None
            return None
        finally:
            dialog.destroy()

    def _choose_image_file(self) -> str | None:
        if os.environ.get("FLATPAK_ID"):
            initial_path = self.image_path or Path.cwd()
            return self._choose_flatpak_file(
                "Screenshot öffnen",
                "open",
                initial_path,
                filters=[("Bilddateien", ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp", "*.tif", "*.tiff"))],
            )
        zenity = shutil.which("zenity")
        if zenity is None:
            return filedialog.askopenfilename(
                title="Screenshot öffnen",
                filetypes=self.IMAGE_TYPES,
                parent=self.root,
            ) or None
        args = ["--title=Screenshot öffnen"]
        if self.image_path is not None:
            args.append(f"--filename={self.image_path}")
        args.append("--file-filter=Bilddateien | *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff")
        return self._run_zenity(args)

    def _choose_output_file(self, default_name: str) -> str | None:
        if os.environ.get("FLATPAK_ID"):
            return self._choose_flatpak_file(
                "Markierten Screenshot speichern",
                "save",
                self.image_path,
                default_name,
                filters=[
                    ("PNG-Bild", ("*.png",)),
                    ("JPEG-Bild", ("*.jpg", "*.jpeg")),
                    ("WEBP-Bild", ("*.webp",)),
                ],
            )
        zenity = shutil.which("zenity")
        if zenity is None:
            return filedialog.asksaveasfilename(
                title="Markierten Screenshot speichern",
                defaultextension=".png",
                initialdir=str(self.image_path.parent) if self.image_path else None,
                initialfile=default_name,
                filetypes=[("PNG-Bild", "*.png"), ("JPEG-Bild", "*.jpg *.jpeg"), ("WEBP-Bild", "*.webp")],
                parent=self.root,
            ) or None
        default_path = str((self.image_path.parent if self.image_path else Path.cwd()) / default_name)
        args = [
            "--title=Markierten Screenshot speichern",
            "--save",
            "--confirm-overwrite",
            f"--filename={default_path}",
            "--file-filter=PNG-Bild | *.png",
            "--file-filter=JPEG-Bild | *.jpg *.jpeg",
            "--file-filter=WEBP-Bild | *.webp",
        ]
        return self._run_zenity(args)

    def close(self) -> None:
        self.root.destroy()


def main() -> None:
    root = tk.Tk(className="ScreenshotMarker")
    app = ScreenshotMarker(root)
    if len(sys.argv) > 1:
        root.after(50, lambda: app.open_image(sys.argv[1]))
    root.mainloop()


if __name__ == "__main__":
    main()
