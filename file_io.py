import base64
import json
import struct
from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QPixmap

from canvas import FBDCanvas, SessionMetadata
from vector_item import VectorItem, DEFAULT_MAGNITUDE, DEFAULT_FONT_SIZE
from point_item import PointItem
from direction_item import DirectionItem
from line_item import LineItem
from moment_item import MomentItem

FBD_VERSION = 1
MAGIC_HEADER_V1 = b"FBD_BIN_v1"
MAGIC_HEADER_V2 = b"FBD_BIN_v2"
MAGIC_HEADER_V3 = b"FBD_BIN_v3"
MAGIC_HEADER_V4 = b"FBD_BIN_v4"
MAGIC_HEADER_V5 = b"FBD_BIN_v5"
MAGIC_HEADER = b"FBD_BIN_v6"
# Old intermediate v7/v8 headers (same format as v6 minus z_order)
MAGIC_HEADER_V8 = b"FBD_BIN_v8"
MAGIC_HEADER_V7 = b"FBD_BIN_v7"
ALL_MAGIC_HEADERS = (MAGIC_HEADER, MAGIC_HEADER_V8, MAGIC_HEADER_V7, MAGIC_HEADER_V5, MAGIC_HEADER_V4, MAGIC_HEADER_V3, MAGIC_HEADER_V2, MAGIC_HEADER_V1)
MAX_IMAGE_BYTES = 100 * 1024 * 1024  # 100 MB sanity limit
MAX_VECTOR_COUNT = 10_000
MAX_POINT_COUNT = 10_000
MAX_DIRECTION_COUNT = 10_000
MAX_LINE_COUNT = 10_000
MAX_MOMENT_COUNT = 10_000
MAX_LABEL_BYTES = 10_000


def pixmap_to_base64(pixmap: QPixmap) -> str:
    """Encode a QPixmap as a base64 PNG string."""
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    return base64.b64encode(buf.data().data()).decode("ascii")


def base64_to_pixmap(data: str) -> QPixmap:
    """Decode a base64 PNG string to a QPixmap."""
    raw = base64.b64decode(data)
    pixmap = QPixmap()
    pixmap.loadFromData(raw, "PNG")
    return pixmap


def pixmap_to_bytes(pixmap: QPixmap) -> bytes:
    """Encode a QPixmap as PNG bytes."""
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    return buf.data().data()


def bytes_to_pixmap(data: bytes) -> QPixmap:
    """Decode PNG bytes to a QPixmap."""
    pixmap = QPixmap()
    pixmap.loadFromData(data, "PNG")
    return pixmap


def _read_exact(f, n: int) -> bytes:
    """Read exactly n bytes from f, raising ValueError if the file is truncated."""
    data = f.read(n)
    if len(data) != n:
        raise ValueError(f"Unexpected end of file (expected {n} bytes, got {len(data)})")
    return data


def save_fbd(canvas: FBDCanvas, file_path: str | Path):
    """Serialize the canvas state to a file (JSON or Binary)."""
    path = Path(file_path)
    if path.suffix.lower() == ".fbdb":
        _save_fbd_binary(canvas, path)
    else:
        _save_fbd_json(canvas, path)


def load_fbd(canvas: FBDCanvas, file_path: str | Path):
    """Deserialize a file and restore the canvas state (JSON or Binary)."""
    path = Path(file_path)
    with open(path, "rb") as f:
        header = f.read(len(MAGIC_HEADER))

    if header in ALL_MAGIC_HEADERS:
        _load_fbd_binary(canvas, path)
    else:
        _load_fbd_json(canvas, path)


