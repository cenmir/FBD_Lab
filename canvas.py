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
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsLineItem, QApplication,
)

from vector_item import VectorItem
from commands import AddVectorCommand, DeleteVectorCommand, MoveVectorCommand


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


class FBDCanvas(QGraphicsView):
    vector_created = pyqtSignal(object)    # emits the new VectorItem
    selection_changed = pyqtSignal()       # emits when selected vector changes
    tool_changed = pyqtSignal(object)      # emits new ToolMode
    modified = pyqtSignal()                # emits when content changes (dirty flag)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._bg_item: QGraphicsPixmapItem | None = None
        self._vectors: list[VectorItem] = []
        self._undo_stack: QUndoStack | None = None

        # Session metadata
        self._metadata = SessionMetadata()
        self._session_start: float = time.time()

        # Tool state
        self._tool = ToolMode.SELECT
        self._drawing = False
        self._draw_start: QPointF | None = None
        self._preview_line: QGraphicsLineItem | None = None

        # Body-drag state
        self._dragging_vector: VectorItem | None = None
        self._drag_start_tail: QPointF | None = None
        self._drag_last: QPointF | None = None

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
            self._scene.setSceneRect(self._bg_item.boundingRect())
        else:
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

            # Select mode — check if clicking on a vector body for dragging
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

        # Body drag
        if self._dragging_vector and self._drag_last:
            scene_pos = self.mapToScene(event.pos())
            delta = scene_pos - self._drag_last
            self._dragging_vector.move_by(delta)
            self._drag_last = scene_pos
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            # Finish vector creation
            if self._drawing:
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

            # Finish body drag
            if self._dragging_vector:
                vec = self._dragging_vector
                self._dragging_vector = None
                self._drag_last = None

                if self._has_undo_stack() and self._drag_start_tail and vec.tail != self._drag_start_tail:
                    # Vector was already moved during drag. Revert it, then push command
                    # so QUndoStack.push() → redo() re-applies the move consistently.
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

    # --- Keyboard ---

    def delete_selected(self):
        vec = self.get_selected_vector()
        if not vec:
            return
        if self._has_undo_stack():
            cmd = DeleteVectorCommand(self, vec)
            self._undo_stack.push(cmd)
        else:
            self.remove_vector(vec)
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
