import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainterPathStroker,
    QPolygonF, QPainter,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem,
    QStyleOptionGraphicsItem, QWidget,
    QGraphicsSceneMouseEvent,
)

from fbd_lab.items.base import (
    BaseLabel, BaseItemProperties, StrokeProperties, LabelProperties,
    SELECTED_COLOR,
)

MOMENT_ARC_COLOR = QColor(220, 50, 50)       # red (same as vectors)
MOMENT_CENTER_COLOR = QColor(220, 50, 50)

DEFAULT_RADIUS = 50.0
DEFAULT_START_ANGLE = 0.0
DEFAULT_SPAN_ANGLE = 270.0


@dataclass
class MomentSettings:
    handle_radius: int = 5
    center_radius: int = 4
    arc_thickness: int = 3
    arrowhead_length: int = 14
    arrowhead_width: int = 12


moment_settings = MomentSettings()  # global singleton


# --- Geometry helpers ---

def _angle_point(center: QPointF, radius: float, angle_deg: float) -> QPointF:
    """Compute a point on the arc circle at the given angle (degrees)."""
    rad = math.radians(angle_deg)
    return QPointF(
        center.x() + radius * math.cos(rad),
        center.y() - radius * math.sin(rad),
    )


def _tangent_direction(angle_deg: float, ccw: bool) -> QPointF:
    """Unit tangent vector at a point on the arc."""
    rad = math.radians(angle_deg)
    if ccw:
        return QPointF(-math.sin(rad), -math.cos(rad))
    else:
        return QPointF(math.sin(rad), math.cos(rad))