def _save_fbd_json(canvas: FBDCanvas, file_path: Path):
    bg_pixmap = canvas.get_background_pixmap()
    data = {
        "version": FBD_VERSION,
        "background_image": pixmap_to_base64(bg_pixmap) if bg_pixmap else None,
        "arrows": canvas.get_vectors_data(),
        "points": canvas.get_points_data(),
        "directions": canvas.get_directions_data(),
        "lines": canvas.get_lines_data(),
        "moments": canvas.get_moments_data(),
        "metadata": canvas.metadata.to_dict(),
    }
    file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_fbd_json(canvas: FBDCanvas, file_path: Path):
    text = file_path.read_text(encoding="utf-8")
    data = json.loads(text)

    # Clear existing state first
    canvas.clear_vectors()
    canvas.clear_points()
    canvas.clear_directions()
    canvas.clear_lines()
    canvas.clear_moments()

    # Restore background
    bg_data = data.get("background_image")
    if bg_data:
        pixmap = base64_to_pixmap(bg_data)
        if not pixmap.isNull():
            canvas.set_background(pixmap)

    # Restore vectors
    for vec_data in data.get("arrows", []):
        vec = VectorItem.from_dict(vec_data)
        canvas.add_vector(vec)

    # Restore points
    for pt_data in data.get("points", []):
        pt = PointItem.from_dict(pt_data)
        canvas.add_point(pt)

    # Restore directions
    for dir_data in data.get("directions", []):
        d = DirectionItem.from_dict(dir_data)
        canvas.add_direction(d)

    # Restore lines
    for line_data in data.get("lines", []):
        ln = LineItem.from_dict(line_data)
        canvas.add_line(ln)

    # Restore moments
    for mom_data in data.get("moments", []):
        m = MomentItem.from_dict(mom_data)
        canvas.add_moment(m)

    # Restore metadata
    meta_data = data.get("metadata")
    if meta_data:
        canvas.metadata = SessionMetadata.from_dict(meta_data)


