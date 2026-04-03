"""SquiggleItem -- a smooth denotation/break line (S-curve) between two points."""

import math

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainterPathStroker, QPainter,
)
from PyQt6.QtWidgets import (
    QStyleOptionGraphicsItem, QWidget,
)

from fbd_lab.items.base import (
    TwoEndpointItem, SELECTED_COLOR, DEFAULT_HANDLE_RADIUS,
)

SQUIGGLE_COLOR = QColor(0, 0, 0)
DEFAULT_WAVES = 1.5
DEFAULT_AMPLITUDE = 25.0
DEFAULT_THICKNESS = 2


class SquiggleItem(TwoEndpointItem):
    """A smooth S-curve denotation line from tail to head."""

    def _default_stroke_color(self) -> QColor:
        return QColor(SQUIGGLE_COLOR)

    def __init__(self, tail: QPointF, head: QPointF, parent=None):
        self._waves = DEFAULT_WAVES
        self._amplitude = DEFAULT_AMPLITUDE
        self._thickness = DEFAULT_THICKNESS
        self._stroke_color = QColor(SQUIGGLE_COLOR)
        self._stroke_opacity = 255

        super().__init__(tail, head, handle_radius=DEFAULT_HANDLE_RADIUS, parent=parent)

        self._rebuild_path()

    # --- Properties ---

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
        is_sel, color = self._paint_preamble()

        pen = QPen(color, self._thickness)
        pen.setCapStyle(pen.capStyle().RoundCap)
        pen.setJoinStyle(pen.joinStyle().RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QBrush())
        painter.drawPath(self.path())

    # --- Serialization ---

    def to_dict(self) -> dict:
        d = self._endpoint_to_dict()
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
        item._stroke_from_dict(data)
        item._label_from_dict(data)
        item._waves = data.get("waves", DEFAULT_WAVES)
        item._amplitude = data.get("amplitude", DEFAULT_AMPLITUDE)
        item._thickness = data.get("thickness", DEFAULT_THICKNESS)
        item._rebuild_path()
        return item
