from dataclasses import dataclass

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath,
    QPainter,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsEllipseItem,
    QStyleOptionGraphicsItem, QWidget,
)

from fbd_lab.items.base import (
    BaseLabel, BaseItemProperties, StrokeProperties, LabelProperties, SELECTED_COLOR,
)

POINT_COLORS = {
    "Red": QColor(220, 50, 50),
    "Black": QColor(0, 0, 0),
    "White": QColor(255, 255, 255),
    "Blue": QColor(0, 0, 255),
    "Cyan": QColor(0, 255, 255),
    "Magenta": QColor(255, 0, 255),
    "Sand": QColor(0xDC, 0xBA, 0x84),
    "Sky": QColor(0x9E, 0xC4, 0xD7),
    "Stone": QColor(0xB7, 0xAE, 0xA7),
}


@dataclass
class PointSettings:
    radius: int = 6
    color_name: str = "Black"

    @property
    def color(self) -> QColor:
        return POINT_COLORS.get(self.color_name, POINT_COLORS["Red"])


point_settings = PointSettings()  # global singleton


class PointItem(BaseItemProperties, StrokeProperties, LabelProperties, QGraphicsEllipseItem):
    """A point marker (filled circle) at a single position."""

    def _default_stroke_color(self) -> QColor:
        return QColor(point_settings.color)

    def __init__(self, pos: QPointF, parent=None):
        super().__init__(parent)
        self._pos = QPointF(pos)
        self._stroke_color = QColor(point_settings.color)
        self._stroke_opacity = 255

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        self._label = BaseLabel(self)
        self._init_base_properties()
        self._init_stroke_properties()
        self._init_label_props()
        self._label.set_font_size(self._font_size)

        self._rebuild()

    # --- Mixin overrides ---

    def label_anchor(self) -> QPointF:
        return QPointF(self._pos)

    def drag_anchor(self) -> QPointF:
        return QPointF(self._pos)

    # --- Properties ---

    @property
    def point_pos(self) -> QPointF:
        return QPointF(self._pos)

    # --- Movement ---

    def move_by(self, delta: QPointF):
        """Translate the point by delta."""
        self._pos += delta
        self._rebuild()

    def set_pos(self, point: QPointF):
        self._pos = QPointF(point)
        self._rebuild()

    # --- Style ---

    def refresh_style(self):
        """Rebuild from current point_settings."""
        self._rebuild()
        self.update()

    def _rebuild(self):
        r = point_settings.radius
        self.setRect(self._pos.x() - r, self._pos.y() - r, 2 * r, 2 * r)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    def shape(self) -> QPainterPath:
        r = point_settings.radius + 4
        path = QPainterPath()
        path.addEllipse(self._pos, r, r)
        return path

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()
        color = SELECTED_COLOR if is_sel else self._get_stroke_color_with_opacity()

        self._label.update_color(is_sel)

        painter.setPen(QPen(color, 1))
        painter.setBrush(QBrush(color))
        r = point_settings.radius
        painter.drawEllipse(self._pos, r, r)

    # --- Serialization ---

    def to_dict(self) -> dict:
        d = self._label_to_dict()
        d.update(self._stroke_to_dict())
        d["pos"] = [self._pos.x(), self._pos.y()]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "PointItem":
        pt = cls(QPointF(data["pos"][0], data["pos"][1]))
        pt._stroke_from_dict(data)
        pt._label_from_dict(data)
        return pt