def _save_fbd_binary(canvas: FBDCanvas, file_path: Path):
    with open(file_path, "wb") as f:
        f.write(MAGIC_HEADER)

        # Background image
        bg_pixmap = canvas.get_background_pixmap()
        if bg_pixmap and not bg_pixmap.isNull():
            img_bytes = pixmap_to_bytes(bg_pixmap)
            f.write(struct.pack("<I", len(img_bytes)))
            f.write(img_bytes)
        else:
            f.write(struct.pack("<I", 0))

        # Vectors
        vectors_data = canvas.get_vectors_data()
        f.write(struct.pack("<I", len(vectors_data)))

        for v in vectors_data:
            f.write(struct.pack("<4f",
                v["tail"][0], v["tail"][1],
                v["head"][0], v["head"][1],
            ))
            label_bytes = v["label_text"].encode("utf-8")
            f.write(struct.pack("<I", len(label_bytes)))
            f.write(label_bytes)
            f.write(struct.pack("?", v["label_visible"]))
            f.write(struct.pack("<2f",
                v["label_offset"][0], v["label_offset"][1],
            ))
            # v6: magnitude as length-prefixed string (was float in v3-v5)
            mag_bytes = v["magnitude"].encode("utf-8")
            f.write(struct.pack("<I", len(mag_bytes)))
            f.write(mag_bytes)
            f.write(struct.pack("?", v["show_magnitude"]))
            f.write(struct.pack("<I", v["font_size"]))
            # v4 fields
            f.write(struct.pack("?", v.get("label_bold", True)))
            f.write(struct.pack("?", v.get("label_italic", True)))
            # v6: z_order
            f.write(struct.pack("<i", v.get("z_order", 0)))

        # v5: Metadata
        meta = canvas.metadata
        for s in (meta.machine_username, meta.machine_hostname):
            s_bytes = s.encode("utf-8")
            f.write(struct.pack("<I", len(s_bytes)))
            f.write(s_bytes)
        f.write(struct.pack("<3d",
            meta.created_at, meta.last_saved_at, meta.total_edit_seconds))
        f.write(struct.pack("<4I",
            meta.session_count, meta.undo_count,
            meta.total_arrows_created, meta.total_arrows_deleted))

        # v6: Points
        points_data = canvas.get_points_data()
        f.write(struct.pack("<I", len(points_data)))

        for p in points_data:
            f.write(struct.pack("<2f", p["pos"][0], p["pos"][1]))
            label_bytes = p["label_text"].encode("utf-8")
            f.write(struct.pack("<I", len(label_bytes)))
            f.write(label_bytes)
            f.write(struct.pack("?", p["label_visible"]))
            f.write(struct.pack("<2f",
                p["label_offset"][0], p["label_offset"][1],
            ))
            f.write(struct.pack("<I", p["font_size"]))
            f.write(struct.pack("?", p.get("label_bold", True)))
            f.write(struct.pack("?", p.get("label_italic", True)))
            f.write(struct.pack("<i", p.get("z_order", 0)))

        # v6: Directions
        directions_data = canvas.get_directions_data()
        f.write(struct.pack("<I", len(directions_data)))

        for d in directions_data:
            f.write(struct.pack("<4f",
                d["tail"][0], d["tail"][1],
                d["head"][0], d["head"][1],
            ))
            label_bytes = d["label_text"].encode("utf-8")
            f.write(struct.pack("<I", len(label_bytes)))
            f.write(label_bytes)
            f.write(struct.pack("?", d["label_visible"]))
            f.write(struct.pack("<2f",
                d["label_offset"][0], d["label_offset"][1],
            ))
            f.write(struct.pack("<I", d["font_size"]))
            f.write(struct.pack("?", d.get("label_bold", True)))
            f.write(struct.pack("?", d.get("label_italic", True)))
            f.write(struct.pack("?", d.get("show_arrowhead", False)))
            f.write(struct.pack("<i", d.get("z_order", 0)))

        # v6: Lines
        lines_data = canvas.get_lines_data()
        f.write(struct.pack("<I", len(lines_data)))

        for ln in lines_data:
            f.write(struct.pack("<4f",
                ln["tail"][0], ln["tail"][1],
                ln["head"][0], ln["head"][1],
            ))
            label_bytes = ln["label_text"].encode("utf-8")
            f.write(struct.pack("<I", len(label_bytes)))
            f.write(label_bytes)
            f.write(struct.pack("?", ln["label_visible"]))
            f.write(struct.pack("<2f",
                ln["label_offset"][0], ln["label_offset"][1],
            ))
            f.write(struct.pack("<I", ln["font_size"]))
            f.write(struct.pack("?", ln.get("label_bold", True)))
            f.write(struct.pack("?", ln.get("label_italic", True)))
            f.write(struct.pack("<2I", ln.get("body_thickness", 10), ln.get("outline_thickness", 2)))
            f.write(struct.pack("<i", ln.get("z_order", 0)))

        # v6: Moments
        moments_data = canvas.get_moments_data()
        f.write(struct.pack("<I", len(moments_data)))

        for m in moments_data:
            f.write(struct.pack("<2f", m["center"][0], m["center"][1]))
            f.write(struct.pack("<f", m["radius"]))
            f.write(struct.pack("<2f", m["start_angle"], m["span_angle"]))
            label_bytes = m["label_text"].encode("utf-8")
            f.write(struct.pack("<I", len(label_bytes)))
            f.write(label_bytes)
            f.write(struct.pack("?", m["label_visible"]))
            f.write(struct.pack("<2f",
                m["label_offset"][0], m["label_offset"][1],
            ))
            f.write(struct.pack("<I", m["font_size"]))
            f.write(struct.pack("?", m.get("label_bold", True)))
            f.write(struct.pack("?", m.get("label_italic", True)))
            f.write(struct.pack("<i", m.get("z_order", 0)))


