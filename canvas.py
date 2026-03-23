import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QPointF
from PyQt6.QtGui import (
    QPixmap, QDragEnterEvent, QDropEvent, QKeyEvent,
    QImage, QKeySequence, QMouseEvent, QPen, QColor, QPainter,
    QUndoStack, QBrush, QPolygonF,
)
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsLineItem, QGraphicsPolygonItem,
    QGraphicsEllipseItem, QApplication, QMenu,
)

from vector_item import VectorItem
from point_item import PointItem
from direction_item import DirectionItem
from line_item import LineItem
from moment_item import MomentItem
from rectangle_item import RectangleItem
from polygon_item import PolygonItem
from ellipse_item import EllipseItem
from text_item import TextItem
from spring_item import SpringItem
from squiggle_item import SquiggleItem
from commands import (
    AddItemCommand, DeleteItemCommand, MoveItemCommand,
    ChangeRadiusCommand, ChangeZValueCommand,
)


@dataclass
class SessionMetadata:
    machine_username: str = ""
    machine_hostname: str = ""
    created_at: float = 0.0
    last_saved_at: float = 0.0
    total_edit_seconds: float = 0.0
    session_count: int = 0
    undo_count: int = 0
    total_arrows_created: int = 0
    total_arrows_deleted: int = 0

    def to_dict(self) -> dict:
        return {
            "machine_username": self.machine_username,
            "machine_hostname": self.machine_hostname,
            "created_at": self.created_at,
            "last_saved_at": self.last_saved_at,
            "total_edit_seconds": self.total_edit_seconds,
            "session_count": self.session_count,
            "undo_count": self.undo_count,
            "total_arrows_created": self.total_arrows_created,
            "total_arrows_deleted": self.total_arrows_deleted,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionMetadata":
        return cls(
            machine_username=data.get("machine_username", ""),
            machine_hostname=data.get("machine_hostname", ""),
            created_at=data.get("created_at", 0.0),
            last_saved_at=data.get("last_saved_at", 0.0),
            total_edit_seconds=data.get("total_edit_seconds", 0.0),
            session_count=data.get("session_count", 0),
            undo_count=data.get("undo_count", 0),
            total_arrows_created=data.get("total_arrows_created", 0),
            total_arrows_deleted=data.get("total_arrows_deleted", 0),
        )


class ToolMode(Enum):
    SELECT = auto()
    VECTOR = auto()
    POINT = auto()
    DIRECTION = auto()
    LINE = auto()
    MOMENT = auto()
    RECTANGLE = auto()
    POLYGON = auto()
    ELLIPSE = auto()
    TEXT = auto()
    SPRING = auto()
    SQUIGGLE = auto()


class FBDCanvas(QGraphicsView):
    vector_created = pyqtSignal(object)    # emits the new VectorItem
    selection_changed = pyqtSignal()       # emits when selected item changes
    tool_changed = pyqtSignal(object)      # emits new ToolMode
    modified = pyqtSignal()                # emits when content changes (dirty flag)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        # White canvas background (sits below everything)
        self._canvas_rect = QGraphicsRectItem(0, 0, 800, 600)
        self._canvas_rect.setBrush(QBrush(QColor(255, 255, 255)))
        self._canvas_rect.setPen(QPen(Qt.PenStyle.NoPen))
        self._canvas_rect.setZValue(-2000)
        self._canvas_rect.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)
        self._canvas_rect.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)
        self._scene.addItem(self._canvas_rect)

        self._bg_item: QGraphicsPixmapItem | None = None
        self._undo_stack: QUndoStack | None = None

        # Item registry — single source of truth for all item lists
        self._items: dict[str, list] = {
            'vectors': [],
            'points': [],
            'directions': [],
            'lines': [],
            'moments': [],
            'rectangles': [],
            'polygons': [],
            'ellipses': [],
            'texts': [],
            'springs': [],
            'squiggles': [],
        }
        self._visibility: dict[str, bool] = {
            'vectors': True,
            'points': True,
            'directions': True,
            'lines': True,
            'moments': True,
            'rectangles': True,
            'polygons': True,
            'ellipses': True,
            'texts': True,
            'springs': True,
            'squiggles': True,
        }
        self._type_classes: dict[str, type] = {
            'vectors': VectorItem,
            'points': PointItem,
            'directions': DirectionItem,
            'lines': LineItem,
            'moments': MomentItem,
            'rectangles': RectangleItem,
            'polygons': PolygonItem,
            'ellipses': EllipseItem,
            'texts': TextItem,
            'springs': SpringItem,
            'squiggles': SquiggleItem,
        }

        # Session metadata
        self._metadata = SessionMetadata()
        self._session_start: float = time.time()

        # Tool state
        self._tool = ToolMode.SELECT
        self._drawing = False
        self._draw_start: QPointF | None = None
        self._preview_line: QGraphicsLineItem | None = None

        # Unified body-drag state (vectors, points, directions, lines)
        self._dragging_item = None
        self._drag_anchor: QPointF | None = None   # item.drag_anchor() at drag start
        self._drag_last: QPointF | None = None

        # Radius-drag state (moments)
        self._dragging_moment_radius: MomentItem | None = None
        self._drag_moment_old_radius: float | None = None

        # Rectangle preview (QGraphicsRectItem instead of line)
        self._preview_rect: QGraphicsRectItem | None = None

        # Ellipse preview
        self._preview_ellipse: QGraphicsEllipseItem | None = None

        # Polygon creation state
        self._polygon_vertices: list[QPointF] = []
        self._polygon_preview_lines: list[QGraphicsLineItem] = []
        self._polygon_tracking_line: QGraphicsLineItem | None = None
        self._polygon_close_marker: QGraphicsEllipseItem | None = None
        self._polygon_preview_fill: QGraphicsPolygonItem | None = None
        _POLYGON_CLOSE_DIST = 15  # pixels to snap-close

        # Clipboard for copy/paste
        self._clipboard: list[tuple[str, dict]] = []  # [(type_key, item_dict), ...]
        self._last_mouse_scene = QPointF(0, 0)

        # Background visibility (separate from item registry)
        self._bg_visible = True

        # Rendering
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Enable drag and drop
        self.setAcceptDrops(True)

        # Notify when scene selection changes
        self._scene.selectionChanged.connect(self._on_scene_selection_changed)

    def _has_undo_stack(self) -> bool:
        return self._undo_stack is not None

    def set_undo_stack(self, stack: QUndoStack):
        self._undo_stack = stack

    @property
    def metadata(self) -> SessionMetadata:
        return self._metadata

    @metadata.setter
    def metadata(self, val: SessionMetadata):
        self._metadata = val
        self._session_start = time.time()

    def accumulate_session_time(self):
        now = time.time()
        self._metadata.total_edit_seconds += now - self._session_start
        self._session_start = now

    def set_tool(self, mode: ToolMode):
        self._tool = mode
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        if mode == ToolMode.SELECT:
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        # Cancel polygon drawing if switching away
        if mode != ToolMode.POLYGON:
            self._cancel_polygon()
        self.tool_changed.emit(mode)

    def _cancel_polygon(self):
        """Remove all polygon preview items and clear vertices."""
        for line in self._polygon_preview_lines:
            self._scene.removeItem(line)
        self._polygon_preview_lines.clear()
        if self._polygon_tracking_line:
            self._scene.removeItem(self._polygon_tracking_line)
            self._polygon_tracking_line = None
        if self._polygon_close_marker:
            self._scene.removeItem(self._polygon_close_marker)
            self._polygon_close_marker = None
        if self._polygon_preview_fill:
            self._scene.removeItem(self._polygon_preview_fill)
            self._polygon_preview_fill = None
        self._polygon_vertices.clear()

    def _finish_polygon(self):
        """Complete polygon from accumulated vertices."""
        verts = self._polygon_vertices
        if len(verts) < 3:
            self._cancel_polygon()
            return
        # Compute centroid and make vertices local
        cx = sum(v.x() for v in verts) / len(verts)
        cy = sum(v.y() for v in verts) / len(verts)
        center = QPointF(cx, cy)
        local_verts = [QPointF(v.x() - cx, v.y() - cy) for v in verts]
        poly = PolygonItem(center, local_verts)
        if self._has_undo_stack():
            cmd = AddItemCommand(self, poly, 'polygons')
            self._undo_stack.push(cmd)
        else:
            self.add_polygon(poly)
            self.modified.emit()
        self._scene.clearSelection()
        poly.setSelected(True)
        # Clean up all preview items
        for line in self._polygon_preview_lines:
            self._scene.removeItem(line)
        self._polygon_preview_lines.clear()
        if self._polygon_tracking_line:
            self._scene.removeItem(self._polygon_tracking_line)
            self._polygon_tracking_line = None
        if self._polygon_close_marker:
            self._scene.removeItem(self._polygon_close_marker)
            self._polygon_close_marker = None
        if self._polygon_preview_fill:
            self._scene.removeItem(self._polygon_preview_fill)
            self._polygon_preview_fill = None
        self._polygon_vertices.clear()
        self.set_tool(ToolMode.SELECT)

    # --- Background ---

    def set_background(self, pixmap: QPixmap):
        if self._bg_item is not None:
            self._scene.removeItem(self._bg_item)
            self._bg_item = None

        if not pixmap.isNull():
            self._bg_item = QGraphicsPixmapItem(pixmap)
            self._bg_item.setZValue(-1000)
            self._bg_item.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable, False)
            self._bg_item.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable, False)
            self._scene.addItem(self._bg_item)
            if not self._bg_visible:
                self._bg_item.setVisible(False)
            rect = self._bg_item.boundingRect()
            self._canvas_rect.setRect(rect)
            self._scene.setSceneRect(rect)
        else:
            self._canvas_rect.setRect(0, 0, 800, 600)
            self._scene.setSceneRect(0, 0, 800, 600)

        self.modified.emit()

    def load_background_from_file(self, file_path: str | Path):
        pixmap = QPixmap(str(file_path))
        if not pixmap.isNull():
            self.set_background(pixmap)

    def get_background_pixmap(self) -> QPixmap | None:
        if self._bg_item is not None:
            return self._bg_item.pixmap()
        return None

    # --- Generic item registry methods ---

    def _add_item(self, type_key: str, item):
        items = self._items[type_key]
        if item not in items:
            self._scene.addItem(item)
            item.added_to_scene(self._scene)
            item.on_modified = lambda: self.modified.emit()
            if self._has_undo_stack():
                item.on_push_undo = lambda cmd: self._undo_stack.push(cmd)
            items.append(item)
            if not self._visibility[type_key]:
                item.set_layer_visible(False)

    def _remove_item(self, type_key: str, item):
        items = self._items[type_key]
        if item in items:
            item.removed_from_scene(self._scene)
            self._scene.removeItem(item)
            items.remove(item)

    def _get_items(self, type_key: str) -> list:
        return list(self._items[type_key])

    def _get_items_data(self, type_key: str) -> list[dict]:
        return [item.to_dict() for item in self._items[type_key]]

    def _get_selected_item(self, item_class: type):
        for item in self._scene.selectedItems():
            if isinstance(item, item_class):
                return item
        return None

    def _clear_items(self, type_key: str):
        for item in list(self._items[type_key]):
            self._remove_item(type_key, item)

    def _set_type_visible(self, type_key: str, visible: bool):
        self._visibility[type_key] = visible
        for item in self._items[type_key]:
            item.set_layer_visible(visible)

    # --- Public wrappers (backward compat) ---

    def add_vector(self, vec):          self._add_item('vectors', vec)
    def remove_vector(self, vec):       self._remove_item('vectors', vec)
    def get_vectors(self):              return self._get_items('vectors')
    def get_vectors_data(self):         return self._get_items_data('vectors')
    def get_selected_vector(self):      return self._get_selected_item(VectorItem)
    def clear_vectors(self):            self._clear_items('vectors')

    def add_point(self, pt):            self._add_item('points', pt)
    def remove_point(self, pt):         self._remove_item('points', pt)
    def get_points(self):               return self._get_items('points')
    def get_points_data(self):          return self._get_items_data('points')
    def get_selected_point(self):       return self._get_selected_item(PointItem)
    def clear_points(self):             self._clear_items('points')

    def add_direction(self, d):         self._add_item('directions', d)
    def remove_direction(self, d):      self._remove_item('directions', d)
    def get_directions(self):           return self._get_items('directions')
    def get_directions_data(self):      return self._get_items_data('directions')
    def get_selected_direction(self):   return self._get_selected_item(DirectionItem)
    def clear_directions(self):         self._clear_items('directions')

    def add_line(self, ln):             self._add_item('lines', ln)
    def remove_line(self, ln):          self._remove_item('lines', ln)
    def get_lines(self):                return self._get_items('lines')
    def get_lines_data(self):           return self._get_items_data('lines')
    def get_selected_line(self):        return self._get_selected_item(LineItem)
    def clear_lines(self):              self._clear_items('lines')

    def add_moment(self, m):            self._add_item('moments', m)
    def remove_moment(self, m):         self._remove_item('moments', m)
    def get_moments(self):              return self._get_items('moments')
    def get_moments_data(self):         return self._get_items_data('moments')
    def get_selected_moment(self):      return self._get_selected_item(MomentItem)
    def clear_moments(self):            self._clear_items('moments')

    def add_rectangle(self, r):         self._add_item('rectangles', r)
    def remove_rectangle(self, r):      self._remove_item('rectangles', r)
    def get_rectangles(self):           return self._get_items('rectangles')
    def get_rectangles_data(self):      return self._get_items_data('rectangles')
    def get_selected_rectangle(self):   return self._get_selected_item(RectangleItem)
    def clear_rectangles(self):         self._clear_items('rectangles')

    def add_polygon(self, p):           self._add_item('polygons', p)
    def remove_polygon(self, p):        self._remove_item('polygons', p)
    def get_polygons(self):             return self._get_items('polygons')
    def get_polygons_data(self):        return self._get_items_data('polygons')
    def get_selected_polygon(self):     return self._get_selected_item(PolygonItem)
    def clear_polygons(self):           self._clear_items('polygons')

    def add_ellipse(self, e):           self._add_item('ellipses', e)
    def remove_ellipse(self, e):        self._remove_item('ellipses', e)
    def get_ellipses(self):             return self._get_items('ellipses')
    def get_ellipses_data(self):        return self._get_items_data('ellipses')
    def get_selected_ellipse(self):     return self._get_selected_item(EllipseItem)
    def clear_ellipses(self):           self._clear_items('ellipses')

    def add_text(self, t):              self._add_item('texts', t)
    def remove_text(self, t):           self._remove_item('texts', t)
    def get_texts(self):                return self._get_items('texts')
    def get_texts_data(self):           return self._get_items_data('texts')
    def get_selected_text(self):        return self._get_selected_item(TextItem)
    def clear_texts(self):              self._clear_items('texts')

    def add_spring(self, s):            self._add_item('springs', s)
    def remove_spring(self, s):         self._remove_item('springs', s)
    def get_springs(self):              return self._get_items('springs')
    def get_springs_data(self):         return self._get_items_data('springs')
    def get_selected_spring(self):      return self._get_selected_item(SpringItem)
    def clear_springs(self):            self._clear_items('springs')

    def add_squiggle(self, s):          self._add_item('squiggles', s)
    def remove_squiggle(self, s):       self._remove_item('squiggles', s)
    def get_squiggles(self):            return self._get_items('squiggles')
    def get_squiggles_data(self):       return self._get_items_data('squiggles')
    def get_selected_squiggle(self):    return self._get_selected_item(SquiggleItem)
    def clear_squiggles(self):          self._clear_items('squiggles')

    # --- Layer visibility ---

    def set_background_visible(self, visible: bool):
        self._bg_visible = visible
        if self._bg_item is not None:
            self._bg_item.setVisible(visible)

    def set_vectors_visible(self, visible):     self._set_type_visible('vectors', visible)
    def set_points_visible(self, visible):      self._set_type_visible('points', visible)
    def set_directions_visible(self, visible):  self._set_type_visible('directions', visible)
    def set_lines_visible(self, visible):       self._set_type_visible('lines', visible)
    def set_moments_visible(self, visible):     self._set_type_visible('moments', visible)
    def set_rectangles_visible(self, visible):  self._set_type_visible('rectangles', visible)
    def set_polygons_visible(self, visible):    self._set_type_visible('polygons', visible)
    def set_ellipses_visible(self, visible):   self._set_type_visible('ellipses', visible)
    def set_texts_visible(self, visible):      self._set_type_visible('texts', visible)
    def set_springs_visible(self, visible):    self._set_type_visible('springs', visible)
    def set_squiggles_visible(self, visible):  self._set_type_visible('squiggles', visible)

    # --- Snapping ---

    SNAP_ANGLE_DEG = 5  # snap when within this many degrees of H or V

    @staticmethod
    def _snap_endpoint(start: QPointF, end: QPointF, snap: bool) -> QPointF:
        """Snap end to vertical or horizontal if within SNAP_ANGLE_DEG degrees."""
        if not snap:
            return end
        import math
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 1:
            return end
        angle = math.degrees(math.atan2(abs(dy), abs(dx)))  # 0=horizontal, 90=vertical
        threshold = FBDCanvas.SNAP_ANGLE_DEG
        if angle <= threshold:
            return QPointF(end.x(), start.y())
        elif angle >= 90 - threshold:
            return QPointF(start.x(), end.y())
        return end

    # --- Mouse events ---

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            # Vector creation mode
            if self._tool == ToolMode.VECTOR:
                self._drawing = True
                self._draw_start = self.mapToScene(event.pos())
                self._preview_line = QGraphicsLineItem()
                self._preview_line.setPen(QPen(QColor(0, 0, 0, 180), 2, Qt.PenStyle.DashLine))
                self._preview_line.setZValue(100)
                self._scene.addItem(self._preview_line)
                return

            # Direction creation mode (same click-drag as vector)
            if self._tool == ToolMode.DIRECTION:
                self._drawing = True
                self._draw_start = self.mapToScene(event.pos())
                self._preview_line = QGraphicsLineItem()
                self._preview_line.setPen(QPen(QColor(0, 0, 0, 180), 2, Qt.PenStyle.DashLine))
                self._preview_line.setZValue(100)
                self._scene.addItem(self._preview_line)
                return

            # Spring creation mode (click-drag like vector)
            if self._tool == ToolMode.SPRING:
                self._drawing = True
                self._draw_start = self.mapToScene(event.pos())
                self._preview_line = QGraphicsLineItem()
                self._preview_line.setPen(QPen(QColor(0, 0, 0, 180), 2, Qt.PenStyle.DashLine))
                self._preview_line.setZValue(100)
                self._scene.addItem(self._preview_line)
                return

            # Squiggle/denotation line mode (click-drag)
            if self._tool == ToolMode.SQUIGGLE:
                self._drawing = True
                self._draw_start = self.mapToScene(event.pos())
                self._preview_line = QGraphicsLineItem()
                self._preview_line.setPen(QPen(QColor(0, 0, 0, 180), 2, Qt.PenStyle.DashLine))
                self._preview_line.setZValue(100)
                self._scene.addItem(self._preview_line)
                return

            # Line creation mode (same click-drag as vector)
            if self._tool == ToolMode.LINE:
                self._drawing = True
                self._draw_start = self.mapToScene(event.pos())
                self._preview_line = QGraphicsLineItem()
                self._preview_line.setPen(QPen(QColor(0, 0, 0, 180), 2, Qt.PenStyle.DashLine))
                self._preview_line.setZValue(100)
                self._scene.addItem(self._preview_line)
                return

            # Moment creation mode (click-drag: click = center, drag distance = radius)
            if self._tool == ToolMode.MOMENT:
                self._drawing = True
                self._draw_start = self.mapToScene(event.pos())
                self._preview_line = QGraphicsLineItem()
                self._preview_line.setPen(QPen(QColor(220, 50, 50, 180), 2, Qt.PenStyle.DashLine))
                self._preview_line.setZValue(100)
                self._scene.addItem(self._preview_line)
                return

            # Rectangle creation mode (click-drag: corner to corner)
            if self._tool == ToolMode.RECTANGLE:
                self._drawing = True
                self._draw_start = self.mapToScene(event.pos())
                self._preview_rect = QGraphicsRectItem()
                self._preview_rect.setPen(QPen(QColor(0x8B, 0x6F, 0x4E, 200), 2, Qt.PenStyle.DashLine))
                self._preview_rect.setBrush(QBrush(QColor(0xD8, 0xBA, 0x94, 100)))
                self._preview_rect.setZValue(100)
                self._scene.addItem(self._preview_rect)
                return

            # Ellipse creation mode (click-drag: bounding box corners, CTRL = circle)
            if self._tool == ToolMode.ELLIPSE:
                self._drawing = True
                self._draw_start = self.mapToScene(event.pos())
                self._preview_ellipse = QGraphicsEllipseItem()
                self._preview_ellipse.setPen(QPen(QColor(0x4A, 0x90, 0xA8, 200), 2, Qt.PenStyle.DashLine))
                self._preview_ellipse.setBrush(QBrush(QColor(0xA8, 0xD8, 0xEA, 100)))
                self._preview_ellipse.setZValue(100)
                self._scene.addItem(self._preview_ellipse)
                return

            # Polygon creation mode (click to add vertices, click near first to close)
            if self._tool == ToolMode.POLYGON:
                scene_pos = self.mapToScene(event.pos())
                # Check if closing the polygon (click near first vertex)
                if len(self._polygon_vertices) >= 3:
                    import math
                    first = self._polygon_vertices[0]
                    dist = math.hypot(scene_pos.x() - first.x(), scene_pos.y() - first.y())
                    if dist < 15:
                        self._finish_polygon()
                        return
                self._polygon_vertices.append(scene_pos)
                # Draw solid edge from previous vertex
                if len(self._polygon_vertices) >= 2:
                    prev = self._polygon_vertices[-2]
                    line = QGraphicsLineItem(prev.x(), prev.y(), scene_pos.x(), scene_pos.y())
                    line.setPen(QPen(QColor(0x8B, 0x6F, 0x4E, 200), 2))
                    line.setZValue(100)
                    self._scene.addItem(line)
                    self._polygon_preview_lines.append(line)
                return

            # Point creation mode
            if self._tool == ToolMode.POINT:
                scene_pos = self.mapToScene(event.pos())
                point = PointItem(scene_pos)
                point.label_text = f"P_{len(self._items['points']) + 1}"
                point.label_visible = True

                if self._has_undo_stack():
                    cmd = AddItemCommand(self, point, 'points')
                    self._undo_stack.push(cmd)
                else:
                    self.add_point(point)
                    self.modified.emit()

                self._scene.clearSelection()
                point.setSelected(True)
                self.selection_changed.emit()
                self.set_tool(ToolMode.SELECT)
                return

            # Text creation mode (single click to place)
            if self._tool == ToolMode.TEXT:
                scene_pos = self.mapToScene(event.pos())
                txt = TextItem(scene_pos)
                if self._has_undo_stack():
                    cmd = AddItemCommand(self, txt, 'texts')
                    self._undo_stack.push(cmd)
                else:
                    self.add_text(txt)
                    self.modified.emit()
                self._scene.clearSelection()
                txt.setSelected(True)
                self.selection_changed.emit()
                self.set_tool(ToolMode.SELECT)
                return

            # Select mode — check if clicking on an item body for dragging
            if self._tool == ToolMode.SELECT:
                scene_pos = self.mapToScene(event.pos())
                item = self._scene.itemAt(scene_pos, self.transform())
                if isinstance(item, MomentItem):
                    # Clicking on the arc body starts a radius drag
                    self._dragging_moment_radius = item
                    self._drag_moment_old_radius = item.radius
                    if not item.isSelected():
                        self._scene.clearSelection()
                        item.setSelected(True)
                    return
                if isinstance(item, (VectorItem, PointItem, DirectionItem, LineItem, RectangleItem, PolygonItem, EllipseItem, TextItem, SpringItem, SquiggleItem)):
                    self._dragging_item = item
                    self._drag_anchor = item.drag_anchor()
                    self._drag_last = scene_pos
                    if not item.isSelected():
                        self._scene.clearSelection()
                        item.setSelected(True)
                    return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        self._last_mouse_scene = self.mapToScene(event.pos())
        # Rectangle creation preview
        if self._drawing and self._preview_rect and self._draw_start:
            end = self.mapToScene(event.pos())
            x1 = min(self._draw_start.x(), end.x())
            y1 = min(self._draw_start.y(), end.y())
            w = abs(end.x() - self._draw_start.x())
            h = abs(end.y() - self._draw_start.y())
            self._preview_rect.setRect(x1, y1, w, h)
            return

        # Ellipse creation preview
        if self._drawing and self._preview_ellipse and self._draw_start:
            end = self.mapToScene(event.pos())
            w = abs(end.x() - self._draw_start.x())
            h = abs(end.y() - self._draw_start.y())
            # CTRL = force circle
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                size = max(w, h)
                w = h = size
            x1 = min(self._draw_start.x(), self._draw_start.x() + (w if end.x() >= self._draw_start.x() else -w))
            y1 = min(self._draw_start.y(), self._draw_start.y() + (h if end.y() >= self._draw_start.y() else -h))
            self._preview_ellipse.setRect(x1, y1, w, h)
            return

        # Vector/Direction/Line/Moment creation preview (line)
        if self._drawing and self._preview_line and self._draw_start:
            end = self.mapToScene(event.pos())
            snap = not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            end = self._snap_endpoint(self._draw_start, end, snap)
            self._preview_line.setLine(
                self._draw_start.x(), self._draw_start.y(),
                end.x(), end.y()
            )
            return

        # Polygon tracking line (from last vertex to cursor)
        if self._tool == ToolMode.POLYGON and self._polygon_vertices:
            import math
            scene_pos = self.mapToScene(event.pos())
            last = self._polygon_vertices[-1]
            # Update or create the tracking line
            if self._polygon_tracking_line is None:
                self._polygon_tracking_line = QGraphicsLineItem()
                self._polygon_tracking_line.setPen(
                    QPen(QColor(0x8B, 0x6F, 0x4E, 150), 2, Qt.PenStyle.DashLine))
                self._polygon_tracking_line.setZValue(100)
                self._scene.addItem(self._polygon_tracking_line)
            self._polygon_tracking_line.setLine(
                last.x(), last.y(), scene_pos.x(), scene_pos.y())
            # Show close indicator when near first vertex
            if len(self._polygon_vertices) >= 3:
                first = self._polygon_vertices[0]
                dist = math.hypot(scene_pos.x() - first.x(), scene_pos.y() - first.y())
                if dist < 15:
                    # Show shaded polygon preview + close marker
                    if self._polygon_close_marker is None:
                        self._polygon_close_marker = QGraphicsEllipseItem(-8, -8, 16, 16)
                        self._polygon_close_marker.setPen(QPen(QColor(0x8B, 0x6F, 0x4E), 2))
                        self._polygon_close_marker.setBrush(QBrush(QColor(0xD8, 0xBA, 0x94, 150)))
                        self._polygon_close_marker.setZValue(101)
                        self._scene.addItem(self._polygon_close_marker)
                    self._polygon_close_marker.setPos(first)
                    self._polygon_close_marker.setVisible(True)
                    # Shaded fill preview
                    if self._polygon_preview_fill is None:
                        self._polygon_preview_fill = QGraphicsPolygonItem()
                        self._polygon_preview_fill.setPen(QPen(QColor(0x8B, 0x6F, 0x4E, 150), 1, Qt.PenStyle.DashLine))
                        self._polygon_preview_fill.setBrush(QBrush(QColor(0xD8, 0xBA, 0x94, 80)))
                        self._polygon_preview_fill.setZValue(99)
                        self._scene.addItem(self._polygon_preview_fill)
                    self._polygon_preview_fill.setPolygon(QPolygonF(self._polygon_vertices))
                    self._polygon_preview_fill.setVisible(True)
                else:
                    if self._polygon_close_marker:
                        self._polygon_close_marker.setVisible(False)
                    if self._polygon_preview_fill:
                        self._polygon_preview_fill.setVisible(False)
            # Don't return — let other events propagate

        # Unified body drag (vector / point / direction / line)
        if self._dragging_item and self._drag_last:
            scene_pos = self.mapToScene(event.pos())
            delta = scene_pos - self._drag_last
            self._dragging_item.move_by(delta)
            self._drag_last = scene_pos
            return

        # Moment radius drag
        if self._dragging_moment_radius:
            import math
            scene_pos = self.mapToScene(event.pos())
            center = self._dragging_moment_radius.center
            new_radius = max(10.0, math.hypot(
                scene_pos.x() - center.x(),
                scene_pos.y() - center.y(),
            ))
            self._dragging_moment_radius.set_radius(new_radius)
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            # Finish vector/direction creation
            if self._drawing:
                creating_tool = self._tool
                self._drawing = False
                end = self.mapToScene(event.pos())
                snap = not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                if self._draw_start:
                    end = self._snap_endpoint(self._draw_start, end, snap)

                if self._preview_line:
                    self._scene.removeItem(self._preview_line)
                    self._preview_line = None
                if self._preview_rect:
                    self._scene.removeItem(self._preview_rect)
                    self._preview_rect = None
                if self._preview_ellipse:
                    self._scene.removeItem(self._preview_ellipse)
                    self._preview_ellipse = None

                if self._draw_start:
                    dx = end.x() - self._draw_start.x()
                    dy = end.y() - self._draw_start.y()
                    if (dx * dx + dy * dy) > 100:  # min 10px
                        if creating_tool == ToolMode.SQUIGGLE:
                            sq = SquiggleItem(self._draw_start, end)
                            if self._has_undo_stack():
                                cmd = AddItemCommand(self, sq, 'squiggles')
                                self._undo_stack.push(cmd)
                            else:
                                self.add_squiggle(sq)
                                self.modified.emit()
                            self._scene.clearSelection()
                            sq.setSelected(True)
                        elif creating_tool == ToolMode.SPRING:
                            sp = SpringItem(self._draw_start, end)
                            if self._has_undo_stack():
                                cmd = AddItemCommand(self, sp, 'springs')
                                self._undo_stack.push(cmd)
                            else:
                                self.add_spring(sp)
                                self.modified.emit()
                            self._scene.clearSelection()
                            sp.setSelected(True)
                        elif creating_tool == ToolMode.DIRECTION:
                            d = DirectionItem(self._draw_start, end)
                            if self._has_undo_stack():
                                cmd = AddItemCommand(self, d, 'directions')
                                self._undo_stack.push(cmd)
                            else:
                                self.add_direction(d)
                                self.modified.emit()
                            self._scene.clearSelection()
                            d.setSelected(True)
                        elif creating_tool == ToolMode.MOMENT:
                            import math
                            center = self._draw_start
                            radius = math.hypot(dx, dy)
                            if radius < 10:
                                radius = 50.0
                            m = MomentItem(center, radius)
                            m.label_text = f"M_{len(self._items['moments']) + 1}"
                            m.label_visible = True
                            if self._has_undo_stack():
                                cmd = AddItemCommand(self, m, 'moments')
                                self._undo_stack.push(cmd)
                            else:
                                self.add_moment(m)
                                self.modified.emit()
                            self._scene.clearSelection()
                            m.setSelected(True)
                        elif creating_tool == ToolMode.RECTANGLE:
                            rect = RectangleItem(self._draw_start, end)
                            if self._has_undo_stack():
                                cmd = AddItemCommand(self, rect, 'rectangles')
                                self._undo_stack.push(cmd)
                            else:
                                self.add_rectangle(rect)
                                self.modified.emit()
                            self._scene.clearSelection()
                            rect.setSelected(True)
                        elif creating_tool == ToolMode.ELLIPSE:
                            # CTRL = force circle
                            w = abs(end.x() - self._draw_start.x())
                            h = abs(end.y() - self._draw_start.y())
                            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                                size = max(w, h)
                                sx = 1 if end.x() >= self._draw_start.x() else -1
                                sy = 1 if end.y() >= self._draw_start.y() else -1
                                end = QPointF(self._draw_start.x() + size * sx,
                                              self._draw_start.y() + size * sy)
                            ell = EllipseItem(self._draw_start, end)
                            if self._has_undo_stack():
                                cmd = AddItemCommand(self, ell, 'ellipses')
                                self._undo_stack.push(cmd)
                            else:
                                self.add_ellipse(ell)
                                self.modified.emit()
                            self._scene.clearSelection()
                            ell.setSelected(True)
                        elif creating_tool == ToolMode.LINE:
                            ln = LineItem(self._draw_start, end)
                            if self._has_undo_stack():
                                cmd = AddItemCommand(self, ln, 'lines')
                                self._undo_stack.push(cmd)
                            else:
                                self.add_line(ln)
                                self.modified.emit()
                            self._scene.clearSelection()
                            ln.setSelected(True)
                        else:
                            vec = VectorItem(self._draw_start, end)
                            vec.label_text = f"F_{len(self._items['vectors']) + 1}"
                            vec.label_visible = True
                            if self._has_undo_stack():
                                self._metadata.total_arrows_created += 1
                                cmd = AddItemCommand(self, vec, 'vectors')
                                self._undo_stack.push(cmd)
                            else:
                                self.add_vector(vec)
                                self.modified.emit()
                            self._scene.clearSelection()
                            vec.setSelected(True)
                            self.vector_created.emit(vec)
                self._draw_start = None
                self.set_tool(ToolMode.SELECT)
                return

            # Finish unified body drag
            if self._dragging_item:
                item = self._dragging_item
                self._dragging_item = None
                self._drag_last = None

                current_anchor = item.drag_anchor()
                if self._has_undo_stack() and self._drag_anchor and current_anchor != self._drag_anchor:
                    original_anchor = self._drag_anchor
                    item.move_by(original_anchor - current_anchor)
                    cmd = MoveItemCommand(item, original_anchor, current_anchor)
                    self._undo_stack.push(cmd)
                else:
                    self.modified.emit()

                self._drag_anchor = None
                self.selection_changed.emit()
                return

            # Finish moment radius drag
            if self._dragging_moment_radius:
                moment = self._dragging_moment_radius
                self._dragging_moment_radius = None
                if self._has_undo_stack() and self._drag_moment_old_radius is not None:
                    new_radius = moment.radius
                    old_radius = self._drag_moment_old_radius
                    if new_radius != old_radius:
                        moment.set_radius(old_radius)
                        cmd = ChangeRadiusCommand(moment, old_radius, new_radius)
                        self._undo_stack.push(cmd)
                else:
                    self.modified.emit()
                self._drag_moment_old_radius = None
                self.selection_changed.emit()
                return

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        # Double-click finishes polygon drawing
        if self._tool == ToolMode.POLYGON and len(self._polygon_vertices) >= 3:
            self._finish_polygon()
            return
        super().mouseDoubleClickEvent(event)

    # --- Selection ---

    def _on_scene_selection_changed(self):
        self.selection_changed.emit()

    # --- Drag & drop ---

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                self.load_background_from_file(file_path)
                event.acceptProposedAction()
                return
        event.ignore()

    # --- Context menu (right-click) ---

    def _find_canvas_item(self, graphics_item):
        """Find the VectorItem/PointItem/DirectionItem/LineItem/MomentItem that owns a graphics item."""
        if isinstance(graphics_item, (VectorItem, PointItem, DirectionItem, LineItem,
                                      MomentItem, RectangleItem, PolygonItem, EllipseItem,
                                      TextItem, SpringItem, SquiggleItem)):
            return graphics_item
        # BaseLabel / BaseControlPoint / Moment handles all use _parent_item
        parent = getattr(graphics_item, '_parent_item', None)
        if parent is not None:
            return parent
        return None

    def _get_all_items(self):
        """Return all canvas items (vectors, points, directions, lines, moments)."""
        result = []
        for items in self._items.values():
            result.extend(items)
        return result

    def _bring_to_front(self, item):
        all_items = self._get_all_items()
        max_z = max((i.z_order for i in all_items if i is not item), default=0)
        new_z = max_z + 1
        if new_z <= item.z_order:
            return
        old_z = item.z_order
        if self._has_undo_stack():
            cmd = ChangeZValueCommand(item, old_z, new_z)
            self._undo_stack.push(cmd)
        else:
            item.z_order = new_z
            self.modified.emit()

    def _send_to_back(self, item):
        all_items = self._get_all_items()
        min_z = min((i.z_order for i in all_items if i is not item), default=0)
        new_z = min_z - 1
        if new_z >= item.z_order:
            return
        old_z = item.z_order
        if self._has_undo_stack():
            cmd = ChangeZValueCommand(item, old_z, new_z)
            self._undo_stack.push(cmd)
        else:
            item.z_order = new_z
            self.modified.emit()

    def bring_selected_to_front(self):
        """Bring the selected item to the front (highest z-order)."""
        for type_key, cls in self._type_classes.items():
            item = self._get_selected_item(cls)
            if item:
                self._bring_to_front(item)
                return

    def send_selected_to_back(self):
        """Send the selected item to the back (lowest z-order)."""
        for type_key, cls in self._type_classes.items():
            item = self._get_selected_item(cls)
            if item:
                self._send_to_back(item)
                return

    def contextMenuEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        item = self._scene.itemAt(scene_pos, self.transform())
        target = self._find_canvas_item(item)

        if target is None:
            super().contextMenuEvent(event)
            return

        if not target.isSelected():
            self._scene.clearSelection()
            target.setSelected(True)
            self.selection_changed.emit()

        menu = QMenu(self)
        bring_front = menu.addAction("Bring to Front")
        send_back = menu.addAction("Send to Back")

        action = menu.exec(event.globalPos())
        if action == bring_front:
            self._bring_to_front(target)
        elif action == send_back:
            self._send_to_back(target)

    # --- Keyboard ---

    def delete_selected(self):
        for type_key, cls in self._type_classes.items():
            item = self._get_selected_item(cls)
            if item:
                if self._has_undo_stack():
                    if type_key == 'vectors':
                        self._metadata.total_arrows_deleted += 1
                    cmd = DeleteItemCommand(self, item, type_key)
                    self._undo_stack.push(cmd)
                else:
                    self._remove_item(type_key, item)
                    self.modified.emit()
                    self.selection_changed.emit()
                return

    def _move_selected_by(self, dx: float, dy: float):
        """Move the selected item by (dx, dy) with undo support."""
        for type_key, cls in self._type_classes.items():
            item = self._get_selected_item(cls)
            if item:
                delta = QPointF(dx, dy)
                old_anchor = item.drag_anchor()
                new_anchor = old_anchor + delta
                if self._has_undo_stack():
                    cmd = MoveItemCommand(item, old_anchor, new_anchor)
                    self._undo_stack.push(cmd)
                else:
                    item.move_by(delta)
                    self.modified.emit()
                return

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Backspace:
            self.delete_selected()
            return

        # Arrow keys: move selected item (Shift = 10px, default = 1px)
        arrow_keys = {
            Qt.Key.Key_Left:  (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up:    (0, -1),
            Qt.Key.Key_Down:  (0, 1),
        }
        if event.key() in arrow_keys:
            dx, dy = arrow_keys[event.key()]
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            self._move_selected_by(dx * step, dy * step)
            return

        if event.matches(QKeySequence.StandardKey.Copy):
            self._copy_selected()
            return

        if event.matches(QKeySequence.StandardKey.Paste):
            # Try pasting diagram items first
            if self._clipboard:
                self._paste_at(self._last_mouse_scene)
                return
            # Fall back to image paste for background
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData()
            if mime.hasImage():
                image = mime.imageData()
                if isinstance(image, QImage) and not image.isNull():
                    self.set_background(QPixmap.fromImage(image))
                    return
            if mime.hasUrls():
                for url in mime.urls():
                    path = url.toLocalFile()
                    if path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                        self.load_background_from_file(path)
                        return
        super().keyPressEvent(event)

    # --- Copy / Paste ---

    _FROM_DICT = {
        'vectors': VectorItem.from_dict,
        'points': PointItem.from_dict,
        'directions': DirectionItem.from_dict,
        'lines': LineItem.from_dict,
        'moments': MomentItem.from_dict,
        'rectangles': RectangleItem.from_dict,
        'polygons': PolygonItem.from_dict,
        'ellipses': EllipseItem.from_dict,
        'texts': TextItem.from_dict,
        'springs': SpringItem.from_dict,
        'squiggles': SquiggleItem.from_dict,
    }

    @staticmethod
    def _item_centroid(type_key: str, d: dict) -> QPointF:
        """Compute the centroid of an item from its serialized dict."""
        if type_key in ('vectors', 'directions', 'lines'):
            tx, ty = d["tail"]
            hx, hy = d["head"]
            return QPointF((tx + hx) / 2, (ty + hy) / 2)
        elif type_key == 'points':
            return QPointF(d["pos"][0], d["pos"][1])
        else:  # moments, rectangles, polygons
            return QPointF(d["center"][0], d["center"][1])

    @staticmethod
    def _offset_item(type_key: str, d: dict, dx: float, dy: float):
        """Offset all position data in a serialized item dict."""
        if type_key in ('vectors', 'directions', 'lines'):
            d["tail"] = [d["tail"][0] + dx, d["tail"][1] + dy]
            d["head"] = [d["head"][0] + dx, d["head"][1] + dy]
        elif type_key == 'points':
            d["pos"] = [d["pos"][0] + dx, d["pos"][1] + dy]
        else:  # moments, rectangles, polygons
            d["center"] = [d["center"][0] + dx, d["center"][1] + dy]
        # Offset label too
        if "label_offset" in d:
            d["label_offset"] = list(d["label_offset"])

    def _copy_selected(self):
        """Copy all selected items to the internal clipboard."""
        copied = []
        for type_key, cls in self._type_classes.items():
            for item in self._scene.selectedItems():
                if isinstance(item, cls):
                    copied.append((type_key, item.to_dict()))
        if copied:
            self._clipboard = copied

    def _paste_at(self, scene_pos: QPointF):
        """Paste clipboard items centered at scene_pos."""
        if not self._clipboard:
            return
        import copy

        # Compute centroid of all copied items
        cx, cy = 0.0, 0.0
        for type_key, d in self._clipboard:
            c = self._item_centroid(type_key, d)
            cx += c.x()
            cy += c.y()
        cx /= len(self._clipboard)
        cy /= len(self._clipboard)

        # Offset to paste position
        dx = scene_pos.x() - cx
        dy = scene_pos.y() - cy

        self._scene.clearSelection()
        for type_key, orig_d in self._clipboard:
            d = copy.deepcopy(orig_d)
            self._offset_item(type_key, d, dx, dy)
            item = self._FROM_DICT[type_key](d)
            if self._has_undo_stack():
                cmd = AddItemCommand(self, item, type_key)
                self._undo_stack.push(cmd)
            else:
                self._add_item(type_key, item)
                self.modified.emit()
            item.setSelected(True)
        self.selection_changed.emit()
