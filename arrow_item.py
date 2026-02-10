import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QPen, QBrush, QColor, QPainterPath, QPolygonF, QPainter
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem,
    QStyleOptionGraphicsItem, QWidget, QApplication,
)

SNAP_ANGLE_DEG = 5

ARROW_COLOR = QColor(220, 50, 50)
SELECTED_COLOR = QColor(50, 150, 255)
ARROW_THICKNESS = 6
HANDLE_RADIUS = 6
ARROWHEAD_LENGTH = 20
ARROWHEAD_WIDTH = 14


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
            # Snap unless Ctrl is held
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


class ArrowItem(QGraphicsPathItem):
    """A straight arrow from tail to head with an arrowhead."""

    def __init__(self, tail: QPointF, head: QPointF, parent=None):
        super().__init__(parent)
        self._tail = QPointF(tail)
        self._head = QPointF(head)
        self._label_text = ""
        self._label_visible = False

        self.on_modified = None  # callback, set by canvas
        self._pen_normal = QPen(ARROW_COLOR, ARROW_THICKNESS)
        self._pen_selected = QPen(SELECTED_COLOR, ARROW_THICKNESS)
        self.setPen(self._pen_normal)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        # Control points (added to scene later)
        self._tail_handle = ControlPoint(tail.x(), tail.y(), self, is_head=False)
        self._head_handle = ControlPoint(head.x(), head.y(), self, is_head=True)

        self._rebuild_path()

    def added_to_scene(self, scene):
        """Call after adding this item to the scene to also add control points."""
        scene.addItem(self._tail_handle)
        scene.addItem(self._head_handle)

    def removed_from_scene(self, scene):
        """Call before removing this item to also remove control points."""
        scene.removeItem(self._tail_handle)
        scene.removeItem(self._head_handle)

    @property
    def tail(self) -> QPointF:
        return QPointF(self._tail)

    @property
    def head(self) -> QPointF:
        return QPointF(self._head)

    @property
    def magnitude(self) -> float:
        dx = self._head.x() - self._tail.x()
        dy = self._head.y() - self._tail.y()
        return math.hypot(dx, dy)

    @property
    def label_text(self) -> str:
        return self._label_text

    @label_text.setter
    def label_text(self, value: str):
        self._label_text = value
        self.update()

    @property
    def label_visible(self) -> bool:
        return self._label_visible

    @label_visible.setter
    def label_visible(self, value: bool):
        self._label_visible = value
        self.update()

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
        path = QPainterPath()
        path.moveTo(self._tail)
        path.lineTo(self._head)

        # Arrowhead
        dx = self._head.x() - self._tail.x()
        dy = self._head.y() - self._tail.y()
        length = math.hypot(dx, dy)
        if length > 0:
            ux, uy = dx / length, dy / length
            # Base of arrowhead
            bx = self._head.x() - ux * ARROWHEAD_LENGTH
            by = self._head.y() - uy * ARROWHEAD_LENGTH
            # Perpendicular
            px, py = -uy * ARROWHEAD_WIDTH / 2, ux * ARROWHEAD_WIDTH / 2

            triangle = QPolygonF([
                self._head,
                QPointF(bx + px, by + py),
                QPointF(bx - px, by - py),
            ])
            path.addPolygon(triangle)
            path.closeSubpath()

        self.setPath(path)
        if self.on_modified:
            self.on_modified()

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()
        self.setPen(self._pen_selected if is_sel else self._pen_normal)

        # Fill arrowhead
        brush = QBrush(SELECTED_COLOR if is_sel else ARROW_COLOR)
        self.setBrush(brush)

        # Show/hide control points
        self._tail_handle.setVisible(is_sel)
        self._head_handle.setVisible(is_sel)

        super().paint(painter, option, widget)

        # Draw label
        if self._label_visible and self._label_text:
            mid = (self._tail + self._head) / 2
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(mid + QPointF(8, -8), self._label_text)

    def boundingRect(self) -> QRectF:
        r = super().boundingRect()
        # Expand for label text
        if self._label_visible and self._label_text:
            r = r.adjusted(-20, -20, 80, 20)
        return r

    def to_dict(self) -> dict:
        return {
            "tail": [self._tail.x(), self._tail.y()],
            "head": [self._head.x(), self._head.y()],
            "label_text": self._label_text,
            "label_visible": self._label_visible,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ArrowItem":
        arrow = cls(
            QPointF(data["tail"][0], data["tail"][1]),
            QPointF(data["head"][0], data["head"][1]),
        )
        arrow.label_text = data.get("label_text", "")
        arrow.label_visible = data.get("label_visible", False)
        return arrow
