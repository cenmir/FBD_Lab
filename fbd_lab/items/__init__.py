"""FBD Lab item types — re-exports all item classes and settings."""

from fbd_lab.items.base import (  # noqa: F401
    # Constants
    SELECTED_COLOR, LABEL_COLOR, DEFAULT_LABEL_OFFSET, DEFAULT_FONT_SIZE,
    DEFAULT_HANDLE_RADIUS, SNAP_ANGLE_DEG, LATEX_TO_UNICODE,
    # Functions
    latex_to_unicode, label_to_html, get_cm_font,
    # Base classes
    BaseLabel, BaseControlPoint,
    BaseItemProperties, StrokeProperties, FillProperties, EdgeProperties,
    LabelProperties,
    TwoEndpointItem,
)

from fbd_lab.items.vector import VectorItem, VectorSettings, vector_settings  # noqa: F401
from fbd_lab.items.point import PointItem, PointSettings, point_settings, POINT_COLORS  # noqa: F401
from fbd_lab.items.direction import DirectionItem  # noqa: F401
from fbd_lab.items.line import LineItem, LineSettings, line_settings  # noqa: F401
from fbd_lab.items.moment import MomentItem, MomentSettings, moment_settings  # noqa: F401
from fbd_lab.items.rectangle import RectangleItem  # noqa: F401
from fbd_lab.items.polygon import PolygonItem  # noqa: F401
from fbd_lab.items.ellipse import EllipseItem  # noqa: F401
from fbd_lab.items.cog import CogItem  # noqa: F401
from fbd_lab.items.text import TextItem  # noqa: F401
from fbd_lab.items.spring import SpringItem  # noqa: F401
from fbd_lab.items.squiggle import SquiggleItem  # noqa: F401
from fbd_lab.items.rotation_handle import RotationHandleItem  # noqa: F401
from fbd_lab.items.pin_support import PinSupportItem  # noqa: F401

# Item type registry: (type_key, ItemClass, json_key)
# json_key is the key used in the v7 JSON payload (historical: vectors are "arrows")
ITEM_REGISTRY = [
    ('vectors',      VectorItem,      'arrows'),
    ('points',       PointItem,       'points'),
    ('directions',   DirectionItem,   'directions'),
    ('lines',        LineItem,        'lines'),
    ('moments',      MomentItem,      'moments'),
    ('rectangles',   RectangleItem,   'rectangles'),
    ('polygons',     PolygonItem,     'polygons'),
    ('ellipses',     EllipseItem,     'ellipses'),
    ('texts',        TextItem,        'texts'),
    ('springs',      SpringItem,      'springs'),
    ('squiggles',    SquiggleItem,    'squiggles'),
    ('cogs',         CogItem,         'cogs'),
    ('pin_supports', PinSupportItem,  'pin_supports'),
]
