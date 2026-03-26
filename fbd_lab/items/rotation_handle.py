"""Rotation handle — draggable UI handle that appears above selected items."""

import math

from PyQt6.QtWidgets import QGraphicsObject, QGraphicsItem
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QCursor, QPixmap, QPainterPath
from PyQt6.QtCore import Qt, QRectF, QPointF

from fbd_lab.items.base import SELECTED_COLOR


class RotationHandleItem(QGraphicsObject):
    """Child item providing a draggable rotation handle above a rotatable item."""

    STEM_LENGTH = 30
    HANDLE_RADIUS = 9
    SNAP_ANGLES = list(range(0, 360, 45))  # every 45 degrees
    SNAP_THRESHOLD = 7  # degrees

    _cursor_cache: dict[str, QCursor] = {}

    def __init__(self, parent_item):
        super().__init__(parent_item)
        self._dragging = False
        self._start_angle = 0.0
        self._start_rotation = 0.0

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setAcceptHoverEvents(True)
        self.setVisible(False)
        self.setZValue(100)

    def update_position(self):
        """Reposition handle at top-center of parent bounding rect."""
        parent = self.parentItem()
        if parent:
            br = parent.boundingRect()
            if not br.isNull():
                self.setPos(br.center().x(), br.top())

    def boundingRect(self) -> QRectF:
        r = self.HANDLE_RADIUS + 2
        return QRectF(-r, -(self.STEM_LENGTH + r), 2 * r, self.STEM_LENGTH + 2 * r)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = SELECTED_COLOR

        pen = QPen(color, 2)
        painter.setPen(pen)

        # Stem
        painter.drawLine(QPointF(0, 0), QPointF(0, -self.STEM_LENGTH))

        # Anchor dot
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QPointF(0, 0), 3, 3)

        # Circle at top
        center = QPointF(0, -self.STEM_LENGTH)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(center, self.HANDLE_RADIUS, self.HANDLE_RADIUS)

        # Circular arrow icon
        painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
        arc_r = 5
        arc_rect = QRectF(center.x() - arc_r, center.y() - arc_r, arc_r * 2, arc_r * 2)
        painter.drawArc(arc_rect, 30 * 16, 260 * 16)

        # Arrowhead
        end_angle_rad = math.radians(290)
        ex = center.x() + arc_r * math.cos(end_angle_rad)
        ey = center.y() - arc_r * math.sin(end_angle_rad)
        arrow = QPainterPath()
        arrow.moveTo(ex, ey)
        arrow.lineTo(ex + 3, ey - 3)
        arrow.lineTo(ex - 1, ey - 2)
        arrow.closeSubpath()
        painter.fillPath(arrow, QBrush(QColor("#FFFFFF")))

    def hoverEnterEvent(self, event):
        self.setCursor(self._rotation_cursor())
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start_angle = self._angle_from_center(event.scenePos())
            self._start_rotation = self.parentItem().rotation()
            self.setCursor(self._rotation_cursor())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            current_angle = self._angle_from_center(event.scenePos())
            delta = current_angle - self._start_angle
            new_rotation = self._start_rotation + delta
            # Ctrl = free rotation, otherwise snap to 45-degree increments
            modifiers = event.modifiers()
            if not (modifiers & Qt.KeyboardModifier.ControlModifier):
                new_rotation = self._snap_angle(new_rotation)
            self.parentItem().setRotation(new_rotation)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            # Notify parent to push undo command
            parent = self.parentItem()
            if hasattr(parent, '_on_rotation_finished'):
                parent._on_rotation_finished(self._start_rotation)
            event.accept()

    def _angle_from_center(self, scene_pos: QPointF) -> float:
        parent = self.parentItem()
        parent_center = parent.mapToScene(parent.boundingRect().center())
        dx = scene_pos.x() - parent_center.x()
        dy = scene_pos.y() - parent_center.y()
        return math.degrees(math.atan2(dy, dx))

    def _snap_angle(self, angle: float) -> float:
        """Snap to nearest 45-degree multiple if within threshold."""
        normalized = angle % 360
        if normalized < 0:
            normalized += 360
        for snap in self.SNAP_ANGLES:
            diff = abs(normalized - snap)
            if diff < self.SNAP_THRESHOLD or abs(diff - 360) < self.SNAP_THRESHOLD:
                return snap + (angle - normalized)
        return angle

    @classmethod
    def _rotation_cursor(cls) -> QCursor:
        key = "default"
        if key in cls._cursor_cache:
            return cls._cursor_cache[key]
        size = 24
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # White outline for contrast
        p.setPen(QPen(QColor("#FFFFFF"), 4))
        arc_rect = QRectF(3, 3, size - 6, size - 6)
        p.drawArc(arc_rect, 45 * 16, 270 * 16)
        p.drawLine(QPointF(size / 2 + 2, 3), QPointF(size / 2, 8))
        p.drawLine(QPointF(size / 2 + 2, 3), QPointF(size / 2 + 7, 5))
        # Black foreground
        p.setPen(QPen(QColor("#000000"), 2))
        p.drawArc(arc_rect, 45 * 16, 270 * 16)
        p.drawLine(QPointF(size / 2 + 2, 3), QPointF(size / 2, 8))
        p.drawLine(QPointF(size / 2 + 2, 3), QPointF(size / 2 + 7, 5))
        p.end()
        cursor = QCursor(pm, size // 2, size // 2)
        cls._cursor_cache[key] = cursor
        return cursor
