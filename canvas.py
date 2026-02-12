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
from commands import (
    AddVectorCommand, DeleteVectorCommand, MoveVectorCommand,
    AddPointCommand, DeletePointCommand, MovePointCommand,
    AddDirectionCommand, DeleteDirectionCommand, MoveDirectionCommand,
    AddLineCommand, DeleteLineCommand, MoveLineCommand,
    ChangeZValueCommand,
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
        self._vectors: list[VectorItem] = []
        self._points: list[PointItem] = []
        self._directions: list[DirectionItem] = []
        self._undo_stack: QUndoStack | None = None

        # Session metadata
        self._metadata = SessionMetadata()
        self._session_start: float = time.time()

        # Tool state
        self._tool = ToolMode.SELECT
        self._drawing = False
        self._draw_start: QPointF | None = None
        self._preview_line: QGraphicsLineItem | None = None

        # Body-drag state (vectors)
        self._dragging_vector: VectorItem | None = None
        self._drag_start_tail: QPointF | None = None
        self._drag_last: QPointF | None = None

        # Body-drag state (points)
        self._dragging_point: PointItem | None = None
        self._drag_start_pos: QPointF | None = None
        self._drag_point_last: QPointF | None = None

        # Body-drag state (directions)
        self._dragging_direction: DirectionItem | None = None
        self._drag_dir_start_tail: QPointF | None = None
        self._drag_dir_last: QPointF | None = None

        # Lines
        self._lines: list[LineItem] = []

        # Body-drag state (lines)
        self._dragging_line: LineItem | None = None
        self._drag_line_start_tail: QPointF | None = None
        self._drag_line_last: QPointF | None = None

        # Layer visibility flags
        self._bg_visible = True
        self._vectors_visible = True
        self._points_visible = True
        self._directions_visible = True
        self._lines_visible = True

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
        if mode == ToolMode.SELECT:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif mode == ToolMode.VECTOR:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == ToolMode.POINT:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == ToolMode.DIRECTION:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == ToolMode.LINE:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
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

    # --- Vectors ---

    def add_vector(self, vec: VectorItem):
        if vec not in self._vectors:
            self._scene.addItem(vec)
            vec.added_to_scene(self._scene)
            vec.on_modified = lambda: self.modified.emit()
            if self._has_undo_stack():
                vec.on_push_undo = lambda cmd: self._undo_stack.push(cmd)
            self._vectors.append(vec)
            if not self._vectors_visible:
                vec.setVisible(False)
                vec._label.setVisible(False)
                vec._tail_handle.setVisible(False)
                vec._head_handle.setVisible(False)

    def remove_vector(self, vec: VectorItem):
        if vec in self._vectors:
            vec.removed_from_scene(self._scene)
            self._scene.removeItem(vec)
            self._vectors.remove(vec)

    def get_vectors(self) -> list[VectorItem]:
        return list(self._vectors)

    def get_vectors_data(self) -> list[dict]:
        return [a.to_dict() for a in self._vectors]

    def get_selected_vector(self) -> VectorItem | None:
        for item in self._scene.selectedItems():
            if isinstance(item, VectorItem):
                return item
        return None

    def clear_vectors(self):
        for vec in list(self._vectors):
            self.remove_vector(vec)

    # --- Points ---

    def add_point(self, point: PointItem):
        if point not in self._points:
            self._scene.addItem(point)
            point.added_to_scene(self._scene)
            point.on_modified = lambda: self.modified.emit()
            if self._has_undo_stack():
                point.on_push_undo = lambda cmd: self._undo_stack.push(cmd)
            self._points.append(point)
            if not self._points_visible:
                point.setVisible(False)
                point._label.setVisible(False)

    def remove_point(self, point: PointItem):
        if point in self._points:
            point.removed_from_scene(self._scene)
            self._scene.removeItem(point)
            self._points.remove(point)

    def get_points(self) -> list[PointItem]:
        return list(self._points)

    def get_points_data(self) -> list[dict]:
        return [p.to_dict() for p in self._points]

    def get_selected_point(self) -> PointItem | None:
        for item in self._scene.selectedItems():
            if isinstance(item, PointItem):
                return item
        return None

    def clear_points(self):
        for point in list(self._points):
            self.remove_point(point)

    # --- Directions ---

    def add_direction(self, direction: DirectionItem):
        if direction not in self._directions:
            self._scene.addItem(direction)
            direction.added_to_scene(self._scene)
            direction.on_modified = lambda: self.modified.emit()
            if self._has_undo_stack():
                direction.on_push_undo = lambda cmd: self._undo_stack.push(cmd)
            self._directions.append(direction)
            if not self._directions_visible:
                direction.setVisible(False)
                direction._label.setVisible(False)
                direction._tail_handle.setVisible(False)
                direction._head_handle.setVisible(False)

    def remove_direction(self, direction: DirectionItem):
        if direction in self._directions:
            direction.removed_from_scene(self._scene)
            self._scene.removeItem(direction)
            self._directions.remove(direction)

    def get_directions(self) -> list[DirectionItem]:
        return list(self._directions)

    def get_directions_data(self) -> list[dict]:
        return [d.to_dict() for d in self._directions]

    def get_selected_direction(self) -> DirectionItem | None:
        for item in self._scene.selectedItems():
            if isinstance(item, DirectionItem):
                return item
        return None

    def clear_directions(self):
        for d in list(self._directions):
            self.remove_direction(d)

    # --- Lines ---

    def add_line(self, line: LineItem):
        if line not in self._lines:
            self._scene.addItem(line)
            line.added_to_scene(self._scene)
            line.on_modified = lambda: self.modified.emit()
            if self._has_undo_stack():
                line.on_push_undo = lambda cmd: self._undo_stack.push(cmd)
            self._lines.append(line)
            if not self._lines_visible:
                line.setVisible(False)
                line._label.setVisible(False)
                line._tail_handle.setVisible(False)
                line._head_handle.setVisible(False)

    def remove_line(self, line: LineItem):
        if line in self._lines:
            line.removed_from_scene(self._scene)
            self._scene.removeItem(line)
            self._lines.remove(line)

    def get_lines(self) -> list[LineItem]:
        return list(self._lines)

    def get_lines_data(self) -> list[dict]:
        return [ln.to_dict() for ln in self._lines]

    def get_selected_line(self) -> LineItem | None:
        for item in self._scene.selectedItems():
            if isinstance(item, LineItem):
                return item
        return None

    def clear_lines(self):
        for ln in list(self._lines):
            self.remove_line(ln)

    # --- Layer visibility ---

    def set_background_visible(self, visible: bool):
        self._bg_visible = visible
        if self._bg_item is not None:
            self._bg_item.setVisible(visible)

    def set_vectors_visible(self, visible: bool):
        self._vectors_visible = visible
        for vec in self._vectors:
            vec.setVisible(visible)
            vec._label.setVisible(
                visible and vec._label_visible and bool(vec._label_text)
            )
            vec._tail_handle.setVisible(visible)
            vec._head_handle.setVisible(visible)

    def set_points_visible(self, visible: bool):
        self._points_visible = visible
        for pt in self._points:
            pt.setVisible(visible)
            pt._label.setVisible(
                visible and pt._label_visible and bool(pt._label_text)
            )

    def set_directions_visible(self, visible: bool):
        self._directions_visible = visible
        for d in self._directions:
            d.setVisible(visible)
            d._label.setVisible(
                visible and d._label_visible and bool(d._label_text)
            )
            d._tail_handle.setVisible(visible)
            d._head_handle.setVisible(visible)

    def set_lines_visible(self, visible: bool):
        self._lines_visible = visible
        for ln in self._lines:
            ln.setVisible(visible)
            ln._label.setVisible(
                visible and ln._label_visible and bool(ln._label_text)
            )
            ln._tail_handle.setVisible(visible)
            ln._head_handle.setVisible(visible)

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

            # Point creation mode
            if self._tool == ToolMode.POINT:
                scene_pos = self.mapToScene(event.pos())
                point = PointItem(scene_pos)
                point.label_text = f"P_{len(self._points) + 1}"
                point.label_visible = True

                if self._has_undo_stack():
                    cmd = AddPointCommand(self, point)
                    self._undo_stack.push(cmd)
                else:
                    self.add_point(point)
                    self.modified.emit()

                self._scene.clearSelection()
                point.setSelected(True)
                self.selection_changed.emit()
                self.set_tool(ToolMode.SELECT)
                return

            # Select mode — check if clicking on a vector or point body for dragging
            if self._tool == ToolMode.SELECT:
                scene_pos = self.mapToScene(event.pos())
                item = self._scene.itemAt(scene_pos, self.transform())
                if isinstance(item, VectorItem):
                    self._dragging_vector = item
                    self._drag_start_tail = QPointF(item.tail)
                    self._drag_last = scene_pos
                    if not item.isSelected():
                        self._scene.clearSelection()
                        item.setSelected(True)
                    return
                if isinstance(item, PointItem):
                    self._dragging_point = item
                    self._drag_start_pos = QPointF(item.point_pos)
                    self._drag_point_last = scene_pos
                    if not item.isSelected():
                        self._scene.clearSelection()
                        item.setSelected(True)
                    return
                if isinstance(item, DirectionItem):
                    self._dragging_direction = item
                    self._drag_dir_start_tail = QPointF(item.tail)
                    self._drag_dir_last = scene_pos
                    if not item.isSelected():
                        self._scene.clearSelection()
                        item.setSelected(True)
                    return
                if isinstance(item, LineItem):
                    self._dragging_line = item
                    self._drag_line_start_tail = QPointF(item.tail)
                    self._drag_line_last = scene_pos
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

        # Vector body drag
        if self._dragging_vector and self._drag_last:
            scene_pos = self.mapToScene(event.pos())
            delta = scene_pos - self._drag_last
            self._dragging_vector.move_by(delta)
            self._drag_last = scene_pos
            return

        # Point body drag
        if self._dragging_point and self._drag_point_last:
            scene_pos = self.mapToScene(event.pos())
            delta = scene_pos - self._drag_point_last
            self._dragging_point.move_by(delta)
            self._drag_point_last = scene_pos
            return

        # Direction body drag
        if self._dragging_direction and self._drag_dir_last:
            scene_pos = self.mapToScene(event.pos())
            delta = scene_pos - self._drag_dir_last
            self._dragging_direction.move_by(delta)
            self._drag_dir_last = scene_pos
            return

        # Line body drag
        if self._dragging_line and self._drag_line_last:
            scene_pos = self.mapToScene(event.pos())
            delta = scene_pos - self._drag_line_last
            self._dragging_line.move_by(delta)
            self._drag_line_last = scene_pos
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
                                cmd = AddDirectionCommand(self, d)
                                self._undo_stack.push(cmd)
                            else:
                                self.add_direction(d)
                                self.modified.emit()
                            self._scene.clearSelection()
                            d.setSelected(True)
                        elif creating_tool == ToolMode.LINE:
                            ln = LineItem(self._draw_start, end)
                            if self._has_undo_stack():
                                cmd = AddLineCommand(self, ln)
                                self._undo_stack.push(cmd)
                            else:
                                self.add_line(ln)
                                self.modified.emit()
                            self._scene.clearSelection()
                            ln.setSelected(True)
                        else:
                            vec = VectorItem(self._draw_start, end)
                            vec.label_text = f"F_{len(self._vectors) + 1}"
                            vec.label_visible = True
                            if self._has_undo_stack():
                                cmd = AddVectorCommand(self, vec)
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

            # Finish vector body drag
            if self._dragging_vector:
                vec = self._dragging_vector
                self._dragging_vector = None
                self._drag_last = None

                if self._has_undo_stack() and self._drag_start_tail and vec.tail != self._drag_start_tail:
                    current_tail = QPointF(vec.tail)
                    original_tail = self._drag_start_tail
                    vec.move_by(original_tail - current_tail)
                    cmd = MoveVectorCommand(vec, original_tail, current_tail)
                    self._undo_stack.push(cmd)
                else:
                    self.modified.emit()

                self._drag_start_tail = None
                self.selection_changed.emit()
                return

            # Finish point body drag
            if self._dragging_point:
                point = self._dragging_point
                self._dragging_point = None
                self._drag_point_last = None

                if self._has_undo_stack() and self._drag_start_pos and point.point_pos != self._drag_start_pos:
                    current_pos = QPointF(point.point_pos)
                    original_pos = self._drag_start_pos
                    point.move_by(original_pos - current_pos)
                    cmd = MovePointCommand(point, original_pos, current_pos)
                    self._undo_stack.push(cmd)
                else:
                    self.modified.emit()

                self._drag_start_pos = None
                self.selection_changed.emit()
                return

            # Finish direction body drag
            if self._dragging_direction:
                d = self._dragging_direction
                self._dragging_direction = None
                self._drag_dir_last = None

                if self._has_undo_stack() and self._drag_dir_start_tail and d.tail != self._drag_dir_start_tail:
                    current_tail = QPointF(d.tail)
                    original_tail = self._drag_dir_start_tail
                    d.move_by(original_tail - current_tail)
                    cmd = MoveDirectionCommand(d, original_tail, current_tail)
                    self._undo_stack.push(cmd)
                else:
                    self.modified.emit()

                self._drag_dir_start_tail = None
                self.selection_changed.emit()
                return

            # Finish line body drag
            if self._dragging_line:
                ln = self._dragging_line
                self._dragging_line = None
                self._drag_line_last = None

                if self._has_undo_stack() and self._drag_line_start_tail and ln.tail != self._drag_line_start_tail:
                    current_tail = QPointF(ln.tail)
                    original_tail = self._drag_line_start_tail
                    ln.move_by(original_tail - current_tail)
                    cmd = MoveLineCommand(ln, original_tail, current_tail)
                    self._undo_stack.push(cmd)
                else:
                    self.modified.emit()

                self._drag_line_start_tail = None
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
        """Find the VectorItem/PointItem/DirectionItem/LineItem that owns a graphics item."""
        if isinstance(graphics_item, (VectorItem, PointItem, DirectionItem, LineItem)):
            return graphics_item
        if hasattr(graphics_item, '_vec'):
            return graphics_item._vec
        if hasattr(graphics_item, '_point'):
            return graphics_item._point
        if hasattr(graphics_item, '_dir'):
            return graphics_item._dir
        if hasattr(graphics_item, '_line'):
            return graphics_item._line
        return None

    def _get_all_items(self):
        """Return all canvas items (vectors, points, directions, lines)."""
        return list(self._vectors) + list(self._points) + list(self._directions) + list(self._lines)

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
        vec = self.get_selected_vector()
        if vec:
            if self._has_undo_stack():
                cmd = DeleteVectorCommand(self, vec)
                self._undo_stack.push(cmd)
            else:
                self.remove_vector(vec)
                self.modified.emit()
                self.selection_changed.emit()
            return

        point = self.get_selected_point()
        if point:
            if self._has_undo_stack():
                cmd = DeletePointCommand(self, point)
                self._undo_stack.push(cmd)
            else:
                self.remove_point(point)
                self.modified.emit()
                self.selection_changed.emit()
            return

        direction = self.get_selected_direction()
        if direction:
            if self._has_undo_stack():
                cmd = DeleteDirectionCommand(self, direction)
                self._undo_stack.push(cmd)
            else:
                self.remove_direction(direction)
                self.modified.emit()
                self.selection_changed.emit()
            return

        line = self.get_selected_line()
        if line:
            if self._has_undo_stack():
                cmd = DeleteLineCommand(self, line)
                self._undo_stack.push(cmd)
            else:
                self.remove_line(line)
                self.modified.emit()
                self.selection_changed.emit()

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
