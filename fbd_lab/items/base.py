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
    QGraphicsPathItem,
    QApplication, QGraphicsSceneMouseEvent,
)

# ─── Shared constants ─────────────────────────────────────────────────────────

SNAP_ANGLE_DEG = 5
DEFAULT_HANDLE_RADIUS = 6

SELECTED_COLOR = QColor(50, 150, 255)
LABEL_COLOR = QColor(0, 0, 0)
DEFAULT_LABEL_OFFSET = QPointF(8, -8)
DEFAULT_FONT_SIZE = 22


# ─── LaTeX-to-Unicode mapping ─────────────────────────────────────────────────

LATEX_TO_UNICODE = {
    # Lowercase Greek
    "\\alpha": "\u03b1", "\\beta": "\u03b2", "\\gamma": "\u03b3",
    "\\delta": "\u03b4", "\\epsilon": "\u03b5", "\\zeta": "\u03b6",
    "\\eta": "\u03b7", "\\theta": "\u03b8", "\\iota": "\u03b9",
    "\\kappa": "\u03ba", "\\lambda": "\u03bb", "\\mu": "\u03bc",
    "\\nu": "\u03bd", "\\xi": "\u03be", "\\pi": "\u03c0",
    "\\rho": "\u03c1", "\\sigma": "\u03c3", "\\tau": "\u03c4",
    "\\phi": "\u03c6", "\\chi": "\u03c7", "\\psi": "\u03c8",
    "\\omega": "\u03c9",
    # Uppercase Greek
    "\\Gamma": "\u0393", "\\Delta": "\u0394", "\\Theta": "\u0398",
    "\\Lambda": "\u039b", "\\Sigma": "\u03a3", "\\Phi": "\u03a6",
    "\\Psi": "\u03a8", "\\Omega": "\u03a9",
    # Common symbols
    "\\circ": "\u00b0", "\\deg": "\u00b0",
    "\\cdot": "\u00b7", "\\times": "\u00d7", "\\pm": "\u00b1",
    "\\inf": "\u221e", "\\infty": "\u221e",
    "\\perp": "\u27c2", "\\parallel": "\u2225",
    "\\neq": "\u2260", "\\leq": "\u2264", "\\geq": "\u2265",
    "\\approx": "\u2248", "\\sum": "\u2211", "\\sqrt": "\u221a",
    "\\rightarrow": "\u2192", "\\leftarrow": "\u2190",
    "\\hat": "\u0302",
}


def latex_to_unicode(text: str) -> str:
    """Replace LaTeX Greek letter commands with Unicode characters."""
    for cmd, char in LATEX_TO_UNICODE.items():
        text = text.replace(cmd, char)
    return text


# ─── Font loading ──────────────────────────────────────────────────────────────

_CM_FONT_FAMILY: str | None = None


def _load_cm_fonts():
    global _CM_FONT_FAMILY
    if _CM_FONT_FAMILY is not None:
        return
    fonts_dir = Path(__file__).parent.parent / "fonts"
    for name in ("cmunrm.otf", "cmunbx.otf", "cmunti.otf", "cmunbi.otf"):
        path = fonts_dir / name
        if path.exists():
            fid = QFontDatabase.addApplicationFont(str(path))
            if fid >= 0 and _CM_FONT_FAMILY is None:
                families = QFontDatabase.applicationFontFamilies(fid)
                if families:
                    _CM_FONT_FAMILY = families[0]
    if _CM_FONT_FAMILY is None:
        _CM_FONT_FAMILY = "Serif"


def get_cm_font(size: int = DEFAULT_FONT_SIZE) -> QFont:
    _load_cm_fonts()
    return QFont(_CM_FONT_FAMILY, size)


# ─── Label text formatting ─────────────────────────────────────────────────────

