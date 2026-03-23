import base64
import json
import struct
from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor

from canvas import FBDCanvas, SessionMetadata
from base_item import DEFAULT_FONT_SIZE
from vector_item import VectorItem, DEFAULT_MAGNITUDE
from point_item import PointItem
from direction_item import DirectionItem
from line_item import LineItem
from moment_item import MomentItem
from rectangle_item import RectangleItem
from polygon_item import PolygonItem
from ellipse_item import EllipseItem
from text_item import TextItem

# --- Current format ---
MAGIC_HEADER_V7_JSON = b"FBDB_v7\x00\x00\x00"  # 10 bytes, hybrid binary+JSON

# --- Legacy format headers ---
MAGIC_HEADER_V6 = b"FBD_BIN_v6"
MAGIC_HEADER_V8 = b"FBD_BIN_v8"
MAGIC_HEADER_V7_OLD = b"FBD_BIN_v7"
MAGIC_HEADER_V5 = b"FBD_BIN_v5"
MAGIC_HEADER_V4 = b"FBD_BIN_v4"
MAGIC_HEADER_V3 = b"FBD_BIN_v3"
MAGIC_HEADER_V2 = b"FBD_BIN_v2"
MAGIC_HEADER_V1 = b"FBD_BIN_v1"

ALL_LEGACY_HEADERS = (
    MAGIC_HEADER_V6, MAGIC_HEADER_V8, MAGIC_HEADER_V7_OLD,
    MAGIC_HEADER_V5, MAGIC_HEADER_V4, MAGIC_HEADER_V3,
    MAGIC_HEADER_V2, MAGIC_HEADER_V1,
)

MAX_HEADER_LEN = 10
MAX_IMAGE_BYTES = 100 * 1024 * 1024  # 100 MB sanity limit
MAX_VECTOR_COUNT = 10_000
MAX_POINT_COUNT = 10_000
MAX_DIRECTION_COUNT = 10_000
MAX_LINE_COUNT = 10_000
MAX_MOMENT_COUNT = 10_000
MAX_LABEL_BYTES = 10_000


def pixmap_to_base64(pixmap: QPixmap) -> str:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    return base64.b64encode(buf.data().data()).decode("ascii")


def base64_to_pixmap(data: str) -> QPixmap:
    raw = base64.b64decode(data)
    pixmap = QPixmap()
    pixmap.loadFromData(raw, "PNG")
    return pixmap


def pixmap_to_bytes(pixmap: QPixmap) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    return buf.data().data()


def bytes_to_pixmap(data: bytes) -> QPixmap:
    pixmap = QPixmap()
    pixmap.loadFromData(data, "PNG")
    return pixmap


def _read_exact(f, n: int) -> bytes:
    data = f.read(n)
    if len(data) != n:
        raise ValueError(f"Unexpected end of file (expected {n} bytes, got {len(data)})")
    return data


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def save_fbd(canvas: FBDCanvas, file_path: str | Path):
    """Save canvas state as v7 binary format (always .fbdb)."""
    _save_v7(canvas, Path(file_path))


def extract_snapshot(file_path: str | Path) -> QPixmap | None:
    """Extract the embedded PNG snapshot from a v7 .fbdb file, or None."""
    path = Path(file_path)
    with open(path, "rb") as f:
        header = f.read(MAX_HEADER_LEN)
        if header != MAGIC_HEADER_V7_JSON:
            return None
        # Skip background image
        img_len = struct.unpack("<I", _read_exact(f, 4))[0]
        if img_len > 0:
            f.seek(img_len, 1)
        # Skip JSON payload
        json_len = struct.unpack("<I", _read_exact(f, 4))[0]
        f.seek(json_len, 1)
        # Read snapshot
        remaining = f.read(4)
        if len(remaining) < 4:
            return None
        snap_len = struct.unpack("<I", remaining)[0]
        if snap_len == 0:
            return None
        snap_bytes = _read_exact(f, snap_len)
        return bytes_to_pixmap(snap_bytes)


def load_fbd(canvas: FBDCanvas, file_path: str | Path):
    """Load canvas state — auto-detects v7 or legacy formats."""
    path = Path(file_path)
    with open(path, "rb") as f:
        header = f.read(MAX_HEADER_LEN)

    if header == MAGIC_HEADER_V7_JSON:
        _load_v7(canvas, path)
    elif header in ALL_LEGACY_HEADERS:
        _load_legacy_binary(canvas, path)
    else:
        # Try JSON fallback for old .fbd files
        _load_legacy_json(canvas, path)


