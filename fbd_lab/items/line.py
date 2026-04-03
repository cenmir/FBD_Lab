import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainterPathStroker,
    QPolygonF, QPainter,
)
from PyQt6.QtWidgets import (
    QStyleOptionGraphicsItem, QWidget,
)

from fbd_lab.items.base import (
    TwoEndpointItem, FillProperties, EdgeProperties, SELECTED_COLOR,
)

LINE_BODY_COLOR = QColor(173, 216, 230)    # light blue
LINE_OUTLINE_COLOR = QColor(0, 0, 0)       # black

DEFAULT_BODY_THICKNESS = 10
ARROWHEAD_LENGTH = 16
ARROWHEAD_WIDTH = 14


@dataclass
class LineSettings:
    handle_radius: int = 6


line_settings = LineSettings()  # global singleton


class LineItem(FillProperties, EdgeProperties, TwoEndpointItem):
    """A solid line rendered as a filled rectangle from tail to head."""

    _DEFAULT_FILL_COLOR = QColor(LINE_BODY_COLOR)
    _DEFAULT_EDGE_COLOR = QColor(LINE_OUTLINE_COLOR)

    def __init__(self, tail: QPointF, head: QPointF, parent=None):
        super().__init__(tail, head, handle_radius=line_settings.handle_radius, parent=parent)
        self._init_fill_properties()
        self._init_edge_properties()

        self._body_thickness = DEFAULT_BODY_THICKNESS
        self._show_arrow_tail = False
        self._show_arrow_head = False
        self._dashed = False

        self._rect_polygon: QPolygonF | None = None
        self._arrow_head_poly: QPolygonF | None = None
        self._arrow_tail_poly: QPolygonF | None = None

        self._rebuild_path()

    # --- Properties ---

    @property
    def body_thickness(self) -> int:
        return self._body_thickness

    @body_thickness.setter
    def body_thickness(self, value: int):
        self._body_thickness = value
        self._rebuild_path()

    @property
    def show_arrow_tail(self) -> bool:
        return self._show_arrow_tail

    @show_arrow_tail.setter
    def show_arrow_tail(self, value: bool):
        self._show_arrow_tail = value
        self._rebuild_path()
        self.update()

    @property
    def show_arrow_head(self) -> bool:
        return self._show_arrow_head

    @show_arrow_head.setter
    def show_arrow_head(self, value: bool):
        self._show_arrow_head = value
        self._rebuild_path()
        self.update()

    @property
    def dashed(self) -> bool:
        return self._dashed

    @dashed.setter
    def dashed(self, value: bool):
        self._dashed = value
        self.update()

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
        self.prepareGeometryChange()
        dx = self._head.x() - self._tail.x()
        dy = self._head.y() - self._tail.y()
        length = math.hypot(dx, dy)

        self._arrow_head_poly = None
        self._arrow_tail_poly = None

        if length > 0:
            ux, uy = dx / length, dy / length
            half_w = self._body_thickness / 2
            px, py = -uy * half_w, ux * half_w

            # Compute effective tail/head (pulled back for arrowheads)
            eff_tail = QPointF(self._tail.x(), self._tail.y())
            eff_head = QPointF(self._head.x(), self._head.y())

            if self._show_arrow_head:
                eff_head = QPointF(self._head.x() - ux * ARROWHEAD_LENGTH,
                                   self._head.y() - uy * ARROWHEAD_LENGTH)
                ah_px, ah_py = -uy * ARROWHEAD_WIDTH / 2, ux * ARROWHEAD_WIDTH / 2
                self._arrow_head_poly = QPolygonF([
                    self._head,
                    QPointF(eff_head.x() + ah_px, eff_head.y() + ah_py),
                    QPointF(eff_head.x() - ah_px, eff_head.y() - ah_py),
                ])

            if self._show_arrow_tail:
                eff_tail = QPointF(self._tail.x() + ux * ARROWHEAD_LENGTH,
                                   self._tail.y() + uy * ARROWHEAD_LENGTH)
                ah_px, ah_py = -uy * ARROWHEAD_WIDTH / 2, ux * ARROWHEAD_WIDTH / 2
                self._arrow_tail_poly = QPolygonF([
                    self._tail,
                    QPointF(eff_tail.x() + ah_px, eff_tail.y() + ah_py),
                    QPointF(eff_tail.x() - ah_px, eff_tail.y() - ah_py),
                ])

            self._rect_polygon = QPolygonF([
                QPointF(eff_tail.x() + px, eff_tail.y() + py),
                QPointF(eff_head.x() + px, eff_head.y() + py),
                QPointF(eff_head.x() - px, eff_head.y() - py),
                QPointF(eff_tail.x() - px, eff_tail.y() - py),
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
        if self._arrow_head_poly:
            path.addPolygon(self._arrow_head_poly)
            path.closeSubpath()
        if self._arrow_tail_poly:
            path.addPolygon(self._arrow_tail_poly)
            path.closeSubpath()
        self.setPath(path)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    def boundingRect(self):
        r = super().boundingRect()
        pad = max(self._outline_thickness, ARROWHEAD_WIDTH / 2) + 2
        return r.adjusted(-pad, -pad, pad, pad)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        if self._rect_polygon is not None:
            path.addPolygon(self._rect_polygon)
            path.closeSubpath()
        else:
            path.moveTo(self._tail)
            path.lineTo(self._head)
        if self._arrow_head_poly:
            path.addPolygon(self._arrow_head_poly)
            path.closeSubpath()
        if self._arrow_tail_poly:
            path.addPolygon(self._arrow_tail_poly)
            path.closeSubpath()
        stroker = QPainterPathStroker()
        stroker.setWidth(4)
        return stroker.createStroke(path) | path

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()

        self._tail_handle.setVisible(is_sel)
        self._head_handle.setVisible(is_sel)
        self._label.update_color(is_sel)

        # Edge (outline) color with opacity
        edge_col = QColor(SELECTED_COLOR if is_sel else self._edge_color)
        edge_col.setAlpha(self._edge_opacity)

        # Fill (body) color with opacity
        fill_col = QColor(self._fill_color)
        fill_col.setAlpha(self._fill_opacity)

        if self._rect_polygon is not None:
            pen = QPen(edge_col, self._outline_thickness)
            if self._dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QBrush(fill_col))
            painter.drawPolygon(self._rect_polygon)

        # Arrowheads (filled with edge color, solid even if line is dashed)
        if self._arrow_head_poly is not None:
            painter.setPen(QPen(edge_col, self._outline_thickness))
            painter.setBrush(QBrush(edge_col))
            painter.drawPolygon(self._arrow_head_poly)
        if self._arrow_tail_poly is not None:
            painter.setPen(QPen(edge_col, self._outline_thickness))
            painter.setBrush(QBrush(edge_col))
            painter.drawPolygon(self._arrow_tail_poly)

    # --- Serialization ---

    def to_dict(self) -> dict:
        d = self._endpoint_to_dict()
        d.update(self._fill_to_dict())
        d.update(self._edge_to_dict())
        d["body_thickness"] = self._body_thickness
        d["show_arrow_tail"] = self._show_arrow_tail
        d["show_arrow_head"] = self._show_arrow_head
        d["dashed"] = self._dashed
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "LineItem":
        ln = cls(
            QPointF(data["tail"][0], data["tail"][1]),
            QPointF(data["head"][0], data["head"][1]),
        )
        ln._label_from_dict(data)
        ln._fill_from_dict(data)
        ln._edge_from_dict(data)
        ln._body_thickness = data.get("body_thickness", DEFAULT_BODY_THICKNESS)
        ln._show_arrow_tail = data.get("show_arrow_tail", False)
        ln._show_arrow_head = data.get("show_arrow_head", False)
        ln._dashed = data.get("dashed", False)
        ln._rebuild_path()
        return ln
