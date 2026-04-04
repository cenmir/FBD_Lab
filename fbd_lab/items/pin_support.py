"""PinSupportItem — pin (hinge) support symbol.

A triangle with a rounded top and pin hole, sitting on a wider rectangular
base that fades to transparent. The triangle scales uniformly via one handle;
the base width is independently adjustable via a second handle.
"""

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainter, QPolygonF,
    QLinearGradient, QUndoCommand,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsEllipseItem, QGraphicsPathItem,
    QGraphicsSceneMouseEvent, QStyleOptionGraphicsItem, QWidget,
)

from fbd_lab.items.base import (
    BaseLabel, BaseItemProperties, FillProperties, EdgeProperties, LabelProperties,
    SELECTED_COLOR,
)
from fbd_lab.items.rotation_handle import RotationHandleItem

DEFAULT_HEIGHT = 40.0       # triangle height
DEFAULT_BASE_WIDTH = 80.0   # base rectangle width (wider than triangle)
MIN_SIZE = 10.0
PIN_HOLE_RATIO = 0.12       # pin hole radius as fraction of height
BASE_HEIGHT_RATIO = 0.80    # base rect height as fraction of triangle height
COLOR_BODY = QColor(0xd8, 0xba, 0x94)   # tan triangle
COLOR_EDGE = QColor(0, 0, 0)            # black outline


# ---------------------------------------------------------------------------
# Handles
# ---------------------------------------------------------------------------

class _ScaleHandle(QGraphicsEllipseItem):
    """Bottom-center of triangle — drag to scale the triangle uniformly."""

    def __init__(self, parent_item: "PinSupportItem", r: int = 5):
        super().__init__(-r, -r, 2 * r, 2 * r, parent_item)
        self._p = parent_item
        self.setBrush(QBrush(SELECTED_COLOR))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.setVisible(False)
        self._old_h: float | None = None
        self._busy = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            return QPointF(0, max(MIN_SIZE, value.y()))
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._busy:
            self._busy = True
            self._p._set_height(max(MIN_SIZE, value.y()))
            self._busy = False
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        self._old_h = self._p._height
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._old_h is None:
            return
        old_h = self._old_h
        new_h = self._p._height
        self._old_h = None
        if abs(old_h - new_h) < 0.5:
            return
        push_fn = self._p.on_push_undo
        if push_fn is not None:
            self._p._set_height(old_h)
            from fbd_lab.commands import ChangeShapePropertyCommand
            cmd = ChangeShapePropertyCommand(
                self._p, 'height', old_h, new_h, "Scale Pin Support")
            push_fn(cmd)


class _BaseWidthHandle(QGraphicsEllipseItem):
    """Right edge of the base rectangle — drag to change base width only."""

    def __init__(self, parent_item: "PinSupportItem", r: int = 5):
        super().__init__(-r, -r, 2 * r, 2 * r, parent_item)
        self._p = parent_item
        self.setBrush(QBrush(SELECTED_COLOR))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.setVisible(False)
        self._old_bw: float | None = None
        self._busy = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # Constrain to horizontal, at the vertical center of the base rect
            h = self._p._height
            base_h = h * BASE_HEIGHT_RATIO
            half_bw = max(MIN_SIZE / 2, abs(value.x()))
            return QPointF(half_bw, h + base_h / 2)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._busy:
            self._busy = True
            self._p._set_base_width(abs(value.x()) * 2)
            self._busy = False
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        self._old_bw = self._p._base_width
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._old_bw is None:
            return
        old_bw = self._old_bw
        new_bw = self._p._base_width
        self._old_bw = None
        if abs(old_bw - new_bw) < 0.5:
            return
        push_fn = self._p.on_push_undo
        if push_fn is not None:
            self._p._set_base_width(old_bw)
            from fbd_lab.commands import ChangeShapePropertyCommand
            cmd = ChangeShapePropertyCommand(
                self._p, 'base_width', old_bw, new_bw, "Resize Base")
            push_fn(cmd)


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------