# ═══════════════════════════════════════════════════════════════════════════════
# v7 format — binary header + background image + JSON payload
# ═══════════════════════════════════════════════════════════════════════════════

def _render_snapshot(canvas: FBDCanvas) -> bytes:
    """Render the canvas to PNG bytes, respecting layer visibility."""
    scene = canvas.scene()
    scene.clearSelection()
    rect = scene.sceneRect()
    if rect.isEmpty():
        return b""
    image = QImage(int(rect.width()), int(rect.height()), QImage.Format.Format_ARGB32)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(painter)
    painter.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return buf.data().data()


def _save_v7(canvas: FBDCanvas, file_path: Path):
    with open(file_path, "wb") as f:
        f.write(MAGIC_HEADER_V7_JSON)

        # Background image (binary, length-prefixed)
        bg_pixmap = canvas.get_background_pixmap()
        if bg_pixmap and not bg_pixmap.isNull():
            img_bytes = pixmap_to_bytes(bg_pixmap)
            f.write(struct.pack("<I", len(img_bytes)))
            f.write(img_bytes)
        else:
            f.write(struct.pack("<I", 0))

        # JSON payload with all item data
        layer_vis = dict(canvas._visibility)
        layer_vis["background"] = canvas._bg_visible
        data = {
            "arrows": canvas.get_vectors_data(),
            "points": canvas.get_points_data(),
            "directions": canvas.get_directions_data(),
            "lines": canvas.get_lines_data(),
            "moments": canvas.get_moments_data(),
            "rectangles": canvas.get_rectangles_data(),
            "polygons": canvas.get_polygons_data(),
            "ellipses": canvas.get_ellipses_data(),
            "texts": canvas.get_texts_data(),
            "metadata": canvas.metadata.to_dict(),
            "layer_visibility": layer_vis,
        }
        json_bytes = json.dumps(data, separators=(",", ":")).encode("utf-8")
        f.write(struct.pack("<I", len(json_bytes)))
        f.write(json_bytes)

        # Embedded PNG snapshot of the model
        snapshot = _render_snapshot(canvas)
        f.write(struct.pack("<I", len(snapshot)))
        if snapshot:
            f.write(snapshot)


def _load_v7(canvas: FBDCanvas, file_path: Path):
    with open(file_path, "rb") as f:
        _read_exact(f, MAX_HEADER_LEN)  # skip header

        # Background image
        img_len = struct.unpack("<I", _read_exact(f, 4))[0]
        if img_len > MAX_IMAGE_BYTES:
            raise ValueError(f"Image size {img_len} exceeds maximum")

        canvas.clear_vectors()
        canvas.clear_points()
        canvas.clear_directions()
        canvas.clear_lines()
        canvas.clear_moments()
        canvas.clear_rectangles()
        canvas.clear_polygons()

        if img_len > 0:
            img_bytes = _read_exact(f, img_len)
            pixmap = bytes_to_pixmap(img_bytes)
            if not pixmap.isNull():
                canvas.set_background(pixmap)

        # JSON payload
        json_len = struct.unpack("<I", _read_exact(f, 4))[0]
        json_bytes = _read_exact(f, json_len)
        data = json.loads(json_bytes.decode("utf-8"))

        for vec_data in data.get("arrows", []):
            canvas.add_vector(VectorItem.from_dict(vec_data))
        for pt_data in data.get("points", []):
            canvas.add_point(PointItem.from_dict(pt_data))
        for dir_data in data.get("directions", []):
            canvas.add_direction(DirectionItem.from_dict(dir_data))
        for line_data in data.get("lines", []):
            canvas.add_line(LineItem.from_dict(line_data))
        for mom_data in data.get("moments", []):
            canvas.add_moment(MomentItem.from_dict(mom_data))
        for rect_data in data.get("rectangles", []):
            canvas.add_rectangle(RectangleItem.from_dict(rect_data))
        for poly_data in data.get("polygons", []):
            canvas.add_polygon(PolygonItem.from_dict(poly_data))
        for ell_data in data.get("ellipses", []):
            canvas.add_ellipse(EllipseItem.from_dict(ell_data))
        for txt_data in data.get("texts", []):
            canvas.add_text(TextItem.from_dict(txt_data))

        meta_data = data.get("metadata")
        if meta_data:
            canvas.metadata = SessionMetadata.from_dict(meta_data)

        # Restore layer visibility
        layer_vis = data.get("layer_visibility")
        if layer_vis:
            canvas.set_background_visible(layer_vis.get("background", True))
            canvas.set_vectors_visible(layer_vis.get("vectors", True))
            canvas.set_points_visible(layer_vis.get("points", True))
            canvas.set_directions_visible(layer_vis.get("directions", True))
            canvas.set_lines_visible(layer_vis.get("lines", True))
            canvas.set_moments_visible(layer_vis.get("moments", True))
            canvas.set_rectangles_visible(layer_vis.get("rectangles", True))
            canvas.set_polygons_visible(layer_vis.get("polygons", True))
            canvas.set_ellipses_visible(layer_vis.get("ellipses", True))
            canvas.set_texts_visible(layer_vis.get("texts", True))


