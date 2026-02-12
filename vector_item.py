import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, Qt
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
    latex_to_unicode, label_to_html,
    SELECTED_COLOR,
)

# Re-export for backward compatibility (file_io.py, etc.)
from base_item import (  # noqa: F401
    label_to_html, get_cm_font, latex_to_unicode,
    LABEL_COLOR, SELECTED_COLOR, DEFAULT_LABEL_OFFSET, DEFAULT_FONT_SIZE,
    SNAP_ANGLE_DEG, LATEX_TO_UNICODE,
)

VECTOR_COLOR = QColor(220, 50, 50)


@dataclass
class VectorSettings:
    arrow_thickness: int = 1
    shaft_thickness: int = 6
    handle_radius: int = 6
    arrowhead_length: int = 22
    arrowhead_width: int = 20
    arrowhead_notch: int = 8  # stealth notch depth (0 = flat triangle)


vector_settings = VectorSettings()  # global singleton
DEFAULT_MAGNITUDE = ""


class VectorItem(LabelPropertiesMixin, QGraphicsPathItem):
    """A straight vector from tail to head with an arrowhead."""

    def __init__(self, tail: QPointF, head: QPointF, parent=None):
        super().__init__(parent)
        self._tail = QPointF(tail)
        self._head = QPointF(head)
        self._magnitude = DEFAULT_MAGNITUDE
        self._show_magnitude = False

        self._rebuild_pens()
        self.setPen(self._pen_normal)
        self._head_polygon: QPolygonF | None = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        # Control points (added to scene later)
        r = vector_settings.handle_radius
        self._tail_handle = BaseControlPoint(tail.x(), tail.y(), self, is_head=False, handle_radius=r)
        self._head_handle = BaseControlPoint(head.x(), head.y(), self, is_head=True, handle_radius=r)

        # Label (added to scene later)
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

    def get_label_html(self) -> str:
        html = label_to_html(self._label_text, self._label_bold, self._label_italic)
        if self._show_magnitude and self._magnitude:
            mag_display = latex_to_unicode(self._magnitude)
            if html:
                html += f" = {mag_display}"
            else:
                html = f"<b>{mag_display}</b>"
        return html

    # --- Properties ---

    @property
    def tail(self) -> QPointF:
        return QPointF(self._tail)

    @property
    def head(self) -> QPointF:
        return QPointF(self._head)

    @property
    def magnitude(self) -> str:
        return self._magnitude

    @magnitude.setter
    def magnitude(self, value: str):
        self._magnitude = value
        self._label.update_display()

    @property
    def show_magnitude(self) -> bool:
        return self._show_magnitude

    @show_magnitude.setter
    def show_magnitude(self, value: bool):
        self._show_magnitude = value
        self._label.update_display()

    @property
    def vector_length(self) -> float:
        """Geometric length of the vector in scene pixels."""
        dx = self._head.x() - self._tail.x()
        dy = self._head.y() - self._tail.y()
        return math.hypot(dx, dy)

    # --- Movement ---

    def move_by(self, delta: QPointF):
        """Translate the entire vector (tail + head) by delta."""
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

    def _rebuild_pens(self):
        s = vector_settings
        self._pen_normal = QPen(VECTOR_COLOR, s.arrow_thickness)
        self._pen_selected = QPen(SELECTED_COLOR, s.arrow_thickness)
        self._shaft_pen_normal = QPen(VECTOR_COLOR, s.shaft_thickness)
        self._shaft_pen_normal.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._shaft_pen_selected = QPen(SELECTED_COLOR, s.shaft_thickness)
        self._shaft_pen_selected.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(self._pen_normal)

    def refresh_style(self):
        """Rebuild pens, handle sizes, and path from current vector_settings."""
        self._rebuild_pens()
        r = vector_settings.handle_radius
        self._tail_handle.setRect(-r, -r, 2 * r, 2 * r)
        self._head_handle.setRect(-r, -r, 2 * r, 2 * r)
        self._rebuild_path()
        self.update()

    # --- Drawing ---

    def _rebuild_path(self):
        # Build arrowhead polygon + shaft endpoint
        s = vector_settings
        dx = self._head.x() - self._tail.x()
        dy = self._head.y() - self._tail.y()
        length = math.hypot(dx, dy)
        if length > 0:
            ux, uy = dx / length, dy / length
            bx = self._head.x() - ux * s.arrowhead_length
            by = self._head.y() - uy * s.arrowhead_length
            px, py = -uy * s.arrowhead_width / 2, ux * s.arrowhead_width / 2
            nx = bx + ux * s.arrowhead_notch
            ny = by + uy * s.arrowhead_notch
            self._head_polygon = QPolygonF([
                self._head,
                QPointF(bx + px, by + py),
                QPointF(nx, ny),
                QPointF(bx - px, by - py),
            ])
            # Pull shaft back so it doesn't blunt the tip
            self._shaft_end = QPointF(self._head.x() - ux * 7, self._head.y() - uy * 7)
        else:
            self._head_polygon = None
            self._shaft_end = QPointF(self._head)

        # Combined path for hit-testing / bounding rect
        path = QPainterPath()
        path.moveTo(self._tail)
        path.lineTo(self._head)
        if self._head_polygon is not None:
            path.addPolygon(self._head_polygon)
            path.closeSubpath()
        self.setPath(path)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(vector_settings.shaft_thickness + 4)
        shaft_path = QPainterPath()
        shaft_path.moveTo(self._tail)
        shaft_path.lineTo(self._head)
        wide = stroker.createStroke(shaft_path)
        if self._head_polygon is not None:
            wide.addPolygon(self._head_polygon)
            wide.closeSubpath()
        return wide

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()
        color = SELECTED_COLOR if is_sel else VECTOR_COLOR

        self._tail_handle.setVisible(is_sel)
        self._head_handle.setVisible(is_sel)
        self._label.update_color(is_sel)

        # Draw shaft with thick pen (pulled back from tip)
        shaft_pen = self._shaft_pen_selected if is_sel else self._shaft_pen_normal
        painter.setPen(shaft_pen)
        painter.drawLine(self._tail, self._shaft_end)

        # Draw arrowhead with thin pen + fill
        if self._head_polygon is not None:
            head_pen = self._pen_selected if is_sel else self._pen_normal
            painter.setPen(head_pen)
            painter.setBrush(QBrush(color))
            painter.drawPolygon(self._head_polygon)

    # --- Serialization ---

    def to_dict(self) -> dict:
        d = self._base_to_dict()
        d["tail"] = [self._tail.x(), self._tail.y()]
        d["head"] = [self._head.x(), self._head.y()]
        d["magnitude"] = self._magnitude
        d["show_magnitude"] = self._show_magnitude
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "VectorItem":
        vec = cls(
            QPointF(data["tail"][0], data["tail"][1]),
            QPointF(data["head"][0], data["head"][1]),
        )
        vec._base_from_dict(data)
        raw_mag = data.get("magnitude", DEFAULT_MAGNITUDE)
        if isinstance(raw_mag, (int, float)):
            vec._magnitude = "" if raw_mag == 100.0 else f"{raw_mag:.10g}"
        else:
            vec._magnitude = raw_mag
        vec._show_magnitude = data.get("show_magnitude", False)
        vec._label.update_display()
        return vec