class PinSupportItem(BaseItemProperties, FillProperties, EdgeProperties, LabelProperties, QGraphicsPathItem):
    """A pin (hinge) support symbol.

    Origin (0,0) is at the pin point (top of triangle).
    _height:     triangle height (scales uniformly — width = height)
    _base_width: the wide base rectangle width (independent of triangle)
    """

    _DEFAULT_FILL_COLOR = QColor(COLOR_BODY)
    _DEFAULT_EDGE_COLOR = QColor(COLOR_EDGE)

    def __init__(self, pos: QPointF, parent=None):
        super().__init__(parent)
        self._height = DEFAULT_HEIGHT
        self._base_width = DEFAULT_BASE_WIDTH
        self._show_pin_hole = True

        self.setPos(pos)
        self.setTransformOriginPoint(QPointF(0, self._height / 2 * 0.35))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(1)

        self._scale_handle = _ScaleHandle(self)
        self._base_handle = _BaseWidthHandle(self)
        self._rotation_handle = RotationHandleItem(self)

        self._label = BaseLabel(self)
        self._init_base_properties()
        self._init_fill_properties()
        self._init_edge_properties()
        self._init_label_props()
        self._label.set_font_size(self._font_size)

        self._rebuild()

    # --- Mixin overrides ---

    def label_anchor(self) -> QPointF:
        return QPointF(self.pos())

    def drag_anchor(self) -> QPointF:
        return QPointF(self.pos())

    def _get_handles(self) -> list:
        return [self._scale_handle, self._base_handle, self._rotation_handle]

    # --- Properties ---

    @property
    def height(self) -> float:
        return self._height

    @height.setter
    def height(self, value: float):
        self._set_height(max(MIN_SIZE, value))

    @property
    def base_width(self) -> float:
        return self._base_width

    @base_width.setter
    def base_width(self, value: float):
        self._set_base_width(max(MIN_SIZE, value))

    @property
    def show_pin_hole(self) -> bool:
        return self._show_pin_hole

    @show_pin_hole.setter
    def show_pin_hole(self, value: bool):
        self._show_pin_hole = value
        self.update()

    @property
    def center(self) -> QPointF:
        return QPointF(self.pos())

    @property
    def angle_ccw(self) -> float:
        return -self.rotation()

    @angle_ccw.setter
    def angle_ccw(self, value: float):
        self.setRotation(-value)
        self.update()

    # --- Rotation ---

    def _on_rotation_finished(self, start_rotation: float):
        new_rotation = self.rotation()
        if abs(new_rotation - start_rotation) < 0.01:
            return
        push_fn = self.on_push_undo
        if push_fn is not None:
            self.setRotation(start_rotation)
            from fbd_lab.commands import ChangeRotationCommand
            cmd = ChangeRotationCommand(self, start_rotation, new_rotation)
            push_fn(cmd)

    # --- Movement ---

    def move_by(self, delta: QPointF):
        self.setPos(self.pos() + delta)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    # --- Internal ---

    def _set_height(self, h: float):
        self.prepareGeometryChange()
        self._height = max(MIN_SIZE, h)
        self.setTransformOriginPoint(QPointF(0, self._height / 2 * 0.35))
        self._rebuild()

    def _set_base_width(self, w: float):
        self.prepareGeometryChange()
        self._base_width = max(MIN_SIZE, w)
        self._rebuild()

    def _rebuild(self):
        h = self._height
        # Triangle width = same as height (equilateral-ish)
        tri_half = h / 2

        path = QPainterPath()
        path.moveTo(0, 0)
        path.lineTo(-tri_half, h)
        path.lineTo(tri_half, h)
        path.closeSubpath()
        self.setPath(path)

        # Position handles
        base_h = h * BASE_HEIGHT_RATIO
        self._scale_handle.setPos(0, h)
        self._base_handle.setPos(self._base_width / 2, h + base_h / 2)
        self._rotation_handle.update_position()

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
        h = self._height
        half_bw = self._base_width / 2
        base_h = h * BASE_HEIGHT_RATIO
        margin = 4
        left = -max(h / 2, half_bw) - margin
        right = max(h / 2, half_bw) + margin
        return QRectF(left, -margin, right - left, h + base_h + 2 * margin)

    def shape(self) -> QPainterPath:
        h = self._height
        tri_half = h / 2 + 4
        base_h = h * BASE_HEIGHT_RATIO
        path = QPainterPath()
        path.addRect(QRectF(-tri_half, -4, tri_half * 2, h + base_h + 8))
        return path

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()
        self._scale_handle.setVisible(is_sel)
        self._base_handle.setVisible(is_sel)
        self._rotation_handle.setVisible(is_sel)
        self._label.update_color(is_sel)

        h = self._height
        tri_half = h / 2          # triangle half-width
        half_bw = self._base_width / 2  # base half-width
        pin_r = h * PIN_HOLE_RATIO
        base_h = h * BASE_HEIGHT_RATIO

        fill_col = QColor(self._fill_color)
        fill_col.setAlpha(self._fill_opacity)
        base_color = QColor(
            max(0, fill_col.red() - 60),
            max(0, fill_col.green() - 50),
            max(0, fill_col.blue() - 30),
            fill_col.alpha(),
        )
        edge_col = QColor(SELECTED_COLOR if is_sel else self._edge_color)
        edge_col.setAlpha(self._edge_opacity)
        pen = QPen(edge_col, self._outline_thickness)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # --- Triangle body with rounded top ---
        round_r = tri_half * 0.35
        tri_path = QPainterPath()
        tri_path.moveTo(-tri_half, h)
        tri_path.lineTo(-round_r, round_r)
        arc_rect = QRectF(-round_r, 0, round_r * 2, round_r * 2)
        tri_path.arcTo(arc_rect, 180, -180)
        tri_path.lineTo(tri_half, h)
        tri_path.closeSubpath()

        painter.setPen(pen)
        painter.setBrush(QBrush(fill_col))
        painter.drawPath(tri_path)

        # Pin hole
        if self._show_pin_hole:
            painter.setBrush(QBrush(QColor(255, 255, 255, fill_col.alpha())))
            painter.drawEllipse(QPointF(0, round_r), pin_r, pin_r)

        # --- Base rectangle (fades to transparent) ---
        base_rect = QRectF(-half_bw, h, self._base_width, base_h)
        grad = QLinearGradient(0, h, 0, h + base_h)
        grad.setColorAt(0, base_color)
        grad.setColorAt(1, QColor(base_color.red(), base_color.green(), base_color.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawRect(base_rect)

        painter.restore()

    # --- Serialization ---

    def to_dict(self) -> dict:
        d = self._label_to_dict()
        d.update(self._fill_to_dict())
        d.update(self._edge_to_dict())
        d["center"] = [self.pos().x(), self.pos().y()]
        d["height"] = self._height
        d["base_width"] = self._base_width
        d["show_pin_hole"] = self._show_pin_hole
        d["rotation"] = self.rotation()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "PinSupportItem":
        cx, cy = data["center"]
        item = cls(QPointF(cx, cy))
        item._label_from_dict(data)
        item._fill_from_dict(data)
        item._edge_from_dict(data)
        item._height = data.get("height", DEFAULT_HEIGHT)
        item._base_width = data.get("base_width", DEFAULT_BASE_WIDTH)
        item._show_pin_hole = data.get("show_pin_hole", True)
        item.setRotation(data.get("rotation", 0.0))
        item._rebuild()
        return item
