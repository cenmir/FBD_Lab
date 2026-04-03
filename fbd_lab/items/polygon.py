"""PolygonItem — a rotatable, editable polygon for FBD diagrams."""

import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainterPathStroker,
    QPainter, QPolygonF,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem,
    QGraphicsSceneMouseEvent, QStyleOptionGraphicsItem, QWidget, QApplication,
)

from fbd_lab.items.base import (
    BaseLabel, BaseItemProperties, FillProperties, EdgeProperties, LabelProperties,
    SELECTED_COLOR,
)
from fbd_lab.items.rotation_handle import RotationHandleItem

POLYGON_FILL_COLOR = QColor(0xD8, 0xBA, 0x94)
POLYGON_OUTLINE_COLOR = QColor(0x8B, 0x6F, 0x4E)


@dataclass
class PolygonSettings:
    handle_radius: int = 6


polygon_settings = PolygonSettings()


class VertexHandle(QGraphicsEllipseItem):
    """Draggable handle at a vertex of a PolygonItem (local coords)."""

    def __init__(self, parent_item: "PolygonItem", vertex_index: int,
                 handle_radius: int = 6):
        # Parent to the PolygonItem so transforms are inherited
        super().__init__(-handle_radius, -handle_radius,
                         2 * handle_radius, 2 * handle_radius, parent_item)
        self._parent_item = parent_item
        self._vertex_index = vertex_index
        self.setBrush(QBrush(SELECTED_COLOR))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.setVisible(False)

        self._drag_old_vertices: list[list[float]] | None = None

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._parent_item._vertex_moved(self._vertex_index, value)
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_vertices = self._parent_item._vertices_as_list()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        if self._drag_old_vertices is None:
            return
        old_verts = self._drag_old_vertices
        new_verts = self._parent_item._vertices_as_list()
        self._drag_old_vertices = None
        if old_verts == new_verts:
            return
        push_fn = self._parent_item.on_push_undo
        if push_fn is not None:
            self._parent_item._set_vertices_from_list(old_verts)
            from fbd_lab.commands import ChangePolygonVerticesCommand
            cmd = ChangePolygonVerticesCommand(self._parent_item, old_verts, new_verts)
            push_fn(cmd)


class PolygonItem(BaseItemProperties, FillProperties, EdgeProperties, LabelProperties, QGraphicsPathItem):
    """A filled polygon that can be moved, edited via vertex handles, and rotated."""

    _DEFAULT_FILL_COLOR = QColor(POLYGON_FILL_COLOR)
    _DEFAULT_EDGE_COLOR = QColor(POLYGON_OUTLINE_COLOR)

    def __init__(self, center: QPointF, vertices: list[QPointF], parent=None):
        """
        center: scene position of the polygon
        vertices: list of QPointF in local coords (relative to center)
        """
        super().__init__(parent)
        self._init_fill_properties()
        self._init_edge_properties()

        self.setPos(center)
        self._vertices = [QPointF(v) for v in vertices]
        self.setTransformOriginPoint(QPointF(0, 0))

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(1)

        # Vertex handles
        r = polygon_settings.handle_radius
        self._handles = [VertexHandle(self, i, r) for i in range(len(vertices))]

        # Rotation handle
        self._rotation_handle = RotationHandleItem(self)

        # Label
        self._label = BaseLabel(self)
        self._init_base_properties()
        self._init_label_props()
        self._label.set_font_size(self._font_size)

        self._rebuild()

    # --- Mixin overrides ---

    def label_anchor(self) -> QPointF:
        return self.mapToScene(self._centroid())

    def drag_anchor(self) -> QPointF:
        return QPointF(self.pos())

    def _get_handles(self) -> list:
        return list(self._handles) + [self._rotation_handle]

    # --- Geometry helpers ---

    def _centroid(self) -> QPointF:
        if not self._vertices:
            return QPointF(0, 0)
        cx = sum(v.x() for v in self._vertices) / len(self._vertices)
        cy = sum(v.y() for v in self._vertices) / len(self._vertices)
        return QPointF(cx, cy)

    def _vertices_as_list(self) -> list[list[float]]:
        return [[v.x(), v.y()] for v in self._vertices]

    def _set_vertices_from_list(self, verts: list[list[float]]):
        self._vertices = [QPointF(v[0], v[1]) for v in verts]
        # Recreate handles if count changed
        if len(self._handles) != len(self._vertices):
            self._recreate_handles()
        self._rebuild()

    def _recreate_handles(self):
        """Rebuild vertex handles to match current vertex count."""
        # Old handles are children — removing from scene removes them
        scene = self.scene()
        for h in self._handles:
            if scene:
                scene.removeItem(h)
        r = polygon_settings.handle_radius
        # New handles parented to self — auto-added to scene
        self._handles = [VertexHandle(self, i, r) for i in range(len(self._vertices))]

    # --- Movement ---

    def move_by(self, delta: QPointF):
        self.setPos(self.pos() + delta)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    # --- Vertex manipulation ---

    def _vertex_moved(self, index: int, new_pos: QPointF):
        if 0 <= index < len(self._vertices):
            self._vertices[index] = QPointF(new_pos)
            self._rebuild()

    # --- Scene management (handles are children, only label needs manual add) ---

    def added_to_scene(self, scene):
        scene.addItem(self._label)

    def removed_from_scene(self, scene):
        scene.removeItem(self._label)

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

    # --- Drawing ---

    def _rebuild(self):
        path = QPainterPath()
        if self._vertices:
            poly = QPolygonF(self._vertices)
            path.addPolygon(poly)
            path.closeSubpath()
        self.setPath(path)

        # Update vertex handles
        for i, handle in enumerate(self._handles):
            handle.setPos(self._vertices[i])

        self._rotation_handle.update_position()
        self._label.update_position()

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        if self._vertices:
            poly = QPolygonF(self._vertices)
            path.addPolygon(poly)
            path.closeSubpath()
        stroker = QPainterPathStroker()
        stroker.setWidth(6)
        return stroker.createStroke(path) | path

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()

        for h in self._handles:
            h.setVisible(is_sel)
        self._rotation_handle.setVisible(is_sel)
        self._label.update_color(is_sel)

        if self._vertices:
            poly = QPolygonF(self._vertices)

            # Edge
            edge_col = QColor(SELECTED_COLOR if is_sel else self._edge_color)
            edge_col.setAlpha(self._edge_opacity)
            painter.setPen(QPen(edge_col, self._outline_thickness))

            # Fill
            fill_col = QColor(self._fill_color)
            fill_col.setAlpha(self._fill_opacity)
            painter.setBrush(QBrush(fill_col))

            painter.drawPolygon(poly)

    # --- Serialization ---

    def to_dict(self) -> dict:
        d = self._label_to_dict()
        d.update(self._fill_to_dict())
        d.update(self._edge_to_dict())
        d["center"] = [self.pos().x(), self.pos().y()]
        d["vertices"] = self._vertices_as_list()
        d["rotation"] = self.rotation()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "PolygonItem":
        center = QPointF(data["center"][0], data["center"][1])
        verts = [QPointF(v[0], v[1]) for v in data["vertices"]]
        item = cls(center, verts)
        item._label_from_dict(data)
        item._fill_from_dict(data)
        item._edge_from_dict(data)
        item.setRotation(data.get("rotation", 0.0))
        item._rebuild()
        return item

    def refresh_style(self):
        r = polygon_settings.handle_radius
        for h in self._handles:
            h.setRect(-r, -r, 2 * r, 2 * r)
        self._rebuild()
        self.update()
