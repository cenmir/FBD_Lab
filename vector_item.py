import math
import re
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainterPathStroker,
    QPolygonF, QPainter, QFont, QFontDatabase,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem,
    QGraphicsTextItem, QStyleOptionGraphicsItem, QWidget,
    QApplication, QGraphicsSceneMouseEvent,
)

SNAP_ANGLE_DEG = 5

VECTOR_COLOR = QColor(220, 50, 50)
SELECTED_COLOR = QColor(50, 150, 255)
LABEL_COLOR = QColor(0, 0, 0)
DEFAULT_LABEL_OFFSET = QPointF(8, -8)

LATEX_TO_UNICODE = {
    "\\alpha": "\u03b1", "\\beta": "\u03b2", "\\gamma": "\u03b3",
    "\\delta": "\u03b4", "\\epsilon": "\u03b5", "\\zeta": "\u03b6",
    "\\eta": "\u03b7", "\\theta": "\u03b8", "\\iota": "\u03b9",
    "\\kappa": "\u03ba", "\\lambda": "\u03bb", "\\mu": "\u03bc",
    "\\nu": "\u03bd", "\\xi": "\u03be", "\\pi": "\u03c0",
    "\\rho": "\u03c1", "\\sigma": "\u03c3", "\\tau": "\u03c4",
    "\\phi": "\u03c6", "\\chi": "\u03c7", "\\psi": "\u03c8",
    "\\omega": "\u03c9",
    "\\Gamma": "\u0393", "\\Delta": "\u0394", "\\Theta": "\u0398",
    "\\Lambda": "\u039b", "\\Sigma": "\u03a3", "\\Phi": "\u03a6",
    "\\Psi": "\u03a8", "\\Omega": "\u03a9",
}


def latex_to_unicode(text: str) -> str:
    """Replace LaTeX Greek letter commands with Unicode characters."""
    for cmd, char in LATEX_TO_UNICODE.items():
        text = text.replace(cmd, char)
    return text


@dataclass
class VectorSettings:
    arrow_thickness: int = 1
    shaft_thickness: int = 6
    handle_radius: int = 6
    arrowhead_length: int = 22
    arrowhead_width: int = 20
    arrowhead_notch: int = 8  # stealth notch depth (0 = flat triangle)


vector_settings = VectorSettings()  # global singleton
DEFAULT_MAGNITUDE = ""
DEFAULT_FONT_SIZE = 22

_CM_FONT_FAMILY: str | None = None


def _load_cm_fonts():
    """Load bundled Computer Modern fonts. Call once after QApplication exists."""
    global _CM_FONT_FAMILY
    if _CM_FONT_FAMILY is not None:
        return
    fonts_dir = Path(__file__).parent / "fonts"
    for name in ("cmunrm.otf", "cmunbx.otf", "cmunti.otf", "cmunbi.otf"):
        path = fonts_dir / name
        if path.exists():
            fid = QFontDatabase.addApplicationFont(str(path))
            if fid >= 0 and _CM_FONT_FAMILY is None:
                families = QFontDatabase.applicationFontFamilies(fid)
                if families:
                    _CM_FONT_FAMILY = families[0]
    if _CM_FONT_FAMILY is None:
        _CM_FONT_FAMILY = "Serif"  # fallback


def get_cm_font(size: int = DEFAULT_FONT_SIZE) -> QFont:
    """Return a Computer Modern font at the given point size."""
    _load_cm_fonts()
    return QFont(_CM_FONT_FAMILY, size)


_LABEL_RE = re.compile(
    r'([A-Za-z]+)_\{([^}]+)\}'   # base_{subscript}
    r'|([A-Za-z]+)_([A-Za-z0-9]+)'  # base_sub
    r'|(.+)'                       # plain text
)


def label_to_html(text: str, bold: bool = True, italic: bool = True) -> str:
    """Convert physics shorthand to HTML with configurable base styling.

    Base text is wrapped with bold/italic as requested.
    Subscripts are always italic-only (never bold).
    """
    if not text:
        return ""

    def _wrap_base(s: str) -> str:
        result = s
        if italic:
            result = f"<i>{result}</i>"
        if bold:
            result = f"<b>{result}</b>"
        return result

    parts = []
    for m in _LABEL_RE.finditer(text):
        if m.group(1) is not None:
            parts.append(f"{_wrap_base(m.group(1))}<sub><i>{m.group(2)}</i></sub>")
        elif m.group(3) is not None:
            parts.append(f"{_wrap_base(m.group(3))}<sub><i>{m.group(4)}</i></sub>")
        elif m.group(5) is not None:
            parts.append(_wrap_base(m.group(5)))
    return "".join(parts)


