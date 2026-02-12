import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QPointF
from PyQt6.QtGui import (
    QPixmap, QDragEnterEvent, QDropEvent, QKeyEvent,
    QImage, QKeySequence, QMouseEvent, QPen, QColor, QPainter,
    QUndoStack,
)
from PyQt6.QtGui import QBrush
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsLineItem, QApplication, QMenu,
)

from vector_item import VectorItem
from point_item import PointItem
from direction_item import DirectionItem
from line_item import LineItem
from moment_item import MomentItem
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
        }
        self._visibility: dict[str, bool] = {
            'vectors': True,
            'points': True,
            'directions': True,
            'lines': True,
            'moments': True,
        }
        self._type_classes: dict[str, type] = {
            'vectors': VectorItem,
            'points': PointItem,
            'directions': DirectionItem,
            'lines': LineItem,
            'moments': MomentItem,
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
        self.tool_changed.emit(mode)

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
                if isinstance(item, (VectorItem, PointItem, DirectionItem, LineItem)):
                    self._dragging_item = item
                    self._drag_anchor = item.drag_anchor()
                    self._drag_last = scene_pos
                    if not item.isSelected():
                        self._scene.clearSelection()
                        item.setSelected(True)
                    return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        # Vector creation preview
        if self._drawing and self._preview_line and self._draw_start:
            end = self.mapToScene(event.pos())
            snap = not (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            end = self._snap_endpoint(self._draw_start, end, snap)
            self._preview_line.setLine(
                self._draw_start.x(), self._draw_start.y(),
                end.x(), end.y()
            )
            return

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

                if self._draw_start:
                    dx = end.x() - self._draw_start.x()
                    dy = end.y() - self._draw_start.y()
                    if (dx * dx + dy * dy) > 100:  # min 10px
                        if creating_tool == ToolMode.DIRECTION:
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
        if isinstance(graphics_item, (VectorItem, PointItem, DirectionItem, LineItem, MomentItem)):
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

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Backspace:
            self.delete_selected()
            return

        if event.matches(QKeySequence.StandardKey.Paste):
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