_TOKEN = r'[A-Za-z0-9\u00b0-\u03ff]+'
_LABEL_RE = re.compile(
    r'(' + _TOKEN + r')_\{([^}]+)\}\^\{([^}]+)\}'
    r'|(' + _TOKEN + r')\^\{([^}]+)\}_\{([^}]+)\}'
    r'|(' + _TOKEN + r')_\{([^}]+)\}'
    r'|(' + _TOKEN + r')_(' + _TOKEN + r')'
    r'|(' + _TOKEN + r')\^\{([^}]+)\}'
    r'|(' + _TOKEN + r')\^(' + _TOKEN + r')'
    r'|\^\{([^}]+)\}'
    r'|\^(' + _TOKEN + r')'
    r'|_\{([^}]+)\}'
    r'|_(' + _TOKEN + r')'
    r'|([^_^]+)'
)


def label_to_html(text: str, bold: bool = True, italic: bool = True) -> str:
    if not text:
        return ""
    text = latex_to_unicode(text)

    def _wrap_base(s):
        r = s
        if italic:
            r = f"<i>{r}</i>"
        if bold:
            r = f"<b>{r}</b>"
        return r

    def _sub(s):
        return f"<sub><i>{latex_to_unicode(s)}</i></sub>"

    def _sup(s):
        return f"<sup><i>{latex_to_unicode(s)}</i></sup>"

    parts = []
    for m in _LABEL_RE.finditer(text):
        if m.group(1) is not None:
            parts.append(f"{_wrap_base(m.group(1))}{_sub(m.group(2))}{_sup(m.group(3))}")
        elif m.group(4) is not None:
            parts.append(f"{_wrap_base(m.group(4))}{_sup(m.group(5))}{_sub(m.group(6))}")
        elif m.group(7) is not None:
            parts.append(f"{_wrap_base(m.group(7))}{_sub(m.group(8))}")
        elif m.group(9) is not None:
            parts.append(f"{_wrap_base(m.group(9))}{_sub(m.group(10))}")
        elif m.group(11) is not None:
            parts.append(f"{_wrap_base(m.group(11))}{_sup(m.group(12))}")
        elif m.group(13) is not None:
            parts.append(f"{_wrap_base(m.group(13))}{_sup(m.group(14))}")
        elif m.group(15) is not None:
            parts.append(_sup(m.group(15)))
        elif m.group(16) is not None:
            parts.append(_sup(m.group(16)))
        elif m.group(17) is not None:
            parts.append(_sub(m.group(17)))
        elif m.group(18) is not None:
            parts.append(_sub(m.group(18)))
        elif m.group(19) is not None:
            parts.append(_wrap_base(m.group(19)))
    return "".join(parts)


# ─── BaseLabel ─────────────────────────────────────────────────────────────────

class BaseLabel(QGraphicsTextItem):
    """Draggable label attached to any FBD item."""

    def __init__(self, parent_item):
        super().__init__()
        self._parent_item = parent_item
        self._drag_old_offset: QPointF | None = None
        self._updating = False
        self._has_background = False
        self._bg_color = QColor(255, 255, 255)

        self.setDefaultTextColor(LABEL_COLOR)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(5)
        self.setVisible(False)

    def set_font_size(self, size: int):
        self.setFont(get_cm_font(size))

    def set_background(self, enabled: bool):
        self._has_background = enabled
        self.update_display()

    def set_bg_color(self, color: QColor):
        self._bg_color = QColor(color)
        self.update_display()

    def update_display(self):
        html = self._parent_item.get_label_html()
        if self._has_background:
            html = f'<span style="background-color: {self._bg_color.name()}; padding: 2px;">{html}</span>'
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
            from fbd_lab.commands import MoveLabelCommand
            cmd = MoveLabelCommand(self._parent_item, old_offset, new_offset)
            push_fn(cmd)


# ─── BaseItemProperties ──────────────────────────────────────────────────────

class BaseItemProperties:
    """Mixin providing callbacks and handle/anchor stubs for all FBD items."""

    def _init_base_properties(self):
        self.on_modified = None
        self.on_push_undo = None

    def drag_anchor(self) -> QPointF:
        raise NotImplementedError

    def _get_handles(self) -> list:
        return []


# ─── StrokeProperties ────────────────────────────────────────────────────────

