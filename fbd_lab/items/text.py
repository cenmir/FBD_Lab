"""TextItem — a standalone text label for FBD diagrams."""

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QPen, QBrush, QColor, QPainterPath, QPainter
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsRectItem,
    QStyleOptionGraphicsItem, QWidget,
)

from fbd_lab.items.base import BaseLabel, LabelPropertiesMixin, SELECTED_COLOR

DEFAULT_TEXT = "Text"


class TextItem(LabelPropertiesMixin, QGraphicsRectItem):
    """A positioned text label — renders via the LaTeX-aware label system."""

    def _default_item_color(self) -> QColor:
        return QColor(0, 0, 0)

    def __init__(self, pos: QPointF, parent=None):
        super().__init__(parent)
        self._pos = QPointF(pos)
        self._item_color = QColor(0, 0, 0)
        self._item_opacity = 255

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        self._label = BaseLabel(self)
        self._init_label_properties()
        # Text items: label always visible, default text, not bold/italic
        self._label_visible = True
        self._label_text = DEFAULT_TEXT
        self._label_bold = False
        self._label_italic = False
        self._label_offset = QPointF(0, 0)
        self._label.set_font_size(self._font_size)
        self._label.update_display()
        self._update_label_visibility()

        self._rebuild()

    # --- LabelPropertiesMixin overrides ---

    def label_anchor(self) -> QPointF:
        return QPointF(self._pos)

    def drag_anchor(self) -> QPointF:
        return QPointF(self._pos)

    # --- Properties ---

    @property
    def text_pos(self) -> QPointF:
        return QPointF(self._pos)

    # --- Movement ---

    def move_by(self, delta: QPointF):
        self._pos += delta
        self._rebuild()

    def set_pos(self, point: QPointF):
        self._pos = QPointF(point)
        self._rebuild()

    # --- Style ---

    def refresh_style(self):
        self._rebuild()
        self.update()

    def _rebuild(self):
        # Small invisible rect at the position for selection hit-testing
        self.setRect(self._pos.x() - 4, self._pos.y() - 4, 8, 8)
        self._label.update_position()
        self._label.update_display()
        if self.on_modified:
            self.on_modified()

    def shape(self) -> QPainterPath:
        # Use the label's bounding rect for click selection
        path = QPainterPath()
        if self._label.isVisible():
            label_rect = self._label.mapRectToScene(self._label.boundingRect())
            path.addRect(label_rect)
        else:
            path.addRect(QRectF(self._pos.x() - 10, self._pos.y() - 10, 20, 20))
        return path

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()
        self._label.update_color(is_sel)

        # Apply item color to label when not selected
        if not is_sel:
            color = self._get_item_color_with_opacity()
            self._label.setDefaultTextColor(color)

        # Draw selection indicator (dotted outline around text area)
        if is_sel:
            painter.setPen(QPen(SELECTED_COLOR, 1))
            painter.setBrush(QBrush(QColor(SELECTED_COLOR.red(), SELECTED_COLOR.green(),
                                           SELECTED_COLOR.blue(), 30)))
            # Map label rect to our coordinate system
            if self._label.isVisible():
                label_rect = self._label.mapRectToItem(self, self._label.boundingRect())
                painter.drawRect(label_rect)

    # --- Serialization ---

    def to_dict(self) -> dict:
        d = self._base_to_dict()
        d["pos"] = [self._pos.x(), self._pos.y()]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "TextItem":
        item = cls(QPointF(data["pos"][0], data["pos"][1]))
        item._base_from_dict(data)
        # Ensure label is always visible for text items
        item._label_visible = True
        item._update_label_visibility()
        item._rebuild()
        return item
