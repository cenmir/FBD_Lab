"""Base classes for FBD Lab items — eliminates duplication across item types."""

import math
import re
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QFont, QFontDatabase,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsEllipseItem, QGraphicsTextItem,
    QApplication, QGraphicsSceneMouseEvent,
)

# ─── Shared constants ─────────────────────────────────────────────────────────

SNAP_ANGLE_DEG = 5

SELECTED_COLOR = QColor(50, 150, 255)
LABEL_COLOR = QColor(0, 0, 0)
DEFAULT_LABEL_OFFSET = QPointF(8, -8)
DEFAULT_FONT_SIZE = 22


# ─── LaTeX-to-Unicode mapping ─────────────────────────────────────────────────

LATEX_TO_UNICODE = {
    "\\alpha": "\u03b1", "\\beta": "\u03b2", "\\gamma": "\u03b3",
    "\\delta": "\u03b4", "\\epsilon": "\u03b5", "\\zeta": "\u03b6",
    "\\eta": "\u03b7", "\\theta": "\u03b8", "\\iota": "\u03b9",
    "\\kappa": "\u03ba", "\\lambda": "\u03bb", "\\mu": "\u03bc",
    "\\nu": "\u03bd", "\\xi": "\u03be", "\\pi": "\u03c0",
    "\\rho": "\u03c1", "\\sigma": "\u03c3", "\\tau": "\u03c4",
    "\\phi": "\u03c6", "\\chi": "\u03c7", "\\psi": "\u03c8",
    "\\omega": "\u03c9",
    "\\Gamma": "\u0393", "\\Delta": "\u0394", "\\Theta": "\u0398",
    "\\Lambda": "\u039b", "\\Sigma": "\u03a3", "\\Phi": "\u03a6",
    "\\Psi": "\u03a8", "\\Omega": "\u03a9",
}


def latex_to_unicode(text: str) -> str:
    """Replace LaTeX Greek letter commands with Unicode characters."""
    for cmd, char in LATEX_TO_UNICODE.items():
        text = text.replace(cmd, char)
    return text


# ─── Font loading ──────────────────────────────────────────────────────────────

_CM_FONT_FAMILY: str | None = None


def _load_cm_fonts():
    """Load bundled Computer Modern fonts. Call once after QApplication exists."""
    global _CM_FONT_FAMILY
    if _CM_FONT_FAMILY is not None:
        return
    fonts_dir = Path(__file__).parent / "fonts"
    for name in ("cmunrm.otf", "cmunbx.otf", "cmunti.otf", "cmunbi.otf"):
        path = fonts_dir / name
        if path.exists():
            fid = QFontDatabase.addApplicationFont(str(path))
            if fid >= 0 and _CM_FONT_FAMILY is None:
                families = QFontDatabase.applicationFontFamilies(fid)
                if families:
                    _CM_FONT_FAMILY = families[0]
    if _CM_FONT_FAMILY is None:
        _CM_FONT_FAMILY = "Serif"  # fallback


def get_cm_font(size: int = DEFAULT_FONT_SIZE) -> QFont:
    """Return a Computer Modern font at the given point size."""
    _load_cm_fonts()
    return QFont(_CM_FONT_FAMILY, size)


# ─── Label text formatting ─────────────────────────────────────────────────────

_LABEL_RE = re.compile(
    r'([A-Za-z]+)_\{([^}]+)\}'       # base_{subscript}
    r'|([A-Za-z]+)_([A-Za-z0-9]+)'   # base_sub
    r'|(.+)'                          # plain text
)


def label_to_html(text: str, bold: bool = True, italic: bool = True) -> str:
    """Convert physics shorthand to HTML with configurable base styling."""
    if not text:
        return ""

    def _wrap_base(s: str) -> str:
        result = s
        if italic:
            result = f"<i>{result}</i>"
        if bold:
            result = f"<b>{result}</b>"
        return result

    parts = []
    for m in _LABEL_RE.finditer(text):
        if m.group(1) is not None:
            parts.append(f"{_wrap_base(m.group(1))}<sub><i>{m.group(2)}</i></sub>")
        elif m.group(3) is not None:
            parts.append(f"{_wrap_base(m.group(3))}<sub><i>{m.group(4)}</i></sub>")
        elif m.group(5) is not None:
            parts.append(_wrap_base(m.group(5)))
    return "".join(parts)