# ═══════════════════════════════════════════════════════════════════════════════
# Legacy JSON loader (for old .fbd files)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_legacy_json(canvas: FBDCanvas, file_path: Path):
    text = file_path.read_text(encoding="utf-8")
    data = json.loads(text)

    canvas.clear_vectors()
    canvas.clear_points()
    canvas.clear_directions()
    canvas.clear_lines()
    canvas.clear_moments()
    canvas.clear_rectangles()
    canvas.clear_polygons()
    canvas.clear_ellipses()
    canvas.clear_texts()

    bg_data = data.get("background_image")
    if bg_data:
        pixmap = base64_to_pixmap(bg_data)
        if not pixmap.isNull():
            canvas.set_background(pixmap)

    for vec_data in data.get("arrows", []):
        canvas.add_vector(VectorItem.from_dict(vec_data))
    for pt_data in data.get("points", []):
        canvas.add_point(PointItem.from_dict(pt_data))
    for dir_data in data.get("directions", []):
        canvas.add_direction(DirectionItem.from_dict(dir_data))
    for line_data in data.get("lines", []):
        canvas.add_line(LineItem.from_dict(line_data))
    for mom_data in data.get("moments", []):
        canvas.add_moment(MomentItem.from_dict(mom_data))
    for rect_data in data.get("rectangles", []):
        canvas.add_rectangle(RectangleItem.from_dict(rect_data))
    for poly_data in data.get("polygons", []):
        canvas.add_polygon(PolygonItem.from_dict(poly_data))
    for ell_data in data.get("ellipses", []):
        canvas.add_ellipse(EllipseItem.from_dict(ell_data))
    for txt_data in data.get("texts", []):
        canvas.add_text(TextItem.from_dict(txt_data))

    meta_data = data.get("metadata")
    if meta_data:
        canvas.metadata = SessionMetadata.from_dict(meta_data)


