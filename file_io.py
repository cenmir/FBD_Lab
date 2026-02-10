import base64
import json
from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QPixmap

from canvas import FBDCanvas
from arrow_item import ArrowItem

FBD_VERSION = 1


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


def save_fbd(canvas: FBDCanvas, file_path: str | Path):
    """Serialize the canvas state to an .fbd file."""
    bg_pixmap = canvas.get_background_pixmap()
    data = {
        "version": FBD_VERSION,
        "background_image": pixmap_to_base64(bg_pixmap) if bg_pixmap else None,
        "arrows": canvas.get_arrows_data(),
    }
    Path(file_path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_fbd(canvas: FBDCanvas, file_path: str | Path):
    """Deserialize an .fbd file and restore the canvas state."""
    text = Path(file_path).read_text(encoding="utf-8")
    data = json.loads(text)

    # Restore background
    bg_data = data.get("background_image")
    if bg_data:
        pixmap = base64_to_pixmap(bg_data)
        if not pixmap.isNull():
            canvas.set_background(pixmap)

    # Restore arrows
    canvas.clear_arrows()
    for arrow_data in data.get("arrows", []):
        arrow = ArrowItem.from_dict(arrow_data)
        canvas.add_arrow(arrow)
