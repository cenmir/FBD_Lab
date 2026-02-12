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

FBD_VERSION = 1
MAGIC_HEADER_V1 = b"FBD_BIN_v1"
MAGIC_HEADER_V2 = b"FBD_BIN_v2"
MAGIC_HEADER_V3 = b"FBD_BIN_v3"
MAGIC_HEADER_V4 = b"FBD_BIN_v4"
MAGIC_HEADER_V5 = b"FBD_BIN_v5"
MAGIC_HEADER = b"FBD_BIN_v6"
ALL_MAGIC_HEADERS = (MAGIC_HEADER, MAGIC_HEADER_V5, MAGIC_HEADER_V4, MAGIC_HEADER_V3, MAGIC_HEADER_V2, MAGIC_HEADER_V1)
MAX_IMAGE_BYTES = 100 * 1024 * 1024  # 100 MB sanity limit
MAX_VECTOR_COUNT = 10_000
MAX_POINT_COUNT = 10_000
MAX_DIRECTION_COUNT = 10_000
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


def _load_fbd_binary(canvas: FBDCanvas, file_path: Path):
    with open(file_path, "rb") as f:
        # Read header — support v1 through v6
        header = _read_exact(f, len(MAGIC_HEADER))
        version = 6 if header == MAGIC_HEADER else 0
        if version == 0:
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

                pt = PointItem.from_dict({
                    "pos": [px, py],
                    "label_text": label_text,
                    "label_visible": label_visible,
                    "label_offset": [ox, oy],
                    "font_size": font_size,
                    "label_bold": label_bold,
                    "label_italic": label_italic,
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
                })
                canvas.add_direction(d)