class StrokeProperties:
    """Mixin providing stroke color and opacity for line/vector-style items."""

    _DEFAULT_STROKE_COLOR = QColor(0, 0, 0)

    def _default_stroke_color(self) -> QColor:
        return QColor(self._DEFAULT_STROKE_COLOR)

    def _init_stroke_properties(self):
        if not hasattr(self, '_stroke_color'):
            self._stroke_color = self._default_stroke_color()
        if not hasattr(self, '_stroke_opacity'):
            self._stroke_opacity = 255

    @property
    def stroke_color(self) -> QColor:
        return QColor(self._stroke_color)

    @stroke_color.setter
    def stroke_color(self, value: QColor):
        self._stroke_color = QColor(value)
        self.update()

    @property
    def stroke_opacity(self) -> int:
        return self._stroke_opacity

    @stroke_opacity.setter
    def stroke_opacity(self, value: int):
        self._stroke_opacity = max(0, min(255, value))
        self.update()

    def _get_stroke_color_with_opacity(self) -> QColor:
        c = QColor(self._stroke_color)
        c.setAlpha(self._stroke_opacity)
        return c

    def _stroke_to_dict(self) -> dict:
        d = {}
        default_color = self._default_stroke_color()
        if self._stroke_color != default_color:
            d["stroke_color"] = self._stroke_color.name()
        if self._stroke_opacity != 255:
            d["stroke_opacity"] = self._stroke_opacity
        return d

    def _stroke_from_dict(self, data: dict):
        color_key = "stroke_color" if "stroke_color" in data else "item_color"
        if color_key in data:
            self._stroke_color = QColor(data[color_key])
        opacity_key = "stroke_opacity" if "stroke_opacity" in data else "item_opacity"
        self._stroke_opacity = data.get(opacity_key, 255)

    # ── Backward-compat aliases (used by main.py panel + undo commands) ──

    @property
    def item_color(self) -> QColor:
        return self.stroke_color

    @item_color.setter
    def item_color(self, value: QColor):
        self.stroke_color = value

    @property
    def item_opacity(self) -> int:
        return self.stroke_opacity

    @item_opacity.setter
    def item_opacity(self, value: int):
        self.stroke_opacity = value

    def _get_item_color_with_opacity(self) -> QColor:
        return self._get_stroke_color_with_opacity()

    def _default_item_color(self) -> QColor:
        return self._default_stroke_color()


# ─── LabelProperties ─────────────────────────────────────────────────────────

# ─── FillProperties ───────────────────────────────────────────────────────────

class FillProperties:
    """Mixin providing fill color and fill opacity for shape items."""

    _DEFAULT_FILL_COLOR = QColor(0xD8, 0xBA, 0x94)

    def _default_fill_color(self) -> QColor:
        return QColor(self._DEFAULT_FILL_COLOR)

    def _init_fill_properties(self):
        if not hasattr(self, '_fill_color'):
            self._fill_color = self._default_fill_color()
        if not hasattr(self, '_fill_opacity'):
            self._fill_opacity = 255

    @property
    def fill_color(self) -> QColor:
        return QColor(self._fill_color)

    @fill_color.setter
    def fill_color(self, value: QColor):
        self._fill_color = QColor(value)
        self.update()

    @property
    def fill_opacity(self) -> int:
        return self._fill_opacity

    @fill_opacity.setter
    def fill_opacity(self, value: int):
        self._fill_opacity = max(0, min(255, value))
        self.update()

    def _fill_to_dict(self) -> dict:
        d = {}
        default = self._default_fill_color()
        if self._fill_color != default:
            d["fill_color"] = self._fill_color.name()
        if self._fill_opacity != 255:
            d["fill_opacity"] = self._fill_opacity
        return d

    def _fill_from_dict(self, data: dict):
        if "fill_color" in data:
            self._fill_color = QColor(data["fill_color"])
        self._fill_opacity = data.get("fill_opacity", 255)


# ─── EdgeProperties ───────────────────────────────────────────────────────────