# ─── BaseLabel ─────────────────────────────────────────────────────────────────

class BaseLabel(QGraphicsTextItem):
    """Draggable label attached to any FBD item."""

    def __init__(self, parent_item):
        super().__init__()
        self._parent_item = parent_item
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
        html = self._parent_item.get_label_html()
        self.setHtml(html)

    def update_color(self, selected: bool):
        self.setDefaultTextColor(SELECTED_COLOR if selected else LABEL_COLOR)
        self.update_display()

    def update_position(self):
        self._updating = True
        anchor = self._parent_item.label_anchor()
        self.setPos(anchor + self._parent_item._label_offset)
        self._updating = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._updating:
            anchor = self._parent_item.label_anchor()
            self._parent_item._label_offset = value - anchor
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_offset = QPointF(self._parent_item._label_offset)
        if not self._parent_item.isSelected():
            if self.scene():
                self.scene().clearSelection()
            self._parent_item.setSelected(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)

        if self._drag_old_offset is None:
            return

        new_offset = QPointF(self._parent_item._label_offset)
        old_offset = self._drag_old_offset
        self._drag_old_offset = None

        if new_offset == old_offset:
            return

        push_fn = self._parent_item.on_push_undo
        if push_fn is not None:
            self._parent_item._label_offset = QPointF(old_offset)
            self.update_position()

            from commands import MoveLabelCommand
            cmd = MoveLabelCommand(self._parent_item, old_offset, new_offset)
            push_fn(cmd)


# ─── LabelPropertiesMixin ─────────────────────────────────────────────────────

class LabelPropertiesMixin:
    """Mixin providing shared label/z-order properties for all FBD item types.

    Subclass must:
    - Call _init_label_properties() in __init__ after creating self._label
    - Implement label_anchor() -> QPointF
    - Implement _get_handles() -> list
    """

    # Default item color — subclasses should set _item_color before calling
    # _init_label_properties, or override _default_item_color().
    _DEFAULT_ITEM_COLOR = QColor(0, 0, 0)

    def _default_item_color(self) -> QColor:
        return QColor(self._DEFAULT_ITEM_COLOR)

    def _init_label_properties(self):
        self._label_text = ""
        self._label_visible = False
        self._label_offset = QPointF(DEFAULT_LABEL_OFFSET)
        self._font_size = DEFAULT_FONT_SIZE
        self._label_bold = True
        self._label_italic = True
        self._z_order = 0
        self.on_modified = None
        self.on_push_undo = None
        # Per-item color and opacity (if not already set by subclass __init__)
        if not hasattr(self, '_item_color'):
            self._item_color = self._default_item_color()
        if not hasattr(self, '_item_opacity'):
            self._item_opacity = 255

    # --- Abstract methods (must override) ---

    def label_anchor(self) -> QPointF:
        raise NotImplementedError

    def drag_anchor(self) -> QPointF:
        """Return the current position anchor for body-drag tracking."""
        raise NotImplementedError

    def _get_handles(self) -> list:
        return []

    def get_label_html(self) -> str:
        return label_to_html(self._label_text, self._label_bold, self._label_italic)

    # --- Properties ---

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

    @property
    def item_color(self) -> QColor:
        return QColor(self._item_color)

    @item_color.setter
    def item_color(self, value: QColor):
        self._item_color = QColor(value)
        self.update()

    @property
    def item_opacity(self) -> int:
        return self._item_opacity

    @item_opacity.setter
    def item_opacity(self, value: int):
        self._item_opacity = max(0, min(255, value))
        self.update()

    def _get_item_color_with_opacity(self) -> QColor:
        """Return item color with opacity applied (for use in paint methods)."""
        c = QColor(self._item_color)
        c.setAlpha(self._item_opacity)
        return c

    @property
    def z_order(self) -> int:
        return self._z_order

    @z_order.setter
    def z_order(self, value: int):
        self._z_order = value
        self.setZValue(1 + value)
        self._label.setZValue(5 + value)
        for handle in self._get_handles():
            handle.setZValue(10 + value)

    def _update_label_visibility(self):
        self._label.setVisible(self._label_visible and bool(self._label_text))

    def set_layer_visible(self, visible: bool):
        """Show/hide this item and all sub-items for layer visibility."""
        self.setVisible(visible)
        self._label.setVisible(
            visible and self._label_visible and bool(self._label_text)
        )
        for handle in self._get_handles():
            handle.setVisible(visible)

    # --- Scene management ---

    def added_to_scene(self, scene):
        for handle in self._get_handles():
            scene.addItem(handle)
        scene.addItem(self._label)

    def removed_from_scene(self, scene):
        for handle in self._get_handles():
            scene.removeItem(handle)
        scene.removeItem(self._label)

    # --- Serialization helpers ---

    def _base_to_dict(self) -> dict:
        d = {
            "label_text": self._label_text,
            "label_visible": self._label_visible,
            "label_offset": [self._label_offset.x(), self._label_offset.y()],
            "font_size": self._font_size,
            "label_bold": self._label_bold,
            "label_italic": self._label_italic,
            "z_order": self._z_order,
        }
        # Only save color/opacity if non-default
        default_color = self._default_item_color()
        if self._item_color != default_color:
            d["item_color"] = self._item_color.name()
        if self._item_opacity != 255:
            d["item_opacity"] = self._item_opacity
        return d

    def _base_from_dict(self, data: dict):
        self._label_text = data.get("label_text", "")
        self._label_visible = data.get("label_visible", False)
        offset = data.get("label_offset", [DEFAULT_LABEL_OFFSET.x(), DEFAULT_LABEL_OFFSET.y()])
        self._label_offset = QPointF(offset[0], offset[1])
        self._font_size = data.get("font_size", DEFAULT_FONT_SIZE)
        self._label_bold = data.get("label_bold", True)
        self._label_italic = data.get("label_italic", True)
        if "item_color" in data:
            self._item_color = QColor(data["item_color"])
        self._item_opacity = data.get("item_opacity", 255)
        self._label.set_font_size(self._font_size)
        self._label.update_display()
        self._update_label_visibility()
        self._label.update_position()
        z = data.get("z_order", 0)
        if z != 0:
            self.z_order = z


