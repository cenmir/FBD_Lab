"""CogItem — standalone center-of-gravity symbol (quadrant circle)."""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainter,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsEllipseItem, QGraphicsPathItem,
    QGraphicsSceneMouseEvent, QStyleOptionGraphicsItem, QWidget,
)

from fbd_lab.items.base import BaseLabel, BaseItemProperties, LabelProperties, SELECTED_COLOR

DEFAULT_RADIUS = 12.0
MIN_RADIUS = 5.0


class CogResizeHandle(QGraphicsEllipseItem):
    """Draggable handle on the edge of the COG circle to resize it."""

    def __init__(self, parent_item: "CogItem", handle_radius: int = 5):
        super().__init__(-handle_radius, -handle_radius,
                         2 * handle_radius, 2 * handle_radius, parent_item)
        self._parent_item = parent_item
        self.setBrush(QBrush(SELECTED_COLOR))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.setVisible(False)
        self._drag_old_radius: float | None = None

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # Constrain to a circle around parent center (0,0)
            import math
            dist = max(MIN_RADIUS, math.hypot(value.x(), value.y()))
            angle = math.atan2(value.y(), value.x())
            return QPointF(dist * math.cos(angle), dist * math.sin(angle))
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            import math
            new_r = math.hypot(value.x(), value.y())
            self._parent_item._set_radius(new_r)
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_radius = self._parent_item._radius
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        if self._drag_old_radius is None:
            return
        old_r = self._drag_old_radius
        new_r = self._parent_item._radius
        self._drag_old_radius = None
        if abs(old_r - new_r) < 0.5:
            return
        push_fn = self._parent_item.on_push_undo
        if push_fn is not None:
            self._parent_item._set_radius(old_r)
            from fbd_lab.commands import ChangeShapePropertyCommand
            cmd = ChangeShapePropertyCommand(
                self._parent_item, 'radius', old_r, new_r, "Resize COG")
            push_fn(cmd)


class CogItem(BaseItemProperties, LabelProperties, QGraphicsPathItem):
    """A standalone center-of-gravity symbol — alternating black/white quadrant circle."""

    def __init__(self, pos: QPointF, parent=None):
        super().__init__(parent)
        self._radius = DEFAULT_RADIUS

        self.setPos(pos)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(1)

        self._handle = CogResizeHandle(self)

        self._label = BaseLabel(self)
        self._init_base_properties()
        self._init_label_props()
        self._label.set_font_size(self._font_size)

        self._rebuild()

    # --- Mixin overrides ---

    def label_anchor(self) -> QPointF:
        return QPointF(self.pos())

    def drag_anchor(self) -> QPointF:
        return QPointF(self.pos())

    def _get_handles(self) -> list:
        return [self._handle]

    # --- Properties ---

    @property
    def radius(self) -> float:
        return self._radius

    @radius.setter
    def radius(self, value: float):
        self._set_radius(max(MIN_RADIUS, value))

    @property
    def center(self) -> QPointF:
        return QPointF(self.pos())

    # --- Movement ---

    def move_by(self, delta: QPointF):
        self.setPos(self.pos() + delta)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    # --- Internal ---

    def _set_radius(self, r: float):
        self.prepareGeometryChange()
        self._radius = max(MIN_RADIUS, r)
        self._rebuild()

    def _rebuild(self):
        r = self._radius
        path = QPainterPath()
        path.addEllipse(QPointF(0, 0), r, r)
        self.setPath(path)
        # Place handle at right edge
        self._handle.setPos(r, 0)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    # --- Scene management ---

    def added_to_scene(self, scene):
        scene.addItem(self._label)

    def removed_from_scene(self, scene):
        scene.removeItem(self._label)

    # --- Drawing ---

    def boundingRect(self) -> QRectF:
        r = self._radius + 2
        return QRectF(-r, -r, 2 * r, 2 * r)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        r = self._radius + 4
        path.addEllipse(QPointF(0, 0), r, r)
        return path

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()
        self._handle.setVisible(is_sel)
        self._label.update_color(is_sel)

        r = self._radius
        arc_rect = QRectF(-r, -r, 2 * r, 2 * r)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Quadrant fills: TL & BR = black, TR & BL = white
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0)))
        painter.drawPie(arc_rect, 90 * 16, 90 * 16)   # TL
        painter.drawPie(arc_rect, 270 * 16, 90 * 16)   # BR
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawPie(arc_rect, 0 * 16, 90 * 16)     # TR
        painter.drawPie(arc_rect, 180 * 16, 90 * 16)   # BL

        # Outline + cross
        outline_color = SELECTED_COLOR if is_sel else QColor(0, 0, 0)
        painter.setPen(QPen(outline_color, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(arc_rect)
        painter.drawLine(QPointF(-r, 0), QPointF(r, 0))
        painter.drawLine(QPointF(0, -r), QPointF(0, r))

        painter.restore()

    # --- Serialization ---

    def to_dict(self) -> dict:
        d = self._label_to_dict()
        d["center"] = [self.pos().x(), self.pos().y()]
        d["radius"] = self._radius
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "CogItem":
        cx, cy = data["center"]
        item = cls(QPointF(cx, cy))
        item._label_from_dict(data)
        item._radius = data.get("radius", DEFAULT_RADIUS)
        item._rebuild()
        return item
