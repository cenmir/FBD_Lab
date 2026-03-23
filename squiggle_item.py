"""SquiggleItem — a smooth denotation/break line (S-curve) between two points."""

import math

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainterPathStroker, QPainter,
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

SQUIGGLE_COLOR = QColor(0, 0, 0)
DEFAULT_WAVES = 1.5
DEFAULT_AMPLITUDE = 25.0
DEFAULT_THICKNESS = 2


class SquiggleItem(LabelPropertiesMixin, QGraphicsPathItem):
    """A smooth S-curve denotation line from tail to head."""

    def _default_item_color(self) -> QColor:
        return QColor(SQUIGGLE_COLOR)

    def __init__(self, tail: QPointF, head: QPointF, parent=None):
        super().__init__(parent)
        self._tail = QPointF(tail)
        self._head = QPointF(head)
        self._waves = DEFAULT_WAVES
        self._amplitude = DEFAULT_AMPLITUDE
        self._thickness = DEFAULT_THICKNESS
        self._item_color = QColor(SQUIGGLE_COLOR)
        self._item_opacity = 255

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        r = vector_settings.handle_radius
        self._tail_handle = BaseControlPoint(tail.x(), tail.y(), self,
                                             is_head=False, handle_radius=r)
        self._head_handle = BaseControlPoint(head.x(), head.y(), self,
                                             is_head=True, handle_radius=r)

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
    def waves(self) -> float:
        return self._waves

    @waves.setter
    def waves(self, value: float):
        self._waves = max(0.5, value)
        self._rebuild_path()
        self.update()

    @property
    def amplitude(self) -> float:
        return self._amplitude

    @amplitude.setter
    def amplitude(self, value: float):
        self._amplitude = max(1, value)
        self._rebuild_path()
        self.update()

    @property
    def thickness(self) -> int:
        return self._thickness

    @thickness.setter
    def thickness(self, value: int):
        self._thickness = max(1, value)
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
        r = vector_settings.handle_radius
        self._tail_handle.setRect(-r, -r, 2 * r, 2 * r)
        self._head_handle.setRect(-r, -r, 2 * r, 2 * r)
        self._rebuild_path()
        self.update()

    # --- Drawing ---

    def _rebuild_path(self):
        self.prepareGeometryChange()
        dx = self._head.x() - self._tail.x()
        dy = self._head.y() - self._tail.y()
        length = math.hypot(dx, dy)

        path = QPainterPath()

        if length < 1:
            path.moveTo(self._tail)
            path.lineTo(self._head)
            self.setPath(path)
            self._label.update_position()
            if self.on_modified:
                self.on_modified()
            return

        ux, uy = dx / length, dy / length
        px, py = -uy, ux  # perpendicular

        # Sample the sine curve at many points for a smooth path
        amp = self._amplitude
        n_waves = self._waves
        steps = max(40, int(n_waves * 30))

        path.moveTo(self._tail)
        for i in range(1, steps + 1):
            t = i / steps
            along = t * length
            perp = amp * math.sin(t * n_waves * 2 * math.pi)
            pt = QPointF(
                self._tail.x() + ux * along + px * perp,
                self._tail.y() + uy * along + py * perp,
            )
            path.lineTo(pt)

        self.setPath(path)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    def boundingRect(self):
        r = super().boundingRect()
        pad = self._amplitude + self._thickness + 2
        return r.adjusted(-pad, -pad, pad, pad)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(self._amplitude * 2 + 8)
        shaft_path = QPainterPath()
        shaft_path.moveTo(self._tail)
        shaft_path.lineTo(self._head)
        return stroker.createStroke(shaft_path)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem,
              widget: QWidget = None):
        is_sel = self.isSelected()
        color = SELECTED_COLOR if is_sel else self._get_item_color_with_opacity()

        self._tail_handle.setVisible(is_sel)
        self._head_handle.setVisible(is_sel)
        self._label.update_color(is_sel)

        pen = QPen(color, self._thickness)
        pen.setCapStyle(pen.capStyle().RoundCap)
        pen.setJoinStyle(pen.joinStyle().RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QBrush())
        painter.drawPath(self.path())

    # --- Serialization ---

    def to_dict(self) -> dict:
        d = self._base_to_dict()
        d["tail"] = [self._tail.x(), self._tail.y()]
        d["head"] = [self._head.x(), self._head.y()]
        d["waves"] = self._waves
        d["amplitude"] = self._amplitude
        d["thickness"] = self._thickness
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SquiggleItem":
        item = cls(
            QPointF(data["tail"][0], data["tail"][1]),
            QPointF(data["head"][0], data["head"][1]),
        )
        item._base_from_dict(data)
        item._waves = data.get("waves", DEFAULT_WAVES)
        item._amplitude = data.get("amplitude", DEFAULT_AMPLITUDE)
        item._thickness = data.get("thickness", DEFAULT_THICKNESS)
        item._rebuild_path()
        return item
