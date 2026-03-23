"""RectangleItem — a rotatable, resizable filled rectangle for FBD diagrams."""

import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainterPathStroker, QPainter,
    QPolygonF, QLinearGradient,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem,
    QGraphicsSceneMouseEvent, QGraphicsSimpleTextItem,
    QStyleOptionGraphicsItem, QWidget,
)

from base_item import BaseLabel, LabelPropertiesMixin, SELECTED_COLOR
from rotation_handle import RotationHandleItem

RECT_FILL_COLOR = QColor(0xD8, 0xBA, 0x94)       # warm wood / crate color
RECT_OUTLINE_COLOR = QColor(0x8B, 0x6F, 0x4E)     # darker brown outline

DEFAULT_FILL_OPACITY = 255       # 0-255
DEFAULT_EDGE_OPACITY = 255       # 0-255
DEFAULT_OUTLINE_THICKNESS = 2
DEFAULT_AXIS_LENGTH = 60.0
COG_RADIUS = 8
ARROWHEAD_LENGTH = 10
ARROWHEAD_WIDTH = 7


@dataclass
class RectangleSettings:
    handle_radius: int = 6


rectangle_settings = RectangleSettings()


class CornerHandle(QGraphicsEllipseItem):
    """Draggable handle at a corner of a RectangleItem.

    Parented to the RectangleItem so it inherits rotation and translation.
    Positions are in the RectangleItem's local coordinate system.
    """

    def __init__(self, parent_item: "RectangleItem", corner_index: int,
                 handle_radius: int = 6):
        # Parent to the RectangleItem so transforms are inherited
        super().__init__(-handle_radius, -handle_radius,
                         2 * handle_radius, 2 * handle_radius, parent_item)
        self._parent_item = parent_item
        self._corner_index = corner_index
        self.setBrush(QBrush(SELECTED_COLOR))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.setVisible(False)

        self._drag_old_rect: QRectF | None = None
        self._trapezoid_mode = False
        self._drag_old_inset: float | None = None

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            if self._trapezoid_mode:
                # Constrain to horizontal movement only
                r = self._parent_item._local_rect
                y = r.top() if self._corner_index in (0, 1) else r.bottom()
                # Clamp inset to half the width
                half_w = r.width() / 2 - 2
                if self._corner_index in (0, 3):   # left side: inset = x - left
                    x = max(r.left(), min(r.left() + half_w, value.x()))
                else:                               # right side: inset = right - x
                    x = max(r.right() - half_w, min(r.right(), value.x()))
                return QPointF(x, y)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if self._trapezoid_mode:
                self._parent_item._corner_inset_changed(self._corner_index, value)
            else:
                self._parent_item._corner_moved(self._corner_index, value)
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        mods = event.modifiers()
        self._trapezoid_mode = bool(
            mods & Qt.KeyboardModifier.ControlModifier
            and mods & Qt.KeyboardModifier.AltModifier
        )
        if self._trapezoid_mode:
            inset_prop = '_top_inset' if self._corner_index in (0, 1) else '_bottom_inset'
            self._drag_old_inset = getattr(self._parent_item, inset_prop)
        else:
            self._drag_old_rect = QRectF(self._parent_item._local_rect)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        push_fn = self._parent_item.on_push_undo

        if self._trapezoid_mode:
            if self._drag_old_inset is None:
                return
            prop = 'top_inset' if self._corner_index in (0, 1) else 'bottom_inset'
            old_val = self._drag_old_inset
            new_val = getattr(self._parent_item, prop)
            self._drag_old_inset = None
            self._trapezoid_mode = False
            if abs(old_val - new_val) < 0.5:
                return
            if push_fn is not None:
                setattr(self._parent_item, prop, old_val)
                from commands import ChangeShapePropertyCommand
                cmd = ChangeShapePropertyCommand(
                    self._parent_item, prop, old_val, new_val, "Change Trapezoid Inset")
                push_fn(cmd)
        else:
            if self._drag_old_rect is None:
                return
            old_rect = self._drag_old_rect
            new_rect = QRectF(self._parent_item._local_rect)
            self._drag_old_rect = None
            if old_rect == new_rect:
                return
            if push_fn is not None:
                self._parent_item._set_local_rect(old_rect)
                from commands import ChangeRectCommand
                cmd = ChangeRectCommand(self._parent_item, old_rect, new_rect)
                push_fn(cmd)


