from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QUndoCommand

from vector_item import VectorItem
from point_item import PointItem
from direction_item import DirectionItem
from line_item import LineItem
from moment_item import MomentItem


# ---------------------------------------------------------------------------
# Vector commands
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Point commands
# ---------------------------------------------------------------------------

class AddPointCommand(QUndoCommand):
    """Command to add a point to the canvas."""

    def __init__(self, canvas, point: PointItem):
        super().__init__("Add Point")
        self._canvas = canvas
        self._point = point

    def redo(self):
        self._canvas.add_point(self._point)
        self._canvas.modified.emit()

    def undo(self):
        self._canvas.remove_point(self._point)
        self._canvas.modified.emit()
        self._canvas.selection_changed.emit()


class DeletePointCommand(QUndoCommand):
    """Command to delete a point from the canvas."""

    def __init__(self, canvas, point: PointItem):
        super().__init__("Delete Point")
        self._canvas = canvas
        self._point = point

    def redo(self):
        self._canvas.remove_point(self._point)
        self._canvas.modified.emit()
        self._canvas.selection_changed.emit()

    def undo(self):
        self._canvas.add_point(self._point)
        self._canvas.modified.emit()


class MovePointCommand(QUndoCommand):
    """Command to move a point by a delta."""

    def __init__(self, point: PointItem, old_pos: QPointF, new_pos: QPointF):
        super().__init__("Move Point")
        self._point = point
        self._delta = new_pos - old_pos

    def redo(self):
        self._point.move_by(self._delta)
        if self._point.on_modified:
            self._point.on_modified()

    def undo(self):
        self._point.move_by(-self._delta)
        if self._point.on_modified:
            self._point.on_modified()


# ---------------------------------------------------------------------------
# Direction commands
# ---------------------------------------------------------------------------

class AddDirectionCommand(QUndoCommand):
    """Command to add a direction to the canvas."""

    def __init__(self, canvas, direction: DirectionItem):
        super().__init__("Add Direction")
        self._canvas = canvas
        self._dir = direction

    def redo(self):
        self._canvas.add_direction(self._dir)
        self._canvas.modified.emit()

    def undo(self):
        self._canvas.remove_direction(self._dir)
        self._canvas.modified.emit()
        self._canvas.selection_changed.emit()


class DeleteDirectionCommand(QUndoCommand):
    """Command to delete a direction from the canvas."""

    def __init__(self, canvas, direction: DirectionItem):
        super().__init__("Delete Direction")
        self._canvas = canvas
        self._dir = direction

    def redo(self):
        self._canvas.remove_direction(self._dir)
        self._canvas.modified.emit()
        self._canvas.selection_changed.emit()

    def undo(self):
        self._canvas.add_direction(self._dir)
        self._canvas.modified.emit()


class MoveDirectionCommand(QUndoCommand):
    """Command to move a direction by a delta."""

    def __init__(self, direction: DirectionItem, old_tail: QPointF, new_tail: QPointF):
        super().__init__("Move Direction")
        self._dir = direction
        self._delta = new_tail - old_tail

    def redo(self):
        self._dir.move_by(self._delta)
        if self._dir.on_modified:
            self._dir.on_modified()

    def undo(self):
        self._dir.move_by(-self._delta)
        if self._dir.on_modified:
            self._dir.on_modified()


class ResizeDirectionCommand(QUndoCommand):
    """Command to change a direction's tail or head endpoint."""

    def __init__(self, direction: DirectionItem, old_tail: QPointF, old_head: QPointF,
                 new_tail: QPointF, new_head: QPointF):
        super().__init__("Resize Direction")
        self._dir = direction
        self._old_tail = QPointF(old_tail)
        self._old_head = QPointF(old_head)
        self._new_tail = QPointF(new_tail)
        self._new_head = QPointF(new_head)

    def redo(self):
        self._dir.set_tail(self._new_tail)
        self._dir.set_head(self._new_head)
        if self._dir.on_modified:
            self._dir.on_modified()

    def undo(self):
        self._dir.set_tail(self._old_tail)
        self._dir.set_head(self._old_head)
        if self._dir.on_modified:
            self._dir.on_modified()


# ---------------------------------------------------------------------------
# Line commands
# ---------------------------------------------------------------------------

class AddLineCommand(QUndoCommand):
    """Command to add a line to the canvas."""

    def __init__(self, canvas, line: LineItem):
        super().__init__("Add Line")
        self._canvas = canvas
        self._line = line

    def redo(self):
        self._canvas.add_line(self._line)
        self._canvas.modified.emit()

    def undo(self):
        self._canvas.remove_line(self._line)
        self._canvas.modified.emit()
        self._canvas.selection_changed.emit()


class DeleteLineCommand(QUndoCommand):
    """Command to delete a line from the canvas."""

    def __init__(self, canvas, line: LineItem):
        super().__init__("Delete Line")
        self._canvas = canvas
        self._line = line

    def redo(self):
        self._canvas.remove_line(self._line)
        self._canvas.modified.emit()
        self._canvas.selection_changed.emit()

    def undo(self):
        self._canvas.add_line(self._line)
        self._canvas.modified.emit()