class VectorLabel(QGraphicsTextItem):
    """Draggable label attached to a vector, rendered with HTML formatting."""

    def __init__(self, vec: "VectorItem"):
        super().__init__()
        self._vec = vec
        self._drag_old_offset: QPointF | None = None
        self._updating = False  # guard against itemChange feedback loop

        self.setDefaultTextColor(LABEL_COLOR)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(5)
        self.setVisible(False)

    def set_font_size(self, size: int):
        self.setFont(get_cm_font(size))

    def update_display(self):
        """Rebuild the HTML from the parent vector's current state."""
        vec = self._vec
        html = label_to_html(vec._label_text, vec._label_bold, vec._label_italic)
        if vec._show_magnitude and vec._magnitude:
            mag_display = latex_to_unicode(vec._magnitude)
            if html:
                html += f" = {mag_display}"
            else:
                html = f"<b>{mag_display}</b>"
        self.setHtml(html)

    def update_color(self, selected: bool):
        """Set text color based on selection state."""
        self.setDefaultTextColor(SELECTED_COLOR if selected else LABEL_COLOR)
        # Re-apply HTML so color takes effect
        self.update_display()

    def update_position(self):
        """Reposition label at vector midpoint + offset."""
        self._updating = True
        mid = (self._vec._tail + self._vec._head) / 2
        self.setPos(mid + self._vec._label_offset)
        self._updating = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._updating:
            mid = (self._vec._tail + self._vec._head) / 2
            self._vec._label_offset = value - mid
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_offset = QPointF(self._vec._label_offset)
        # Select the parent vector when clicking the label
        if not self._vec.isSelected():
            if self.scene():
                self.scene().clearSelection()
            self._vec.setSelected(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)

        if self._drag_old_offset is None:
            return

        new_offset = QPointF(self._vec._label_offset)
        old_offset = self._drag_old_offset
        self._drag_old_offset = None

        if new_offset == old_offset:
            return

        push_fn = self._vec.on_push_undo
        if push_fn is not None:
            # Revert, then let command's redo() re-apply
            self._vec._label_offset = QPointF(old_offset)
            self.update_position()

            from commands import MoveLabelCommand
            cmd = MoveLabelCommand(self._vec, old_offset, new_offset)
            push_fn(cmd)


class ControlPoint(QGraphicsEllipseItem):
    """Draggable handle at the tail or head of a vector."""

    def __init__(self, x: float, y: float, vec: "VectorItem", is_head: bool):
        r = vector_settings.handle_radius
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.setPos(x, y)
        self._vec = vec
        self._is_head = is_head
        self.setBrush(QBrush(SELECTED_COLOR))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.setVisible(False)

        self._drag_old_tail: QPointF | None = None
        self._drag_old_head: QPointF | None = None

    @staticmethod
    def _snap(anchor: QPointF, pos: QPointF) -> QPointF:
        """Snap pos to H/V relative to anchor if within SNAP_ANGLE_DEG."""
        dx = pos.x() - anchor.x()
        dy = pos.y() - anchor.y()
        length = math.hypot(dx, dy)
        if length < 1:
            return pos
        angle = math.degrees(math.atan2(abs(dy), abs(dx)))
        if angle <= SNAP_ANGLE_DEG:
            return QPointF(pos.x(), anchor.y())
        elif angle >= 90 - SNAP_ANGLE_DEG:
            return QPointF(anchor.x(), pos.y())
        return pos

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            modifiers = QApplication.keyboardModifiers()
            if not (modifiers & Qt.KeyboardModifier.ControlModifier):
                anchor = self._vec.tail if self._is_head else self._vec.head
                value = self._snap(anchor, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if self._is_head:
                self._vec.set_head(value)
            else:
                self._vec.set_tail(value)
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_tail = QPointF(self._vec.tail)
        self._drag_old_head = QPointF(self._vec.head)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)

        if self._drag_old_tail is None:
            return

        new_tail = QPointF(self._vec.tail)
        new_head = QPointF(self._vec.head)
        old_tail = self._drag_old_tail
        old_head = self._drag_old_head
        self._drag_old_tail = None
        self._drag_old_head = None

        if new_tail == old_tail and new_head == old_head:
            return

        push_fn = self._vec.on_push_undo
        if push_fn is not None:
            self._vec.set_tail(old_tail)
            self._vec.set_head(old_head)

            from commands import ResizeVectorCommand
            cmd = ResizeVectorCommand(self._vec, old_tail, old_head, new_tail, new_head)
            push_fn(cmd)


