from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QUndoCommand

from vector_item import VectorItem


class AddVectorCommand(QUndoCommand):
    """Command to add a vector to the canvas."""

    def __init__(self, canvas, vec: VectorItem):
        super().__init__("Add Vector")
        self._canvas = canvas
        self._vec = vec
        canvas._metadata.total_arrows_created += 1

    def redo(self):
        self._canvas.add_vector(self._vec)
        self._canvas.modified.emit()

    def undo(self):
        self._canvas.remove_vector(self._vec)
        self._canvas.modified.emit()
        self._canvas.selection_changed.emit()


class DeleteVectorCommand(QUndoCommand):
    """Command to delete a vector from the canvas."""

    def __init__(self, canvas, vec: VectorItem):
        super().__init__("Delete Vector")
        self._canvas = canvas
        self._vec = vec
        canvas._metadata.total_arrows_deleted += 1

    def redo(self):
        self._canvas.remove_vector(self._vec)
        self._canvas.modified.emit()
        self._canvas.selection_changed.emit()

    def undo(self):
        self._canvas.add_vector(self._vec)
        self._canvas.modified.emit()


class MoveVectorCommand(QUndoCommand):
    """Command to move an entire vector by a delta."""

    def __init__(self, vec: VectorItem, old_tail: QPointF, new_tail: QPointF):
        super().__init__("Move Vector")
        self._vec = vec
        self._delta = new_tail - old_tail

    def redo(self):
        self._vec.move_by(self._delta)
        if self._vec.on_modified:
            self._vec.on_modified()

    def undo(self):
        self._vec.move_by(-self._delta)
        if self._vec.on_modified:
            self._vec.on_modified()


class ResizeVectorCommand(QUndoCommand):
    """Command to change a vector's tail or head endpoint."""

    def __init__(self, vec: VectorItem, old_tail: QPointF, old_head: QPointF,
                 new_tail: QPointF, new_head: QPointF):
        super().__init__("Resize Vector")
        self._vec = vec
        self._old_tail = QPointF(old_tail)
        self._old_head = QPointF(old_head)
        self._new_tail = QPointF(new_tail)
        self._new_head = QPointF(new_head)

    def redo(self):
        self._vec.set_tail(self._new_tail)
        self._vec.set_head(self._new_head)
        if self._vec.on_modified:
            self._vec.on_modified()

    def undo(self):
        self._vec.set_tail(self._old_tail)
        self._vec.set_head(self._old_head)
        if self._vec.on_modified:
            self._vec.on_modified()


class ChangeLabelTextCommand(QUndoCommand):
    """Command to change a vector's label text."""

    def __init__(self, vec: VectorItem, old_text: str, new_text: str):
        super().__init__("Change Label Text")
        self._vec = vec
        self._old_text = old_text
        self._new_text = new_text

    def redo(self):
        self._vec.label_text = self._new_text
        if self._vec.on_modified:
            self._vec.on_modified()

    def undo(self):
        self._vec.label_text = self._old_text
        if self._vec.on_modified:
            self._vec.on_modified()


class ChangeLabelVisibilityCommand(QUndoCommand):
    """Command to toggle a vector's label visibility."""

    def __init__(self, vec: VectorItem, old_vis: bool, new_vis: bool):
        super().__init__("Toggle Label")
        self._vec = vec
        self._old_vis = old_vis
        self._new_vis = new_vis

    def redo(self):
        self._vec.label_visible = self._new_vis
        if self._vec.on_modified:
            self._vec.on_modified()

    def undo(self):
        self._vec.label_visible = self._old_vis
        if self._vec.on_modified:
            self._vec.on_modified()


class MoveLabelCommand(QUndoCommand):
    """Command to move a label's offset relative to its vector midpoint."""

    def __init__(self, vec: VectorItem, old_offset: QPointF, new_offset: QPointF):
        super().__init__("Move Label")
        self._vec = vec
        self._old_offset = QPointF(old_offset)
        self._new_offset = QPointF(new_offset)

    def redo(self):
        self._vec.label_offset = self._new_offset
        if self._vec.on_modified:
            self._vec.on_modified()

    def undo(self):
        self._vec.label_offset = self._old_offset
        if self._vec.on_modified:
            self._vec.on_modified()


class ChangeMagnitudeCommand(QUndoCommand):
    """Command to change a vector's magnitude value."""

    def __init__(self, vec: VectorItem, old_mag: float, new_mag: float):
        super().__init__("Change Magnitude")
        self._vec = vec
        self._old_mag = old_mag
        self._new_mag = new_mag

    def redo(self):
        self._vec.magnitude = self._new_mag
        if self._vec.on_modified:
            self._vec.on_modified()

    def undo(self):
        self._vec.magnitude = self._old_mag
        if self._vec.on_modified:
            self._vec.on_modified()


class ChangeShowMagnitudeCommand(QUndoCommand):
    """Command to toggle displaying magnitude on the vector label."""

    def __init__(self, vec: VectorItem, old_val: bool, new_val: bool):
        super().__init__("Toggle Magnitude Display")
        self._vec = vec
        self._old_val = old_val
        self._new_val = new_val

    def redo(self):
        self._vec.show_magnitude = self._new_val
        if self._vec.on_modified:
            self._vec.on_modified()

    def undo(self):
        self._vec.show_magnitude = self._old_val
        if self._vec.on_modified:
            self._vec.on_modified()


class ChangeFontSizeCommand(QUndoCommand):
    """Command to change a vector label's font size."""

    def __init__(self, vec: VectorItem, old_size: int, new_size: int):
        super().__init__("Change Font Size")
        self._vec = vec
        self._old_size = old_size
        self._new_size = new_size

    def redo(self):
        self._vec.font_size = self._new_size
        if self._vec.on_modified:
            self._vec.on_modified()

    def undo(self):
        self._vec.font_size = self._old_size
        if self._vec.on_modified:
            self._vec.on_modified()


class ChangeLabelBoldCommand(QUndoCommand):
    """Command to toggle a vector label's bold state."""

    def __init__(self, vec: VectorItem, old_val: bool, new_val: bool):
        super().__init__("Toggle Bold")
        self._vec = vec
        self._old_val = old_val
        self._new_val = new_val

    def redo(self):
        self._vec.label_bold = self._new_val
        if self._vec.on_modified:
            self._vec.on_modified()

    def undo(self):
        self._vec.label_bold = self._old_val
        if self._vec.on_modified:
            self._vec.on_modified()


class ChangeLabelItalicCommand(QUndoCommand):
    """Command to toggle a vector label's italic state."""

    def __init__(self, vec: VectorItem, old_val: bool, new_val: bool):
        super().__init__("Toggle Italic")
        self._vec = vec
        self._old_val = old_val
        self._new_val = new_val

    def redo(self):
        self._vec.label_italic = self._new_val
        if self._vec.on_modified:
            self._vec.on_modified()

    def undo(self):
        self._vec.label_italic = self._old_val
        if self._vec.on_modified:
            self._vec.on_modified()