class MoveLineCommand(QUndoCommand):
    """Command to move a line by a delta."""

    def __init__(self, line: LineItem, old_tail: QPointF, new_tail: QPointF):
        super().__init__("Move Line")
        self._line = line
        self._delta = new_tail - old_tail

    def redo(self):
        self._line.move_by(self._delta)
        if self._line.on_modified:
            self._line.on_modified()

    def undo(self):
        self._line.move_by(-self._delta)
        if self._line.on_modified:
            self._line.on_modified()


class ResizeLineCommand(QUndoCommand):
    """Command to change a line's tail or head endpoint."""

    def __init__(self, line: LineItem, old_tail: QPointF, old_head: QPointF,
                 new_tail: QPointF, new_head: QPointF):
        super().__init__("Resize Line")
        self._line = line
        self._old_tail = QPointF(old_tail)
        self._old_head = QPointF(old_head)
        self._new_tail = QPointF(new_tail)
        self._new_head = QPointF(new_head)

    def redo(self):
        self._line.set_tail(self._new_tail)
        self._line.set_head(self._new_head)
        if self._line.on_modified:
            self._line.on_modified()

    def undo(self):
        self._line.set_tail(self._old_tail)
        self._line.set_head(self._old_head)
        if self._line.on_modified:
            self._line.on_modified()


class ChangeBodyThicknessCommand(QUndoCommand):
    """Command to change a line's body thickness."""

    def __init__(self, line: LineItem, old_val: int, new_val: int):
        super().__init__("Change Body Thickness")
        self._line = line
        self._old_val = old_val
        self._new_val = new_val

    def redo(self):
        self._line.body_thickness = self._new_val
        if self._line.on_modified:
            self._line.on_modified()

    def undo(self):
        self._line.body_thickness = self._old_val
        if self._line.on_modified:
            self._line.on_modified()


class ChangeOutlineThicknessCommand(QUndoCommand):
    """Command to change a line's outline thickness."""

    def __init__(self, line: LineItem, old_val: int, new_val: int):
        super().__init__("Change Outline Thickness")
        self._line = line
        self._old_val = old_val
        self._new_val = new_val

    def redo(self):
        self._line.outline_thickness = self._new_val
        if self._line.on_modified:
            self._line.on_modified()

    def undo(self):
        self._line.outline_thickness = self._old_val
        if self._line.on_modified:
            self._line.on_modified()


# ---------------------------------------------------------------------------
# Moment commands
# ---------------------------------------------------------------------------

class AddMomentCommand(QUndoCommand):
    """Command to add a moment to the canvas."""

    def __init__(self, canvas, moment: MomentItem):
        super().__init__("Add Moment")
        self._canvas = canvas
        self._moment = moment

    def redo(self):
        self._canvas.add_moment(self._moment)
        self._canvas.modified.emit()

    def undo(self):
        self._canvas.remove_moment(self._moment)
        self._canvas.modified.emit()
        self._canvas.selection_changed.emit()


class DeleteMomentCommand(QUndoCommand):
    """Command to delete a moment from the canvas."""

    def __init__(self, canvas, moment: MomentItem):
        super().__init__("Delete Moment")
        self._canvas = canvas
        self._moment = moment

    def redo(self):
        self._canvas.remove_moment(self._moment)
        self._canvas.modified.emit()
        self._canvas.selection_changed.emit()

    def undo(self):
        self._canvas.add_moment(self._moment)
        self._canvas.modified.emit()


class MoveMomentCommand(QUndoCommand):
    """Command to move a moment's center."""

    def __init__(self, moment: MomentItem, old_center: QPointF, new_center: QPointF):
        super().__init__("Move Moment")
        self._moment = moment
        self._old_center = QPointF(old_center)
        self._new_center = QPointF(new_center)

    def redo(self):
        self._moment.set_center(self._new_center)
        if self._moment.on_modified:
            self._moment.on_modified()

    def undo(self):
        self._moment.set_center(self._old_center)
        if self._moment.on_modified:
            self._moment.on_modified()


class ChangeRadiusCommand(QUndoCommand):
    """Command to change a moment's radius."""

    def __init__(self, moment: MomentItem, old_radius: float, new_radius: float):
        super().__init__("Change Radius")
        self._moment = moment
        self._old_radius = old_radius
        self._new_radius = new_radius

    def redo(self):
        self._moment.set_radius(self._new_radius)
        if self._moment.on_modified:
            self._moment.on_modified()

    def undo(self):
        self._moment.set_radius(self._old_radius)
        if self._moment.on_modified:
            self._moment.on_modified()


class ChangeAnglesCommand(QUndoCommand):
    """Command to change a moment's start and span angles."""

    def __init__(self, moment: MomentItem, old_start: float, old_span: float,
                 new_start: float, new_span: float):
        super().__init__("Change Angles")
        self._moment = moment
        self._old_start = old_start
        self._old_span = old_span
        self._new_start = new_start
        self._new_span = new_span

    def redo(self):
        self._moment.set_angles(self._new_start, self._new_span)
        if self._moment.on_modified:
            self._moment.on_modified()

    def undo(self):
        self._moment.set_angles(self._old_start, self._old_span)
        if self._moment.on_modified:
            self._moment.on_modified()


