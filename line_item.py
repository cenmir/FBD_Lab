import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainterPathStroker,
    QPolygonF, QPainter,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem,
    QGraphicsTextItem, QStyleOptionGraphicsItem, QWidget,
    QApplication, QGraphicsSceneMouseEvent,
)

from vector_item import (
    label_to_html, get_cm_font,
    LABEL_COLOR, SELECTED_COLOR, DEFAULT_LABEL_OFFSET, DEFAULT_FONT_SIZE,
    SNAP_ANGLE_DEG,
)

LINE_BODY_COLOR = QColor(173, 216, 230)    # light blue
LINE_OUTLINE_COLOR = QColor(0, 0, 0)       # black


DEFAULT_BODY_THICKNESS = 10
DEFAULT_OUTLINE_THICKNESS = 2


@dataclass
class LineSettings:
    handle_radius: int = 6


line_settings = LineSettings()  # global singleton


class LineLabel(QGraphicsTextItem):
    """Draggable label attached to a line, rendered with HTML formatting."""

    def __init__(self, line: "LineItem"):
        super().__init__()
        self._line = line
        self._drag_old_offset: QPointF | None = None
        self._updating = False

        self.setDefaultTextColor(LABEL_COLOR)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(5)
        self.setVisible(False)

    def set_font_size(self, size: int):
        self.setFont(get_cm_font(size))

    def update_display(self):
        ln = self._line
        html = label_to_html(ln._label_text, ln._label_bold, ln._label_italic)
        self.setHtml(html)

    def update_color(self, selected: bool):
        self.setDefaultTextColor(SELECTED_COLOR if selected else LABEL_COLOR)
        self.update_display()

    def update_position(self):
        self._updating = True
        mid = (self._line._tail + self._line._head) / 2
        self.setPos(mid + self._line._label_offset)
        self._updating = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._updating:
            mid = (self._line._tail + self._line._head) / 2
            self._line._label_offset = value - mid
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_offset = QPointF(self._line._label_offset)
        if not self._line.isSelected():
            if self.scene():
                self.scene().clearSelection()
            self._line.setSelected(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        if self._drag_old_offset is None:
            return
        new_offset = QPointF(self._line._label_offset)
        old_offset = self._drag_old_offset
        self._drag_old_offset = None
        if new_offset == old_offset:
            return
        push_fn = self._line.on_push_undo
        if push_fn is not None:
            self._line._label_offset = QPointF(old_offset)
            self.update_position()
            from commands import MoveLabelCommand
            cmd = MoveLabelCommand(self._line, old_offset, new_offset)
            push_fn(cmd)


class LineControlPoint(QGraphicsEllipseItem):
    """Draggable handle at the tail or head of a line."""

    def __init__(self, x: float, y: float, line: "LineItem", is_head: bool):
        r = line_settings.handle_radius
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.setPos(x, y)
        self._line = line
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
                anchor = self._line.tail if self._is_head else self._line.head
                value = self._snap(anchor, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if self._is_head:
                self._line.set_head(value)
            else:
                self._line.set_tail(value)
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_tail = QPointF(self._line.tail)
        self._drag_old_head = QPointF(self._line.head)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        if self._drag_old_tail is None:
            return
        new_tail = QPointF(self._line.tail)
        new_head = QPointF(self._line.head)
        old_tail = self._drag_old_tail
        old_head = self._drag_old_head
        self._drag_old_tail = None
        self._drag_old_head = None
        if new_tail == old_tail and new_head == old_head:
            return
        push_fn = self._line.on_push_undo
        if push_fn is not None:
            self._line.set_tail(old_tail)
            self._line.set_head(old_head)
            from commands import ResizeLineCommand
            cmd = ResizeLineCommand(self._line, old_tail, old_head, new_tail, new_head)
            push_fn(cmd)


class LineItem(QGraphicsPathItem):
    """A solid line rendered as a filled rectangle from tail to head."""

    def __init__(self, tail: QPointF, head: QPointF, parent=None):
        super().__init__(parent)
        self._tail = QPointF(tail)
        self._head = QPointF(head)
        self._label_text = ""
        self._label_visible = False
        self._label_offset = QPointF(DEFAULT_LABEL_OFFSET)
        self._font_size = DEFAULT_FONT_SIZE
        self._label_bold = True
        self._label_italic = True
        self._body_thickness = DEFAULT_BODY_THICKNESS
        self._outline_thickness = DEFAULT_OUTLINE_THICKNESS

        self._z_order = 0

        self.on_modified = None
        self.on_push_undo = None

        self._rect_polygon: QPolygonF | None = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        self._tail_handle = LineControlPoint(tail.x(), tail.y(), self, is_head=False)
        self._head_handle = LineControlPoint(head.x(), head.y(), self, is_head=True)

        self._label = LineLabel(self)
        self._label.set_font_size(self._font_size)

        self._rebuild_path()

    def added_to_scene(self, scene):
        scene.addItem(self._tail_handle)
        scene.addItem(self._head_handle)
        scene.addItem(self._label)

    def removed_from_scene(self, scene):
        scene.removeItem(self._tail_handle)
        scene.removeItem(self._head_handle)
        scene.removeItem(self._label)

    # --- Properties ---

    @property
    def tail(self) -> QPointF:
        return QPointF(self._tail)

    @property
    def head(self) -> QPointF:
        return QPointF(self._head)

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
    def body_thickness(self) -> int:
        return self._body_thickness

    @body_thickness.setter
    def body_thickness(self, value: int):
        self._body_thickness = value
        self._rebuild_path()

    @property
    def outline_thickness(self) -> int:
        return self._outline_thickness

    @outline_thickness.setter
    def outline_thickness(self, value: int):
        self._outline_thickness = value
        self.update()

    def _update_label_visibility(self):
        self._label.setVisible(self._label_visible and bool(self._label_text))

    # --- Movement ---

    def move_by(self, delta: QPointF):
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

    # --- Style ---

    def refresh_style(self):
        """Rebuild from current line_settings."""
        r = line_settings.handle_radius
        self._tail_handle.setRect(-r, -r, 2 * r, 2 * r)
        self._head_handle.setRect(-r, -r, 2 * r, 2 * r)
        self._rebuild_path()
        self.update()

    # --- Drawing ---

    def _rebuild_path(self):
        dx = self._head.x() - self._tail.x()
        dy = self._head.y() - self._tail.y()
        length = math.hypot(dx, dy)

        if length > 0:
            half_w = self._body_thickness / 2
            # Perpendicular unit vector
            px = -dy / length * half_w
            py = dx / length * half_w
            self._rect_polygon = QPolygonF([
                QPointF(self._tail.x() + px, self._tail.y() + py),
                QPointF(self._head.x() + px, self._head.y() + py),
                QPointF(self._head.x() - px, self._head.y() - py),
                QPointF(self._tail.x() - px, self._tail.y() - py),
            ])
        else:
            self._rect_polygon = None

        path = QPainterPath()
        if self._rect_polygon is not None:
            path.addPolygon(self._rect_polygon)
            path.closeSubpath()
        else:
            path.moveTo(self._tail)
            path.lineTo(self._head)
        self.setPath(path)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    def shape(self) -> QPainterPath:
        if self._rect_polygon is not None:
            path = QPainterPath()
            path.addPolygon(self._rect_polygon)
            path.closeSubpath()
            # Add a small stroke around the polygon for easier clicking
            stroker = QPainterPathStroker()
            stroker.setWidth(4)
            return stroker.createStroke(path) | path
        stroker = QPainterPathStroker()
        stroker.setWidth(self._body_thickness + 4)
        shaft_path = QPainterPath()
        shaft_path.moveTo(self._tail)
        shaft_path.lineTo(self._head)
        return stroker.createStroke(shaft_path)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()
        outline_color = SELECTED_COLOR if is_sel else LINE_OUTLINE_COLOR

        self._tail_handle.setVisible(is_sel)
        self._head_handle.setVisible(is_sel)
        self._label.update_color(is_sel)

        if self._rect_polygon is not None:
            # Fill the rectangle body
            painter.setPen(QPen(outline_color, self._outline_thickness))
            painter.setBrush(QBrush(LINE_BODY_COLOR))
            painter.drawPolygon(self._rect_polygon)

    # --- Serialization ---

    def to_dict(self) -> dict:
        return {
            "tail": [self._tail.x(), self._tail.y()],
            "head": [self._head.x(), self._head.y()],
            "label_text": self._label_text,
            "label_visible": self._label_visible,
            "label_offset": [self._label_offset.x(), self._label_offset.y()],
            "font_size": self._font_size,
            "label_bold": self._label_bold,
            "label_italic": self._label_italic,
            "body_thickness": self._body_thickness,
            "outline_thickness": self._outline_thickness,
            "z_order": self._z_order,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LineItem":
        ln = cls(
            QPointF(data["tail"][0], data["tail"][1]),
            QPointF(data["head"][0], data["head"][1]),
        )
        ln._label_text = data.get("label_text", "")
        ln._label_visible = data.get("label_visible", False)
        offset = data.get("label_offset", [DEFAULT_LABEL_OFFSET.x(), DEFAULT_LABEL_OFFSET.y()])
        ln._label_offset = QPointF(offset[0], offset[1])
        ln._font_size = data.get("font_size", DEFAULT_FONT_SIZE)
        ln._label_bold = data.get("label_bold", True)
        ln._label_italic = data.get("label_italic", True)
        ln._body_thickness = data.get("body_thickness", DEFAULT_BODY_THICKNESS)
        ln._outline_thickness = data.get("outline_thickness", DEFAULT_OUTLINE_THICKNESS)
        ln._label.set_font_size(ln._font_size)
        ln._label.update_display()
        ln._update_label_visibility()
        ln._label.update_position()
        ln._rebuild_path()
        z = data.get("z_order", 0)
        if z != 0:
            ln.z_order = z
        return ln