class MomentCenterMarker(QGraphicsEllipseItem):
    """Small filled dot at the moment center. Drag to move the whole moment."""

    def __init__(self, moment: "MomentItem"):
        r = moment_settings.center_radius
        super().__init__(-r, -r, 2 * r, 2 * r)
        self._parent_item = moment
        self.setPos(moment._center)
        self.setBrush(QBrush(MOMENT_CENTER_COLOR))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        self._drag_old_center: QPointF | None = None

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            m = self._parent_item
            m._center = QPointF(value)
            m._start_handle.setPos(
                _angle_point(m._center, m._radius, m._start_angle))
            m._end_handle.setPos(
                _angle_point(m._center, m._radius, m.end_angle))
            m._rebuild_path()
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_center = QPointF(self._parent_item._center)
        if not self._parent_item.isSelected():
            if self.scene():
                self.scene().clearSelection()
            self._parent_item.setSelected(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        if self._drag_old_center is None:
            return
        new_center = QPointF(self._parent_item._center)
        old_center = self._drag_old_center
        self._drag_old_center = None
        if new_center == old_center:
            return
        push_fn = self._parent_item.on_push_undo
        if push_fn is not None:
            self._parent_item.set_center(old_center)
            from fbd_lab.commands import MoveMomentCommand
            cmd = MoveMomentCommand(self._parent_item, old_center, new_center)
            push_fn(cmd)


class MomentArcEndpoint(QGraphicsEllipseItem):
    """Draggable handle at the start or end of the arc. Changes angle at constant radius."""

    def __init__(self, moment: "MomentItem", is_start: bool):
        r = moment_settings.handle_radius
        super().__init__(-r, -r, 2 * r, 2 * r)
        self._parent_item = moment
        self._is_start = is_start

        angle = moment._start_angle if is_start else moment.end_angle
        pos = _angle_point(moment._center, moment._radius, angle)
        self.setPos(pos)

        self.setBrush(QBrush(SELECTED_COLOR))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.setVisible(False)

        self._drag_old_start_angle: float | None = None
        self._drag_old_span_angle: float | None = None
        self._constraining = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._constraining:
            m = self._parent_item
            dx = value.x() - m._center.x()
            dy = -(value.y() - m._center.y())  # negate Y for math coords
            new_angle = math.degrees(math.atan2(dy, dx)) % 360

            if self._is_start:
                old_end = (m._start_angle + m._span_angle) % 360
                m._start_angle = new_angle
                m._span_angle = (old_end - new_angle) % 360
                if m._span_angle == 0:
                    m._span_angle = 360
            else:
                new_span = (new_angle - m._start_angle) % 360
                if new_span == 0:
                    new_span = 360
                m._span_angle = new_span

            constrained_pos = _angle_point(m._center, m._radius, new_angle)
            self._constraining = True
            self.setPos(constrained_pos)
            self._constraining = False

            m._rebuild_path()
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_start_angle = self._parent_item._start_angle
        self._drag_old_span_angle = self._parent_item._span_angle
        if not self._parent_item.isSelected():
            if self.scene():
                self.scene().clearSelection()
            self._parent_item.setSelected(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        if self._drag_old_start_angle is None:
            return
        new_start = self._parent_item._start_angle
        new_span = self._parent_item._span_angle
        old_start = self._drag_old_start_angle
        old_span = self._drag_old_span_angle
        self._drag_old_start_angle = None
        self._drag_old_span_angle = None
        if new_start == old_start and new_span == old_span:
            return
        push_fn = self._parent_item.on_push_undo
        if push_fn is not None:
            self._parent_item.set_angles(old_start, old_span)
            from fbd_lab.commands import ChangeAnglesCommand
            cmd = ChangeAnglesCommand(self._parent_item, old_start, old_span, new_start, new_span)
            push_fn(cmd)


class MomentItem(BaseItemProperties, StrokeProperties, LabelProperties, QGraphicsPathItem):
    """A moment (rotational force) visualized as a curved arc arrow."""

    def _default_stroke_color(self) -> QColor:
        return QColor(MOMENT_ARC_COLOR)

    def __init__(self, center: QPointF, radius: float = DEFAULT_RADIUS,
                 start_angle: float = DEFAULT_START_ANGLE,
                 span_angle: float = DEFAULT_SPAN_ANGLE, parent=None):
        super().__init__(parent)
        self._center = QPointF(center)
        self._radius = radius
        self._start_angle = start_angle
        self._span_angle = span_angle
        self._stroke_color = QColor(MOMENT_ARC_COLOR)
        self._stroke_opacity = 255
        self._reversed = False

        self._arrowhead_polygon: QPolygonF | None = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        self._center_marker = MomentCenterMarker(self)
        self._start_handle = MomentArcEndpoint(self, is_start=True)
        self._end_handle = MomentArcEndpoint(self, is_start=False)

        self._label = BaseLabel(self)
        self._init_base_properties()
        self._init_stroke_properties()
        self._init_label_props()
        self._label.set_font_size(self._font_size)

        self._rebuild_path()

    # --- Mixin overrides ---

    def label_anchor(self) -> QPointF:
        return QPointF(self._center)

    def drag_anchor(self) -> QPointF:
        return QPointF(self._center)

    def _get_handles(self) -> list:
        return [self._center_marker, self._start_handle, self._end_handle]

    # --- Properties ---

    @property
    def center(self) -> QPointF:
        return QPointF(self._center)

    @property
    def radius(self) -> float:
        return self._radius

    @property
    def start_angle(self) -> float:
        return self._start_angle

    @property
    def span_angle(self) -> float:
        return self._span_angle

    @property
    def end_angle(self) -> float:
        return (self._start_angle + self._span_angle) % 360

    @property
    def reversed(self) -> bool:
        return self._reversed

    @reversed.setter
    def reversed(self, value: bool):
        self._reversed = value
        self._rebuild_path()
        self.update()

    # --- Movement / mutation ---

    def move_by(self, delta: QPointF):
        self._center += delta
        self._center_marker.setPos(self._center)
        self._start_handle.setPos(
            _angle_point(self._center, self._radius, self._start_angle))
        self._end_handle.setPos(
            _angle_point(self._center, self._radius, self.end_angle))
        self._rebuild_path()

    def set_center(self, center: QPointF):
        self._center = QPointF(center)
        self._center_marker.setPos(self._center)
        self._start_handle.setPos(
            _angle_point(self._center, self._radius, self._start_angle))
        self._end_handle.setPos(
            _angle_point(self._center, self._radius, self.end_angle))
        self._rebuild_path()

    def set_radius(self, radius: float):
        self._radius = radius
        self._start_handle.setPos(
            _angle_point(self._center, self._radius, self._start_angle))
        self._end_handle.setPos(
            _angle_point(self._center, self._radius, self.end_angle))
        self._rebuild_path()

    def set_angles(self, start_angle: float, span_angle: float):
        self._start_angle = start_angle
        self._span_angle = span_angle
        self._start_handle.setPos(
            _angle_point(self._center, self._radius, self._start_angle))
        self._end_handle.setPos(
            _angle_point(self._center, self._radius, self.end_angle))
        self._rebuild_path()

    # --- Layer visibility ---

    def set_layer_visible(self, visible: bool):
        self.setVisible(visible)
        self._label.setVisible(
            visible and self._label_visible and bool(self._label_text)
        )
        self._center_marker.setVisible(visible)
        self._start_handle.setVisible(visible and self.isSelected())
        self._end_handle.setVisible(visible and self.isSelected())

    # --- Style ---

    def refresh_style(self):
        """Rebuild from current moment_settings."""
        r = moment_settings.handle_radius
        self._start_handle.setRect(-r, -r, 2 * r, 2 * r)
        self._end_handle.setRect(-r, -r, 2 * r, 2 * r)
        cr = moment_settings.center_radius
        self._center_marker.setRect(-cr, -cr, 2 * cr, 2 * cr)
        self._rebuild_path()
        self.update()

    # --- Drawing ---

    def _rebuild_path(self):
        s = moment_settings
        r = self._radius

        arc_rect = QRectF(
            self._center.x() - r, self._center.y() - r,
            2 * r, 2 * r,
        )

        path = QPainterPath()
        path.arcMoveTo(arc_rect, self._start_angle)
        path.arcTo(arc_rect, self._start_angle, self._span_angle)

        # Arrowhead: at end of arc normally, at start when reversed
        ccw = self._span_angle > 0
        if self._reversed:
            arrow_angle_deg = self._start_angle % 360
            tip = _angle_point(self._center, r, arrow_angle_deg)
            tangent = _tangent_direction(arrow_angle_deg, not ccw)
        else:
            arrow_angle_deg = self.end_angle
            tip = _angle_point(self._center, r, arrow_angle_deg)
            tangent = _tangent_direction(arrow_angle_deg, ccw)
        t_len = math.hypot(tangent.x(), tangent.y())
        if t_len > 0:
            tx, ty = tangent.x() / t_len, tangent.y() / t_len
        else:
            tx, ty = 1.0, 0.0

        # Perpendicular to tangent
        px, py = -ty, tx

        ah_len = s.arrowhead_length
        ah_half_w = s.arrowhead_width / 2

        base_center = QPointF(tip.x() - tx * ah_len, tip.y() - ty * ah_len)
        self._arrowhead_polygon = QPolygonF([
            tip,
            QPointF(base_center.x() + px * ah_half_w, base_center.y() + py * ah_half_w),
            QPointF(base_center.x() - px * ah_half_w, base_center.y() - py * ah_half_w),
        ])

        path.addPolygon(self._arrowhead_polygon)
        path.closeSubpath()

        self.setPath(path)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    def shape(self) -> QPainterPath:
        r = self._radius
        arc_rect = QRectF(
            self._center.x() - r, self._center.y() - r,
            2 * r, 2 * r,
        )
        arc_path = QPainterPath()
        arc_path.arcMoveTo(arc_rect, self._start_angle)
        arc_path.arcTo(arc_rect, self._start_angle, self._span_angle)

        stroker = QPainterPathStroker()
        stroker.setWidth(moment_settings.arc_thickness + 8)
        wide = stroker.createStroke(arc_path)

        if self._arrowhead_polygon is not None:
            ah_path = QPainterPath()
            ah_path.addPolygon(self._arrowhead_polygon)
            ah_path.closeSubpath()
            wide = wide | ah_path
        return wide

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()
        color = SELECTED_COLOR if is_sel else self._get_stroke_color_with_opacity()

        self._start_handle.setVisible(is_sel)
        self._end_handle.setVisible(is_sel)
        self._center_marker.setBrush(QBrush(SELECTED_COLOR if is_sel else self._get_stroke_color_with_opacity()))
        self._label.update_color(is_sel)

        # Draw the arc
        r = self._radius
        arc_rect = QRectF(
            self._center.x() - r, self._center.y() - r,
            2 * r, 2 * r,
        )
        arc_pen = QPen(color, moment_settings.arc_thickness)
        arc_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(arc_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(arc_rect, int(self._start_angle * 16), int(self._span_angle * 16))

        # Draw filled arrowhead
        if self._arrowhead_polygon is not None:
            painter.setPen(QPen(color, 1))
            painter.setBrush(QBrush(color))
            painter.drawPolygon(self._arrowhead_polygon)

    # --- Serialization ---

    def to_dict(self) -> dict:
        d = self._label_to_dict()
        d.update(self._stroke_to_dict())
        d["center"] = [self._center.x(), self._center.y()]
        d["radius"] = self._radius
        d["start_angle"] = self._start_angle
        d["span_angle"] = self._span_angle
        d["reversed"] = self._reversed
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "MomentItem":
        m = cls(
            QPointF(data["center"][0], data["center"][1]),
            radius=data.get("radius", DEFAULT_RADIUS),
            start_angle=data.get("start_angle", DEFAULT_START_ANGLE),
            span_angle=data.get("span_angle", DEFAULT_SPAN_ANGLE),
        )
        m._reversed = data.get("reversed", False)
        m._stroke_from_dict(data)
        m._label_from_dict(data)
        m._rebuild_path()
        return m
