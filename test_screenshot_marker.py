import unittest
import math
import tkinter as tk
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from screenshot_marker import (
    Annotation,
    ScreenshotMarker,
    annotation_box,
    arrow_points,
    arrow_hit_test,
    annotation_hit_test,
    circle_box,
    ellipse_box,
    crop_bounds,
    image_to_ppm_bytes,
    marker_text_color,
    move_annotation,
    number_marker_box,
    next_marker_number,
    render_annotations,
    render_selection,
    rotate_arrow,
    _point_in_polygon,
    _point_segment_distance,
    window_size_for_image,
)
import screenshot_marker as app_module


class FakeButton:
    def __init__(self):
        self.state = None

    def configure(self, **kwargs):
        self.state = kwargs["state"]


class FakeCanvas:
    def delete(self, _tag):
        pass


class FakeStatus:
    def __init__(self):
        self.text = ""

    def configure(self, **kwargs):
        self.text = kwargs.get("text", self.text)


class FakeClipboard:
    def __init__(self, image=None):
        self.image = image
        self.stored = False

    def wait_for_image(self):
        return self.image

    def set_image(self, image):
        self.image = image

    def store(self):
        self.stored = True


class RenderingTests(unittest.TestCase):
    def test_arrow_polygon_points_to_end(self):
        points = arrow_points((10, 20), (90, 20), 8)
        self.assertEqual(points[3], (90, 20))
        self.assertEqual(len(points), 7)

    def test_short_arrow_is_safe(self):
        self.assertEqual(arrow_points((1, 1), (1, 1), 8), [])

    def test_shift_circle_drag_is_normalized_to_a_true_circle(self):
        box = circle_box((10, 20), (30, 80), (100, 100))
        self.assertEqual(box[2] - box[0], box[3] - box[1])
        self.assertEqual(box, (10, 20, 70, 80))

    def test_circle_is_clipped_to_the_image_edge(self):
        self.assertEqual(circle_box((95, 90), (96, 95), (100, 100)), (95, 90, 99, 94))

    def test_ellipse_keeps_independent_drag_dimensions_and_is_clipped(self):
        self.assertEqual(ellipse_box((10, 20), (30, 80), (100, 100)), (10, 20, 30, 80))
        self.assertEqual(ellipse_box((90, 95), (110, 80), (100, 100)), (90, 80, 99, 95))

    def test_shift_circle_annotation_renders_as_circle_and_default_as_ellipse(self):
        source = Image.new("RGBA", (100, 100), "white")
        ellipse = Annotation("circle", (10, 20), (30, 80), "#ff0000", 2)
        circle = Annotation("circle", (10, 20), (30, 80), "#ff0000", 2, perfect_circle=True)
        self.assertEqual(render_annotations(source, [ellipse]).getpixel((20, 20)), (255, 0, 0, 255))
        self.assertEqual(render_annotations(source, [circle]).getpixel((70, 50)), (255, 0, 0, 255))

    def test_arrow_rotation_preserves_length_midpoint_and_bounds(self):
        arrow = Annotation("arrow", (10, 50), (90, 50), "#ff0000", 6)
        rotated = rotate_arrow(arrow, math.pi / 2, (100, 100))
        self.assertAlmostEqual(rotated.start[0], 50)
        self.assertAlmostEqual(rotated.end[0], 50)
        self.assertAlmostEqual(rotated.start[1], 10)
        self.assertAlmostEqual(rotated.end[1], 90)
        self.assertAlmostEqual(math.dist(rotated.start, rotated.end), 80)

    def test_arrow_rotation_clamps_translation_to_image(self):
        arrow = Annotation("arrow", (10, 10), (90, 10), "#ff0000", 6)
        rotated = rotate_arrow(arrow, -math.pi / 2, (100, 100))
        self.assertGreaterEqual(min(rotated.start[0], rotated.end[0]), 0)
        self.assertGreaterEqual(min(rotated.start[1], rotated.end[1]), 0)
        self.assertLessEqual(max(rotated.start[0], rotated.end[0]), 99)
        self.assertLessEqual(max(rotated.start[1], rotated.end[1]), 99)

    def test_crop_bounds_use_exclusive_right_and_bottom_edges(self):
        self.assertEqual(crop_bounds((10.2, 5.5, 20.1, 14.2), (40, 30)), (10, 5, 21, 15))
        self.assertEqual(crop_bounds((-8, -3, 50, 40), (40, 30)), (0, 0, 40, 30))
        self.assertEqual(crop_bounds((4, 3, 4, 3), (40, 30)), (4, 3, 5, 4))

    def test_hit_test_geometry_handles_degenerate_and_nonmatching_shapes(self):
        self.assertEqual(_point_segment_distance((2, 2), (1, 1), (1, 1)), math.sqrt(2))
        square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertTrue(_point_in_polygon((5, 5), square))
        self.assertFalse(_point_in_polygon((12, 5), square))
        self.assertFalse(arrow_hit_test((2, 2), Annotation("circle", (0, 0), (10, 10), "#f00", 2), 1))
        self.assertFalse(annotation_hit_test((5, 5), Annotation("move", (0, 0), (1, 1), "#f00", 2), 1, (20, 20)))
        self.assertEqual(rotate_arrow(Annotation("circle", (0, 0), (5, 5), "#f00", 2), 1.0, (10, 10)).kind, "circle")
        self.assertEqual(marker_text_color("invalid"), "#ffffff")

    def test_paste_window_size_respects_available_screen(self):
        self.assertEqual(
            window_size_for_image((1920, 1080), (1366, 768)),
            (1326, 688, 20, 40),
        )
        width, height, x, y = window_size_for_image((640, 360), (1366, 768))
        self.assertEqual((width, height), (720, 575))
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)

    def test_number_marker_box_is_clamped_inside_image(self):
        self.assertEqual(number_marker_box((0, 0), (100, 80), 1), (0, 0, 36, 36))
        box = number_marker_box((0, 0), (20, 12), 12)
        self.assertGreaterEqual(box[0], 0)
        self.assertGreaterEqual(box[1], 0)
        self.assertLessEqual(box[2], 20)
        self.assertLessEqual(box[3], 12)

    def test_number_marker_renders_a_colored_badge_and_contrasting_text(self):
        source = Image.new("RGBA", (80, 80), "white")
        marker = Annotation("number", (40, 40), (40, 40), "#ef4444", 8, 1)
        result = render_annotations(source, [marker])
        red_pixels = sum(1 for pixel in result.getdata() if pixel[0] > 200 and pixel[1] < 100 and pixel[2] < 100)
        self.assertGreater(red_pixels, 500)
        self.assertEqual(marker_text_color("#f59e0b"), "#111827")
        self.assertEqual(marker_text_color("#3b82f6"), "#ffffff")

    def test_marked_image_exports_to_png_jpeg_and_webp(self):
        source = Image.new("RGBA", (80, 60), "white")
        annotations = [
            Annotation("arrow", (5, 30), (70, 30), "#ef4444", 6),
            Annotation("circle", (15, 10), (45, 40), "#3b82f6", 4),
            Annotation("number", (60, 15), (60, 15), "#22c55e", 8, 1),
        ]
        marked = render_annotations(source, annotations)
        for image_format in ("PNG", "JPEG", "WEBP"):
            with self.subTest(format=image_format):
                stream = BytesIO()
                (marked.convert("RGB") if image_format == "JPEG" else marked).save(stream, format=image_format)
                stream.seek(0)
                with Image.open(stream) as decoded:
                    decoded.load()
                    self.assertEqual(decoded.size, source.size)

    def test_number_markers_get_the_next_sequence_number(self):
        self.assertEqual(next_marker_number([]), 1)
        existing = [
            Annotation("number", (5, 5), (5, 5), "#ff0000", 8, 1),
            Annotation("number", (15, 5), (15, 5), "#ff0000", 8, 2),
            Annotation("circle", (20, 20), (30, 30), "#00ff00", 4),
        ]
        self.assertEqual(next_marker_number(existing), 3)

    def test_number_tool_places_markers_on_click_and_ignores_drags(self):
        buttons = [FakeButton() for _ in range(4)]
        app = SimpleNamespace(
            image=Image.new("RGBA", (100, 80), "white"),
            tool="number",
            start_image=(20, 20),
            zoom=1,
            offset_x=0,
            offset_y=0,
            canvas=FakeCanvas(),
            preview_id=None,
            width=SimpleNamespace(get=lambda: 8),
            color="#ef4444",
            annotations=[],
            undo_stack=[],
            redo_stack=[],
            dirty=False,
            crop_drag_kind=None,
            move_index=None,
            rotate_index=None,
            move_start=None,
            copy_button=buttons[0],
            undo_button=buttons[1],
            redo_button=buttons[2],
            clear_button=buttons[3],
            redraw=lambda: None,
        )
        app._to_image = lambda x, y, clamp=True: ScreenshotMarker._to_image(app, x, y, clamp)
        app._push_undo_state = lambda: ScreenshotMarker._push_undo_state(app)
        app._update_actions = lambda: ScreenshotMarker._update_actions(app)
        ScreenshotMarker.on_release(app, SimpleNamespace(x=20, y=20))
        app.start_image = (40, 40)
        ScreenshotMarker.on_release(app, SimpleNamespace(x=40, y=40))
        app.start_image = (50, 50)
        ScreenshotMarker.on_release(app, SimpleNamespace(x=70, y=50))
        self.assertEqual([item.number for item in app.annotations], [1, 2])

    def test_circle_tool_only_constrains_shape_when_shift_is_held(self):
        for state, expected in ((0, False), (0x0001, True)):
            with self.subTest(shift=bool(state)):
                buttons = [FakeButton() for _ in range(4)]
                app = SimpleNamespace(
                    image=Image.new("RGBA", (100, 100), "white"), tool="circle",
                    start_image=(10, 10), zoom=1, offset_x=0, offset_y=0,
                    canvas=FakeCanvas(), preview_id=None,
                    width=SimpleNamespace(get=lambda: 8), color="#ef4444", annotations=[],
                    undo_stack=[], redo_stack=[], dirty=False, crop_drag_kind=None,
                    move_index=None, rotate_index=None, copy_button=buttons[0],
                    undo_button=buttons[1], redo_button=buttons[2], clear_button=buttons[3],
                    redraw=lambda: None,
                )
                app._to_image = lambda x, y, clamp=True: ScreenshotMarker._to_image(app, x, y, clamp)
                app._push_undo_state = lambda: ScreenshotMarker._push_undo_state(app)
                app._update_actions = lambda: ScreenshotMarker._update_actions(app)
                ScreenshotMarker.on_release(app, SimpleNamespace(x=30, y=50, state=state))
                self.assertEqual(app.annotations[0].perfect_circle, expected)
                self.assertEqual(annotation_box(app.annotations[0], app.image.size), (10, 10, 50, 50) if expected else (10, 10, 30, 50))

    def test_clipboard_paste_converts_rgba_pixels_and_resets_layers(self):
        pixels = bytes((255, 0, 0, 255, 0, 255, 0, 128, 0, 0, 255, 255, 10, 20, 30, 255))
        pixbuf = SimpleNamespace(
            get_width=lambda: 2,
            get_height=lambda: 2,
            get_has_alpha=lambda: True,
            get_pixels=lambda: pixels,
            get_rowstride=lambda: 8,
        )
        clipboard = FakeClipboard(pixbuf)
        app = SimpleNamespace(
            _confirm_discard=lambda: True,
            _gtk_clipboard=lambda: (clipboard, None, None),
            root=SimpleNamespace(title=lambda _title: None),
            image=None,
            image_path=None,
            crop_rect=(0, 0, 1, 1),
            crop_drag_kind="move",
            annotations=[Annotation("number", (5, 5), (5, 5), "#ef4444", 8, 1)],
            undo_stack=[[]],
            redo_stack=[[]],
            dirty=True,
            status=FakeStatus(),
            _update_actions=lambda: None,
            _resize_window_to_image=lambda: None,
            redraw=lambda: None,
        )
        ScreenshotMarker.paste_from_clipboard(app)
        self.assertEqual(app.image.size, (2, 2))
        self.assertEqual(app.image.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(app.image.getpixel((1, 0)), (0, 255, 0, 128))
        self.assertEqual((app.annotations, app.undo_stack, app.redo_stack), ([], [], []))
        self.assertIsNone(app.crop_rect)
        self.assertFalse(app.dirty)

    def test_clipboard_copy_packages_only_the_cropped_rendered_layers(self):
        source = Image.new("RGBA", (20, 20), "white")
        annotations = [
            Annotation("circle", (4, 4), (16, 16), "#3b82f6", 3),
            Annotation("number", (10, 10), (10, 10), "#22c55e", 8, 1),
        ]
        captured = {}

        class PixbufFactory:
            @staticmethod
            def new_from_bytes(pixels, _colorspace, has_alpha, bits, width, height, rowstride):
                captured.update(
                    pixels=pixels,
                    has_alpha=has_alpha,
                    bits=bits,
                    size=(width, height),
                    rowstride=rowstride,
                )
                return captured

        clipboard = FakeClipboard()
        gdk_pixbuf = SimpleNamespace(
            Pixbuf=PixbufFactory,
            Colorspace=SimpleNamespace(RGB="RGB"),
        )
        glib = SimpleNamespace(Bytes=SimpleNamespace(new=lambda pixels: pixels))
        app = SimpleNamespace(
            image=source,
            annotations=annotations,
            crop_rect=(5, 5, 15, 15),
            _gtk_clipboard=lambda: (clipboard, gdk_pixbuf, glib),
            status=FakeStatus(),
        )
        expected = render_selection(source, annotations, app.crop_rect).convert("RGBA")
        ScreenshotMarker.copy_to_clipboard(app)
        self.assertEqual(captured["size"], expected.size)
        self.assertEqual(captured["pixels"], expected.tobytes())
        self.assertTrue(captured["has_alpha"])
        self.assertEqual(captured["bits"], 8)
        self.assertEqual(captured["rowstride"], expected.width * 4)
        self.assertTrue(clipboard.stored)
        self.assertIn(f"{expected.width} × {expected.height}", app.status.text)

    def test_cut_commits_selected_pixels_and_annotations_as_new_image(self):
        source = Image.new("RGBA", (30, 24), "white")
        annotations = [
            Annotation("arrow", (8, 12), (20, 12), "#ef4444", 4),
            Annotation("number", (10, 10), (10, 10), "#22c55e", 8, 1),
        ]
        crop_rect = (5, 4, 22, 20)
        app = SimpleNamespace(
            image=source, annotations=annotations.copy(), crop_rect=crop_rect, crop_drag_kind=None,
            crop_drag_start=None, crop_fixed_point=None, crop_original_rect=None,
            undo_stack=[[]], redo_stack=[[]], dirty=False, status=FakeStatus(),
            _update_actions=Mock(), _resize_window_to_image=Mock(), redraw=Mock(),
        )
        expected = render_selection(source, annotations, crop_rect).convert("RGBA")
        ScreenshotMarker.cut_to_selection(app)
        self.assertEqual(app.image.size, (17, 16))
        self.assertEqual(app.image.tobytes(), expected.tobytes())
        self.assertEqual(app.annotations, [])
        self.assertIsNone(app.crop_rect)
        self.assertEqual((app.undo_stack, app.redo_stack), ([], []))
        self.assertTrue(app.dirty)
        app._resize_window_to_image.assert_called_once_with()
        self.assertIn("17 × 16", app.status.text)

    def test_open_png_then_save_annotated_png_round_trips(self):
        with TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.png"
            target_path = Path(directory) / "annotated.png"
            source = Image.new("RGBA", (80, 60), "white")
            source.save(source_path)
            app = SimpleNamespace(
                _confirm_discard=lambda: True,
                root=SimpleNamespace(title=lambda _title: None),
                image=None,
                image_path=None,
                crop_rect=(1, 1, 4, 4),
                crop_drag_kind="move",
                annotations=[Annotation("number", (5, 5), (5, 5), "#ef4444", 8, 1)],
                undo_stack=[[]],
                redo_stack=[[]],
                dirty=True,
                status=FakeStatus(),
                _update_actions=lambda: None,
                redraw=lambda: None,
            )
            ScreenshotMarker.open_image(app, str(source_path))
            self.assertEqual(app.image.size, (80, 60))
            self.assertEqual(app.image_path, source_path)
            self.assertEqual((app.annotations, app.undo_stack, app.redo_stack), ([], [], []))
            self.assertIsNone(app.crop_rect)
            app.annotations = [Annotation("arrow", (5, 30), (70, 30), "#ef4444", 6)]
            app._choose_output_file = lambda _default_name: str(target_path)
            app.dirty = True
            expected = render_annotations(app.image, app.annotations)
            self.assertTrue(ScreenshotMarker.save_as(app))
            with Image.open(target_path) as saved:
                saved.load()
                self.assertEqual(saved.size, expected.size)
                self.assertEqual(saved.convert("RGBA").tobytes(), expected.tobytes())

    def test_every_marker_type_can_be_hit_and_moved(self):
        arrow = Annotation("arrow", (10, 20), (80, 20), "#ff0000", 8)
        self.assertTrue(arrow_hit_test((50, 20), arrow, 2))
        self.assertFalse(arrow_hit_test((50, 50), arrow, 2))
        circle = Annotation("circle", (20, 20), (40, 40), "#22c55e", 4)
        number = Annotation("number", (50, 50), (50, 50), "#3b82f6", 8, 1)
        size = (100, 100)
        self.assertTrue(annotation_hit_test((30, 20), circle, 2, size))
        self.assertFalse(annotation_hit_test((30, 30), circle, 2, size))
        self.assertTrue(annotation_hit_test((50, 50), number, 2, size))
        self.assertEqual(move_annotation(circle, (5, -5), size).start, (25, 15))
        self.assertEqual(move_annotation(number, (5, 10), size).start, (55, 60))
        edge_number = move_annotation(
            Annotation("number", (0, 0), (0, 0), "#ef4444", 8, 1),
            (-20, -20),
            size,
        )
        self.assertEqual(edge_number.start, (18, 18))
        clipped_circle = move_annotation(circle, (100, 100), size)
        self.assertEqual(clipped_circle.end, (99, 99))
        shifted = move_annotation(arrow, (5, 10), size)
        self.assertEqual((shifted.start, shifted.end), ((15, 30), (85, 30)))
        clipped = move_annotation(arrow, (50, 0), size)
        self.assertEqual((clipped.start, clipped.end), ((29, 20), (99, 20)))

    def test_snapshot_undo_and_redo_restore_a_moved_arrow(self):
        original = Annotation("arrow", (10, 20), (80, 20), "#ff0000", 8)
        moved = move_annotation(original, (5, 10), (100, 100))
        app = SimpleNamespace(
            annotations=[moved],
            undo_stack=[[original]],
            redo_stack=[],
            dirty=False,
            _update_actions=lambda: None,
            redraw=lambda: None,
        )
        ScreenshotMarker.undo(app)
        self.assertEqual(app.annotations, [original])
        ScreenshotMarker.redo(app)
        self.assertEqual(app.annotations, [moved])

    def test_move_tool_drag_updates_arrows_circles_and_numbers(self):
        markers = (
            (Annotation("arrow", (10, 20), (80, 20), "#ff0000", 8), (50, 20), (55, 30), ((15, 30), (85, 30))),
            (Annotation("circle", (20, 20), (40, 40), "#22c55e", 4), (30, 20), (35, 30), ((25, 30), (45, 50))),
            (Annotation("number", (50, 50), (50, 50), "#3b82f6", 8, 1), (50, 50), (55, 60), ((55, 60), (55, 60))),
        )
        for marker, press, release, expected in markers:
            with self.subTest(kind=marker.kind):
                buttons = [FakeButton() for _ in range(4)]
                app = SimpleNamespace(
                    image=Image.new("RGBA", (100, 100), "white"),
                    annotations=[marker],
                    zoom=1,
                    offset_x=0,
                    offset_y=0,
                    undo_stack=[],
                    redo_stack=[],
                    dirty=False,
                    move_index=None,
                    move_start=None,
                    move_original_annotations=None,
                    status=SimpleNamespace(configure=lambda **_kwargs: None),
                    copy_button=buttons[0],
                    undo_button=buttons[1],
                    redo_button=buttons[2],
                    clear_button=buttons[3],
                    redraw=lambda: None,
                )
                app._to_image = lambda x, y, clamp=True: ScreenshotMarker._to_image(app, x, y, clamp)
                app._annotation_index_at = lambda point: ScreenshotMarker._annotation_index_at(app, point)
                app._drag_annotation_move = lambda event: ScreenshotMarker._drag_annotation_move(app, event)
                app._update_actions = lambda: ScreenshotMarker._update_actions(app)
                ScreenshotMarker._begin_annotation_move(app, SimpleNamespace(x=press[0], y=press[1]))
                self.assertEqual(app.move_index, 0)
                ScreenshotMarker._drag_annotation_move(app, SimpleNamespace(x=release[0], y=release[1]))
                ScreenshotMarker._finish_annotation_move(app, SimpleNamespace(x=release[0], y=release[1]))
                self.assertEqual((app.annotations[0].start, app.annotations[0].end), expected)
                self.assertEqual(app.undo_stack, [[marker]])

    def test_rotate_tool_drag_rotates_arrow_and_is_undoable(self):
        marker = Annotation("arrow", (10, 50), (90, 50), "#ff0000", 6)
        buttons = [FakeButton() for _ in range(4)]
        app = SimpleNamespace(
            image=Image.new("RGBA", (100, 100), "white"), annotations=[marker], zoom=1,
            offset_x=0, offset_y=0, rotate_index=None, rotate_center=None,
            rotate_pointer_angle=None, rotate_original_annotations=None, undo_stack=[],
            redo_stack=[], dirty=False, status=FakeStatus(), canvas=FakeCanvas(),
            copy_button=buttons[0], undo_button=buttons[1], redo_button=buttons[2], clear_button=buttons[3],
            redraw=lambda: None,
        )
        app._to_image = lambda x, y, clamp=True: ScreenshotMarker._to_image(app, x, y, clamp)
        app._arrow_index_at = lambda point: ScreenshotMarker._arrow_index_at(app, point)
        app._drag_arrow_rotate = lambda event: ScreenshotMarker._drag_arrow_rotate(app, event)
        app._update_actions = lambda: ScreenshotMarker._update_actions(app)
        ScreenshotMarker._begin_arrow_rotate(app, SimpleNamespace(x=70, y=50))
        ScreenshotMarker._drag_arrow_rotate(app, SimpleNamespace(x=50, y=70))
        ScreenshotMarker._finish_arrow_rotate(app, SimpleNamespace(x=50, y=70))
        self.assertAlmostEqual(app.annotations[0].start[0], 50)
        self.assertAlmostEqual(app.annotations[0].end[0], 50)
        self.assertAlmostEqual(app.annotations[0].start[1], 10)
        self.assertAlmostEqual(app.annotations[0].end[1], 90)
        self.assertEqual(app.undo_stack, [[marker]])

    def test_shift_and_control_gestures_work_as_tool_overrides(self):
        marker = Annotation("arrow", (10, 50), (90, 50), "#ff0000", 6)
        for modifier, press, release, expected in (
            (0x0001, (70, 50), (55, 60), ((0, 60), (80, 60))),
            (0x0004, (70, 50), (50, 70), ((50, 10), (50, 90))),
        ):
            with self.subTest(modifier=modifier):
                buttons = [FakeButton() for _ in range(4)]
                app = SimpleNamespace(
                    image=Image.new("RGBA", (100, 100), "white"), annotations=[marker],
                    tool="circle", zoom=1, offset_x=0, offset_y=0, crop_drag_kind=None,
                    move_index=None, move_start=None, move_original_annotations=None,
                    rotate_index=None, rotate_center=None, rotate_pointer_angle=None,
                    rotate_original_annotations=None, start_image=None, undo_stack=[],
                    redo_stack=[], dirty=False, status=FakeStatus(), canvas=FakeCanvas(),
                    copy_button=buttons[0], undo_button=buttons[1], redo_button=buttons[2],
                    clear_button=buttons[3], redraw=lambda: None,
                )
                app._to_image = lambda x, y, clamp=True: ScreenshotMarker._to_image(app, x, y, clamp)
                app._annotation_index_at = lambda point: ScreenshotMarker._annotation_index_at(app, point)
                app._arrow_index_at = lambda point: ScreenshotMarker._arrow_index_at(app, point)
                app._begin_annotation_move = lambda event: ScreenshotMarker._begin_annotation_move(app, event)
                app._drag_annotation_move = lambda event: ScreenshotMarker._drag_annotation_move(app, event)
                app._finish_annotation_move = lambda event: ScreenshotMarker._finish_annotation_move(app, event)
                app._begin_arrow_rotate = lambda event: ScreenshotMarker._begin_arrow_rotate(app, event)
                app._drag_arrow_rotate = lambda event: ScreenshotMarker._drag_arrow_rotate(app, event)
                app._finish_arrow_rotate = lambda event: ScreenshotMarker._finish_arrow_rotate(app, event)
                app._update_actions = lambda: ScreenshotMarker._update_actions(app)
                ScreenshotMarker.on_press(app, SimpleNamespace(x=press[0], y=press[1], state=modifier))
                self.assertEqual(app.move_index is not None, modifier == 0x0001)
                self.assertEqual(app.rotate_index is not None, modifier == 0x0004)
                ScreenshotMarker.on_drag(app, SimpleNamespace(x=release[0], y=release[1], state=modifier))
                ScreenshotMarker.on_release(app, SimpleNamespace(x=release[0], y=release[1], state=modifier))
                self.assertEqual((app.annotations[0].start, app.annotations[0].end), expected)
                self.assertEqual(app.undo_stack, [[marker]])

    def test_close_does_not_prompt_for_unsaved_changes(self):
        root = SimpleNamespace(destroy=Mock())
        app = SimpleNamespace(root=root)
        ScreenshotMarker.close(app)
        root.destroy.assert_called_once_with()

    def test_selection_contains_rendered_annotation_layers(self):
        source = Image.new("RGBA", (60, 50), "white")
        annotations = [
            Annotation("circle", (10, 10), (30, 30), "#ff0000", 3),
            Annotation("arrow", (35, 8), (50, 35), "#0000ff", 4),
            Annotation("number", (22, 32), (22, 32), "#22c55e", 8, 1),
        ]
        full_render = render_annotations(source, annotations)
        cropped = render_selection(source, annotations, (5, 5, 40, 40))
        self.assertEqual(cropped.size, (35, 35))
        self.assertEqual(cropped.tobytes(), full_render.crop((5, 5, 40, 40)).tobytes())

    def test_copy_button_tracks_whether_an_image_is_loaded(self):
        app = SimpleNamespace(
            image=None,
            annotations=[],
            undo_stack=[],
            redo_stack=[],
            copy_button=FakeButton(),
            undo_button=FakeButton(),
            redo_button=FakeButton(),
            clear_button=FakeButton(),
        )
        ScreenshotMarker._update_actions(app)
        self.assertEqual(app.copy_button.state, "disabled")
        app.image = object()
        ScreenshotMarker._update_actions(app)
        self.assertEqual(app.copy_button.state, "normal")

    def test_rendering_does_not_modify_source(self):
        source = Image.new("RGBA", (120, 100), "white")
        annotations = [
            Annotation("circle", (10, 10), (60, 60), "#ff0000", 5),
            Annotation("arrow", (20, 80), (100, 80), "#0000ff", 6),
        ]
        result = render_annotations(source, annotations)
        self.assertEqual(source.getpixel((10, 35)), (255, 255, 255, 255))
        self.assertNotEqual(result.getpixel((10, 35)), (255, 255, 255, 255))
        self.assertNotEqual(result.getpixel((100, 80)), (255, 255, 255, 255))

    def test_preview_conversion_produces_binary_ppm(self):
        source = Image.new("RGBA", (3, 2), (12, 34, 56, 128))
        ppm = image_to_ppm_bytes(source)
        self.assertTrue(ppm.startswith(b"P6\n3 2\n255\n"))
        self.assertEqual(len(ppm), len(b"P6\n3 2\n255\n") + 3 * 2 * 3)


class ApplicationServiceTests(unittest.TestCase):
    def test_confirm_discard_all_choices(self):
        app = SimpleNamespace(dirty=False, save_as=Mock(return_value=True), root=Mock())
        self.assertTrue(ScreenshotMarker._confirm_discard(app))
        app.dirty = True
        with patch.object(app_module.messagebox, "askyesnocancel", return_value=None):
            self.assertFalse(ScreenshotMarker._confirm_discard(app))
        with patch.object(app_module.messagebox, "askyesnocancel", return_value=False):
            self.assertTrue(ScreenshotMarker._confirm_discard(app))
        with patch.object(app_module.messagebox, "askyesnocancel", return_value=True):
            self.assertTrue(ScreenshotMarker._confirm_discard(app))
        app.save_as.assert_called_once_with()

    def test_open_image_success_cancel_and_invalid_file(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            Image.new("RGB", (9, 7), "blue").save(source)
            app = SimpleNamespace(
                _confirm_discard=lambda: True, _choose_image_file=lambda: None,
                root=SimpleNamespace(title=Mock()), image=None, image_path=None,
                crop_rect=(1, 1, 2, 2), crop_drag_kind="move", annotations=[Annotation("arrow", (1, 1), (4, 4), "#f00", 2)],
                undo_stack=[[]], redo_stack=[[]], dirty=True, status=FakeStatus(),
                _update_actions=Mock(), redraw=Mock(),
            )
            ScreenshotMarker.open_image(app)
            self.assertIsNone(app.image)
            ScreenshotMarker.open_image(app, str(source))
            self.assertEqual(app.image.size, (9, 7))
            self.assertEqual(app.image.mode, "RGBA")
            self.assertEqual(app.image_path, source)
            self.assertIsNone(app.crop_rect)
            self.assertEqual((app.annotations, app.undo_stack, app.redo_stack), ([], [], []))
            self.assertFalse(app.dirty)
            with patch.object(app_module.messagebox, "showerror") as showerror:
                ScreenshotMarker.open_image(app, str(Path(directory) / "missing.png"))
                showerror.assert_called_once()

    def test_save_as_png_jpeg_cancel_missing_image_and_error(self):
        with TemporaryDirectory() as directory:
            image = Image.new("RGBA", (8, 6), (20, 30, 40, 128))
            app = SimpleNamespace(
                image=image, image_path=Path(directory) / "source.png", annotations=[], dirty=True,
                status=FakeStatus(), root=Mock(), _choose_output_file=lambda _name: str(Path(directory) / "out"),
            )
            self.assertTrue(ScreenshotMarker.save_as(app))
            self.assertTrue((Path(directory) / "out.png").exists())
            app._choose_output_file = lambda _name: str(Path(directory) / "out.jpg")
            self.assertTrue(ScreenshotMarker.save_as(app))
            with Image.open(Path(directory) / "out.jpg") as saved:
                self.assertEqual(saved.mode, "RGB")
            app._choose_output_file = lambda _name: None
            self.assertFalse(ScreenshotMarker.save_as(app))
            app.image = None
            with patch.object(app_module.messagebox, "showinfo") as showinfo:
                self.assertFalse(ScreenshotMarker.save_as(app))
                showinfo.assert_called_once()
            app.image = image
            app._choose_output_file = lambda _name: str(Path(directory) / "absent" / "bad.png")
            with patch.object(app_module.messagebox, "showerror") as showerror:
                self.assertFalse(ScreenshotMarker.save_as(app))
                showerror.assert_called_once()

    @patch.dict(app_module.os.environ, {"FLATPAK_ID": ""})
    def test_zenity_success_cancel_errors_and_picker_arguments(self):
        app = SimpleNamespace(root=Mock(), image_path=Path("/tmp/input.png"), IMAGE_TYPES=ScreenshotMarker.IMAGE_TYPES)
        ok = SimpleNamespace(returncode=0, stdout="/tmp/out.png\n", stderr="")
        with patch.object(app_module.shutil, "which", return_value="/usr/bin/zenity"), patch.object(app_module.subprocess, "run", return_value=ok) as run:
            self.assertEqual(ScreenshotMarker._run_zenity(app, ["--title=Test"]), "/tmp/out.png")
            self.assertIn("--modal", run.call_args.args[0])
        cancel = SimpleNamespace(returncode=1, stdout="", stderr="")
        with patch.object(app_module.shutil, "which", return_value="zenity"), patch.object(app_module.subprocess, "run", return_value=cancel):
            self.assertIsNone(ScreenshotMarker._run_zenity(app, []))
        failure = SimpleNamespace(returncode=2, stdout="", stderr="dialog failure")
        with patch.object(app_module.shutil, "which", return_value="zenity"), patch.object(app_module.subprocess, "run", return_value=failure), patch.object(app_module.messagebox, "showerror") as showerror:
            self.assertIsNone(ScreenshotMarker._run_zenity(app, []))
            showerror.assert_called_once()
        with patch.object(app_module.shutil, "which", return_value="zenity"), patch.object(app_module.subprocess, "run", side_effect=OSError("missing")), patch.object(app_module.messagebox, "showerror") as showerror:
            self.assertIsNone(ScreenshotMarker._run_zenity(app, []))
            showerror.assert_called_once()
        with patch.object(app_module.shutil, "which", return_value=None):
            self.assertIsNone(ScreenshotMarker._run_zenity(app, []))
            with patch.object(app_module.filedialog, "askopenfilename", return_value="/tmp/picked.png") as chooser:
                self.assertEqual(ScreenshotMarker._choose_image_file(app), "/tmp/picked.png")
                chooser.assert_called_once()
            with patch.object(app_module.filedialog, "asksaveasfilename", return_value="/tmp/saved.png") as chooser:
                self.assertEqual(ScreenshotMarker._choose_output_file(app, "saved.png"), "/tmp/saved.png")
                chooser.assert_called_once()
        app._run_zenity = lambda args: args
        with patch.object(app_module.shutil, "which", return_value="zenity"):
            image_args = ScreenshotMarker._choose_image_file(app)
            save_args = ScreenshotMarker._choose_output_file(app, "export.png")
        self.assertTrue(any("--filename=/tmp/input.png" == item for item in image_args))
        self.assertTrue(any(item.startswith("--confirm-overwrite") for item in save_args))

    def test_flatpak_uses_native_portal_chooser_for_open_and_save(self):
        choose = Mock(return_value="/tmp/selected.png")
        app = SimpleNamespace(image_path=Path("/tmp/source.png"), _choose_flatpak_file=choose)
        with patch.dict(app_module.os.environ, {"FLATPAK_ID": "org.kelra.ScreenshotMarker"}):
            self.assertEqual(ScreenshotMarker._choose_image_file(app), "/tmp/selected.png")
            self.assertEqual(choose.call_args.args[1:3], ("open", Path("/tmp/source.png")))
            self.assertEqual(choose.call_args.kwargs["filters"][0][0], "Bilddateien")

            self.assertEqual(ScreenshotMarker._choose_output_file(app, "result.png"), "/tmp/selected.png")
            self.assertEqual(choose.call_args.args[1:4], ("save", Path("/tmp/source.png"), "result.png"))
            self.assertEqual(len(choose.call_args.kwargs["filters"]), 3)

    def test_main_entrypoint_with_and_without_file_argument(self):
        fake_root = Mock()
        fake_app = Mock()
        with patch.object(app_module.tk, "Tk", return_value=fake_root), patch.object(app_module, "ScreenshotMarker", return_value=fake_app), patch.object(app_module.sys, "argv", ["screenshot_marker.py"]):
            app_module.main()
            fake_root.mainloop.assert_called_once_with()
            fake_root.after.assert_not_called()
        fake_root.reset_mock()
        with patch.object(app_module.tk, "Tk", return_value=fake_root), patch.object(app_module, "ScreenshotMarker", return_value=fake_app), patch.object(app_module.sys, "argv", ["screenshot_marker.py", "/tmp/test.png"]):
            app_module.main()
            fake_root.after.assert_called_once()


class NativeGuiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Desktop session unavailable: {exc}")

    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("960x720+20+20")
        self.root.deiconify()
        self.root.update_idletasks()
        self.app = ScreenshotMarker(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_real_widgets_tools_rendering_crop_and_cut(self):
        app = self.app
        self.assertEqual(app.cut_button.winfo_manager(), "")
        self.assertTrue(app.root.bind("<Control-o>"))
        app.image = Image.new("RGBA", (120, 80), "white")
        app.annotations = [
            Annotation("circle", (15, 15), (45, 35), "#ef4444", 3),
            Annotation("arrow", (10, 50), (70, 50), "#3b82f6", 4),
            Annotation("number", (90, 20), (90, 20), "#22c55e", 8, 1),
        ]
        app.redraw()
        self.assertGreaterEqual(len(app.canvas.find_all()), 5)
        app._view_transform()
        canvas_point = app._to_canvas((30, 20))
        self.assertAlmostEqual(app._to_image(*canvas_point)[0], 30, places=4)
        self.assertAlmostEqual(app._to_image(*canvas_point)[1], 20, places=4)
        self.assertEqual(app._to_image_edge(*app._to_canvas((120, 80))), (120, 80))
        for annotation in app.annotations:
            self.assertIsNotNone(app._draw_canvas_annotation(annotation))
        app.set_color("#a855f7")
        self.assertEqual(app.color, "#a855f7")
        with patch.object(app_module.colorchooser, "askcolor", return_value=((1, 2, 3), "#123456")):
            app.choose_color()
        self.assertEqual(app.color, "#123456")
        app.arrow_button.invoke()
        self.assertEqual(app.tool, "arrow")
        app.rotate_button.invoke()
        self.assertEqual(app.tool, "rotate")
        app.move_button.invoke()
        self.assertEqual(app.tool, "move")
        app.number_button.invoke()
        self.assertEqual(app.tool, "number")
        app.circle_button.invoke()
        self.assertEqual(app.tool, "circle")
        app.crop_button.invoke()
        self.assertEqual(app.tool, "crop")
        self.assertEqual(app.cut_button.winfo_manager(), "")

        app.crop_rect = None
        app.annotations = []
        app.redraw()
        app._view_transform()
        start = app._to_canvas((10, 10))
        end = app._to_canvas((60, 50))
        app.on_press(SimpleNamespace(x=start[0], y=start[1], state=0))
        app.on_drag(SimpleNamespace(x=end[0], y=end[1], state=0))
        app.on_release(SimpleNamespace(x=end[0], y=end[1], state=0))
        self.assertEqual(app.crop_rect, (10.0, 10.0, 60.0, 50.0))
        self.assertEqual(app.cut_button.winfo_manager(), "pack")
        app._draw_crop_overlay()
        nw = app._to_canvas((10, 10))
        app.on_canvas_motion(SimpleNamespace(x=nw[0], y=nw[1]))
        self.assertEqual(app.canvas.cget("cursor"), "hand2")
        app._resize_window_to_image = Mock()
        app.cut_button.invoke()
        self.assertEqual(app.image.size, (50, 40))
        self.assertEqual(app.crop_rect, None)
        self.assertEqual(app.cut_button.winfo_manager(), "")
        app._resize_window_to_image.assert_called_once_with()
        app._update_actions()
        self.assertEqual(str(app.copy_button.cget("state")), "normal")

    def test_real_crop_handle_resize_and_inside_move(self):
        app = self.app
        app.image = Image.new("RGBA", (100, 80), "white")
        app.set_tool("crop")
        app.crop_rect = (10, 10, 50, 40)
        app.redraw()
        app._view_transform()
        nw = app._to_canvas((10, 10))
        nw_end = app._to_canvas((5, 6))
        app._crop_press(SimpleNamespace(x=nw[0], y=nw[1]))
        self.assertEqual(app.crop_drag_kind, "resize")
        app._crop_drag(SimpleNamespace(x=nw_end[0], y=nw_end[1]))
        app._crop_release(SimpleNamespace(x=nw_end[0], y=nw_end[1]))
        self.assertEqual(app.crop_rect, (5, 6, 50, 40))
        center = app._to_canvas((20, 20))
        moved = app._to_canvas((25, 24))
        app._crop_press(SimpleNamespace(x=center[0], y=center[1]))
        self.assertEqual(app.crop_drag_kind, "move")
        app._crop_drag(SimpleNamespace(x=moved[0], y=moved[1]))
        app._crop_release(SimpleNamespace(x=moved[0], y=moved[1]))
        self.assertEqual(app.crop_rect, (10.0, 10.0, 55.0, 44.0))

    def test_real_gtk_private_selection_image_paste_and_copy(self):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("Gdk", "3.0")
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import Gdk, GdkPixbuf, GLib, Gtk
        except (ImportError, ValueError) as exc:
            self.skipTest(f"GTK image clipboard unavailable: {exc}")
        initialized = Gtk.init_check()
        if isinstance(initialized, tuple):
            initialized = initialized[0]
        if not initialized:
            self.skipTest("GTK could not connect to the desktop")
        display = Gdk.Display.get_default()
        selection = Gdk.Atom.intern("SCREENSHOT_MARKER_PRIVATE_QA", False)
        clipboard = Gtk.Clipboard.get_for_display(display, selection)
        width, height = 6, 4
        source_bytes = bytes((255, 255, 255, 255) * (width * height))
        pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes.new(source_bytes), GdkPixbuf.Colorspace.RGB, True, 8,
            width, height, width * 4,
        )
        clipboard.set_image(pixbuf)
        clipboard.store()
        self.root.update()

        app = self.app
        app._gtk_clipboard = lambda: (clipboard, GdkPixbuf, GLib)
        app._confirm_discard = lambda: True
        app._resize_window_to_image = Mock()
        app.paste_from_clipboard()
        self.assertEqual(app.image.size, (width, height))
        self.assertEqual(app.image.tobytes(), source_bytes)
        app.annotations = [Annotation("arrow", (0, 2), (5, 2), "#ef4444", 2)]
        app.crop_rect = (1, 0, 5, 4)
        expected = render_selection(app.image, app.annotations, app.crop_rect).convert("RGBA")
        app.copy_to_clipboard()
        copied = clipboard.wait_for_image()
        self.assertEqual((copied.get_width(), copied.get_height()), expected.size)
        copied_data = bytes(copied.get_pixels())
        rowstride = copied.get_rowstride()
        packed = b"".join(copied_data[row * rowstride:row * rowstride + expected.width * 4] for row in range(expected.height))
        self.assertEqual(packed, expected.tobytes())

    def test_real_image_open_save_clear_undo_redo_and_close(self):
        app = self.app
        with TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.png"
            output_path = Path(directory) / "result.png"
            Image.new("RGB", (24, 18), "white").save(input_path)
            app._confirm_discard = lambda: True
            app.open_image(str(input_path))
            self.assertEqual(app.image.size, (24, 18))
            self.assertEqual(app.image.mode, "RGBA")
            app.annotations = [Annotation("arrow", (2, 8), (20, 8), "#ef4444", 3)]
            app._push_undo_state()
            app.annotations.clear()
            app.undo()
            self.assertEqual(len(app.annotations), 1)
            app.redo()
            self.assertEqual(app.annotations, [])
            app.annotations = [Annotation("number", (12, 8), (12, 8), "#22c55e", 8, 1)]
            with patch.object(app_module.messagebox, "askyesno", return_value=True):
                app.clear_annotations()
            self.assertEqual(app.annotations, [])
            app._choose_output_file = lambda _default: str(output_path)
            app.annotations = [Annotation("circle", (3, 3), (18, 13), "#3b82f6", 2)]
            self.assertTrue(app.save_as())
            with Image.open(output_path) as saved:
                self.assertEqual(saved.size, (24, 18))
            destroy = Mock(wraps=app.root.destroy)
            app.root.destroy = destroy
            app.close()
            destroy.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
