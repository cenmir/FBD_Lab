import math

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (
    QPen, QColor, QPainterPath, QPainterPathStroker,
    QPolygonF, QPainter,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem,
    QGraphicsTextItem, QStyleOptionGraphicsItem, QWidget,
    QApplication, QGraphicsSceneMouseEvent,
)

from vector_item import (
    label_to_html, get_cm_font,
    LABEL_COLOR, SELECTED_COLOR, DEFAULT_LABEL_OFFSET, DEFAULT_FONT_SIZE,
    SNAP_ANGLE_DEG, vector_settings,
)

DIRECTION_COLOR = QColor(0, 0, 0)
ARROWHEAD_LENGTH = 18
ARROWHEAD_WIDTH = 14


class DirectionLabel(QGraphicsTextItem):
    """Draggable label attached to a direction, rendered with HTML formatting."""

    def __init__(self, direction: "DirectionItem"):
        super().__init__()
        self._dir = direction
        self._drag_old_offset: QPointF | None = None
        self._updating = False

        self.setDefaultTextColor(LABEL_COLOR)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(5)
        self.setVisible(False)

    def set_font_size(self, size: int):
        self.setFont(get_cm_font(size))

    def update_display(self):
        d = self._dir
        html = label_to_html(d._label_text, d._label_bold, d._label_italic)
        self.setHtml(html)

    def update_color(self, selected: bool):
        self.setDefaultTextColor(SELECTED_COLOR if selected else LABEL_COLOR)
        self.update_display()

    def update_position(self):
        self._updating = True
        mid = (self._dir._tail + self._dir._head) / 2
        self.setPos(mid + self._dir._label_offset)
        self._updating = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._updating:
            mid = (self._dir._tail + self._dir._head) / 2
            self._dir._label_offset = value - mid
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_offset = QPointF(self._dir._label_offset)
        if not self._dir.isSelected():
            if self.scene():
                self.scene().clearSelection()
            self._dir.setSelected(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        if self._drag_old_offset is None:
            return
        new_offset = QPointF(self._dir._label_offset)
        old_offset = self._drag_old_offset
        self._drag_old_offset = None
        if new_offset == old_offset:
            return
        push_fn = self._dir.on_push_undo
        if push_fn is not None:
            self._dir._label_offset = QPointF(old_offset)
            self.update_position()
            from commands import MoveLabelCommand
            cmd = MoveLabelCommand(self._dir, old_offset, new_offset)
            push_fn(cmd)


class DirectionControlPoint(QGraphicsEllipseItem):
    """Draggable handle at the tail or head of a direction."""

    def __init__(self, x: float, y: float, direction: "DirectionItem", is_head: bool):
        r = vector_settings.handle_radius
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.setPos(x, y)
        self._dir = direction
        self._is_head = is_head
        from PyQt6.QtGui import QBrush
        self.setBrush(QBrush(SELECTED_COLOR))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.setVisible(False)

        self._drag_old_tail: QPointF | None = None
        self._drag_old_head: QPointF | None = None

    @staticmethod
    def _snap(anchor: QPointF, pos: QPointF) -> QPointF:
        dx = pos.x() - anchor.x()
        dy = pos.y() - anchor.y()
        length = math.hypot(dx, dy)
        if length < 1:
            return pos
        angle = math.degrees(math.atan2(abs(dy), abs(dx)))
        if angle <= SNAP_ANGLE_DEG:
            return QPointF(pos.x(), anchor.y())
        elif angle >= 90 - SNAP_ANGLE_DEG:
            return QPointF(anchor.x(), pos.y())
        return pos

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            modifiers = QApplication.keyboardModifiers()
            if not (modifiers & Qt.KeyboardModifier.ControlModifier):
                anchor = self._dir.tail if self._is_head else self._dir.head
                value = self._snap(anchor, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if self._is_head:
                self._dir.set_head(value)
            else:
                self._dir.set_tail(value)
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_tail = QPointF(self._dir.tail)
        self._drag_old_head = QPointF(self._dir.head)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        if self._drag_old_tail is None:
            return
        new_tail = QPointF(self._dir.tail)
        new_head = QPointF(self._dir.head)
        old_tail = self._drag_old_tail
        old_head = self._drag_old_head
        self._drag_old_tail = None
        self._drag_old_head = None
        if new_tail == old_tail and new_head == old_head:
            return
        push_fn = self._dir.on_push_undo
        if push_fn is not None:
            self._dir.set_tail(old_tail)
            self._dir.set_head(old_head)
            from commands import ResizeDirectionCommand
            cmd = ResizeDirectionCommand(self._dir, old_tail, old_head, new_tail, new_head)
            push_fn(cmd)


class DirectionItem(QGraphicsPathItem):
    """A dashed line from tail to head with an optional open-triangle arrowhead."""

    def __init__(self, tail: QPointF, head: QPointF, parent=None):
        super().__init__(parent)
        self._tail = QPointF(tail)
        self._head = QPointF(head)
        self._label_text = ""
        self._label_visible = False
        self._label_offset = QPointF(DEFAULT_LABEL_OFFSET)
        self._font_size = DEFAULT_FONT_SIZE
        self._label_bold = True
        self._label_italic = True
        self._show_arrowhead = False

        self._z_order = 0

        self.on_modified = None
        self.on_push_undo = None

        self._head_polygon: QPolygonF | None = None
        self._shaft_end = QPointF(head)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        self._tail_handle = DirectionControlPoint(tail.x(), tail.y(), self, is_head=False)
        self._head_handle = DirectionControlPoint(head.x(), head.y(), self, is_head=True)

        self._label = DirectionLabel(self)
        self._label.set_font_size(self._font_size)

        self._rebuild_path()

    def added_to_scene(self, scene):
        scene.addItem(self._tail_handle)
        scene.addItem(self._head_handle)
        scene.addItem(self._label)

    def removed_from_scene(self, scene):
        scene.removeItem(self._tail_handle)
        scene.removeItem(self._head_handle)
        scene.removeItem(self._label)

    # --- Properties ---

    @property
    def tail(self) -> QPointF:
        return QPointF(self._tail)

    @property
    def head(self) -> QPointF:
        return QPointF(self._head)

    @property
    def z_order(self) -> int:
        return self._z_order

    @z_order.setter
    def z_order(self, value: int):
        self._z_order = value
        self.setZValue(1 + value)
        self._label.setZValue(5 + value)
        self._tail_handle.setZValue(10 + value)
        self._head_handle.setZValue(10 + value)

    @property
    def show_arrowhead(self) -> bool:
        return self._show_arrowhead

    @show_arrowhead.setter
    def show_arrowhead(self, value: bool):
        self._show_arrowhead = value
        self._rebuild_path()

    @property
    def label_text(self) -> str:
        return self._label_text

    @label_text.setter
    def label_text(self, value: str):
        self._label_text = value
        self._label.update_display()
        self._update_label_visibility()

    @property
    def label_visible(self) -> bool:
        return self._label_visible

    @label_visible.setter
    def label_visible(self, value: bool):
        self._label_visible = value
        self._update_label_visibility()

    @property
    def label_offset(self) -> QPointF:
        return QPointF(self._label_offset)

    @label_offset.setter
    def label_offset(self, value: QPointF):
        self._label_offset = QPointF(value)
        self._label.update_position()

    @property
    def font_size(self) -> int:
        return self._font_size

    @font_size.setter
    def font_size(self, value: int):
        self._font_size = value
        self._label.set_font_size(value)

    @property
    def label_bold(self) -> bool:
        return self._label_bold

    @label_bold.setter
    def label_bold(self, value: bool):
        self._label_bold = value
        self._label.update_display()

    @property
    def label_italic(self) -> bool:
        return self._label_italic

    @label_italic.setter
    def label_italic(self, value: bool):
        self._label_italic = value
        self._label.update_display()

    def _update_label_visibility(self):
        self._label.setVisible(self._label_visible and bool(self._label_text))

    # --- Movement ---

    def move_by(self, delta: QPointF):
        self._tail += delta
        self._head += delta
        self._tail_handle.setPos(self._tail)
        self._head_handle.setPos(self._head)
        self._rebuild_path()

    def set_tail(self, point: QPointF):
        self._tail = QPointF(point)
        self._tail_handle.setPos(point)
        self._rebuild_path()

    def set_head(self, point: QPointF):
        self._head = QPointF(point)
        self._head_handle.setPos(point)
        self._rebuild_path()

    # --- Drawing ---

    def _rebuild_path(self):
        dx = self._head.x() - self._tail.x()
        dy = self._head.y() - self._tail.y()
        length = math.hypot(dx, dy)

        if self._show_arrowhead and length > 0:
            ux, uy = dx / length, dy / length
            bx = self._head.x() - ux * ARROWHEAD_LENGTH
            by = self._head.y() - uy * ARROWHEAD_LENGTH
            px, py = -uy * ARROWHEAD_WIDTH / 2, ux * ARROWHEAD_WIDTH / 2
            self._head_polygon = QPolygonF([
                QPointF(bx + px, by + py),
                self._head,
                QPointF(bx - px, by - py),
            ])
            self._shaft_end = QPointF(self._head.x() - ux * 5, self._head.y() - uy * 5)
        else:
            self._head_polygon = None
            self._shaft_end = QPointF(self._head)

        path = QPainterPath()
        path.moveTo(self._tail)
        path.lineTo(self._head)
        if self._head_polygon is not None:
            path.addPolygon(self._head_polygon)
        self.setPath(path)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(10)
        shaft_path = QPainterPath()
        shaft_path.moveTo(self._tail)
        shaft_path.lineTo(self._head)
        wide = stroker.createStroke(shaft_path)
        if self._head_polygon is not None:
            wide.addPolygon(self._head_polygon)
        return wide

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()
        color = SELECTED_COLOR if is_sel else DIRECTION_COLOR

        self._tail_handle.setVisible(is_sel)
        self._head_handle.setVisible(is_sel)
        self._label.update_color(is_sel)

        # Draw dashed line
        dash_pen = QPen(color, 2, Qt.PenStyle.DashLine)
        dash_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(dash_pen)
        painter.drawLine(self._tail, self._shaft_end)

        # Draw open triangle arrowhead (outline only, no fill)
        if self._head_polygon is not None:
            arrow_pen = QPen(color, 2)
            arrow_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setPen(arrow_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline(self._head_polygon)

    # --- Serialization ---

    def to_dict(self) -> dict:
        return {
            "tail": [self._tail.x(), self._tail.y()],
            "head": [self._head.x(), self._head.y()],
            "label_text": self._label_text,
            "label_visible": self._label_visible,
            "label_offset": [self._label_offset.x(), self._label_offset.y()],
            "font_size": self._font_size,
            "label_bold": self._label_bold,
            "label_italic": self._label_italic,
            "show_arrowhead": self._show_arrowhead,
            "z_order": self._z_order,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DirectionItem":
        d = cls(
            QPointF(data["tail"][0], data["tail"][1]),
            QPointF(data["head"][0], data["head"][1]),
        )
        d._label_text = data.get("label_text", "")
        d._label_visible = data.get("label_visible", False)
        offset = data.get("label_offset", [DEFAULT_LABEL_OFFSET.x(), DEFAULT_LABEL_OFFSET.y()])
        d._label_offset = QPointF(offset[0], offset[1])
        d._font_size = data.get("font_size", DEFAULT_FONT_SIZE)
        d._label_bold = data.get("label_bold", True)
        d._label_italic = data.get("label_italic", True)
        d._show_arrowhead = data.get("show_arrowhead", False)
        d._label.set_font_size(d._font_size)
        d._label.update_display()
        d._update_label_visibility()
        d._label.update_position()
        z = data.get("z_order", 0)
        if z != 0:
            d.z_order = z
        return d