class ChangeZValueCommand(QUndoCommand):
    """Command to change an item's z-order (Bring to Front / Send to Back)."""

    def __init__(self, item, old_z: int, new_z: int):
        super().__init__("Change Z-Order")
        self._item = item
        self._old_z = old_z
        self._new_z = new_z

    def redo(self):
        self._item.z_order = self._new_z
        if self._item.on_modified:
            self._item.on_modified()

    def undo(self):
        self._item.z_order = self._old_z
        if self._item.on_modified:
            self._item.on_modified()


class ChangeShowArrowheadCommand(QUndoCommand):
    """Command to toggle a direction's arrowhead visibility."""

    def __init__(self, direction: DirectionItem, old_val: bool, new_val: bool):
        super().__init__("Toggle Arrowhead")
        self._dir = direction
        self._old_val = old_val
        self._new_val = new_val

    def redo(self):
        self._dir.show_arrowhead = self._new_val
        if self._dir.on_modified:
            self._dir.on_modified()

    def undo(self):
        self._dir.show_arrowhead = self._old_val
        if self._dir.on_modified:
            self._dir.on_modified()


# ---------------------------------------------------------------------------
# Shared label commands (work with any item that has the label interface)
# ---------------------------------------------------------------------------

class ChangeLabelTextCommand(QUndoCommand):
    """Command to change an item's label text."""

    def __init__(self, item, old_text: str, new_text: str):
        super().__init__("Change Label Text")
        self._item = item
        self._old_text = old_text
        self._new_text = new_text

    def redo(self):
        self._item.label_text = self._new_text
        if self._item.on_modified:
            self._item.on_modified()

    def undo(self):
        self._item.label_text = self._old_text
        if self._item.on_modified:
            self._item.on_modified()


class ChangeLabelVisibilityCommand(QUndoCommand):
    """Command to toggle an item's label visibility."""

    def __init__(self, item, old_vis: bool, new_vis: bool):
        super().__init__("Toggle Label")
        self._item = item
        self._old_vis = old_vis
        self._new_vis = new_vis

    def redo(self):
        self._item.label_visible = self._new_vis
        if self._item.on_modified:
            self._item.on_modified()

    def undo(self):
        self._item.label_visible = self._old_vis
        if self._item.on_modified:
            self._item.on_modified()


class MoveLabelCommand(QUndoCommand):
    """Command to move a label's offset relative to its parent item."""

    def __init__(self, item, old_offset: QPointF, new_offset: QPointF):
        super().__init__("Move Label")
        self._item = item
        self._old_offset = QPointF(old_offset)
        self._new_offset = QPointF(new_offset)

    def redo(self):
        self._item.label_offset = self._new_offset
        if self._item.on_modified:
            self._item.on_modified()

    def undo(self):
        self._item.label_offset = self._old_offset
        if self._item.on_modified:
            self._item.on_modified()


# ---------------------------------------------------------------------------
# Vector-specific property commands
# ---------------------------------------------------------------------------

class ChangeMagnitudeCommand(QUndoCommand):
    """Command to change a vector's magnitude value."""

    def __init__(self, vec: VectorItem, old_mag: str, new_mag: str):
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


# ---------------------------------------------------------------------------
# Shared style commands (work with any item that has the style interface)
# ---------------------------------------------------------------------------

class ChangeFontSizeCommand(QUndoCommand):
    """Command to change a label's font size."""

    def __init__(self, item, old_size: int, new_size: int):
        super().__init__("Change Font Size")
        self._item = item
        self._old_size = old_size
        self._new_size = new_size

    def redo(self):
        self._item.font_size = self._new_size
        if self._item.on_modified:
            self._item.on_modified()

    def undo(self):
        self._item.font_size = self._old_size
        if self._item.on_modified:
            self._item.on_modified()


class ChangeLabelBoldCommand(QUndoCommand):
    """Command to toggle a label's bold state."""

    def __init__(self, item, old_val: bool, new_val: bool):
        super().__init__("Toggle Bold")
        self._item = item
        self._old_val = old_val
        self._new_val = new_val

    def redo(self):
        self._item.label_bold = self._new_val
        if self._item.on_modified:
            self._item.on_modified()

    def undo(self):
        self._item.label_bold = self._old_val
        if self._item.on_modified:
            self._item.on_modified()


class ChangeLabelItalicCommand(QUndoCommand):
    """Command to toggle a label's italic state."""

    def __init__(self, item, old_val: bool, new_val: bool):
        super().__init__("Toggle Italic")
        self._item = item
        self._old_val = old_val
        self._new_val = new_val

    def redo(self):
        self._item.label_italic = self._new_val
        if self._item.on_modified:
            self._item.on_modified()

    def undo(self):
        self._item.label_italic = self._old_val
        if self._item.on_modified:
            self._item.on_modified()