class EdgeProperties:
    """Mixin providing edge/outline color, opacity, and thickness for shape items."""

    _DEFAULT_EDGE_COLOR = QColor(0x8B, 0x6F, 0x4E)
    _DEFAULT_OUTLINE_THICKNESS = 2

    def _default_edge_color(self) -> QColor:
        return QColor(self._DEFAULT_EDGE_COLOR)

    def _init_edge_properties(self):
        if not hasattr(self, '_edge_color'):
            self._edge_color = self._default_edge_color()
        if not hasattr(self, '_edge_opacity'):
            self._edge_opacity = 255
        if not hasattr(self, '_outline_thickness'):
            self._outline_thickness = self._DEFAULT_OUTLINE_THICKNESS

    @property
    def edge_color(self) -> QColor:
        return QColor(self._edge_color)

    @edge_color.setter
    def edge_color(self, value: QColor):
        self._edge_color = QColor(value)
        self.update()

    @property
    def edge_opacity(self) -> int:
        return self._edge_opacity

    @edge_opacity.setter
    def edge_opacity(self, value: int):
        self._edge_opacity = max(0, min(255, value))
        self.update()

    @property
    def outline_thickness(self) -> int:
        return self._outline_thickness

    @outline_thickness.setter
    def outline_thickness(self, value: int):
        self._outline_thickness = value
        self.update()

    def _edge_to_dict(self) -> dict:
        d = {}
        default = self._default_edge_color()
        if self._edge_color != default:
            d["edge_color"] = self._edge_color.name()
        if self._edge_opacity != 255:
            d["edge_opacity"] = self._edge_opacity
        if self._outline_thickness != self._DEFAULT_OUTLINE_THICKNESS:
            d["outline_thickness"] = self._outline_thickness
        return d

    def _edge_from_dict(self, data: dict):
        if "edge_color" in data:
            self._edge_color = QColor(data["edge_color"])
        self._edge_opacity = data.get("edge_opacity", 255)
        self._outline_thickness = data.get("outline_thickness", self._DEFAULT_OUTLINE_THICKNESS)


# ─── LabelProperties ─────────────────────────────────────────────────────────

class LabelProperties:
    """Mixin providing label text, font, visibility, z-order, and scene management."""

    def _init_label_props(self):
        self._label_text = ""
        self._label_visible = False
        self._label_offset = QPointF(DEFAULT_LABEL_OFFSET)
        self._font_size = DEFAULT_FONT_SIZE
        self._label_bold = True
        self._label_italic = True
        self._label_background = False
        self._label_bg_color = QColor(255, 255, 255)
        self._z_order = 0

    def label_anchor(self) -> QPointF:
        raise NotImplementedError

    def get_label_html(self) -> str:
        return label_to_html(self._label_text, self._label_bold, self._label_italic)

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
    def label_background(self) -> bool:
        return self._label_background

    @label_background.setter
    def label_background(self, value: bool):
        self._label_background = value
        self._label.set_background(value)

    @property
    def label_bg_color(self) -> QColor:
        return QColor(self._label_bg_color)

    @label_bg_color.setter
    def label_bg_color(self, value: QColor):
        self._label_bg_color = QColor(value)
        self._label.set_bg_color(value)

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
        self.setVisible(visible)
        self._label.setVisible(
            visible and self._label_visible and bool(self._label_text)
        )
        for handle in self._get_handles():
            handle.setVisible(visible)

    def added_to_scene(self, scene):
        for handle in self._get_handles():
            scene.addItem(handle)
        scene.addItem(self._label)

    def removed_from_scene(self, scene):
        for handle in self._get_handles():
            scene.removeItem(handle)
        scene.removeItem(self._label)

    def _label_to_dict(self) -> dict:
        d = {
            "label_text": self._label_text,
            "label_visible": self._label_visible,
            "label_offset": [self._label_offset.x(), self._label_offset.y()],
            "font_size": self._font_size,
            "label_bold": self._label_bold,
            "label_italic": self._label_italic,
            "label_background": self._label_background,
            "z_order": self._z_order,
        }
        if self._label_bg_color != QColor(255, 255, 255):
            d["label_bg_color"] = self._label_bg_color.name()
        return d

    def _label_from_dict(self, data: dict):
        self._label_text = data.get("label_text", "")
        self._label_visible = data.get("label_visible", False)
        offset = data.get("label_offset", [DEFAULT_LABEL_OFFSET.x(), DEFAULT_LABEL_OFFSET.y()])
        self._label_offset = QPointF(offset[0], offset[1])
        self._font_size = data.get("font_size", DEFAULT_FONT_SIZE)
        self._label_bold = data.get("label_bold", True)
        self._label_italic = data.get("label_italic", True)
        self._label_background = data.get("label_background", False)
        if "label_bg_color" in data:
            self._label_bg_color = QColor(data["label_bg_color"])
            self._label.set_bg_color(self._label_bg_color)
        if self._label_background:
            self._label.set_background(True)
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
            from fbd_lab.commands import ResizeItemCommand
            cmd = ResizeItemCommand(self._parent_item, old_tail, old_head,
                                    new_tail, new_head)
            push_fn(cmd)


