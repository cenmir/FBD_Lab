import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainterPathStroker,
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
    """Compute a point on the arc circle at the given angle (degrees).

    Qt convention: 0° = 3 o'clock, positive = counterclockwise.
    Screen Y is inverted, so sin is negated.
    """
    rad = math.radians(angle_deg)
    return QPointF(
        center.x() + radius * math.cos(rad),
        center.y() - radius * math.sin(rad),
    )


def _tangent_direction(angle_deg: float, ccw: bool) -> QPointF:
    """Unit tangent vector at a point on the arc.

    For CCW (positive span): tangent points in direction of increasing angle.
    For CW (negative span): tangent points in direction of decreasing angle.
    """
    rad = math.radians(angle_deg)
    if ccw:
        return QPointF(-math.sin(rad), -math.cos(rad))
    else:
        return QPointF(math.sin(rad), math.cos(rad))


class MomentLabel(QGraphicsTextItem):
    """Draggable label attached to a moment, rendered with HTML formatting."""

    def __init__(self, moment: "MomentItem"):
        super().__init__()
        self._moment = moment
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
        m = self._moment
        html = label_to_html(m._label_text, m._label_bold, m._label_italic)
        self.setHtml(html)

    def update_color(self, selected: bool):
        self.setDefaultTextColor(SELECTED_COLOR if selected else LABEL_COLOR)
        self.update_display()

    def update_position(self):
        self._updating = True
        self.setPos(self._moment._center + self._moment._label_offset)
        self._updating = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._updating:
            self._moment._label_offset = value - self._moment._center
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_offset = QPointF(self._moment._label_offset)
        if not self._moment.isSelected():
            if self.scene():
                self.scene().clearSelection()
            self._moment.setSelected(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        if self._drag_old_offset is None:
            return
        new_offset = QPointF(self._moment._label_offset)
        old_offset = self._drag_old_offset
        self._drag_old_offset = None
        if new_offset == old_offset:
            return
        push_fn = self._moment.on_push_undo
        if push_fn is not None:
            self._moment._label_offset = QPointF(old_offset)
            self.update_position()
            from commands import MoveLabelCommand
            cmd = MoveLabelCommand(self._moment, old_offset, new_offset)
            push_fn(cmd)


class MomentCenterMarker(QGraphicsEllipseItem):
    """Small filled dot at the moment center. Drag to move the whole moment."""

    def __init__(self, moment: "MomentItem"):
        r = moment_settings.center_radius
        super().__init__(-r, -r, 2 * r, 2 * r)
        self._moment = moment
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
            self._moment._center = QPointF(value)
            self._moment._start_handle.setPos(
                _angle_point(self._moment._center, self._moment._radius, self._moment._start_angle))
            self._moment._end_handle.setPos(
                _angle_point(self._moment._center, self._moment._radius, self._moment.end_angle))
            self._moment._rebuild_path()
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_center = QPointF(self._moment._center)
        if not self._moment.isSelected():
            if self.scene():
                self.scene().clearSelection()
            self._moment.setSelected(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        if self._drag_old_center is None:
            return
        new_center = QPointF(self._moment._center)
        old_center = self._drag_old_center
        self._drag_old_center = None
        if new_center == old_center:
            return
        push_fn = self._moment.on_push_undo
        if push_fn is not None:
            self._moment.set_center(old_center)
            from commands import MoveMomentCommand
            cmd = MoveMomentCommand(self._moment, old_center, new_center)
            push_fn(cmd)


class MomentArcEndpoint(QGraphicsEllipseItem):
    """Draggable handle at the start or end of the arc. Changes angle at constant radius."""

    def __init__(self, moment: "MomentItem", is_start: bool):
        r = moment_settings.handle_radius
        super().__init__(-r, -r, 2 * r, 2 * r)
        self._moment = moment
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
            # Compute angle from center to this position
            dx = value.x() - self._moment._center.x()
            dy = -(value.y() - self._moment._center.y())  # negate Y for math coords
            new_angle = math.degrees(math.atan2(dy, dx)) % 360

            if self._is_start:
                old_end = (self._moment._start_angle + self._moment._span_angle) % 360
                self._moment._start_angle = new_angle
                self._moment._span_angle = (old_end - new_angle) % 360
                if self._moment._span_angle == 0:
                    self._moment._span_angle = 360
            else:
                new_span = (new_angle - self._moment._start_angle) % 360
                if new_span == 0:
                    new_span = 360
                self._moment._span_angle = new_span

            # Constrain handle to the arc circle
            constrained_pos = _angle_point(self._moment._center, self._moment._radius, new_angle)
            self._constraining = True
            self.setPos(constrained_pos)
            self._constraining = False

            self._moment._rebuild_path()
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_start_angle = self._moment._start_angle
        self._drag_old_span_angle = self._moment._span_angle
        if not self._moment.isSelected():
            if self.scene():
                self.scene().clearSelection()
            self._moment.setSelected(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        if self._drag_old_start_angle is None:
            return
        new_start = self._moment._start_angle
        new_span = self._moment._span_angle
        old_start = self._drag_old_start_angle
        old_span = self._drag_old_span_angle
        self._drag_old_start_angle = None
        self._drag_old_span_angle = None
        if new_start == old_start and new_span == old_span:
            return
        push_fn = self._moment.on_push_undo
        if push_fn is not None:
            self._moment.set_angles(old_start, old_span)
            from commands import ChangeAnglesCommand
            cmd = ChangeAnglesCommand(self._moment, old_start, old_span, new_start, new_span)
            push_fn(cmd)


class MomentItem(QGraphicsPathItem):
    """A moment (rotational force) visualized as a curved arc arrow."""

    def __init__(self, center: QPointF, radius: float = DEFAULT_RADIUS,
                 start_angle: float = DEFAULT_START_ANGLE,
                 span_angle: float = DEFAULT_SPAN_ANGLE, parent=None):
        super().__init__(parent)
        self._center = QPointF(center)
        self._radius = radius
        self._start_angle = start_angle
        self._span_angle = span_angle

        self._label_text = ""
        self._label_visible = False
        self._label_offset = QPointF(DEFAULT_LABEL_OFFSET)
        self._font_size = DEFAULT_FONT_SIZE
        self._label_bold = True
        self._label_italic = True

        self._z_order = 0

        self.on_modified = None
        self.on_push_undo = None

        self._arrowhead_polygon: QPolygonF | None = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        self._center_marker = MomentCenterMarker(self)
        self._start_handle = MomentArcEndpoint(self, is_start=True)
        self._end_handle = MomentArcEndpoint(self, is_start=False)

        self._label = MomentLabel(self)
        self._label.set_font_size(self._font_size)

        self._rebuild_path()

    def added_to_scene(self, scene):
        scene.addItem(self._center_marker)
        scene.addItem(self._start_handle)
        scene.addItem(self._end_handle)
        scene.addItem(self._label)

    def removed_from_scene(self, scene):
        scene.removeItem(self._center_marker)
        scene.removeItem(self._start_handle)
        scene.removeItem(self._end_handle)
        scene.removeItem(self._label)

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
    def z_order(self) -> int:
        return self._z_order

    @z_order.setter
    def z_order(self, value: int):
        self._z_order = value
        self.setZValue(1 + value)
        self._label.setZValue(5 + value)
        self._center_marker.setZValue(10 + value)
        self._start_handle.setZValue(10 + value)
        self._end_handle.setZValue(10 + value)

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

        # Arrowhead at the end of the arc
        end_angle_deg = self.end_angle
        tip = _angle_point(self._center, r, end_angle_deg)

        ccw = self._span_angle > 0
        tangent = _tangent_direction(end_angle_deg, ccw)
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
        color = SELECTED_COLOR if is_sel else MOMENT_ARC_COLOR

        self._start_handle.setVisible(is_sel)
        self._end_handle.setVisible(is_sel)
        self._center_marker.setBrush(QBrush(SELECTED_COLOR if is_sel else MOMENT_CENTER_COLOR))
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
        return {
            "center": [self._center.x(), self._center.y()],
            "radius": self._radius,
            "start_angle": self._start_angle,
            "span_angle": self._span_angle,
            "label_text": self._label_text,
            "label_visible": self._label_visible,
            "label_offset": [self._label_offset.x(), self._label_offset.y()],
            "font_size": self._font_size,
            "label_bold": self._label_bold,
            "label_italic": self._label_italic,
            "z_order": self._z_order,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MomentItem":
        m = cls(
            QPointF(data["center"][0], data["center"][1]),
            radius=data.get("radius", DEFAULT_RADIUS),
            start_angle=data.get("start_angle", DEFAULT_START_ANGLE),
            span_angle=data.get("span_angle", DEFAULT_SPAN_ANGLE),
        )
        m._label_text = data.get("label_text", "")
        m._label_visible = data.get("label_visible", False)
        offset = data.get("label_offset", [DEFAULT_LABEL_OFFSET.x(), DEFAULT_LABEL_OFFSET.y()])
        m._label_offset = QPointF(offset[0], offset[1])
        m._font_size = data.get("font_size", DEFAULT_FONT_SIZE)
        m._label_bold = data.get("label_bold", True)
        m._label_italic = data.get("label_italic", True)
        m._label.set_font_size(m._font_size)
        m._label.update_display()
        m._update_label_visibility()
        m._label.update_position()
        z = data.get("z_order", 0)
        if z != 0:
            m.z_order = z
        return m