# ═══════════════════════════════════════════════════════════════════════════════
# Legacy binary loader (v1-v6/v8)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_legacy_binary(canvas: FBDCanvas, file_path: Path):
    with open(file_path, "rb") as f:
        header = _read_exact(f, MAX_HEADER_LEN)
        has_z_order = (header == MAGIC_HEADER_V6)
        if header in (MAGIC_HEADER_V6, MAGIC_HEADER_V8, MAGIC_HEADER_V7_OLD):
            version = 6
        else:
            version = 0
            f.seek(0)
            header = _read_exact(f, len(MAGIC_HEADER_V5))
            if header == MAGIC_HEADER_V5:
                version = 5
            elif header == MAGIC_HEADER_V4:
                version = 4
            elif header == MAGIC_HEADER_V3:
                version = 3
            elif header == MAGIC_HEADER_V2:
                version = 2
            elif header == MAGIC_HEADER_V1:
                version = 1
            else:
                raise ValueError("Invalid FBD binary file: bad magic header")

        canvas.clear_vectors()
        canvas.clear_points()
        canvas.clear_directions()
        canvas.clear_lines()
        canvas.clear_moments()
        canvas.clear_rectangles()
        canvas.clear_polygons()
        canvas.clear_ellipses()
        canvas.clear_texts()

        # Background image
        img_len = struct.unpack("<I", _read_exact(f, 4))[0]
        if img_len > MAX_IMAGE_BYTES:
            raise ValueError(f"Image size {img_len} exceeds maximum ({MAX_IMAGE_BYTES})")
        if img_len > 0:
            img_bytes = _read_exact(f, img_len)
            pixmap = bytes_to_pixmap(img_bytes)
            if not pixmap.isNull():
                canvas.set_background(pixmap)

        # Vectors
        vector_count = struct.unpack("<I", _read_exact(f, 4))[0]
        if vector_count > MAX_VECTOR_COUNT:
            raise ValueError(f"Vector count {vector_count} exceeds maximum")

        for _ in range(vector_count):
            x1, y1, x2, y2 = struct.unpack("<4f", _read_exact(f, 16))
            lbl_len = struct.unpack("<I", _read_exact(f, 4))[0]
            if lbl_len > MAX_LABEL_BYTES:
                raise ValueError(f"Label size {lbl_len} exceeds maximum")
            label_text = _read_exact(f, lbl_len).decode("utf-8")
            label_visible = struct.unpack("?", _read_exact(f, 1))[0]

            label_offset = [8.0, -8.0]
            if version >= 2:
                ox, oy = struct.unpack("<2f", _read_exact(f, 8))
                label_offset = [ox, oy]

            magnitude = DEFAULT_MAGNITUDE
            show_magnitude = False
            font_size = DEFAULT_FONT_SIZE
            if version >= 6:
                mag_len = struct.unpack("<I", _read_exact(f, 4))[0]
                if mag_len > MAX_LABEL_BYTES:
                    raise ValueError(f"Magnitude size {mag_len} exceeds maximum")
                magnitude = _read_exact(f, mag_len).decode("utf-8")
                show_magnitude = struct.unpack("?", _read_exact(f, 1))[0]
                font_size = struct.unpack("<I", _read_exact(f, 4))[0]
            elif version >= 3:
                mag_float = struct.unpack("<f", _read_exact(f, 4))[0]
                magnitude = "" if mag_float == 100.0 else f"{mag_float:.10g}"
                show_magnitude = struct.unpack("?", _read_exact(f, 1))[0]
                font_size = struct.unpack("<I", _read_exact(f, 4))[0]

            label_bold = True
            label_italic = True
            if version >= 4:
                label_bold = struct.unpack("?", _read_exact(f, 1))[0]
                label_italic = struct.unpack("?", _read_exact(f, 1))[0]

            z_order = 0
            if has_z_order:
                z_order = struct.unpack("<i", _read_exact(f, 4))[0]

            canvas.add_vector(VectorItem.from_dict({
                "tail": [x1, y1], "head": [x2, y2],
                "label_text": label_text, "label_visible": label_visible,
                "label_offset": label_offset, "magnitude": magnitude,
                "show_magnitude": show_magnitude, "font_size": font_size,
                "label_bold": label_bold, "label_italic": label_italic,
                "z_order": z_order,
            }))

        # v5: Metadata
        if version >= 5:
            def _read_string() -> str:
                slen = struct.unpack("<I", _read_exact(f, 4))[0]
                if slen > MAX_LABEL_BYTES:
                    raise ValueError(f"Metadata string size {slen} exceeds maximum")
                return _read_exact(f, slen).decode("utf-8")

            username = _read_string()
            hostname = _read_string()
            created_at, last_saved_at, total_edit_seconds = struct.unpack(
                "<3d", _read_exact(f, 24))
            session_count, undo_count, arrows_created, arrows_deleted = struct.unpack(
                "<4I", _read_exact(f, 16))
            canvas.metadata = SessionMetadata(
                machine_username=username, machine_hostname=hostname,
                created_at=created_at, last_saved_at=last_saved_at,
                total_edit_seconds=total_edit_seconds,
                session_count=session_count, undo_count=undo_count,
                total_arrows_created=arrows_created,
                total_arrows_deleted=arrows_deleted,
            )

        # v6: Points
        if version >= 6:
            point_count = struct.unpack("<I", _read_exact(f, 4))[0]
            if point_count > MAX_POINT_COUNT:
                raise ValueError(f"Point count {point_count} exceeds maximum")
            for _ in range(point_count):
                px, py = struct.unpack("<2f", _read_exact(f, 8))
                lbl_len = struct.unpack("<I", _read_exact(f, 4))[0]
                label_text = _read_exact(f, lbl_len).decode("utf-8")
                label_visible = struct.unpack("?", _read_exact(f, 1))[0]
                ox, oy = struct.unpack("<2f", _read_exact(f, 8))
                font_size = struct.unpack("<I", _read_exact(f, 4))[0]
                label_bold = struct.unpack("?", _read_exact(f, 1))[0]
                label_italic = struct.unpack("?", _read_exact(f, 1))[0]
                z_order = 0
                if has_z_order:
                    z_order = struct.unpack("<i", _read_exact(f, 4))[0]
                canvas.add_point(PointItem.from_dict({
                    "pos": [px, py], "label_text": label_text,
                    "label_visible": label_visible, "label_offset": [ox, oy],
                    "font_size": font_size, "label_bold": label_bold,
                    "label_italic": label_italic, "z_order": z_order,
                }))

        # v6: Directions
        if version >= 6:
            dir_count = struct.unpack("<I", _read_exact(f, 4))[0]
            if dir_count > MAX_DIRECTION_COUNT:
                raise ValueError(f"Direction count {dir_count} exceeds maximum")
            for _ in range(dir_count):
                x1, y1, x2, y2 = struct.unpack("<4f", _read_exact(f, 16))
                lbl_len = struct.unpack("<I", _read_exact(f, 4))[0]
                label_text = _read_exact(f, lbl_len).decode("utf-8")
                label_visible = struct.unpack("?", _read_exact(f, 1))[0]
                ox, oy = struct.unpack("<2f", _read_exact(f, 8))
                font_size = struct.unpack("<I", _read_exact(f, 4))[0]
                label_bold = struct.unpack("?", _read_exact(f, 1))[0]
                label_italic = struct.unpack("?", _read_exact(f, 1))[0]
                show_arrowhead = struct.unpack("?", _read_exact(f, 1))[0]
                z_order = 0
                if has_z_order:
                    z_order = struct.unpack("<i", _read_exact(f, 4))[0]
                canvas.add_direction(DirectionItem.from_dict({
                    "tail": [x1, y1], "head": [x2, y2],
                    "label_text": label_text, "label_visible": label_visible,
                    "label_offset": [ox, oy], "font_size": font_size,
                    "label_bold": label_bold, "label_italic": label_italic,
                    "show_arrowhead": show_arrowhead, "z_order": z_order,
                }))

        # v6: Lines, Moments, Rectangles, Polygons (may not exist in older files)
        if version >= 6:
            remaining = f.read(4)
            if len(remaining) == 4:
                line_count = struct.unpack("<I", remaining)[0]
                for _ in range(line_count):
                    x1, y1, x2, y2 = struct.unpack("<4f", _read_exact(f, 16))
                    lbl_len = struct.unpack("<I", _read_exact(f, 4))[0]
                    label_text = _read_exact(f, lbl_len).decode("utf-8")
                    label_visible = struct.unpack("?", _read_exact(f, 1))[0]
                    ox, oy = struct.unpack("<2f", _read_exact(f, 8))
                    font_size = struct.unpack("<I", _read_exact(f, 4))[0]
                    label_bold = struct.unpack("?", _read_exact(f, 1))[0]
                    label_italic = struct.unpack("?", _read_exact(f, 1))[0]
                    body_thickness, outline_thickness = struct.unpack("<2I", _read_exact(f, 8))
                    z_order = struct.unpack("<i", _read_exact(f, 4))[0]
                    canvas.add_line(LineItem.from_dict({
                        "tail": [x1, y1], "head": [x2, y2],
                        "label_text": label_text, "label_visible": label_visible,
                        "label_offset": [ox, oy], "font_size": font_size,
                        "label_bold": label_bold, "label_italic": label_italic,
                        "body_thickness": body_thickness,
                        "outline_thickness": outline_thickness, "z_order": z_order,
                    }))

                remaining2 = f.read(4)
                if len(remaining2) == 4:
                    moment_count = struct.unpack("<I", remaining2)[0]
                    for _ in range(moment_count):
                        cx, cy = struct.unpack("<2f", _read_exact(f, 8))
                        radius = struct.unpack("<f", _read_exact(f, 4))[0]
                        start_angle, span_angle = struct.unpack("<2f", _read_exact(f, 8))
                        lbl_len = struct.unpack("<I", _read_exact(f, 4))[0]
                        label_text = _read_exact(f, lbl_len).decode("utf-8")
                        label_visible = struct.unpack("?", _read_exact(f, 1))[0]
                        ox, oy = struct.unpack("<2f", _read_exact(f, 8))
                        font_size = struct.unpack("<I", _read_exact(f, 4))[0]
                        label_bold = struct.unpack("?", _read_exact(f, 1))[0]
                        label_italic = struct.unpack("?", _read_exact(f, 1))[0]
                        z_order = struct.unpack("<i", _read_exact(f, 4))[0]
                        canvas.add_moment(MomentItem.from_dict({
                            "center": [cx, cy], "radius": radius,
                            "start_angle": start_angle, "span_angle": span_angle,
                            "label_text": label_text, "label_visible": label_visible,
                            "label_offset": [ox, oy], "font_size": font_size,
                            "label_bold": label_bold, "label_italic": label_italic,
                            "z_order": z_order,
                        }))

                    remaining3 = f.read(4)
                    if len(remaining3) == 4:
                        rect_count = struct.unpack("<I", remaining3)[0]
                        for _ in range(rect_count):
                            cx, cy = struct.unpack("<2f", _read_exact(f, 8))
                            w, h = struct.unpack("<2f", _read_exact(f, 8))
                            rotation = struct.unpack("<f", _read_exact(f, 4))[0]
                            outline_thickness = struct.unpack("<I", _read_exact(f, 4))[0]
                            lbl_len = struct.unpack("<I", _read_exact(f, 4))[0]
                            label_text = _read_exact(f, lbl_len).decode("utf-8")
                            label_visible = struct.unpack("?", _read_exact(f, 1))[0]
                            ox, oy = struct.unpack("<2f", _read_exact(f, 8))
                            font_size = struct.unpack("<I", _read_exact(f, 4))[0]
                            label_bold = struct.unpack("?", _read_exact(f, 1))[0]
                            label_italic = struct.unpack("?", _read_exact(f, 1))[0]
                            z_order = struct.unpack("<i", _read_exact(f, 4))[0]
                            canvas.add_rectangle(RectangleItem.from_dict({
                                "center": [cx, cy], "width": w, "height": h,
                                "rotation": rotation,
                                "outline_thickness": outline_thickness,
                                "label_text": label_text, "label_visible": label_visible,
                                "label_offset": [ox, oy], "font_size": font_size,
                                "label_bold": label_bold, "label_italic": label_italic,
                                "z_order": z_order,
                            }))

                        remaining4 = f.read(4)
                        if len(remaining4) == 4:
                            poly_count = struct.unpack("<I", remaining4)[0]
                            for _ in range(poly_count):
                                cx, cy = struct.unpack("<2f", _read_exact(f, 8))
                                rotation = struct.unpack("<f", _read_exact(f, 4))[0]
                                outline_thickness = struct.unpack("<I", _read_exact(f, 4))[0]
                                vert_count = struct.unpack("<I", _read_exact(f, 4))[0]
                                vertices = []
                                for _ in range(vert_count):
                                    vx, vy = struct.unpack("<2f", _read_exact(f, 8))
                                    vertices.append([vx, vy])
                                lbl_len = struct.unpack("<I", _read_exact(f, 4))[0]
                                label_text = _read_exact(f, lbl_len).decode("utf-8")
                                label_visible = struct.unpack("?", _read_exact(f, 1))[0]
                                ox, oy = struct.unpack("<2f", _read_exact(f, 8))
                                font_size = struct.unpack("<I", _read_exact(f, 4))[0]
                                label_bold = struct.unpack("?", _read_exact(f, 1))[0]
                                label_italic = struct.unpack("?", _read_exact(f, 1))[0]
                                z_order = struct.unpack("<i", _read_exact(f, 4))[0]
                                canvas.add_polygon(PolygonItem.from_dict({
                                    "center": [cx, cy], "vertices": vertices,
                                    "rotation": rotation,
                                    "outline_thickness": outline_thickness,
                                    "label_text": label_text, "label_visible": label_visible,
                                    "label_offset": [ox, oy], "font_size": font_size,
                                    "label_bold": label_bold, "label_italic": label_italic,
                                    "z_order": z_order,
                                }))