# ─── TwoEndpointItem ─────────────────────────────────────────────────────────

class TwoEndpointItem(BaseItemProperties, StrokeProperties, LabelProperties, QGraphicsPathItem):
    """Base class for items defined by a tail and head point.

    Provides: tail/head storage, control point handles, move_by, set_tail,
    set_head, label_anchor, drag_anchor, _get_handles, and base to_dict/from_dict.

    Subclass must implement:
    - _rebuild_path()  — build the QPainterPath and call setPath()
    - paint()
    """

    def __init__(self, tail: QPointF, head: QPointF, handle_radius: int = DEFAULT_HANDLE_RADIUS,
                 parent=None):
        super().__init__(parent)
        self._tail = QPointF(tail)
        self._head = QPointF(head)

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        self._tail_handle = BaseControlPoint(tail.x(), tail.y(), self,
                                             is_head=False, handle_radius=handle_radius)
        self._head_handle = BaseControlPoint(head.x(), head.y(), self,
                                             is_head=True, handle_radius=handle_radius)

        self._label = BaseLabel(self)
        self._init_base_properties()
        self._init_stroke_properties()
        self._init_label_props()
        self._label.set_font_size(self._font_size)

    # --- Mixin overrides ---

    def label_anchor(self) -> QPointF:
        return (self._tail + self._head) / 2

    def drag_anchor(self) -> QPointF:
        return QPointF(self._tail)

    def _get_handles(self) -> list:
        return [self._tail_handle, self._head_handle]

    # --- Properties ---

    @property
    def tail(self) -> QPointF:
        return QPointF(self._tail)

    @property
    def head(self) -> QPointF:
        return QPointF(self._head)

    # --- Movement ---

    def move_by(self, delta: QPointF):
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

    def refresh_style(self):
        r = self._tail_handle.rect().width() / 2
        self._tail_handle.setRect(-r, -r, 2 * r, 2 * r)
        self._head_handle.setRect(-r, -r, 2 * r, 2 * r)
        self._rebuild_path()
        self.update()

    # --- Abstract ---

    def _rebuild_path(self):
        raise NotImplementedError

    # --- Paint helper ---

    def _paint_preamble(self) -> tuple[bool, "QColor"]:
        """Common paint() setup. Returns (is_selected, color)."""
        is_sel = self.isSelected()
        color = SELECTED_COLOR if is_sel else self._get_stroke_color_with_opacity()
        self._tail_handle.setVisible(is_sel)
        self._head_handle.setVisible(is_sel)
        self._label.update_color(is_sel)
        return is_sel, color

    # --- Serialization ---

    def _endpoint_to_dict(self) -> dict:
        d = self._label_to_dict()
        d.update(self._stroke_to_dict())
        d["tail"] = [self._tail.x(), self._tail.y()]
        d["head"] = [self._head.x(), self._head.y()]
        return d

    @classmethod
    def _endpoint_from_dict(cls, data: dict, **kwargs) -> "TwoEndpointItem":
        item = cls(
            QPointF(data["tail"][0], data["tail"][1]),
            QPointF(data["head"][0], data["head"][1]),
            **kwargs,
        )
        item._stroke_from_dict(data)
        item._label_from_dict(data)
        return item
