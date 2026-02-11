import math
import re
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

ARROW_COLOR = QColor(220, 50, 50)
SELECTED_COLOR = QColor(50, 150, 255)
LABEL_COLOR = QColor(0, 0, 0)
ARROW_THICKNESS = 1
SHAFT_THICKNESS = 6
HANDLE_RADIUS = 6
ARROWHEAD_LENGTH = 22
ARROWHEAD_WIDTH = 20
ARROWHEAD_NOTCH = 8  # stealth notch depth (0 = flat triangle)
DEFAULT_LABEL_OFFSET = QPointF(8, -8)
DEFAULT_MAGNITUDE = 100.0
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


def _format_sig_figs(value: float, figs: int = 3) -> str:
    """Format a float to a given number of significant figures."""
    if value == 0:
        return "0"
    return f"{value:.{figs}g}"


class ArrowLabel(QGraphicsTextItem):
    """Draggable label attached to an arrow, rendered with HTML formatting."""

    def __init__(self, arrow: "ArrowItem"):
        super().__init__()
        self._arrow = arrow
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
        """Rebuild the HTML from the parent arrow's current state."""
        arrow = self._arrow
        html = label_to_html(arrow._label_text, arrow._label_bold, arrow._label_italic)
        if arrow._show_magnitude and html:
            mag_str = _format_sig_figs(arrow._magnitude)
            html += f" = {mag_str}"
        elif arrow._show_magnitude:
            mag_str = _format_sig_figs(arrow._magnitude)
            html = f"<b>{mag_str}</b>"
        self.setHtml(html)

    def update_color(self, selected: bool):
        """Set text color based on selection state."""
        self.setDefaultTextColor(SELECTED_COLOR if selected else LABEL_COLOR)
        # Re-apply HTML so color takes effect
        self.update_display()

    def update_position(self):
        """Reposition label at arrow midpoint + offset."""
        self._updating = True
        mid = (self._arrow._tail + self._arrow._head) / 2
        self.setPos(mid + self._arrow._label_offset)
        self._updating = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._updating:
            mid = (self._arrow._tail + self._arrow._head) / 2
            self._arrow._label_offset = value - mid
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_offset = QPointF(self._arrow._label_offset)
        # Select the parent arrow when clicking the label
        if not self._arrow.isSelected():
            if self.scene():
                self.scene().clearSelection()
            self._arrow.setSelected(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)

        if self._drag_old_offset is None:
            return

        new_offset = QPointF(self._arrow._label_offset)
        old_offset = self._drag_old_offset
        self._drag_old_offset = None

        if new_offset == old_offset:
            return

        push_fn = self._arrow.on_push_undo
        if push_fn is not None:
            # Revert, then let command's redo() re-apply
            self._arrow._label_offset = QPointF(old_offset)
            self.update_position()

            from commands import MoveLabelCommand
            cmd = MoveLabelCommand(self._arrow, old_offset, new_offset)
            push_fn(cmd)


class ControlPoint(QGraphicsEllipseItem):
    """Draggable handle at the tail or head of an arrow."""

    def __init__(self, x: float, y: float, arrow: "ArrowItem", is_head: bool):
        r = HANDLE_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.setPos(x, y)
        self._arrow = arrow
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
                anchor = self._arrow.tail if self._is_head else self._arrow.head
                value = self._snap(anchor, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if self._is_head:
                self._arrow.set_head(value)
            else:
                self._arrow.set_tail(value)
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_tail = QPointF(self._arrow.tail)
        self._drag_old_head = QPointF(self._arrow.head)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)

        if self._drag_old_tail is None:
            return

        new_tail = QPointF(self._arrow.tail)
        new_head = QPointF(self._arrow.head)
        old_tail = self._drag_old_tail
        old_head = self._drag_old_head
        self._drag_old_tail = None
        self._drag_old_head = None

        if new_tail == old_tail and new_head == old_head:
            return

        push_fn = self._arrow.on_push_undo
        if push_fn is not None:
            self._arrow.set_tail(old_tail)
            self._arrow.set_head(old_head)

            from commands import ResizeArrowCommand
            cmd = ResizeArrowCommand(self._arrow, old_tail, old_head, new_tail, new_head)
            push_fn(cmd)


class ArrowItem(QGraphicsPathItem):
    """A straight arrow from tail to head with an arrowhead."""

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

        self.on_modified = None      # callback: canvas marks dirty
        self.on_push_undo = None     # callback: canvas pushes QUndoCommand

        self._pen_normal = QPen(ARROW_COLOR, ARROW_THICKNESS)
        self._pen_selected = QPen(SELECTED_COLOR, ARROW_THICKNESS)
        self._shaft_pen_normal = QPen(ARROW_COLOR, SHAFT_THICKNESS)
        self._shaft_pen_normal.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._shaft_pen_selected = QPen(SELECTED_COLOR, SHAFT_THICKNESS)
        self._shaft_pen_selected.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(self._pen_normal)
        self._head_polygon: QPolygonF | None = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        # Control points (added to scene later)
        self._tail_handle = ControlPoint(tail.x(), tail.y(), self, is_head=False)
        self._head_handle = ControlPoint(head.x(), head.y(), self, is_head=True)

        # Label (added to scene later)
        self._label = ArrowLabel(self)
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
    def magnitude(self) -> float:
        return self._magnitude

    @magnitude.setter
    def magnitude(self, value: float):
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
    def arrow_length(self) -> float:
        """Geometric length of the arrow in scene pixels."""
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
        """Translate the entire arrow (tail + head) by delta."""
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

    def _rebuild_path(self):
        # Build arrowhead polygon + shaft endpoint
        dx = self._head.x() - self._tail.x()
        dy = self._head.y() - self._tail.y()
        length = math.hypot(dx, dy)
        if length > 0:
            ux, uy = dx / length, dy / length
            bx = self._head.x() - ux * ARROWHEAD_LENGTH
            by = self._head.y() - uy * ARROWHEAD_LENGTH
            px, py = -uy * ARROWHEAD_WIDTH / 2, ux * ARROWHEAD_WIDTH / 2
            nx = bx + ux * ARROWHEAD_NOTCH
            ny = by + uy * ARROWHEAD_NOTCH
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
        stroker.setWidth(SHAFT_THICKNESS + 4)  # slightly wider than visual for easy clicking
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
        color = SELECTED_COLOR if is_sel else ARROW_COLOR

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
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ArrowItem":
        arrow = cls(
            QPointF(data["tail"][0], data["tail"][1]),
            QPointF(data["head"][0], data["head"][1]),
        )
        arrow._label_text = data.get("label_text", "")
        arrow._label_visible = data.get("label_visible", False)
        offset = data.get("label_offset", [DEFAULT_LABEL_OFFSET.x(), DEFAULT_LABEL_OFFSET.y()])
        arrow._label_offset = QPointF(offset[0], offset[1])
        arrow._magnitude = data.get("magnitude", DEFAULT_MAGNITUDE)
        arrow._show_magnitude = data.get("show_magnitude", False)
        arrow._font_size = data.get("font_size", DEFAULT_FONT_SIZE)
        arrow._label_bold = data.get("label_bold", True)
        arrow._label_italic = data.get("label_italic", True)
        arrow._label.set_font_size(arrow._font_size)
        arrow._label.update_display()
        arrow._update_label_visibility()
        arrow._label.update_position()
        return arrow
