"""SpringItem -- a zigzag/coil spring line between two points."""

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

SPRING_COLOR = QColor(0, 0, 0)

DEFAULT_COILS = 2
DEFAULT_AMPLITUDE = 20.0
DEFAULT_THICKNESS = 2


class SpringItem(TwoEndpointItem):
    """A zigzag spring line from tail to head."""

    def _default_stroke_color(self) -> QColor:
        return QColor(SPRING_COLOR)

    def __init__(self, tail: QPointF, head: QPointF, parent=None):
        self._coils = DEFAULT_COILS
        self._amplitude = DEFAULT_AMPLITUDE
        self._thickness = DEFAULT_THICKNESS
        self._stroke_color = QColor(SPRING_COLOR)
        self._stroke_opacity = 255

        super().__init__(tail, head, handle_radius=DEFAULT_HANDLE_RADIUS, parent=parent)

        self._rebuild_path()

    # --- Properties ---

    @property
    def coils(self) -> int:
        return self._coils

    @coils.setter
    def coils(self, value: int):
        self._coils = max(1, value)
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

        # Unit vectors along and perpendicular to the axis
        ux, uy = dx / length, dy / length
        px, py = -uy, ux  # perpendicular

        # Smooth S-curve using cubic Bezier segments
        # Each half-wave is one cubic Bezier curve
        n = self._coils
        amp = self._amplitude
        half_waves = n * 2  # each coil = one full wave = 2 half-waves
        seg_len = length / half_waves

        def _pt(along: float, perp: float) -> QPointF:
            return QPointF(
                self._tail.x() + ux * along + px * perp,
                self._tail.y() + uy * along + py * perp,
            )

        path.moveTo(self._tail)

        for i in range(half_waves):
            t0 = i * seg_len
            t1 = (i + 1) * seg_len
            side = amp if (i % 2 == 0) else -amp
            # Control points at 1/3 and 2/3 of the segment, offset perpendicularly
            cp1 = _pt(t0 + seg_len / 3, side)
            cp2 = _pt(t0 + 2 * seg_len / 3, side)
            end = _pt(t1, 0)
            path.cubicTo(cp1, cp2, end)

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
        d["coils"] = self._coils
        d["amplitude"] = self._amplitude
        d["thickness"] = self._thickness
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SpringItem":
        item = cls(
            QPointF(data["tail"][0], data["tail"][1]),
            QPointF(data["head"][0], data["head"][1]),
        )
        item._stroke_from_dict(data)
        item._label_from_dict(data)
        item._coils = data.get("coils", DEFAULT_COILS)
        item._amplitude = data.get("amplitude", DEFAULT_AMPLITUDE)
        item._thickness = data.get("thickness", DEFAULT_THICKNESS)
        item._rebuild_path()
        return item
