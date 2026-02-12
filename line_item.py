import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainterPathStroker,
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

LINE_BODY_COLOR = QColor(173, 216, 230)    # light blue
LINE_OUTLINE_COLOR = QColor(0, 0, 0)       # black

DEFAULT_BODY_THICKNESS = 10
DEFAULT_OUTLINE_THICKNESS = 2


@dataclass
class LineSettings:
    handle_radius: int = 6


line_settings = LineSettings()  # global singleton


class LineItem(LabelPropertiesMixin, QGraphicsPathItem):
    """A solid line rendered as a filled rectangle from tail to head."""

    def __init__(self, tail: QPointF, head: QPointF, parent=None):
        super().__init__(parent)
        self._tail = QPointF(tail)
        self._head = QPointF(head)
        self._body_thickness = DEFAULT_BODY_THICKNESS
        self._outline_thickness = DEFAULT_OUTLINE_THICKNESS

        self._rect_polygon: QPolygonF | None = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        r = line_settings.handle_radius
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
    def body_thickness(self) -> int:
        return self._body_thickness

    @body_thickness.setter
    def body_thickness(self, value: int):
        self._body_thickness = value
        self._rebuild_path()

    @property
    def outline_thickness(self) -> int:
        return self._outline_thickness

    @outline_thickness.setter
    def outline_thickness(self, value: int):
        self._outline_thickness = value
        self.update()

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

    # --- Style ---

    def refresh_style(self):
        """Rebuild from current line_settings."""
        r = line_settings.handle_radius
        self._tail_handle.setRect(-r, -r, 2 * r, 2 * r)
        self._head_handle.setRect(-r, -r, 2 * r, 2 * r)
        self._rebuild_path()
        self.update()

    # --- Drawing ---

    def _rebuild_path(self):
        dx = self._head.x() - self._tail.x()
        dy = self._head.y() - self._tail.y()
        length = math.hypot(dx, dy)

        if length > 0:
            half_w = self._body_thickness / 2
            # Perpendicular unit vector
            px = -dy / length * half_w
            py = dx / length * half_w
            self._rect_polygon = QPolygonF([
                QPointF(self._tail.x() + px, self._tail.y() + py),
                QPointF(self._head.x() + px, self._head.y() + py),
                QPointF(self._head.x() - px, self._head.y() - py),
                QPointF(self._tail.x() - px, self._tail.y() - py),
            ])
        else:
            self._rect_polygon = None

        path = QPainterPath()
        if self._rect_polygon is not None:
            path.addPolygon(self._rect_polygon)
            path.closeSubpath()
        else:
            path.moveTo(self._tail)
            path.lineTo(self._head)
        self.setPath(path)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    def shape(self) -> QPainterPath:
        if self._rect_polygon is not None:
            path = QPainterPath()
            path.addPolygon(self._rect_polygon)
            path.closeSubpath()
            # Add a small stroke around the polygon for easier clicking
            stroker = QPainterPathStroker()
            stroker.setWidth(4)
            return stroker.createStroke(path) | path
        stroker = QPainterPathStroker()
        stroker.setWidth(self._body_thickness + 4)
        shaft_path = QPainterPath()
        shaft_path.moveTo(self._tail)
        shaft_path.lineTo(self._head)
        return stroker.createStroke(shaft_path)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()
        outline_color = SELECTED_COLOR if is_sel else LINE_OUTLINE_COLOR

        self._tail_handle.setVisible(is_sel)
        self._head_handle.setVisible(is_sel)
        self._label.update_color(is_sel)

        if self._rect_polygon is not None:
            # Fill the rectangle body
            painter.setPen(QPen(outline_color, self._outline_thickness))
            painter.setBrush(QBrush(LINE_BODY_COLOR))
            painter.drawPolygon(self._rect_polygon)

    # --- Serialization ---

    def to_dict(self) -> dict:
        d = self._base_to_dict()
        d["tail"] = [self._tail.x(), self._tail.y()]
        d["head"] = [self._head.x(), self._head.y()]
        d["body_thickness"] = self._body_thickness
        d["outline_thickness"] = self._outline_thickness
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "LineItem":
        ln = cls(
            QPointF(data["tail"][0], data["tail"][1]),
            QPointF(data["head"][0], data["head"][1]),
        )
        ln._base_from_dict(data)
        ln._body_thickness = data.get("body_thickness", DEFAULT_BODY_THICKNESS)
        ln._outline_thickness = data.get("outline_thickness", DEFAULT_OUTLINE_THICKNESS)
        ln._rebuild_path()
        return ln
