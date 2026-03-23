"""EllipseItem — a rotatable, resizable filled ellipse for FBD diagrams."""

from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainterPathStroker, QPainter,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem,
    QGraphicsSceneMouseEvent, QStyleOptionGraphicsItem, QWidget,
)

from base_item import BaseLabel, LabelPropertiesMixin, SELECTED_COLOR
from rotation_handle import RotationHandleItem

ELLIPSE_FILL_COLOR = QColor(0xA8, 0xD8, 0xEA)    # light blue
ELLIPSE_OUTLINE_COLOR = QColor(0x4A, 0x90, 0xA8)  # darker blue

DEFAULT_FILL_OPACITY = 255
DEFAULT_EDGE_OPACITY = 255
DEFAULT_OUTLINE_THICKNESS = 2


@dataclass
class EllipseSettings:
    handle_radius: int = 6


ellipse_settings = EllipseSettings()


class EllipseCornerHandle(QGraphicsEllipseItem):
    """Draggable handle at a corner of the ellipse bounding rect.

    Corners: 0=TL, 1=TR, 2=BR, 3=BL.
    CTRL constrains resize to maintain aspect ratio (isometric).
    """

    def __init__(self, parent_item: "EllipseItem", corner_index: int,
                 handle_radius: int = 6):
        super().__init__(-handle_radius, -handle_radius,
                         2 * handle_radius, 2 * handle_radius, parent_item)
        self._parent_item = parent_item
        self._corner_index = corner_index
        self.setBrush(QBrush(SELECTED_COLOR))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.setVisible(False)
        self._drag_old_rect: QRectF | None = None
        self._iso_mode = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            if self._iso_mode:
                return self._constrain_isometric(value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._parent_item._corner_moved(self._corner_index, value)
        return super().itemChange(change, value)

    def _constrain_isometric(self, new_pos: QPointF) -> QPointF:
        """Constrain to maintain aspect ratio."""
        r = self._parent_item._local_rect
        corners = [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]
        opposite = (self._corner_index + 2) % 4
        opp = corners[opposite]
        dx = new_pos.x() - opp.x()
        dy = new_pos.y() - opp.y()
        # Use the larger dimension, maintain sign
        size = max(abs(dx), abs(dy))
        if abs(dx) < 1e-6:
            dx = 1.0
        if abs(dy) < 1e-6:
            dy = 1.0
        return QPointF(opp.x() + size * (1 if dx > 0 else -1),
                       opp.y() + size * (1 if dy > 0 else -1))

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_rect = QRectF(self._parent_item._local_rect)
        self._iso_mode = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        if self._drag_old_rect is None:
            return
        old_rect = self._drag_old_rect
        new_rect = QRectF(self._parent_item._local_rect)
        self._drag_old_rect = None
        self._iso_mode = False
        if old_rect == new_rect:
            return
        push_fn = self._parent_item.on_push_undo
        if push_fn is not None:
            self._parent_item._set_local_rect(old_rect)
            from commands import ChangeRectCommand
            cmd = ChangeRectCommand(self._parent_item, old_rect, new_rect)
            push_fn(cmd)


class EllipseItem(LabelPropertiesMixin, QGraphicsPathItem):
    """A filled ellipse that can be moved, resized via corner handles, and rotated.

    Constructed from two opposite corners of the bounding rectangle.
    """

    def _default_item_color(self) -> QColor:
        return QColor(ELLIPSE_OUTLINE_COLOR)

    def __init__(self, corner1: QPointF, corner2: QPointF, parent=None):
        super().__init__(parent)
        self._outline_thickness = DEFAULT_OUTLINE_THICKNESS
        self._fill_color = QColor(ELLIPSE_FILL_COLOR)
        self._fill_opacity = DEFAULT_FILL_OPACITY
        self._edge_color = QColor(ELLIPSE_OUTLINE_COLOR)
        self._edge_opacity = DEFAULT_EDGE_OPACITY

        # Compute the axis-aligned rect from the two corners
        x1, y1 = min(corner1.x(), corner2.x()), min(corner1.y(), corner2.y())
        x2, y2 = max(corner1.x(), corner2.x()), max(corner1.y(), corner2.y())
        w, h = x2 - x1, y2 - y1

        # Position the item at the rect center; local rect is centered at origin
        center = QPointF((x1 + x2) / 2, (y1 + y2) / 2)
        self.setPos(center)
        self._local_rect = QRectF(-w / 2, -h / 2, w, h)
        self.setTransformOriginPoint(QPointF(0, 0))

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(1)

        # Corner handles: TL, TR, BR, BL
        r = ellipse_settings.handle_radius
        self._handles = [EllipseCornerHandle(self, i, r) for i in range(4)]

        # Rotation handle
        self._rotation_handle = RotationHandleItem(self)

        # Label
        self._label = BaseLabel(self)
        self._init_label_properties()
        self._label.set_font_size(self._font_size)

        self._rebuild()

    # --- LabelPropertiesMixin overrides ---

    def label_anchor(self) -> QPointF:
        return self.mapToScene(self._local_rect.center())

    def drag_anchor(self) -> QPointF:
        return QPointF(self.pos())

    def _get_handles(self) -> list:
        return list(self._handles) + [self._rotation_handle]

    # --- Properties ---

    @property
    def center(self) -> QPointF:
        return QPointF(self.pos())

    @property
    def rect_width(self) -> float:
        return self._local_rect.width()

    @property
    def rect_height(self) -> float:
        return self._local_rect.height()

    @property
    def outline_thickness(self) -> int:
        return self._outline_thickness

    @outline_thickness.setter
    def outline_thickness(self, value: int):
        self._outline_thickness = value
        self.update()

    @property
    def fill_color(self) -> QColor:
        return QColor(self._fill_color)

    @fill_color.setter
    def fill_color(self, value: QColor):
        self._fill_color = QColor(value)
        self.update()

    @property
    def fill_opacity(self) -> int:
        return self._fill_opacity

    @fill_opacity.setter
    def fill_opacity(self, value: int):
        self._fill_opacity = max(0, min(255, value))
        self.update()

    @property
    def edge_color(self) -> QColor:
        return QColor(self._edge_color)

    @edge_color.setter
    def edge_color(self, value: QColor):
        self._edge_color = QColor(value)
        self.update()

    @property
    def edge_opacity(self) -> int:
        return self._edge_opacity

    @edge_opacity.setter
    def edge_opacity(self, value: int):
        self._edge_opacity = max(0, min(255, value))
        self.update()

    @property
    def angle_ccw(self) -> float:
        return -self.rotation()

    @angle_ccw.setter
    def angle_ccw(self, value: float):
        self.setRotation(-value)
        self.update()

    # --- Movement ---

    def move_by(self, delta: QPointF):
        self.setPos(self.pos() + delta)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    # --- Rect manipulation ---

    def _set_local_rect(self, rect: QRectF):
        self._local_rect = QRectF(rect)
        self._rebuild()

    def _corner_moved(self, index: int, new_pos: QPointF):
        """Called when a corner handle is dragged. Opposite corner stays fixed."""
        r = self._local_rect
        corners = [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]
        opposite = (index + 2) % 4
        opp = corners[opposite]
        x1 = min(opp.x(), new_pos.x())
        y1 = min(opp.y(), new_pos.y())
        x2 = max(opp.x(), new_pos.x())
        y2 = max(opp.y(), new_pos.y())
        self._local_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
        self._recenter()
        self._rebuild()

    def _recenter(self):
        c = self._local_rect.center()
        if abs(c.x()) > 0.01 or abs(c.y()) > 0.01:
            self.setPos(self.mapToScene(c))
            w, h = self._local_rect.width(), self._local_rect.height()
            self._local_rect = QRectF(-w / 2, -h / 2, w, h)

    def _get_corners(self) -> list[QPointF]:
        r = self._local_rect
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]

    # --- Rotation ---

    def _on_rotation_finished(self, start_rotation: float):
        new_rotation = self.rotation()
        if abs(new_rotation - start_rotation) < 0.01:
            return
        push_fn = self.on_push_undo
        if push_fn is not None:
            self.setRotation(start_rotation)
            from commands import ChangeRotationCommand
            cmd = ChangeRotationCommand(self, start_rotation, new_rotation)
            push_fn(cmd)

    # --- Scene management ---

    def added_to_scene(self, scene):
        scene.addItem(self._label)

    def removed_from_scene(self, scene):
        scene.removeItem(self._label)

    # --- Drawing ---

    def _rebuild(self):
        path = QPainterPath()
        path.addEllipse(self._local_rect)
        self.setPath(path)

        corners = self._get_corners()
        for i, handle in enumerate(self._handles):
            handle.setPos(corners[i])

        self._rotation_handle.update_position()
        self._label.update_position()

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(self._local_rect)
        stroker = QPainterPathStroker()
        stroker.setWidth(6)
        return stroker.createStroke(path) | path

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()

        for h in self._handles:
            h.setVisible(is_sel)
        self._rotation_handle.setVisible(is_sel)
        self._label.update_color(is_sel)

        r = self._local_rect

        # Edge
        edge_col = QColor(SELECTED_COLOR if is_sel else self._edge_color)
        edge_col.setAlpha(self._edge_opacity)
        painter.setPen(QPen(edge_col, self._outline_thickness))

        # Fill
        fill_col = QColor(self._fill_color)
        fill_col.setAlpha(self._fill_opacity)
        painter.setBrush(QBrush(fill_col))

        painter.drawEllipse(r)

    # --- Serialization ---

    def to_dict(self) -> dict:
        d = self._base_to_dict()
        d["center"] = [self.pos().x(), self.pos().y()]
        d["width"] = self._local_rect.width()
        d["height"] = self._local_rect.height()
        d["rotation"] = self.rotation()
        d["outline_thickness"] = self._outline_thickness
        d["fill_color"] = self._fill_color.name()
        d["fill_opacity"] = self._fill_opacity
        d["edge_color"] = self._edge_color.name()
        d["edge_opacity"] = self._edge_opacity
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "EllipseItem":
        cx, cy = data["center"]
        w, h = data["width"], data["height"]
        corner1 = QPointF(cx - w / 2, cy - h / 2)
        corner2 = QPointF(cx + w / 2, cy + h / 2)
        item = cls(corner1, corner2)
        item._base_from_dict(data)
        item._outline_thickness = data.get("outline_thickness", DEFAULT_OUTLINE_THICKNESS)
        if "fill_color" in data:
            item._fill_color = QColor(data["fill_color"])
        item._fill_opacity = data.get("fill_opacity", DEFAULT_FILL_OPACITY)
        if "edge_color" in data:
            item._edge_color = QColor(data["edge_color"])
        item._edge_opacity = data.get("edge_opacity", DEFAULT_EDGE_OPACITY)
        item.setRotation(data.get("rotation", 0.0))
        item._rebuild()
        return item

    def refresh_style(self):
        r = ellipse_settings.handle_radius
        for h in self._handles:
            h.setRect(-r, -r, 2 * r, 2 * r)
        self._rebuild()
        self.update()