class AxisHandle(QGraphicsEllipseItem):
    """Draggable handle at the end of a local coordinate axis.

    Constrained to move along its axis direction only (changes length).
    axis: 'n' for normal (up / -Y) or 't' for tangent (right / +X).
    """

    def __init__(self, parent_item: "RectangleItem", axis: str,
                 handle_radius: int = 5):
        super().__init__(-handle_radius, -handle_radius,
                         2 * handle_radius, 2 * handle_radius, parent_item)
        self._parent_item = parent_item
        self._axis = axis
        self.setBrush(QBrush(QColor(0, 0, 0)))
        self.setPen(QPen(QColor(255, 255, 255), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10)
        self.setVisible(False)
        self._drag_old_length: float | None = None

    def itemChange(self, change, value):
        c = self._parent_item._local_rect.center()
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # Constrain to axis direction, relative to rect center
            if self._axis == 'n':
                new_len = max(15, c.y() - value.y())
                return QPointF(c.x(), c.y() - new_len)
            else:
                new_len = max(15, value.x() - c.x())
                return QPointF(c.x() + new_len, c.y())
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._parent_item.prepareGeometryChange()
            if self._axis == 'n':
                self._parent_item._n_length = c.y() - value.y()
            else:
                self._parent_item._t_length = value.x() - c.x()
            self._parent_item._update_axis_labels()
            self._parent_item.update()
            if self._parent_item.on_modified:
                self._parent_item.on_modified()
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if self._axis == 'n':
            self._drag_old_length = self._parent_item._n_length
        else:
            self._drag_old_length = self._parent_item._t_length
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        if self._drag_old_length is None:
            return
        old_len = self._drag_old_length
        prop = 'n_length' if self._axis == 'n' else 't_length'
        new_len = getattr(self._parent_item, prop)
        self._drag_old_length = None
        if abs(old_len - new_len) < 0.5:
            return
        push_fn = self._parent_item.on_push_undo
        if push_fn is not None:
            setattr(self._parent_item, prop, old_len)
            from commands import ChangeShapePropertyCommand
            cmd = ChangeShapePropertyCommand(
                self._parent_item, prop, old_len, new_len,
                f"Change {self._axis.upper()}-axis Length")
            push_fn(cmd)


class RectangleItem(LabelPropertiesMixin, QGraphicsPathItem):
    """A filled rectangle that can be moved, resized via corner handles, and rotated.

    Constructed from two opposite scene-space corners (the click-drag points).
    """

    def __init__(self, corner1: QPointF, corner2: QPointF, parent=None):
        super().__init__(parent)
        self._outline_thickness = DEFAULT_OUTLINE_THICKNESS
        self._fill_color = QColor(RECT_FILL_COLOR)
        self._fill_opacity = DEFAULT_FILL_OPACITY
        self._edge_color = QColor(RECT_OUTLINE_COLOR)
        self._edge_opacity = DEFAULT_EDGE_OPACITY

        # Fade mode
        self._fade = False

        # Trapezoid insets (symmetric offset from rect edge)
        self._top_inset = 0.0
        self._bottom_inset = 0.0

        # COG and local coordinate system
        self._show_cog = False
        self._show_local_cs = False
        self._show_cs_labels = True
        self._n_length = DEFAULT_AXIS_LENGTH
        self._t_length = DEFAULT_AXIS_LENGTH
        self._n_label_text = "n"
        self._t_label_text = "t"

        # Compute the axis-aligned rect from the two corners
        x1, y1 = min(corner1.x(), corner2.x()), min(corner1.y(), corner2.y())
        x2, y2 = max(corner1.x(), corner2.x()), max(corner1.y(), corner2.y())
        w, h = x2 - x1, y2 - y1

        # Position the item at the rect center; local rect is centered at origin
        center = QPointF((x1 + x2) / 2, (y1 + y2) / 2)
        self.setPos(center)
        self._local_rect = QRectF(-w / 2, -h / 2, w, h)
        self.setTransformOriginPoint(QPointF(0, 0))

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(1)

        # Corner handles: TL, TR, BR, BL — parented to self
        r = rectangle_settings.handle_radius
        self._handles = [CornerHandle(self, i, r) for i in range(4)]

        # Rotation handle — parented to self
        self._rotation_handle = RotationHandleItem(self)

        # Axis handles — parented to self
        self._n_handle = AxisHandle(self, 'n')
        self._t_handle = AxisHandle(self, 't')

        # Axis labels — parented to self so they rotate with the rectangle
        self._n_label_item = QGraphicsSimpleTextItem(self)
        self._t_label_item = QGraphicsSimpleTextItem(self)
        self._n_label_item.setVisible(False)
        self._t_label_item.setVisible(False)

        # Label
        self._label = BaseLabel(self)
        self._init_label_properties()
        self._label.set_font_size(self._font_size)

        self._rebuild()

    # --- LabelPropertiesMixin overrides ---

    def label_anchor(self) -> QPointF:
        return self.mapToScene(self._local_rect.center())

    def drag_anchor(self) -> QPointF:
        return QPointF(self.pos())

    def _get_handles(self) -> list:
        return list(self._handles) + [self._rotation_handle,
                                       self._n_handle, self._t_handle]

    # --- Properties ---

    @property
    def center(self) -> QPointF:
        return QPointF(self.pos())

    @property
    def rect_width(self) -> float:
        return self._local_rect.width()

    @property
    def rect_height(self) -> float:
        return self._local_rect.height()

    @property
    def outline_thickness(self) -> int:
        return self._outline_thickness

    @outline_thickness.setter
    def outline_thickness(self, value: int):
        self._outline_thickness = value
        self.update()

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
    def fade(self) -> bool:
        return self._fade

    @fade.setter
    def fade(self, value: bool):
        self._fade = value
        self.update()

    @property
    def top_inset(self) -> float:
        return self._top_inset

    @top_inset.setter
    def top_inset(self, value: float):
        self._top_inset = value
        self._rebuild()
        self.update()

    @property
    def bottom_inset(self) -> float:
        return self._bottom_inset

    @bottom_inset.setter
    def bottom_inset(self, value: float):
        self._bottom_inset = value
        self._rebuild()
        self.update()

    # --- COG & local coordinate system properties ---

    @property
    def show_cog(self) -> bool:
        return self._show_cog

    @show_cog.setter
    def show_cog(self, value: bool):
        self.prepareGeometryChange()
        self._show_cog = value
        self.update()

    @property
    def show_local_cs(self) -> bool:
        return self._show_local_cs

    @show_local_cs.setter
    def show_local_cs(self, value: bool):
        self.prepareGeometryChange()
        self._show_local_cs = value
        self._update_cs_visibility()
        self.update()

    @property
    def show_cs_labels(self) -> bool:
        return self._show_cs_labels

    @show_cs_labels.setter
    def show_cs_labels(self, value: bool):
        self._show_cs_labels = value
        self._update_cs_visibility()
        self.update()

    @property
    def n_length(self) -> float:
        return self._n_length

    @n_length.setter
    def n_length(self, value: float):
        self.prepareGeometryChange()
        self._n_length = max(15, value)
        c = self._local_rect.center()
        self._n_handle.setPos(c.x(), c.y() - self._n_length)
        self._update_axis_labels()
        self.update()

    @property
    def t_length(self) -> float:
        return self._t_length

    @t_length.setter
    def t_length(self, value: float):
        self.prepareGeometryChange()
        self._t_length = max(15, value)
        c = self._local_rect.center()
        self._t_handle.setPos(c.x() + self._t_length, c.y())
        self._update_axis_labels()
        self.update()

    @property
    def n_label_text(self) -> str:
        return self._n_label_text

    @n_label_text.setter
    def n_label_text(self, value: str):
        self._n_label_text = value
        self._update_axis_labels()

    @property
    def t_label_text(self) -> str:
        return self._t_label_text

    @t_label_text.setter
    def t_label_text(self, value: str):
        self._t_label_text = value
        self._update_axis_labels()

    # --- Movement ---

    def move_by(self, delta: QPointF):
        self.setPos(self.pos() + delta)
        self._label.update_position()
        if self.on_modified:
            self.on_modified()

    # --- Rect manipulation ---

    def _recenter(self):
        """Shift pos so that local rect is centered at origin."""
        c = self._local_rect.center()
        if abs(c.x()) > 0.01 or abs(c.y()) > 0.01:
            # Move the item position by the offset (in scene coords, accounting for rotation)
            self.setPos(self.mapToScene(c))
            w, h = self._local_rect.width(), self._local_rect.height()
            self._local_rect = QRectF(-w / 2, -h / 2, w, h)

    def _set_local_rect(self, rect: QRectF):
        self._local_rect = QRectF(rect)
        self._rebuild()

    def _polygon_to_rect_x(self, index: int, x: float) -> float:
        """Convert a polygon corner X to the corresponding rect corner X."""
        if index == 0:   return x - self._top_inset      # TL
        elif index == 1: return x + self._top_inset      # TR
        elif index == 2: return x + self._bottom_inset   # BR
        else:            return x - self._bottom_inset   # BL

    def _corner_moved(self, index: int, new_pos: QPointF):
        """Called when a corner handle is dragged. Opposite corner stays fixed."""
        # Convert polygon corners back to rect corners
        new_rect_x = self._polygon_to_rect_x(index, new_pos.x())
        opposite = (index + 2) % 4
        opp_rect = self._get_rect_corners()[opposite]
        x1 = min(opp_rect.x(), new_rect_x)
        y1 = min(opp_rect.y(), new_pos.y())
        x2 = max(opp_rect.x(), new_rect_x)
        y2 = max(opp_rect.y(), new_pos.y())
        self._local_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
        self._recenter()
        self._rebuild()

    def _corner_inset_changed(self, index: int, new_pos: QPointF):
        """Called when a corner is dragged in trapezoid mode (CTRL+ALT)."""
        r = self._local_rect
        if index == 0:    # TL: inset = x - left
            self._top_inset = new_pos.x() - r.left()
        elif index == 1:  # TR: inset = right - x
            self._top_inset = r.right() - new_pos.x()
        elif index == 2:  # BR: inset = right - x
            self._bottom_inset = r.right() - new_pos.x()
        elif index == 3:  # BL: inset = x - left
            self._bottom_inset = new_pos.x() - r.left()
        self._rebuild()

    def _get_rect_corners(self) -> list[QPointF]:
        """Base rectangle corners (without insets)."""
        r = self._local_rect
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]

    def _get_corners(self) -> list[QPointF]:
        """Actual visible corners (with trapezoid insets applied)."""
        r = self._local_rect
        ti, bi = self._top_inset, self._bottom_inset
        return [
            QPointF(r.left() + ti, r.top()),       # TL
            QPointF(r.right() - ti, r.top()),      # TR
            QPointF(r.right() - bi, r.bottom()),   # BR
            QPointF(r.left() + bi, r.bottom()),    # BL
        ]

    # --- Rotation ---

    @property
    def angle_ccw(self) -> float:
        """Rotation angle in counter-clockwise degrees (for display)."""
        return -self.rotation()

    @angle_ccw.setter
    def angle_ccw(self, value: float):
        self.setRotation(-value)
        self.update()

    def _on_rotation_finished(self, start_rotation: float):
        """Called by RotationHandleItem when drag ends."""
        new_rotation = self.rotation()
        if abs(new_rotation - start_rotation) < 0.01:
            return
        push_fn = self.on_push_undo
        if push_fn is not None:
            self.setRotation(start_rotation)
            from commands import ChangeRotationCommand
            cmd = ChangeRotationCommand(self, start_rotation, new_rotation)
            push_fn(cmd)

    # --- Local CS visibility helpers ---

    def _update_cs_visibility(self):
        show = self._show_local_cs
        is_sel = self.isSelected()
        self._n_handle.setVisible(show and is_sel)
        self._t_handle.setVisible(show and is_sel)
        show_labels = show and self._show_cs_labels
        self._n_label_item.setVisible(show_labels)
        self._t_label_item.setVisible(show_labels)

    def _update_axis_labels(self):
        c = self._local_rect.center()
        font = self._n_label_item.font()
        font.setPointSize(11)
        font.setItalic(True)
        for label_item, text, pos in [
            (self._n_label_item, self._n_label_text,
             QPointF(c.x() + 6, c.y() - self._n_length - 8)),
            (self._t_label_item, self._t_label_text,
             QPointF(c.x() + self._t_length - 4, c.y() + 10)),
        ]:
            label_item.setText(text)
            label_item.setFont(font)
            label_item.setBrush(QBrush(QColor(0, 0, 0)))
            label_item.setPos(pos)

    # --- Scene management (handles are children, only label needs manual add) ---

    def added_to_scene(self, scene):
        # Handles are QGraphicsItem children — auto-added to scene.
        # Only the label is a standalone scene item.
        scene.addItem(self._label)

    def removed_from_scene(self, scene):
        scene.removeItem(self._label)

    # --- Drawing ---

    def _rebuild(self):
        path = QPainterPath()
        corners = self._get_corners()
        if self._top_inset != 0 or self._bottom_inset != 0:
            poly = QPolygonF(corners + [corners[0]])  # close the polygon
            path.addPolygon(poly)
        else:
            path.addRect(self._local_rect)
        self.setPath(path)

        # Update corner handle positions (polygon corners with insets)
        for i, handle in enumerate(self._handles):
            handle.setPos(corners[i])

        # Update axis handle positions (relative to rect center)
        c = self._local_rect.center()
        self._n_handle.setPos(c.x(), c.y() - self._n_length)
        self._t_handle.setPos(c.x() + self._t_length, c.y())
        self._update_axis_labels()

        self._rotation_handle.update_position()
        self._label.update_position()

    def boundingRect(self) -> QRectF:
        r = QRectF(self._local_rect)
        pad = max(self._outline_thickness, 2) + 1
        r.adjust(-pad, -pad, pad, pad)
        c = self._local_rect.center()
        if self._show_cog:
            cr = COG_RADIUS + 2
            r = r.united(QRectF(c.x() - cr, c.y() - cr, 2 * cr, 2 * cr))
        if self._show_local_cs:
            # n-axis extends upward from center, t-axis extends right
            r = r.united(QRectF(c.x() - 5, c.y() - self._n_length - 20,
                                10, self._n_length + 20))
            r = r.united(QRectF(c.x(), c.y() - 5,
                                self._t_length + 30, 10))
        return r

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        if self._top_inset != 0 or self._bottom_inset != 0:
            corners = self._get_corners()
            path.addPolygon(QPolygonF(corners + [corners[0]]))
        else:
            path.addRect(self._local_rect)
        stroker = QPainterPathStroker()
        stroker.setWidth(6)
        return stroker.createStroke(path) | path

    def _draw_arrowhead(self, painter: QPainter, tip: QPointF,
                        dx: float, dy: float):
        """Draw an open-triangle arrowhead at tip pointing in direction (dx, dy)."""
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return
        ux, uy = dx / length, dy / length
        # Base of arrowhead
        bx = tip.x() - ux * ARROWHEAD_LENGTH
        by = tip.y() - uy * ARROWHEAD_LENGTH
        # Perpendicular
        px, py = -uy * ARROWHEAD_WIDTH / 2, ux * ARROWHEAD_WIDTH / 2
        arrow = QPolygonF([
            QPointF(bx + px, by + py),
            tip,
            QPointF(bx - px, by - py),
        ])
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(arrow)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        is_sel = self.isSelected()

        for h in self._handles:
            h.setVisible(is_sel)
        self._rotation_handle.setVisible(is_sel)
        self._label.update_color(is_sel)

        # Update axis handle/label visibility
        self._update_cs_visibility()

        r = self._local_rect
        corners = self._get_corners()
        is_trapezoid = self._top_inset != 0 or self._bottom_inset != 0

        if self._fade:
            # Fade mode: gradient fill from top edge to transparent, top edge only
            fill_col = QColor(self._fill_color)
            fill_col.setAlpha(self._fill_opacity)
            grad = QLinearGradient(QPointF(r.center().x(), r.top()),
                                   QPointF(r.center().x(), r.bottom()))
            grad.setColorAt(0.0, fill_col)
            transparent = QColor(fill_col)
            transparent.setAlpha(0)
            grad.setColorAt(1.0, transparent)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(grad))
            if is_trapezoid:
                painter.drawPolygon(QPolygonF(corners))
            else:
                painter.drawRect(r)

            # Top edge only
            edge_col = QColor(SELECTED_COLOR if is_sel else self._edge_color)
            edge_col.setAlpha(self._edge_opacity)
            painter.setPen(QPen(edge_col, self._outline_thickness))
            painter.drawLine(corners[0], corners[1])
        else:
            # Normal mode
            edge_col = QColor(SELECTED_COLOR if is_sel else self._edge_color)
            edge_col.setAlpha(self._edge_opacity)
            painter.setPen(QPen(edge_col, self._outline_thickness))

            fill_col = QColor(self._fill_color)
            fill_col.setAlpha(self._fill_opacity)
            painter.setBrush(QBrush(fill_col))

            if is_trapezoid:
                painter.drawPolygon(QPolygonF(corners))
            else:
                painter.drawRect(r)

        # COG and local CS are drawn at the rect center
        cx, cy = r.center().x(), r.center().y()

        # COG symbol — quadrant circle (alternating black/white)
        if self._show_cog:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            cr = COG_RADIUS
            arc_rect = QRectF(cx - cr, cy - cr, 2 * cr, 2 * cr)
            # Top-left & bottom-right quadrants = black
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0)))
            painter.drawPie(arc_rect, 90 * 16, 90 * 16)
            painter.drawPie(arc_rect, 270 * 16, 90 * 16)
            # Top-right & bottom-left quadrants = white
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            painter.drawPie(arc_rect, 0 * 16, 90 * 16)
            painter.drawPie(arc_rect, 180 * 16, 90 * 16)
            # Circle outline + cross
            painter.setPen(QPen(QColor(0, 0, 0), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(arc_rect)
            painter.drawLine(QPointF(cx - cr, cy), QPointF(cx + cr, cy))
            painter.drawLine(QPointF(cx, cy - cr), QPointF(cx, cy + cr))
            painter.restore()

        # Local n-t coordinate system
        if self._show_local_cs:
            dash_pen = QPen(QColor(0, 0, 0), 1.5, Qt.PenStyle.DashLine)
            dash_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            arrow_pen = QPen(QColor(0, 0, 0), 1.5)
            arrow_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            center = QPointF(cx, cy)

            # n-axis (up = -Y in Qt)
            n_tip = QPointF(cx, cy - self._n_length)
            painter.setPen(dash_pen)
            painter.drawLine(center, QPointF(cx, cy - self._n_length + ARROWHEAD_LENGTH))
            painter.setPen(arrow_pen)
            self._draw_arrowhead(painter, n_tip, 0, -1)

            # t-axis (right = +X)
            t_tip = QPointF(cx + self._t_length, cy)
            painter.setPen(dash_pen)
            painter.drawLine(center, QPointF(cx + self._t_length - ARROWHEAD_LENGTH, cy))
            painter.setPen(arrow_pen)
            self._draw_arrowhead(painter, t_tip, 1, 0)

    # --- Serialization ---

    def to_dict(self) -> dict:
        d = self._base_to_dict()
        d["center"] = [self.pos().x(), self.pos().y()]
        d["width"] = self._local_rect.width()
        d["height"] = self._local_rect.height()
        d["rotation"] = self.rotation()
        d["outline_thickness"] = self._outline_thickness
        d["fill_color"] = self._fill_color.name()
        d["fill_opacity"] = self._fill_opacity
        d["edge_color"] = self._edge_color.name()
        d["edge_opacity"] = self._edge_opacity
        d["fade"] = self._fade
        d["top_inset"] = self._top_inset
        d["bottom_inset"] = self._bottom_inset
        d["show_cog"] = self._show_cog
        d["show_local_cs"] = self._show_local_cs
        d["show_cs_labels"] = self._show_cs_labels
        d["n_length"] = self._n_length
        d["t_length"] = self._t_length
        d["n_label_text"] = self._n_label_text
        d["t_label_text"] = self._t_label_text
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "RectangleItem":
        cx, cy = data["center"]
        w, h = data["width"], data["height"]
        # Reconstruct from two corners (centered at origin initially)
        corner1 = QPointF(cx - w / 2, cy - h / 2)
        corner2 = QPointF(cx + w / 2, cy + h / 2)
        item = cls(corner1, corner2)
        item._base_from_dict(data)
        item._outline_thickness = data.get("outline_thickness", DEFAULT_OUTLINE_THICKNESS)
        if "fill_color" in data:
            item._fill_color = QColor(data["fill_color"])
        item._fill_opacity = data.get("fill_opacity", DEFAULT_FILL_OPACITY)
        if "edge_color" in data:
            item._edge_color = QColor(data["edge_color"])
        item._edge_opacity = data.get("edge_opacity", DEFAULT_EDGE_OPACITY)
        item._fade = data.get("fade", False)
        item._top_inset = data.get("top_inset", 0.0)
        item._bottom_inset = data.get("bottom_inset", 0.0)
        item._show_cog = data.get("show_cog", False)
        item._show_local_cs = data.get("show_local_cs", False)
        item._show_cs_labels = data.get("show_cs_labels", True)
        item._n_length = data.get("n_length", DEFAULT_AXIS_LENGTH)
        item._t_length = data.get("t_length", DEFAULT_AXIS_LENGTH)
        item._n_label_text = data.get("n_label_text", "n")
        item._t_label_text = data.get("t_label_text", "t")
        item.setRotation(data.get("rotation", 0.0))
        item._rebuild()
        return item

    def refresh_style(self):
        r = rectangle_settings.handle_radius
        for h in self._handles:
            h.setRect(-r, -r, 2 * r, 2 * r)
        self._rebuild()
        self.update()