def _load_fbd_binary(canvas: FBDCanvas, file_path: Path):
    with open(file_path, "rb") as f:
        # Read header — support v1 through v8
        header = _read_exact(f, len(MAGIC_HEADER))
        has_z_order = (header == MAGIC_HEADER)
        if header in (MAGIC_HEADER, MAGIC_HEADER_V8, MAGIC_HEADER_V7):
            version = 6  # v6/v7/v8 share the same data layout
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

        # Clear existing state first
        canvas.clear_vectors()
        canvas.clear_points()
        canvas.clear_directions()
        canvas.clear_lines()
        canvas.clear_moments()

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
            raise ValueError(f"Vector count {vector_count} exceeds maximum ({MAX_VECTOR_COUNT})")

        for _ in range(vector_count):
            x1, y1, x2, y2 = struct.unpack("<4f", _read_exact(f, 16))
            lbl_len = struct.unpack("<I", _read_exact(f, 4))[0]
            if lbl_len > MAX_LABEL_BYTES:
                raise ValueError(f"Label size {lbl_len} exceeds maximum ({MAX_LABEL_BYTES})")
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
                # v6: magnitude is a length-prefixed UTF-8 string
                mag_len = struct.unpack("<I", _read_exact(f, 4))[0]
                if mag_len > MAX_LABEL_BYTES:
                    raise ValueError(f"Magnitude size {mag_len} exceeds maximum ({MAX_LABEL_BYTES})")
                magnitude = _read_exact(f, mag_len).decode("utf-8")
                show_magnitude = struct.unpack("?", _read_exact(f, 1))[0]
                font_size = struct.unpack("<I", _read_exact(f, 4))[0]
            elif version >= 3:
                # v3-v5: magnitude was a float
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

            vec = VectorItem.from_dict({
                "tail": [x1, y1],
                "head": [x2, y2],
                "label_text": label_text,
                "label_visible": label_visible,
                "label_offset": label_offset,
                "magnitude": magnitude,
                "show_magnitude": show_magnitude,
                "font_size": font_size,
                "label_bold": label_bold,
                "label_italic": label_italic,
                "z_order": z_order,
            })
            canvas.add_vector(vec)

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
                machine_username=username,
                machine_hostname=hostname,
                created_at=created_at,
                last_saved_at=last_saved_at,
                total_edit_seconds=total_edit_seconds,
                session_count=session_count,
                undo_count=undo_count,
                total_arrows_created=arrows_created,
                total_arrows_deleted=arrows_deleted,
            )

        # v6: Points
        if version >= 6:
            point_count = struct.unpack("<I", _read_exact(f, 4))[0]
            if point_count > MAX_POINT_COUNT:
                raise ValueError(f"Point count {point_count} exceeds maximum ({MAX_POINT_COUNT})")

            for _ in range(point_count):
                px, py = struct.unpack("<2f", _read_exact(f, 8))
                lbl_len = struct.unpack("<I", _read_exact(f, 4))[0]
                if lbl_len > MAX_LABEL_BYTES:
                    raise ValueError(f"Label size {lbl_len} exceeds maximum ({MAX_LABEL_BYTES})")
                label_text = _read_exact(f, lbl_len).decode("utf-8")
                label_visible = struct.unpack("?", _read_exact(f, 1))[0]
                ox, oy = struct.unpack("<2f", _read_exact(f, 8))
                font_size = struct.unpack("<I", _read_exact(f, 4))[0]
                label_bold = struct.unpack("?", _read_exact(f, 1))[0]
                label_italic = struct.unpack("?", _read_exact(f, 1))[0]
                z_order = 0
                if has_z_order:
                    z_order = struct.unpack("<i", _read_exact(f, 4))[0]

                pt = PointItem.from_dict({
                    "pos": [px, py],
                    "label_text": label_text,
                    "label_visible": label_visible,
                    "label_offset": [ox, oy],
                    "font_size": font_size,
                    "label_bold": label_bold,
                    "label_italic": label_italic,
                    "z_order": z_order,
                })
                canvas.add_point(pt)

        # v6: Directions
        if version >= 6:
            dir_count = struct.unpack("<I", _read_exact(f, 4))[0]
            if dir_count > MAX_DIRECTION_COUNT:
                raise ValueError(f"Direction count {dir_count} exceeds maximum ({MAX_DIRECTION_COUNT})")

            for _ in range(dir_count):
                x1, y1, x2, y2 = struct.unpack("<4f", _read_exact(f, 16))
                lbl_len = struct.unpack("<I", _read_exact(f, 4))[0]
                if lbl_len > MAX_LABEL_BYTES:
                    raise ValueError(f"Label size {lbl_len} exceeds maximum ({MAX_LABEL_BYTES})")
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

                d = DirectionItem.from_dict({
                    "tail": [x1, y1],
                    "head": [x2, y2],
                    "label_text": label_text,
                    "label_visible": label_visible,
                    "label_offset": [ox, oy],
                    "font_size": font_size,
                    "label_bold": label_bold,
                    "label_italic": label_italic,
                    "show_arrowhead": show_arrowhead,
                    "z_order": z_order,
                })
                canvas.add_direction(d)

        # v6: Lines (may not exist in older files)
        if version >= 6:
            remaining = f.read(4)
            if len(remaining) == 4:
                line_count = struct.unpack("<I", remaining)[0]
                if line_count > MAX_LINE_COUNT:
                    raise ValueError(f"Line count {line_count} exceeds maximum ({MAX_LINE_COUNT})")

                for _ in range(line_count):
                    x1, y1, x2, y2 = struct.unpack("<4f", _read_exact(f, 16))
                    lbl_len = struct.unpack("<I", _read_exact(f, 4))[0]
                    if lbl_len > MAX_LABEL_BYTES:
                        raise ValueError(f"Label size {lbl_len} exceeds maximum ({MAX_LABEL_BYTES})")
                    label_text = _read_exact(f, lbl_len).decode("utf-8")
                    label_visible = struct.unpack("?", _read_exact(f, 1))[0]
                    ox, oy = struct.unpack("<2f", _read_exact(f, 8))
                    font_size = struct.unpack("<I", _read_exact(f, 4))[0]
                    label_bold = struct.unpack("?", _read_exact(f, 1))[0]
                    label_italic = struct.unpack("?", _read_exact(f, 1))[0]
                    body_thickness, outline_thickness = struct.unpack("<2I", _read_exact(f, 8))
                    z_order = struct.unpack("<i", _read_exact(f, 4))[0]

                    ln = LineItem.from_dict({
                        "tail": [x1, y1],
                        "head": [x2, y2],
                        "label_text": label_text,
                        "label_visible": label_visible,
                        "label_offset": [ox, oy],
                        "font_size": font_size,
                        "label_bold": label_bold,
                        "label_italic": label_italic,
                        "body_thickness": body_thickness,
                        "outline_thickness": outline_thickness,
                        "z_order": z_order,
                    })
                    canvas.add_line(ln)

                # v6: Moments (may not exist in older files)
                remaining2 = f.read(4)
                if len(remaining2) == 4:
                    moment_count = struct.unpack("<I", remaining2)[0]
                    if moment_count > MAX_MOMENT_COUNT:
                        raise ValueError(f"Moment count {moment_count} exceeds maximum ({MAX_MOMENT_COUNT})")

                    for _ in range(moment_count):
                        cx, cy = struct.unpack("<2f", _read_exact(f, 8))
                        radius = struct.unpack("<f", _read_exact(f, 4))[0]
                        start_angle, span_angle = struct.unpack("<2f", _read_exact(f, 8))
                        lbl_len = struct.unpack("<I", _read_exact(f, 4))[0]
                        if lbl_len > MAX_LABEL_BYTES:
                            raise ValueError(f"Label size {lbl_len} exceeds maximum ({MAX_LABEL_BYTES})")
                        label_text = _read_exact(f, lbl_len).decode("utf-8")
                        label_visible = struct.unpack("?", _read_exact(f, 1))[0]
                        ox, oy = struct.unpack("<2f", _read_exact(f, 8))
                        font_size = struct.unpack("<I", _read_exact(f, 4))[0]
                        label_bold = struct.unpack("?", _read_exact(f, 1))[0]
                        label_italic = struct.unpack("?", _read_exact(f, 1))[0]
                        z_order = struct.unpack("<i", _read_exact(f, 4))[0]

                        m = MomentItem.from_dict({
                            "center": [cx, cy],
                            "radius": radius,
                            "start_angle": start_angle,
                            "span_angle": span_angle,
                            "label_text": label_text,
                            "label_visible": label_visible,
                            "label_offset": [ox, oy],
                            "font_size": font_size,
                            "label_bold": label_bold,
                            "label_italic": label_italic,
                            "z_order": z_order,
                        })
                        canvas.add_moment(m)
