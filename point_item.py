from dataclasses import dataclass

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath,
    QPainter,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsEllipseItem,
    QGraphicsTextItem, QStyleOptionGraphicsItem, QWidget,
    QGraphicsSceneMouseEvent,
)

from vector_item import (
    label_to_html, get_cm_font,
    LABEL_COLOR, SELECTED_COLOR, DEFAULT_LABEL_OFFSET, DEFAULT_FONT_SIZE,
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


class PointLabel(QGraphicsTextItem):
    """Draggable label attached to a point, rendered with HTML formatting."""

    def __init__(self, point: "PointItem"):
        super().__init__()
        self._point = point
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
        """Rebuild the HTML from the parent point's current state."""
        pt = self._point
        html = label_to_html(pt._label_text, pt._label_bold, pt._label_italic)
        self.setHtml(html)

    def update_color(self, selected: bool):
        """Set text color based on selection state."""
        self.setDefaultTextColor(SELECTED_COLOR if selected else LABEL_COLOR)
        self.update_display()

    def update_position(self):
        """Reposition label at point position + offset."""
        self._updating = True
        self.setPos(self._point._pos + self._point._label_offset)
        self._updating = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._updating:
            self._point._label_offset = value - self._point._pos
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_offset = QPointF(self._point._label_offset)
        if not self._point.isSelected():
            if self.scene():
                self.scene().clearSelection()
            self._point.setSelected(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)

        if self._drag_old_offset is None:
            return

        new_offset = QPointF(self._point._label_offset)
        old_offset = self._drag_old_offset
        self._drag_old_offset = None

        if new_offset == old_offset:
            return

        push_fn = self._point.on_push_undo
        if push_fn is not None:
            self._point._label_offset = QPointF(old_offset)
            self.update_position()

            from commands import MoveLabelCommand
            cmd = MoveLabelCommand(self._point, old_offset, new_offset)
            push_fn(cmd)


class PointItem(QGraphicsEllipseItem):
    """A point marker (filled circle) at a single position."""

    def __init__(self, pos: QPointF, parent=None):
        super().__init__(parent)
        self._pos = QPointF(pos)
        self._label_text = ""
        self._label_visible = False
        self._label_offset = QPointF(DEFAULT_LABEL_OFFSET)
        self._font_size = DEFAULT_FONT_SIZE
        self._label_bold = True
        self._label_italic = True

        self.on_modified = None
        self.on_push_undo = None

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        self._label = PointLabel(self)
        self._label.set_font_size(self._font_size)

        self._rebuild()

    def added_to_scene(self, scene):
        """Call after adding this item to the scene to also add the label."""
        scene.addItem(self._label)

    def removed_from_scene(self, scene):
        """Call before removing this item to also remove the label."""
        scene.removeItem(self._label)

    # --- Properties ---

    @property
    def point_pos(self) -> QPointF:
        return QPointF(self._pos)

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
        color = SELECTED_COLOR if is_sel else point_settings.color

        self._label.update_color(is_sel)

        painter.setPen(QPen(color, 1))
        painter.setBrush(QBrush(color))
        r = point_settings.radius
        painter.drawEllipse(self._pos, r, r)

    # --- Serialization ---

    def to_dict(self) -> dict:
        return {
            "pos": [self._pos.x(), self._pos.y()],
            "label_text": self._label_text,
            "label_visible": self._label_visible,
            "label_offset": [self._label_offset.x(), self._label_offset.y()],
            "font_size": self._font_size,
            "label_bold": self._label_bold,
            "label_italic": self._label_italic,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PointItem":
        pt = cls(QPointF(data["pos"][0], data["pos"][1]))
        pt._label_text = data.get("label_text", "")
        pt._label_visible = data.get("label_visible", False)
        offset = data.get("label_offset", [DEFAULT_LABEL_OFFSET.x(), DEFAULT_LABEL_OFFSET.y()])
        pt._label_offset = QPointF(offset[0], offset[1])
        pt._font_size = data.get("font_size", DEFAULT_FONT_SIZE)
        pt._label_bold = data.get("label_bold", True)
        pt._label_italic = data.get("label_italic", True)
        pt._label.set_font_size(pt._font_size)
        pt._label.update_display()
        pt._update_label_visibility()
        pt._label.update_position()
        return pt