# ─── BaseControlPoint ─────────────────────────────────────────────────────────

class BaseControlPoint(QGraphicsEllipseItem):
    """Draggable handle at the tail or head of a two-endpoint item."""

    def __init__(self, x: float, y: float, parent_item, is_head: bool,
                 handle_radius: int = 6):
        super().__init__(-handle_radius, -handle_radius,
                         2 * handle_radius, 2 * handle_radius)
        self.setPos(x, y)
        self._parent_item = parent_item
        self._is_head = is_head
        self.setBrush(QBrush(SELECTED_COLOR))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.setVisible(False)

        self._drag_old_tail: QPointF | None = None
        self._drag_old_head: QPointF | None = None

    @staticmethod
    def _snap(anchor: QPointF, pos: QPointF) -> QPointF:
        """Snap pos to H/V relative to anchor if within SNAP_ANGLE_DEG."""
        dx = pos.x() - anchor.x()
        dy = pos.y() - anchor.y()
        length = math.hypot(dx, dy)
        if length < 1:
            return pos
        angle = math.degrees(math.atan2(abs(dy), abs(dx)))
        if angle <= SNAP_ANGLE_DEG:
            return QPointF(pos.x(), anchor.y())
        elif angle >= 90 - SNAP_ANGLE_DEG:
            return QPointF(anchor.x(), pos.y())
        return pos

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            modifiers = QApplication.keyboardModifiers()
            if not (modifiers & Qt.KeyboardModifier.ControlModifier):
                anchor = self._parent_item.tail if self._is_head else self._parent_item.head
                value = self._snap(anchor, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if self._is_head:
                self._parent_item.set_head(value)
            else:
                self._parent_item.set_tail(value)
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        self._drag_old_tail = QPointF(self._parent_item.tail)
        self._drag_old_head = QPointF(self._parent_item.head)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)

        if self._drag_old_tail is None:
            return

        new_tail = QPointF(self._parent_item.tail)
        new_head = QPointF(self._parent_item.head)
        old_tail = self._drag_old_tail
        old_head = self._drag_old_head
        self._drag_old_tail = None
        self._drag_old_head = None

        if new_tail == old_tail and new_head == old_head:
            return

        push_fn = self._parent_item.on_push_undo
        if push_fn is not None:
            self._parent_item.set_tail(old_tail)
            self._parent_item.set_head(old_head)

            from commands import ResizeItemCommand
            cmd = ResizeItemCommand(self._parent_item, old_tail, old_head,
                                    new_tail, new_head)
            push_fn(cmd)
