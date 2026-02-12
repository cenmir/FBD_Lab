import math

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (
    QPen, QColor, QPainterPath, QPainterPathStroker,
    QPolygonF, QPainter,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsPathItem,
    QStyleOptionGraphicsItem, QWidget,
)

from base_item import (
    BaseLabel, BaseControlPoint, LabelPropertiesMixin,
    SELECTED_COLOR,
)
from vector_item import vector_settings

DIRECTION_COLOR = QColor(0, 0, 0)
ARROWHEAD_LENGTH = 18
ARROWHEAD_WIDTH = 14


class DirectionItem(LabelPropertiesMixin, QGraphicsPathItem):
    """A dashed line from tail to head with an optional open-triangle arrowhead."""

    def __init__(self, tail: QPointF, head: QPointF, parent=None):
        super().__init__(parent)
        self._tail = QPointF(tail)
        self._head = QPointF(head)
        self._show_arrowhead = False

        self._head_polygon: QPolygonF | None = None
        self._shaft_end = QPointF(head)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        r = vector_settings.handle_radius
        self._tail_handle = BaseControlPoint(tail.x(), tail.y(), self, is_head=False, handle_radius=r)
        self._head_handle = BaseControlPoint(head.x(), head.y(), self, is_head=True, handle_radius=r)

        self._label = BaseLabel(self)
        self._init_label_properties()
        self._label.set_font_size(self._font_size)

        self._rebuild_path()

    # --- LabelPropertiesMixin overrides ---

    def label_anchor(self) -> QPointF:
        return (self._tail + self._head) / 2

    def drag_anchor(self) -> QPointF:
        return QPointF(self._tail)

    def _get_handles(self) -> list:
        return [self._tail_handle, self._head_handle]

    # --- Properties ---

    @property
    def tail(self) -> QPointF:
        return QPointF(self._tail)

    @property
    def head(self) -> QPointF:
        return QPointF(self._head)

    @property
    def show_arrowhead(self) -> bool:
        return self._show_arrowhead

    @show_arrowhead.setter
    def show_arrowhead(self, value: bool):
        self._show_arrowhead = value
        self._rebuild_path()

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
        d = self._base_to_dict()
        d["tail"] = [self._tail.x(), self._tail.y()]
        d["head"] = [self._head.x(), self._head.y()]
        d["show_arrowhead"] = self._show_arrowhead
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "DirectionItem":
        d = cls(
            QPointF(data["tail"][0], data["tail"][1]),
            QPointF(data["head"][0], data["head"][1]),
        )
        d._base_from_dict(data)
        d._show_arrowhead = data.get("show_arrowhead", False)
        d._rebuild_path()
        return d