class VectorItem(QGraphicsPathItem):
    """A straight vector from tail to head with an arrowhead."""

    def __init__(self, tail: QPointF, head: QPointF, parent=None):
        super().__init__(parent)
        self._tail = QPointF(tail)
        self._head = QPointF(head)
        self._label_text = ""
        self._label_visible = False
        self._label_offset = QPointF(DEFAULT_LABEL_OFFSET)
        self._magnitude = DEFAULT_MAGNITUDE
        self._show_magnitude = False
        self._font_size = DEFAULT_FONT_SIZE
        self._label_bold = True
        self._label_italic = True

        self._z_order = 0

        self.on_modified = None      # callback: canvas marks dirty
        self.on_push_undo = None     # callback: canvas pushes QUndoCommand

        self._rebuild_pens()
        self.setPen(self._pen_normal)
        self._head_polygon: QPolygonF | None = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        # Control points (added to scene later)
        self._tail_handle = ControlPoint(tail.x(), tail.y(), self, is_head=False)
        self._head_handle = ControlPoint(head.x(), head.y(), self, is_head=True)

        # Label (added to scene later)
        self._label = VectorLabel(self)
        self._label.set_font_size(self._font_size)

        self._rebuild_path()

    def added_to_scene(self, scene):
        """Call after adding this item to the scene to also add control points and label."""
        scene.addItem(self._tail_handle)
        scene.addItem(self._head_handle)
        scene.addItem(self._label)

    def removed_from_scene(self, scene):
        """Call before removing this item to also remove control points and label."""
        scene.removeItem(self._tail_handle)
        scene.removeItem(self._head_handle)
        scene.removeItem(self._label)

    @property
    def tail(self) -> QPointF:
        return QPointF(self._tail)

    @property
    def head(self) -> QPointF:
        return QPointF(self._head)

    @property
    def magnitude(self) -> str:
        return self._magnitude

    @magnitude.setter
    def magnitude(self, value: str):
        self._magnitude = value
        self._label.update_display()

    @property
    def show_magnitude(self) -> bool:
        return self._show_magnitude

    @show_magnitude.setter
    def show_magnitude(self, value: bool):
        self._show_magnitude = value
        self._label.update_display()

    @property
    def font_size(self) -> int:
        return self._font_size

    @font_size.setter
    def font_size(self, value: int):
        self._font_size = value
        self._label.set_font_size(value)

    @property
    def label_bold(self) -> bool:
        return self._label_bold

    @label_bold.setter
    def label_bold(self, value: bool):
        self._label_bold = value
        self._label.update_display()

    @property
    def label_italic(self) -> bool:
        return self._label_italic

    @label_italic.setter
    def label_italic(self, value: bool):
        self._label_italic = value
        self._label.update_display()

    @property
    def z_order(self) -> int:
        return self._z_order

    @z_order.setter
    def z_order(self, value: int):
        self._z_order = value
        self.setZValue(1 + value)
        self._label.setZValue(5 + value)
        self._tail_handle.setZValue(10 + value)
        self._head_handle.setZValue(10 + value)

    @property
    def vector_length(self) -> float:
        """Geometric length of the vector in scene pixels."""
        dx = self._head.x() - self._tail.x()
        dy = self._head.y() - self._tail.y()
        return math.hypot(dx, dy)

    @property
    def label_text(self) -> str:
        return self._label_text

    @label_text.setter
    def label_text(self, value: str):
        self._label_text = value
        self._label.update_display()
        self._update_label_visibility()

    @property
    def label_visible(self) -> bool:
        return self._label_visible

    @label_visible.setter
    def label_visible(self, value: bool):
        self._label_visible = value
        self._update_label_visibility()

    @property
    def label_offset(self) -> QPointF:
        return QPointF(self._label_offset)

    @label_offset.setter
    def label_offset(self, value: QPointF):
        self._label_offset = QPointF(value)
        self._label.update_position()

    def _update_label_visibility(self):
        self._label.setVisible(self._label_visible and bool(self._label_text))

    def move_by(self, delta: QPointF):
        """Translate the entire vector (tail + head) by delta."""
        self._tail += delta
        self._head += delta
        self._tail_handle.setPos(self._tail)
        self._head_handle.setPos(self._head)
        self._rebuild_path()

    def set_tail(self, point: QPointF):
        self._tail = QPointF(point)
        self._tail_handle.setPos(point)
        self._rebuild_path()

    def set_head(self, point: QPointF):
        self._head = QPointF(point)
        self._head_handle.setPos(point)
        self._rebuild_path()

    def _rebuild_pens(self):
        s = vector_settings
        self._pen_normal = QPen(VECTOR_COLOR, s.arrow_thickness)
        self._pen_selected = QPen(SELECTED_COLOR, s.arrow_thickness)
        self._shaft_pen_normal = QPen(VECTOR_COLOR, s.shaft_thickness)
        self._shaft_pen_normal.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._shaft_pen_selected = QPen(SELECTED_COLOR, s.shaft_thickness)
        self._shaft_pen_selected.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(self._pen_normal)

    def refresh_style(self):
        """Rebuild pens, handle sizes, and path from current vector_settings."""
        self._rebuild_pens()
        r = vector_settings.handle_radius
        self._tail_handle.setRect(-r, -r, 2 * r, 2 * r)
        self._head_handle.setRect(-r, -r, 2 * r, 2 * r)
        self._rebuild_path()
        self.update()

    def _rebuild_path(self):
        # Build arrowhead polygon + shaft endpoint
        s = vector_settings
        dx = self._head.x() - self._tail.x()
        dy = self._head.y() - self._tail.y()
        length = math.hypot(dx, dy)
        if length > 0:
            ux, uy = dx / length, dy / length
            bx = self._head.x() - ux * s.arrowhead_length
            by = self._head.y() - uy * s.arrowhead_length
            px, py = -uy * s.arrowhead_width / 2, ux * s.arrowhead_width / 2
            nx = bx + ux * s.arrowhead_notch
            ny = by + uy * s.arrowhead_notch
            self._head_polygon = QPolygonF([
                self._head,
                QPointF(bx + px, by + py),
                QPointF(nx, ny),
                QPointF(bx - px, by - py),
            ])
            # Pull shaft back so it doesn't blunt the tip
            self._shaft_end = QPointF(self._head.x() - ux * 7, self._head.y() - uy * 7)
        else:
            self._head_polygon = None
            self._shaft_end = QPointF(self._head)

        # Combined path for hit-testing / bounding rect
        path = QPainterPath()
        path.moveTo(self._tail)
        path.lineTo(self._head)
        if self._head_polygon is not None:
            path.addPolygon(self._head_polygon)
            path.closeSubpath()
        self.setPath(path)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(vector_settings.shaft_thickness + 4)  # slightly wider than visual for easy clicking
        shaft_path = QPainterPath()
        shaft_path.moveTo(self._tail)
        shaft_path.lineTo(self._head)
        wide = stroker.createStroke(shaft_path)
        if self._head_polygon is not None:
            wide.addPolygon(self._head_polygon)
            wide.closeSubpath()
        return wide

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()
        color = SELECTED_COLOR if is_sel else VECTOR_COLOR

        self._tail_handle.setVisible(is_sel)
        self._head_handle.setVisible(is_sel)
        self._label.update_color(is_sel)

        # Draw shaft with thick pen (pulled back from tip)
        shaft_pen = self._shaft_pen_selected if is_sel else self._shaft_pen_normal
        painter.setPen(shaft_pen)
        painter.drawLine(self._tail, self._shaft_end)

        # Draw arrowhead with thin pen + fill
        if self._head_polygon is not None:
            head_pen = self._pen_selected if is_sel else self._pen_normal
            painter.setPen(head_pen)
            painter.setBrush(QBrush(color))
            painter.drawPolygon(self._head_polygon)

    def to_dict(self) -> dict:
        return {
            "tail": [self._tail.x(), self._tail.y()],
            "head": [self._head.x(), self._head.y()],
            "label_text": self._label_text,
            "label_visible": self._label_visible,
            "label_offset": [self._label_offset.x(), self._label_offset.y()],
            "magnitude": self._magnitude,
            "show_magnitude": self._show_magnitude,
            "font_size": self._font_size,
            "label_bold": self._label_bold,
            "label_italic": self._label_italic,
            "z_order": self._z_order,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VectorItem":
        vec = cls(
            QPointF(data["tail"][0], data["tail"][1]),
            QPointF(data["head"][0], data["head"][1]),
        )
        vec._label_text = data.get("label_text", "")
        vec._label_visible = data.get("label_visible", False)
        offset = data.get("label_offset", [DEFAULT_LABEL_OFFSET.x(), DEFAULT_LABEL_OFFSET.y()])
        vec._label_offset = QPointF(offset[0], offset[1])
        raw_mag = data.get("magnitude", DEFAULT_MAGNITUDE)
        if isinstance(raw_mag, (int, float)):
            vec._magnitude = "" if raw_mag == 100.0 else f"{raw_mag:.10g}"
        else:
            vec._magnitude = raw_mag
        vec._show_magnitude = data.get("show_magnitude", False)
        vec._font_size = data.get("font_size", DEFAULT_FONT_SIZE)
        vec._label_bold = data.get("label_bold", True)
        vec._label_italic = data.get("label_italic", True)
        vec._label.set_font_size(vec._font_size)
        vec._label.update_display()
        vec._update_label_visibility()
        vec._label.update_position()
        z = data.get("z_order", 0)
        if z != 0:
            vec.z_order = z
        return vec
