import argparse
import getpass
import hashlib
import signal
import socket
import sys
import time
from functools import partial
from importlib.metadata import version as pkg_version
from pathlib import Path

from PyQt6.QtCore import QPointF, QSettings, QEvent, Qt
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QMessageBox, QMenu,
    QToolBar, QSpinBox, QLabel, QWidget, QHBoxLayout, QComboBox,
    QColorDialog, QPushButton, QFrame, QCheckBox, QDoubleSpinBox, QLineEdit,
)
from PyQt6.QtGui import (
    QPalette, QColor, QKeySequence, QShortcut, QAction, QPixmap, QIcon,
    QUndoStack, QImage, QPainter,
)
from PyQt6 import uic

from canvas import FBDCanvas, ToolMode, SessionMetadata  # noqa: F401 — FBDCanvas needed for uic promotion
from vector_item import vector_settings
from point_item import point_settings, POINT_COLORS
from line_item import line_settings
from moment_item import moment_settings
from commands import (
    ResizeVectorCommand, ChangeLabelTextCommand, ChangeLabelVisibilityCommand,
    ChangeMagnitudeCommand, ChangeShowMagnitudeCommand, ChangeFontSizeCommand,
    ChangeLabelBoldCommand, ChangeLabelItalicCommand,
    MovePointCommand,
    ResizeDirectionCommand, ChangeShowArrowheadCommand,
    ResizeLineCommand, ChangeBodyThicknessCommand, ChangeOutlineThicknessCommand,
    MoveMomentCommand, ChangeRadiusCommand, ChangeAnglesCommand,
    ChangeShapePropertyCommand, ChangeRotationCommand,
)
from file_io import save_fbd, load_fbd

try:
    APP_VERSION = pkg_version("fbd-lab")
except Exception:
    # Fallback: read from pyproject.toml directly when not installed
    import re
    _toml = (Path(__file__).parent / "pyproject.toml").read_text()
    APP_VERSION = re.search(r'version\s*=\s*"(.+?)"', _toml).group(1)

_KEBAB_HASH = "7ddb76ec781e3c955f9128b4896f9a3bb40a28c25292254836375578605cd2b2"


class SpinDragFilter(QWidget):
    """Event filter that adds click-drag-to-scrub on any QSpinBox / QDoubleSpinBox.

    Also disables keyboard tracking so valueChanged only fires on Enter / focus-out.
    Install with: spin.installEventFilter(SpinDragFilter(spin))
    """

    DRAG_THRESHOLD = 3  # pixels before drag starts

    def __init__(self, spinbox, sensitivity: float = 1.0, parent=None):
        super().__init__(parent or spinbox)
        self._spin = spinbox
        self._sensitivity = sensitivity
        self._dragging = False
        self._drag_start_y = 0
        self._drag_start_value = 0
        self._accumulated = 0.0
        spinbox.setKeyboardTracking(False)
        spinbox.setCursor(Qt.CursorShape.SizeVerCursor)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_y = event.globalPosition().y()
            self._drag_start_value = self._spin.value()
            self._accumulated = 0.0
            self._dragging = False
            return False

        if event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
            dy = self._drag_start_y - event.globalPosition().y()
            if not self._dragging and abs(dy) >= self.DRAG_THRESHOLD:
                self._dragging = True
                self._drag_start_y = event.globalPosition().y()
                dy = 0
            if self._dragging:
                step = self._spin.singleStep()
                self._accumulated += dy * self._sensitivity * 0.1
                self._drag_start_y = event.globalPosition().y()
                ticks = int(self._accumulated)
                if ticks != 0:
                    self._accumulated -= ticks
                    new_val = self._spin.value() + ticks * step
                    new_val = max(self._spin.minimum(), min(self._spin.maximum(), new_val))
                    self._spin.setValue(new_val)
                return True

        if event.type() == QEvent.Type.MouseButtonRelease and self._dragging:
            self._dragging = False
            return True

        return False


def _register_file_types():
    """Register .fbdb file association in the Windows registry."""
    if sys.platform != "win32":
        QMessageBox.information(None, "Not supported", "File registration is only supported on Windows.")
        return

    if not getattr(sys, "frozen", False):
        QMessageBox.warning(
            None, "Not a standalone executable",
            "File type registration is only available when running as a packaged .exe.\n\n"
            "Running from a Python script would register the Python interpreter instead."
        )
        return

    import winreg

    exe = sys.executable
    icon = exe + ",0"

    try:
        for ext in (".fbdb",):
            prog_id = f"FBDLab{ext.replace('.', '').upper()}"

            # Register ProgID
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog_id}") as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "FBD Lab File")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog_id}\DefaultIcon") as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, icon)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog_id}\shell\open\command") as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{exe}" "%1"')

            # Associate extension with ProgID
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{ext}") as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, prog_id)

        # Notify Windows of the change
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)

        QMessageBox.information(
            None, "File Types Registered",
            f"Registered .fbdb to open with:\n{exe}\n\n"
            "You can now double-click FBD files to open them."
        )
    except OSError as e:
        QMessageBox.warning(None, "Registration Failed", f"Could not write registry:\n{e}")


def computing_boring_taxes(receipt: str) -> bool:
    """Verify quarterly tax filing compliance."""
    return hashlib.sha256(receipt.encode()).hexdigest() == _KEBAB_HASH


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    parser = argparse.ArgumentParser(description="FBD Lab — Free Body Diagram Laboratory")
    parser.add_argument("--version", action="version", version=f"FBD Lab v{APP_VERSION}")
    parser.add_argument("--admin", metavar="PASSWORD", help="Unlock admin mode")
    parser.add_argument("file", nargs="?", default=None, help="FBD file to open")
    args = parser.parse_args()

    kebabsås = args.admin is not None and computing_boring_taxes(args.admin)
    if args.admin and not kebabsås:
        print("Incorrect admin password.")
        sys.exit(1)

    APP_TITLE = f"FBD Lab v{APP_VERSION}" if kebabsås else f"FBD Lab (Student) v{APP_VERSION}"

    app = QApplication(sys.argv)
    current_file = None
    dirty = False

    # Dark mode palette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(43, 43, 43))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(208, 208, 208))
    palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(50, 50, 50))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(50, 50, 50))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(208, 208, 208))
    palette.setColor(QPalette.ColorRole.Text, QColor(208, 208, 208))
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(208, 208, 208))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 51, 51))
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(128, 128, 128))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(128, 128, 128))
    app.setPalette(palette)
    app.setStyle("Fusion")

    # Load UI
    ui_path = Path(__file__).parent / "ui" / "mainwindow.ui"
    window = uic.loadUi(str(ui_path))
    window.setWindowTitle(APP_TITLE)

    icon_path = Path(__file__).parent / "ui" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Undo stack
    undo_stack = QUndoStack(window)
    window.canvas.set_undo_stack(undo_stack)

    def do_undo():
        undo_stack.undo()
        window.canvas.metadata.undo_count += 1

    window.actionUndo.triggered.connect(do_undo)
    window.actionRedo.triggered.connect(undo_stack.redo)
    undo_stack.canUndoChanged.connect(window.actionUndo.setEnabled)
    undo_stack.canRedoChanged.connect(window.actionRedo.setEnabled)
    window.actionUndo.setEnabled(False)
    window.actionRedo.setEnabled(False)

    def _init_new_metadata():
        window.canvas.metadata = SessionMetadata(
            machine_username=getpass.getuser(),
            machine_hostname=socket.gethostname(),
            created_at=time.time(),
            session_count=1,
        )

    def _update_metadata_for_save():
        window.canvas.accumulate_session_time()
        window.canvas.metadata.last_saved_at = time.time()

    _init_new_metadata()

    def update_title():
        nonlocal dirty
        name = Path(current_file).name if current_file else "Untitled"
        prefix = "* " if dirty else ""
        window.setWindowTitle(f"{prefix}{name} — {APP_TITLE}")

    def mark_dirty():
        nonlocal dirty
        if not dirty:
            dirty = True
            update_title()

    def mark_clean():
        nonlocal dirty
        dirty = False
        update_title()

    # Load default file
    if kebabsås:
        default_file = Path(__file__).parent / "models" / "test.fbdb"
        if default_file.exists():
            load_fbd(window.canvas, default_file)
            window.canvas.metadata.session_count += 1
    else:
        default_bg = Path(__file__).parent / "models" / "FBD1.png"
        if default_bg.exists():
            window.canvas.load_background_from_file(default_bg)

    # --- Recent Files ---
    MAX_RECENT_FILES = 5
    settings = QSettings("FBDLab", "FBDLab")

    recent_menu = QMenu("Open Recent", window)
    window.menuFile.insertMenu(window.actionSave, recent_menu)

    def update_recent_files_menu():
        recent_menu.clear()
        files = settings.value("recent_files", [])
        if not isinstance(files, list):
            files = []

        for path in files:
            action = QAction(str(path), window)
            action.triggered.connect(partial(load_recent_file, path))
            recent_menu.addAction(action)

        if not files:
            dummy = QAction("No Recent Files", window)
            dummy.setEnabled(False)
            recent_menu.addAction(dummy)

    def add_recent_file(path):
        files = settings.value("recent_files", [])
        if not isinstance(files, list):
            files = []

        if path in files:
            files.remove(path)
        files.insert(0, path)
        files = files[:MAX_RECENT_FILES]

        settings.setValue("recent_files", files)
        update_recent_files_menu()

    def load_recent_file(path):
        nonlocal current_file
        if not check_unsaved_changes():
            return
        if not Path(path).exists():
            QMessageBox.warning(window, "File Not Found", f"The file {path} does not exist.")
            files = settings.value("recent_files", [])
            if isinstance(files, list) and path in files:
                files.remove(path)
                settings.setValue("recent_files", files)
                update_recent_files_menu()
            return
        _do_open(path)

    update_recent_files_menu()

    # --- Menu actions ---

    def check_unsaved_changes():
        """Returns True if safe to continue (saved or discarded), False if cancelled."""
        if not dirty:
            return True
        reply = QMessageBox.question(
            window, "Unsaved Changes",
            "You have unsaved changes. Do you want to save before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Save:
            save()
            return True
        elif reply == QMessageBox.StandardButton.Discard:
            return True
        return False

    def _sync_layer_checkboxes():
        """Sync layer checkboxes and identifier to match the canvas state."""
        c = window.canvas
        window.identifierLineEdit.setText(c.identifier)
        window.backgroundLayerCheckBox.setChecked(c._bg_visible)
        window.vectorsLayerCheckBox.setChecked(c._visibility.get('vectors', True))
        window.pointsLayerCheckBox.setChecked(c._visibility.get('points', True))
        window.directionsLayerCheckBox.setChecked(c._visibility.get('directions', True))
        window.linesLayerCheckBox.setChecked(c._visibility.get('lines', True))
        window.momentsLayerCheckBox.setChecked(c._visibility.get('moments', True))
        window.rectanglesLayerCheckBox.setChecked(c._visibility.get('rectangles', True))
        window.polygonsLayerCheckBox.setChecked(c._visibility.get('polygons', True))
        window.ellipsesLayerCheckBox.setChecked(c._visibility.get('ellipses', True))
        window.textsLayerCheckBox.setChecked(c._visibility.get('texts', True))
        window.springsLayerCheckBox.setChecked(c._visibility.get('springs', True))
        window.squigglesLayerCheckBox.setChecked(c._visibility.get('squiggles', True))
        window.cogsLayerCheckBox.setChecked(c._visibility.get('cogs', True))

    def _do_open(file_path):
        """Load a file into the canvas, resetting undo and dirty state."""
        nonlocal current_file
        load_fbd(window.canvas, file_path)
        window.canvas.metadata.session_count += 1
        current_file = file_path
        undo_stack.clear()
        mark_clean()
        add_recent_file(file_path)
        _sync_layer_checkboxes()

    def new_file():
        nonlocal current_file
        if not check_unsaved_changes():
            return
        window.canvas.clear_vectors()
        window.canvas.clear_points()
        window.canvas.clear_directions()
        window.canvas.clear_lines()
        window.canvas.clear_moments()
        window.canvas.clear_rectangles()
        window.canvas.clear_polygons()
        window.canvas.clear_ellipses()
        window.canvas.clear_texts()
        window.canvas.clear_springs()
        window.canvas.clear_squiggles()
        window.canvas.clear_cogs()
        window.canvas.set_background(QPixmap())
        window.canvas.identifier = ""
        window.identifierLineEdit.setText("")
        _init_new_metadata()
        current_file = None
        undo_stack.clear()
        mark_clean()

    def import_background():
        file_path, _ = QFileDialog.getOpenFileName(
            window, "Import Background Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if file_path:
            window.canvas.load_background_from_file(file_path)

    def save_as():
        nonlocal current_file
        file_path, _ = QFileDialog.getSaveFileName(
            window, "Save FBD File", "",
            "FBD Files (*.fbdb);;All Files (*)"
        )
        if not file_path:
            return
        if not file_path.endswith(".fbdb"):
            file_path += ".fbdb"

        _update_metadata_for_save()
        save_fbd(window.canvas, file_path)
        current_file = file_path
        mark_clean()
        add_recent_file(current_file)

    def save():
        nonlocal current_file
        if current_file:
            _update_metadata_for_save()
            save_fbd(window.canvas, current_file)
            mark_clean()
        else:
            save_as()

    def open_file():
        if not check_unsaved_changes():
            return
        filters = "FBD Files (*.fbdb);;Legacy FBD (*.fbd);;All Files (*)"
        file_path, _ = QFileDialog.getOpenFileName(
            window, "Open FBD File", "", filters
        )
        if file_path:
            _do_open(file_path)

    def export_png():
        file_path, _ = QFileDialog.getSaveFileName(
            window, "Export as PNG", "",
            "PNG Images (*.png);;All Files (*)"
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".png"):
            file_path += ".png"
        scene = window.canvas.scene()
        # Clear selection so handles/highlights don't appear in export
        scene.clearSelection()
        rect = scene.sceneRect()
        image = QImage(int(rect.width()), int(rect.height()), QImage.Format.Format_ARGB32)
        image.fill(QColor(255, 255, 255))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scene.render(painter)
        painter.end()
        image.save(file_path)

    window.actionNew.triggered.connect(new_file)
    window.actionImportBackground.triggered.connect(import_background)
    window.actionSave.triggered.connect(save)
    window.actionSaveAs.triggered.connect(save_as)
    window.actionOpen.triggered.connect(open_file)
    window.actionExportPNG.triggered.connect(export_png)

    if sys.platform == "win32":
        register_action = QAction("Register File Type (.fbdb)", window)
        register_action.triggered.connect(_register_file_types)
        window.menuFile.addSeparator()
        window.menuFile.addAction(register_action)

    # Open file from command line argument
    if args.file:
        file_to_open = Path(args.file)
        if file_to_open.exists():
            _do_open(str(file_to_open.resolve()))

    # --- Vector Settings toolbar ---
    vector_toolbar = QToolBar("Vector Settings", window)
    vector_toolbar.setFixedHeight(50)
    vector_toolbar.setMovable(False)
    window.addToolBar(vector_toolbar)
    vector_toolbar.setVisible(False)

    def _make_toolbar_spinbox(toolbar, label_text: str, value: int, min_val: int, max_val: int):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(6, 0, 6, 0)
        lbl = QLabel(label_text)
        sb = QSpinBox()
        sb.setRange(min_val, max_val)
        sb.setValue(value)
        sb.setFixedWidth(60)
        layout.addWidget(lbl)
        layout.addWidget(sb)
        toolbar.addWidget(container)
        return sb

    def _refresh_all_vectors():
        for vec in window.canvas.get_vectors():
            vec.refresh_style()

    sb_shaft = _make_toolbar_spinbox(vector_toolbar, "Shaft:", vector_settings.shaft_thickness, 1, 30)
    sb_head_len = _make_toolbar_spinbox(vector_toolbar, "Head Length:", vector_settings.arrowhead_length, 4, 60)
    sb_head_width = _make_toolbar_spinbox(vector_toolbar, "Head Width:", vector_settings.arrowhead_width, 4, 60)
    sb_notch = _make_toolbar_spinbox(vector_toolbar, "Notch:", vector_settings.arrowhead_notch, 0, 40)
    sb_outline = _make_toolbar_spinbox(vector_toolbar, "Outline:", vector_settings.arrow_thickness, 0, 10)
    sb_handle = _make_toolbar_spinbox(vector_toolbar, "Handle:", vector_settings.handle_radius, 2, 20)

    def _on_shaft(v):
        vector_settings.shaft_thickness = v
        _refresh_all_vectors()

    def _on_head_len(v):
        vector_settings.arrowhead_length = v
        _refresh_all_vectors()

    def _on_head_width(v):
        vector_settings.arrowhead_width = v
        _refresh_all_vectors()

    def _on_notch(v):
        vector_settings.arrowhead_notch = v
        _refresh_all_vectors()

    def _on_outline(v):
        vector_settings.arrow_thickness = v
        _refresh_all_vectors()

    def _on_handle(v):
        vector_settings.handle_radius = v
        _refresh_all_vectors()

    sb_shaft.valueChanged.connect(_on_shaft)
    sb_head_len.valueChanged.connect(_on_head_len)
    sb_head_width.valueChanged.connect(_on_head_width)
    sb_notch.valueChanged.connect(_on_notch)
    sb_outline.valueChanged.connect(_on_outline)
    sb_handle.valueChanged.connect(_on_handle)

    # --- Point Settings toolbar ---
    point_toolbar = QToolBar("Point Settings", window)
    point_toolbar.setFixedHeight(50)
    point_toolbar.setMovable(False)
    window.addToolBar(point_toolbar)
    point_toolbar.setVisible(False)

    sb_point_radius = _make_toolbar_spinbox(point_toolbar, "Point Size:", point_settings.radius, 1, 50)

    def _on_point_radius(v):
        point_settings.radius = v
        for p in window.canvas.get_points():
            p.refresh_style()

    sb_point_radius.valueChanged.connect(_on_point_radius)

    # Point color combo
    color_container = QWidget()
    color_layout = QHBoxLayout(color_container)
    color_layout.setContentsMargins(6, 0, 6, 0)
    color_layout.addWidget(QLabel("Color:"))
    cb_point_color = QComboBox()
    for name, qcolor in POINT_COLORS.items():
        cb_point_color.addItem(name, name)
    cb_point_color.setCurrentText(point_settings.color_name)
    cb_point_color.setFixedWidth(100)
    color_layout.addWidget(cb_point_color)
    point_toolbar.addWidget(color_container)

    def _on_point_color(name):
        point_settings.color_name = name
        for p in window.canvas.get_points():
            p.update()

    cb_point_color.currentTextChanged.connect(_on_point_color)

    # --- Line Settings toolbar ---
    line_toolbar = QToolBar("Line Settings", window)
    line_toolbar.setFixedHeight(50)
    line_toolbar.setMovable(False)
    window.addToolBar(line_toolbar)
    line_toolbar.setVisible(False)

    sb_line_handle = _make_toolbar_spinbox(line_toolbar, "Handle:", line_settings.handle_radius, 2, 20)

    def _refresh_all_lines():
        for ln in window.canvas.get_lines():
            ln.refresh_style()

    def _on_line_handle(v):
        line_settings.handle_radius = v
        _refresh_all_lines()

    sb_line_handle.valueChanged.connect(_on_line_handle)

    # --- Moment Settings toolbar ---
    moment_toolbar = QToolBar("Moment Settings", window)
    moment_toolbar.setFixedHeight(50)
    moment_toolbar.setMovable(False)
    window.addToolBar(moment_toolbar)
    moment_toolbar.setVisible(False)

    sb_arc_thick = _make_toolbar_spinbox(moment_toolbar, "Arc:", moment_settings.arc_thickness, 1, 10)
    sb_ah_len = _make_toolbar_spinbox(moment_toolbar, "Head Len:", moment_settings.arrowhead_length, 4, 30)
    sb_ah_wid = _make_toolbar_spinbox(moment_toolbar, "Head Wid:", moment_settings.arrowhead_width, 4, 30)
    sb_m_handle = _make_toolbar_spinbox(moment_toolbar, "Handle:", moment_settings.handle_radius, 2, 20)
    sb_m_center = _make_toolbar_spinbox(moment_toolbar, "Center:", moment_settings.center_radius, 1, 20)

    def _refresh_all_moments():
        for m in window.canvas.get_moments():
            m.refresh_style()

    def _on_arc_thick(v):
        moment_settings.arc_thickness = v
        _refresh_all_moments()

    def _on_ah_len(v):
        moment_settings.arrowhead_length = v
        _refresh_all_moments()

    def _on_ah_wid(v):
        moment_settings.arrowhead_width = v
        _refresh_all_moments()

    def _on_m_handle(v):
        moment_settings.handle_radius = v
        _refresh_all_moments()

    def _on_m_center(v):
        moment_settings.center_radius = v
        _refresh_all_moments()

    sb_arc_thick.valueChanged.connect(_on_arc_thick)
    sb_ah_len.valueChanged.connect(_on_ah_len)
    sb_ah_wid.valueChanged.connect(_on_ah_wid)
    sb_m_handle.valueChanged.connect(_on_m_handle)
    sb_m_center.valueChanged.connect(_on_m_center)

    # --- "Shape Format" menu on menu bar ---
    shape_format_menu = QMenu("Shape Format", window)
    window.menubar.addMenu(shape_format_menu)

    toggle_vector_toolbar = QAction("Vector Settings", window)
    toggle_vector_toolbar.setCheckable(True)
    toggle_vector_toolbar.toggled.connect(vector_toolbar.setVisible)
    shape_format_menu.addAction(toggle_vector_toolbar)

    toggle_point_toolbar = QAction("Point Settings", window)
    toggle_point_toolbar.setCheckable(True)
    toggle_point_toolbar.toggled.connect(point_toolbar.setVisible)
    shape_format_menu.addAction(toggle_point_toolbar)

    toggle_line_toolbar = QAction("Line Settings", window)
    toggle_line_toolbar.setCheckable(True)
    toggle_line_toolbar.toggled.connect(line_toolbar.setVisible)
    shape_format_menu.addAction(toggle_line_toolbar)

    toggle_moment_toolbar = QAction("Moment Settings", window)
    toggle_moment_toolbar.setCheckable(True)
    toggle_moment_toolbar.toggled.connect(moment_toolbar.setVisible)
    shape_format_menu.addAction(toggle_moment_toolbar)

    # --- Tool creation toggles ---
    def on_vector_toggle(checked):
        if checked:
            window.canvas.set_tool(ToolMode.VECTOR)
        else:
            window.canvas.set_tool(ToolMode.SELECT)

    def on_point_toggle(checked):
        if checked:
            window.canvas.set_tool(ToolMode.POINT)
        else:
            window.canvas.set_tool(ToolMode.SELECT)

    def on_direction_toggle(checked):
        if checked:
            window.canvas.set_tool(ToolMode.DIRECTION)
        else:
            window.canvas.set_tool(ToolMode.SELECT)

    def on_line_toggle(checked):
        if checked:
            window.canvas.set_tool(ToolMode.LINE)
        else:
            window.canvas.set_tool(ToolMode.SELECT)

    def on_moment_toggle(checked):
        if checked:
            window.canvas.set_tool(ToolMode.MOMENT)
        else:
            window.canvas.set_tool(ToolMode.SELECT)

    def on_rectangle_toggle(checked):
        if checked:
            window.canvas.set_tool(ToolMode.RECTANGLE)
        else:
            window.canvas.set_tool(ToolMode.SELECT)

    def on_polygon_toggle(checked):
        if checked:
            window.canvas.set_tool(ToolMode.POLYGON)
        else:
            window.canvas.set_tool(ToolMode.SELECT)

    def on_ellipse_toggle(checked):
        if checked:
            window.canvas.set_tool(ToolMode.ELLIPSE)
        else:
            window.canvas.set_tool(ToolMode.SELECT)

    def on_text_toggle(checked):
        if checked:
            window.canvas.set_tool(ToolMode.TEXT)
        else:
            window.canvas.set_tool(ToolMode.SELECT)

    def on_spring_toggle(checked):
        if checked:
            window.canvas.set_tool(ToolMode.SPRING)
        else:
            window.canvas.set_tool(ToolMode.SELECT)

    def on_squiggle_toggle(checked):
        if checked:
            window.canvas.set_tool(ToolMode.SQUIGGLE)
        else:
            window.canvas.set_tool(ToolMode.SELECT)

    def on_cog_toggle(checked):
        if checked:
            window.canvas.set_tool(ToolMode.COG)
        else:
            window.canvas.set_tool(ToolMode.SELECT)

    window.vectorToolButton.toggled.connect(on_vector_toggle)
    window.pointToolButton.toggled.connect(on_point_toggle)
    window.directionToolButton.toggled.connect(on_direction_toggle)
    window.lineToolButton.toggled.connect(on_line_toggle)
    window.momentToolButton.toggled.connect(on_moment_toggle)
    window.rectangleToolButton.toggled.connect(on_rectangle_toggle)
    window.polygonToolButton.toggled.connect(on_polygon_toggle)
    window.ellipseToolButton.toggled.connect(on_ellipse_toggle)
    window.textToolButton.toggled.connect(on_text_toggle)
    window.springToolButton.toggled.connect(on_spring_toggle)
    window.squiggleToolButton.toggled.connect(on_squiggle_toggle)
    window.cogToolButton.toggled.connect(on_cog_toggle)

    def on_tool_changed(mode):
        _all_tool_buttons = [
            window.vectorToolButton, window.pointToolButton,
            window.directionToolButton, window.lineToolButton,
            window.momentToolButton, window.rectangleToolButton,
            window.polygonToolButton, window.ellipseToolButton,
            window.textToolButton, window.springToolButton,
            window.squiggleToolButton, window.cogToolButton,
        ]
        _tool_mode_map = {
            ToolMode.VECTOR: window.vectorToolButton,
            ToolMode.POINT: window.pointToolButton,
            ToolMode.DIRECTION: window.directionToolButton,
            ToolMode.LINE: window.lineToolButton,
            ToolMode.MOMENT: window.momentToolButton,
            ToolMode.RECTANGLE: window.rectangleToolButton,
            ToolMode.POLYGON: window.polygonToolButton,
            ToolMode.ELLIPSE: window.ellipseToolButton,
            ToolMode.TEXT: window.textToolButton,
            ToolMode.SPRING: window.springToolButton,
            ToolMode.SQUIGGLE: window.squiggleToolButton,
            ToolMode.COG: window.cogToolButton,
        }
        for btn in _all_tool_buttons:
            btn.blockSignals(True)
            btn.setChecked(btn is _tool_mode_map.get(mode))
            btn.blockSignals(False)

        status_msgs = {
            ToolMode.VECTOR: "Force creation mode — click and drag to draw",
            ToolMode.POINT: "Point creation mode — click to place a point",
            ToolMode.DIRECTION: "Direction creation mode — click and drag to draw",
            ToolMode.LINE: "Line creation mode — click and drag to draw",
            ToolMode.MOMENT: "Moment creation mode — click and drag to set center and radius",
            ToolMode.RECTANGLE: "Rectangle creation mode — click and drag to draw",
            ToolMode.POLYGON: "Polygon creation mode — click to add vertices, double-click to finish",
            ToolMode.ELLIPSE: "Ellipse creation mode — click and drag (CTRL = circle)",
            ToolMode.TEXT: "Text creation mode — click to place text",
            ToolMode.SPRING: "Spring creation mode — click and drag to draw",
            ToolMode.SQUIGGLE: "Squiggle creation mode — click and drag to draw",
            ToolMode.COG: "COG creation mode — click to place center of gravity",
        }
        window.statusbar.showMessage(status_msgs.get(mode, "Ready"))

    window.canvas.tool_changed.connect(on_tool_changed)
    window.statusbar.show()
    window.statusbar.showMessage("Ready")

    # "F" shortcut to toggle force/vector mode
    shortcut_f = QShortcut(QKeySequence("F"), window)
    shortcut_f.activated.connect(lambda: window.vectorToolButton.toggle())

    # "P" shortcut to toggle point mode
    shortcut_p = QShortcut(QKeySequence("P"), window)
    shortcut_p.activated.connect(lambda: window.pointToolButton.toggle())

    # "D" shortcut to toggle direction mode
    shortcut_d = QShortcut(QKeySequence("D"), window)
    shortcut_d.activated.connect(lambda: window.directionToolButton.toggle())

    # "L" shortcut to toggle line mode
    shortcut_l = QShortcut(QKeySequence("L"), window)
    shortcut_l.activated.connect(lambda: window.lineToolButton.toggle())

    # "M" shortcut to toggle moment mode
    shortcut_m = QShortcut(QKeySequence("M"), window)
    shortcut_m.activated.connect(lambda: window.momentToolButton.toggle())

    # "R" shortcut to toggle rectangle mode
    shortcut_r = QShortcut(QKeySequence("R"), window)
    shortcut_r.activated.connect(lambda: window.rectangleToolButton.toggle())

    # "G" shortcut to toggle polygon mode
    shortcut_g = QShortcut(QKeySequence("G"), window)
    shortcut_g.activated.connect(lambda: window.polygonToolButton.toggle())

    # "E" shortcut to toggle ellipse mode
    shortcut_e = QShortcut(QKeySequence("E"), window)
    shortcut_e.activated.connect(lambda: window.ellipseToolButton.toggle())

    # "T" shortcut to toggle text mode
    shortcut_t = QShortcut(QKeySequence("T"), window)
    shortcut_t.activated.connect(lambda: window.textToolButton.toggle())

    # "S" shortcut to toggle spring mode
    shortcut_s = QShortcut(QKeySequence("S"), window)
    shortcut_s.activated.connect(lambda: window.springToolButton.toggle())

    # "W" shortcut to toggle squiggle mode
    shortcut_w = QShortcut(QKeySequence("W"), window)
    shortcut_w.activated.connect(lambda: window.squiggleToolButton.toggle())

    # "C" shortcut to toggle COG mode
    shortcut_c = QShortcut(QKeySequence("C"), window)
    shortcut_c.activated.connect(lambda: window.cogToolButton.toggle())

    # Delete action
    window.actionDelete.triggered.connect(window.canvas.delete_selected)

    # Bring to Front / Send to Back shortcuts (Ctrl+Plus / Ctrl+Minus on numpad)
    for key in ("Ctrl+]", "Ctrl++"):
        s = QShortcut(QKeySequence(key), window)
        s.activated.connect(window.canvas.bring_selected_to_front)
    for key in ("Ctrl+[", "Ctrl+-"):
        s = QShortcut(QKeySequence(key), window)
        s.activated.connect(window.canvas.send_selected_to_back)

    # --- Enable drag-to-scrub on all property panel spin boxes ---
    for _sb in [window.startXSpinBox, window.startYSpinBox,
                window.endXSpinBox, window.endYSpinBox,
                window.posXSpinBox, window.posYSpinBox,
                window.fontSizeSpinBox,
                window.bodyThicknessSpinBox, window.outlineThicknessSpinBox,
                window.centerXSpinBox, window.centerYSpinBox,
                window.radiusSpinBox, window.startAngleSpinBox, window.spanAngleSpinBox]:
        _sb.installEventFilter(SpinDragFilter(_sb))

    # --- Shape style widgets (added programmatically) ---
    _form = window.propertiesLayout

    def _make_color_button(name):
        btn = QPushButton()
        btn.setObjectName(name)
        btn.setFixedSize(60, 24)
        btn.setCursor(btn.cursor())
        return btn

    def _set_button_color(btn, color: QColor):
        btn.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888;")

    # Label background checkbox (common to all items with labels)
    _label_bg_label = QLabel("Label BG:")
    _label_bg_check = QCheckBox()
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _label_bg_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _label_bg_check)

    # --- Item color/opacity widgets (for vector, direction, point, moment) ---
    _item_color_divider = QFrame()
    _item_color_divider.setFrameShape(QFrame.Shape.HLine)
    _item_color_divider.setFrameShadow(QFrame.Shadow.Sunken)
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.SpanningRole, _item_color_divider)

    _item_color_label = QLabel("Color:")
    _item_color_btn = _make_color_button("itemColorButton")
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _item_color_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _item_color_btn)

    _item_opacity_label = QLabel("Opacity:")
    _item_opacity_spin = QSpinBox()
    _item_opacity_spin.setRange(0, 255)
    _item_opacity_spin.setValue(255)
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _item_opacity_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _item_opacity_spin)

    # Divider (for shape-specific style controls)
    _shape_divider = QFrame()
    _shape_divider.setFrameShape(QFrame.Shape.HLine)
    _shape_divider.setFrameShadow(QFrame.Shadow.Sunken)
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.SpanningRole, _shape_divider)

    # Fill Color
    _fill_color_label = QLabel("Fill Color:")
    _fill_color_btn = _make_color_button("fillColorButton")
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _fill_color_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _fill_color_btn)

    # Fill Opacity
    _fill_opacity_label = QLabel("Fill Opacity:")
    _fill_opacity_spin = QSpinBox()
    _fill_opacity_spin.setRange(0, 255)
    _fill_opacity_spin.setValue(255)
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _fill_opacity_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _fill_opacity_spin)

    # Edge Color
    _edge_color_label = QLabel("Edge Color:")
    _edge_color_btn = _make_color_button("edgeColorButton")
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _edge_color_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _edge_color_btn)

    # Edge Opacity
    _edge_opacity_label = QLabel("Edge Opacity:")
    _edge_opacity_spin = QSpinBox()
    _edge_opacity_spin.setRange(0, 255)
    _edge_opacity_spin.setValue(255)
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _edge_opacity_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _edge_opacity_spin)

    # Edge Thickness
    _edge_thickness_label = QLabel("Edge Thickness:")
    _edge_thickness_spin = QSpinBox()
    _edge_thickness_spin.setRange(0, 20)
    _edge_thickness_spin.setValue(2)
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _edge_thickness_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _edge_thickness_spin)

    # --- Rectangle-only widgets ---

    # Rotation Angle (counter-clockwise)
    _rect_angle_label = QLabel("Angle (CCW):")
    _rect_angle_spin = QDoubleSpinBox()
    _rect_angle_spin.setRange(-360, 360)
    _rect_angle_spin.setDecimals(1)
    _rect_angle_spin.setSuffix("\u00b0")
    _rect_angle_spin.setValue(0)
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _rect_angle_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _rect_angle_spin)

    # Fade
    _fade_label = QLabel("Fade:")
    _fade_check = QCheckBox()
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _fade_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _fade_check)

    # Show COG
    _show_cog_label = QLabel("Show COG:")
    _show_cog_check = QCheckBox()
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _show_cog_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _show_cog_check)

    # Show Local CS
    _show_cs_label = QLabel("Local n-t CS:")
    _show_cs_check = QCheckBox()
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _show_cs_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _show_cs_check)

    # Show CS Labels
    _show_cs_labels_label = QLabel("CS Labels:")
    _show_cs_labels_check = QCheckBox()
    _show_cs_labels_check.setChecked(True)
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _show_cs_labels_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _show_cs_labels_check)

    # n-axis label
    _n_label_label = QLabel("n Label:")
    _n_label_edit = QLineEdit()
    _n_label_edit.setText("n")
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _n_label_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _n_label_edit)

    # t-axis label
    _t_label_label = QLabel("t Label:")
    _t_label_edit = QLineEdit()
    _t_label_edit.setText("t")
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _t_label_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _t_label_edit)

    # Install drag filters on shape style spinboxes
    for _sb in [_item_opacity_spin, _fill_opacity_spin, _edge_opacity_spin,
                _edge_thickness_spin, _rect_angle_spin]:
        _sb.installEventFilter(SpinDragFilter(_sb))

    # --- Properties panel sync ---
    _updating_panel = False  # guard against feedback loops

    _item_color_widgets = [
        _item_color_divider,
        _item_color_label, _item_color_btn,
        _item_opacity_label, _item_opacity_spin,
    ]

    _shape_style_widgets = [
        _shape_divider,
        _fill_color_label, _fill_color_btn,
        _fill_opacity_label, _fill_opacity_spin,
        _edge_color_label, _edge_color_btn,
        _edge_opacity_label, _edge_opacity_spin,
        _edge_thickness_label, _edge_thickness_spin,
    ]

    _rect_only_widgets = [
        _rect_angle_label, _rect_angle_spin,
        _fade_label, _fade_check,
        _show_cog_label, _show_cog_check,
        _show_cs_label, _show_cs_check,
        _show_cs_labels_label, _show_cs_labels_check,
        _n_label_label, _n_label_edit,
        _t_label_label, _t_label_edit,
    ]

    _cs_label_widgets = [
        _show_cs_labels_label, _show_cs_labels_check,
        _n_label_label, _n_label_edit,
        _t_label_label, _t_label_edit,
    ]

    # Widget groups for conditional visibility
    _start_end_widgets = [
        window.startXLabel, window.startXSpinBox,
        window.startYLabel, window.startYSpinBox,
        window.endXLabel, window.endXSpinBox,
        window.endYLabel, window.endYSpinBox,
    ]
    _magnitude_widgets = [
        window.magnitudeLabel, window.magnitudeLineEdit,
        window.showMagnitudeLabel, window.showMagnitudeCheckBox,
    ]
    _point_only_widgets = [
        window.posXLabel, window.posXSpinBox,
        window.posYLabel, window.posYSpinBox,
    ]
    _direction_only_widgets = [
        window.showArrowheadLabel, window.showArrowheadCheckBox,
    ]
    # Line arrow/dashed widgets (added programmatically)
    _line_arrow_tail_label = QLabel("Arrow Tail:")
    _line_arrow_tail_check = QCheckBox()
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _line_arrow_tail_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _line_arrow_tail_check)

    _line_arrow_head_label = QLabel("Arrow Head:")
    _line_arrow_head_check = QCheckBox()
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _line_arrow_head_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _line_arrow_head_check)

    _line_dashed_label = QLabel("Dashed:")
    _line_dashed_check = QCheckBox()
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _line_dashed_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _line_dashed_check)

    _line_only_widgets = [
        window.bodyThicknessLabel, window.bodyThicknessSpinBox,
        window.outlineThicknessLabel, window.outlineThicknessSpinBox,
        _line_arrow_tail_label, _line_arrow_tail_check,
        _line_arrow_head_label, _line_arrow_head_check,
        _line_dashed_label, _line_dashed_check,
    ]
    # Spring-specific widgets
    _spring_coils_label = QLabel("Coils:")
    _spring_coils_spin = QSpinBox()
    _spring_coils_spin.setRange(1, 20)
    _spring_coils_spin.setValue(2)
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _spring_coils_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _spring_coils_spin)

    _spring_amplitude_label = QLabel("Amplitude:")
    _spring_amplitude_spin = QSpinBox()
    _spring_amplitude_spin.setRange(1, 100)
    _spring_amplitude_spin.setValue(20)
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _spring_amplitude_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _spring_amplitude_spin)

    _spring_thickness_label = QLabel("Thickness:")
    _spring_thickness_spin = QSpinBox()
    _spring_thickness_spin.setRange(1, 20)
    _spring_thickness_spin.setValue(2)
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _spring_thickness_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _spring_thickness_spin)

    for _sb in [_spring_coils_spin, _spring_amplitude_spin, _spring_thickness_spin]:
        _sb.installEventFilter(SpinDragFilter(_sb))

    _spring_only_widgets = [
        _spring_coils_label, _spring_coils_spin,
        _spring_amplitude_label, _spring_amplitude_spin,
        _spring_thickness_label, _spring_thickness_spin,
    ]

    _reverse_moment_label = QLabel("Reverse:")
    _reverse_moment_check = QCheckBox()
    next_row = _form.rowCount()
    _form.setWidget(next_row, _form.ItemRole.LabelRole, _reverse_moment_label)
    _form.setWidget(next_row, _form.ItemRole.FieldRole, _reverse_moment_check)

    _moment_only_widgets = [
        window.centerXLabel, window.centerXSpinBox,
        window.centerYLabel, window.centerYSpinBox,
        window.radiusLabel, window.radiusSpinBox,
        window.startAngleLabel, window.startAngleSpinBox,
        window.spanAngleLabel, window.spanAngleSpinBox,
        _reverse_moment_label, _reverse_moment_check,
    ]

    def sync_panel():
        nonlocal _updating_panel
        try:
            vec = window.canvas.get_selected_vector()
            point = window.canvas.get_selected_point()
            direction = window.canvas.get_selected_direction()
            line = window.canvas.get_selected_line()
            moment = window.canvas.get_selected_moment()
            rect = window.canvas.get_selected_rectangle()
            polygon = window.canvas.get_selected_polygon()
            ellipse = window.canvas.get_selected_ellipse()
            text = window.canvas.get_selected_text()
            cog = window.canvas.get_selected_cog()
        except RuntimeError:
            return  # scene already destroyed during shutdown

        spring = window.canvas.get_selected_spring()
        squiggle = window.canvas.get_selected_squiggle()

        if vec is None and point is None and direction is None and line is None and moment is None and rect is None and polygon is None and ellipse is None and text is None and spring is None and squiggle is None and cog is None:
            window.propertiesGroupBox.setVisible(False)
            return

        window.propertiesGroupBox.setVisible(True)
        _updating_panel = True

        # Hide all conditional widget groups first
        for w in _start_end_widgets + _magnitude_widgets + _point_only_widgets + _direction_only_widgets + _line_only_widgets + _spring_only_widgets + _moment_only_widgets + _item_color_widgets + _shape_style_widgets + _rect_only_widgets + [_label_bg_label, _label_bg_check]:
            w.setVisible(False)

        if vec is not None:
            for w in _start_end_widgets + _magnitude_widgets:
                w.setVisible(True)

            window.startXSpinBox.setValue(vec.tail.x())
            window.startYSpinBox.setValue(vec.tail.y())
            window.endXSpinBox.setValue(vec.head.x())
            window.endYSpinBox.setValue(vec.head.y())
            window.magnitudeLineEdit.setText(vec.magnitude)
            window.showMagnitudeCheckBox.setChecked(vec.show_magnitude)
            window.showLabelCheckBox.setChecked(vec.label_visible)
            window.labelTextLineEdit.setText(vec.label_text)
            window.fontSizeSpinBox.setValue(vec.font_size)
            window.boldButton.setChecked(vec.label_bold)
            window.italicButton.setChecked(vec.label_italic)

        elif direction is not None:
            for w in _start_end_widgets + _direction_only_widgets:
                w.setVisible(True)

            window.startXSpinBox.setValue(direction.tail.x())
            window.startYSpinBox.setValue(direction.tail.y())
            window.endXSpinBox.setValue(direction.head.x())
            window.endYSpinBox.setValue(direction.head.y())
            window.showArrowheadCheckBox.setChecked(direction.show_arrowhead)
            window.showLabelCheckBox.setChecked(direction.label_visible)
            window.labelTextLineEdit.setText(direction.label_text)
            window.fontSizeSpinBox.setValue(direction.font_size)
            window.boldButton.setChecked(direction.label_bold)
            window.italicButton.setChecked(direction.label_italic)

        elif point is not None:
            for w in _point_only_widgets:
                w.setVisible(True)

            window.posXSpinBox.setValue(point.point_pos.x())
            window.posYSpinBox.setValue(point.point_pos.y())
            window.showLabelCheckBox.setChecked(point.label_visible)
            window.labelTextLineEdit.setText(point.label_text)
            window.fontSizeSpinBox.setValue(point.font_size)
            window.boldButton.setChecked(point.label_bold)
            window.italicButton.setChecked(point.label_italic)

        elif line is not None:
            for w in _start_end_widgets + _line_only_widgets:
                w.setVisible(True)

            window.startXSpinBox.setValue(line.tail.x())
            window.startYSpinBox.setValue(line.tail.y())
            window.endXSpinBox.setValue(line.head.x())
            window.endYSpinBox.setValue(line.head.y())
            window.bodyThicknessSpinBox.setValue(line.body_thickness)
            window.outlineThicknessSpinBox.setValue(line.outline_thickness)
            _line_arrow_tail_check.setChecked(line.show_arrow_tail)
            _line_arrow_head_check.setChecked(line.show_arrow_head)
            _line_dashed_check.setChecked(line.dashed)
            window.showLabelCheckBox.setChecked(line.label_visible)
            window.labelTextLineEdit.setText(line.label_text)
            window.fontSizeSpinBox.setValue(line.font_size)
            window.boldButton.setChecked(line.label_bold)
            window.italicButton.setChecked(line.label_italic)

        elif moment is not None:
            for w in _moment_only_widgets:
                w.setVisible(True)

            window.centerXSpinBox.setValue(moment.center.x())
            window.centerYSpinBox.setValue(moment.center.y())
            window.radiusSpinBox.setValue(moment.radius)
            window.startAngleSpinBox.setValue(moment.start_angle)
            window.spanAngleSpinBox.setValue(moment.span_angle)
            _reverse_moment_check.setChecked(moment.reversed)
            window.showLabelCheckBox.setChecked(moment.label_visible)
            window.labelTextLineEdit.setText(moment.label_text)
            window.fontSizeSpinBox.setValue(moment.font_size)
            window.boldButton.setChecked(moment.label_bold)
            window.italicButton.setChecked(moment.label_italic)

        # Spring properties
        if spring is not None:
            for w in _start_end_widgets + _spring_only_widgets:
                w.setVisible(True)
            window.startXSpinBox.setValue(spring.tail.x())
            window.startYSpinBox.setValue(spring.tail.y())
            window.endXSpinBox.setValue(spring.head.x())
            window.endYSpinBox.setValue(spring.head.y())
            _spring_coils_spin.setValue(spring.coils)
            _spring_amplitude_spin.setValue(int(spring.amplitude))
            _spring_thickness_spin.setValue(spring.thickness)
            window.showLabelCheckBox.setChecked(spring.label_visible)
            window.labelTextLineEdit.setText(spring.label_text)
            window.fontSizeSpinBox.setValue(spring.font_size)
            window.boldButton.setChecked(spring.label_bold)
            window.italicButton.setChecked(spring.label_italic)

        # Squiggle properties (shares spring property widgets)
        if squiggle is not None:
            for w in _start_end_widgets + _spring_only_widgets:
                w.setVisible(True)
            window.startXSpinBox.setValue(squiggle.tail.x())
            window.startYSpinBox.setValue(squiggle.tail.y())
            window.endXSpinBox.setValue(squiggle.head.x())
            window.endYSpinBox.setValue(squiggle.head.y())
            _spring_coils_spin.setValue(int(squiggle.waves))
            _spring_amplitude_spin.setValue(int(squiggle.amplitude))
            _spring_thickness_spin.setValue(squiggle.thickness)
            window.showLabelCheckBox.setChecked(squiggle.label_visible)
            window.labelTextLineEdit.setText(squiggle.label_text)
            window.fontSizeSpinBox.setValue(squiggle.font_size)
            window.boldButton.setChecked(squiggle.label_bold)
            window.italicButton.setChecked(squiggle.label_italic)

        # Item color/opacity (for vector, direction, point, moment, text, spring, squiggle)
        color_item = vec or direction or point or moment or text or spring or squiggle
        if color_item is not None:
            for w in _item_color_widgets:
                w.setVisible(True)
            _set_button_color(_item_color_btn, color_item.item_color)
            _item_opacity_spin.setValue(color_item.item_opacity)

        # Shape style panel (rectangle, polygon, or ellipse)
        shape = rect or polygon or ellipse
        if shape is not None:
            for w in _shape_style_widgets:
                w.setVisible(True)
            _set_button_color(_fill_color_btn, shape.fill_color)
            _fill_opacity_spin.setValue(shape.fill_opacity)
            _set_button_color(_edge_color_btn, shape.edge_color)
            _edge_opacity_spin.setValue(shape.edge_opacity)
            _edge_thickness_spin.setValue(shape.outline_thickness)
            window.showLabelCheckBox.setChecked(shape.label_visible)
            window.labelTextLineEdit.setText(shape.label_text)
            window.fontSizeSpinBox.setValue(shape.font_size)
            window.boldButton.setChecked(shape.label_bold)
            window.italicButton.setChecked(shape.label_italic)

        # Rectangle-only properties
        if rect is not None:
            for w in _rect_only_widgets:
                w.setVisible(True)
            _rect_angle_spin.setValue(rect.angle_ccw)
            _fade_check.setChecked(rect.fade)
            _show_cog_check.setChecked(rect.show_cog)
            _show_cs_check.setChecked(rect.show_local_cs)
            _show_cs_labels_check.setChecked(rect.show_cs_labels)
            _n_label_edit.setText(rect.n_label_text)
            _t_label_edit.setText(rect.t_label_text)
            # Only show CS label controls when local CS is visible
            if not rect.show_local_cs:
                for w in _cs_label_widgets:
                    w.setVisible(False)

        # Ellipse angle (reuse the angle spinbox)
        if ellipse is not None:
            _rect_angle_label.setVisible(True)
            _rect_angle_spin.setVisible(True)
            _rect_angle_spin.setValue(ellipse.angle_ccw)

        # COG item
        if cog is not None:
            window.showLabelCheckBox.setChecked(cog.label_visible)
            window.labelTextLineEdit.setText(cog.label_text)
            window.fontSizeSpinBox.setValue(cog.font_size)
            window.boldButton.setChecked(cog.label_bold)
            window.italicButton.setChecked(cog.label_italic)

        # Text item (label controls are common, just sync values)
        if text is not None:
            window.showLabelCheckBox.setChecked(text.label_visible)
            window.labelTextLineEdit.setText(text.label_text)
            window.fontSizeSpinBox.setValue(text.font_size)
            window.boldButton.setChecked(text.label_bold)
            window.italicButton.setChecked(text.label_italic)

        # Label background (common to all items)
        any_item = _get_selected_item()
        if any_item is not None:
            _label_bg_label.setVisible(True)
            _label_bg_check.setVisible(True)
            _label_bg_check.setChecked(any_item.label_background)

        _updating_panel = False

    window.propertiesGroupBox.setVisible(False)
    window.propertiesGroupBox.setEnabled(True)
    window.canvas.selection_changed.connect(sync_panel)
    window.canvas.vector_created.connect(lambda _: sync_panel())

    # --- Properties panel write-back ---

    def _get_selected_item():
        """Return any selected item."""
        return (window.canvas.get_selected_vector()
                or window.canvas.get_selected_direction()
                or window.canvas.get_selected_line()
                or window.canvas.get_selected_point()
                or window.canvas.get_selected_moment()
                or window.canvas.get_selected_rectangle()
                or window.canvas.get_selected_polygon()
                or window.canvas.get_selected_ellipse()
                or window.canvas.get_selected_text()
                or window.canvas.get_selected_spring()
                or window.canvas.get_selected_squiggle()
                or window.canvas.get_selected_cog())

    def _get_selected_line_item():
        """Return the selected vector, direction, line, spring, or squiggle (items with tail/head)."""
        return (window.canvas.get_selected_vector()
                or window.canvas.get_selected_direction()
                or window.canvas.get_selected_line()
                or window.canvas.get_selected_spring()
                or window.canvas.get_selected_squiggle())

    def _push_resize(item, old_tail, old_head, new_tail, new_head):
        """Push a resize command, reverting item first for consistent redo."""
        from direction_item import DirectionItem
        from line_item import LineItem
        item.set_tail(old_tail)
        item.set_head(old_head)
        if isinstance(item, DirectionItem):
            cmd = ResizeDirectionCommand(item, old_tail, old_head, new_tail, new_head)
        elif isinstance(item, LineItem):
            cmd = ResizeLineCommand(item, old_tail, old_head, new_tail, new_head)
        else:
            cmd = ResizeVectorCommand(item, old_tail, old_head, new_tail, new_head)
        undo_stack.push(cmd)

    def on_start_x_changed(val):
        if _updating_panel:
            return
        item = _get_selected_line_item()
        if item is None:
            return
        old_tail, old_head = item.tail, item.head
        new_tail = QPointF(val, old_tail.y())
        _push_resize(item, old_tail, old_head, new_tail, old_head)

    def on_start_y_changed(val):
        if _updating_panel:
            return
        item = _get_selected_line_item()
        if item is None:
            return
        old_tail, old_head = item.tail, item.head
        new_tail = QPointF(old_tail.x(), val)
        _push_resize(item, old_tail, old_head, new_tail, old_head)

    def on_end_x_changed(val):
        if _updating_panel:
            return
        item = _get_selected_line_item()
        if item is None:
            return
        old_tail, old_head = item.tail, item.head
        new_head = QPointF(val, old_head.y())
        _push_resize(item, old_tail, old_head, old_tail, new_head)

    def on_end_y_changed(val):
        if _updating_panel:
            return
        item = _get_selected_line_item()
        if item is None:
            return
        old_tail, old_head = item.tail, item.head
        new_head = QPointF(old_head.x(), val)
        _push_resize(item, old_tail, old_head, old_tail, new_head)

    def on_pos_x_changed(val):
        if _updating_panel:
            return
        point = window.canvas.get_selected_point()
        if point is None:
            return
        old_pos = point.point_pos
        new_pos = QPointF(val, old_pos.y())
        if new_pos == old_pos:
            return
        point.set_pos(old_pos)  # revert for consistent redo
        cmd = MovePointCommand(point, old_pos, new_pos)
        undo_stack.push(cmd)

    def on_pos_y_changed(val):
        if _updating_panel:
            return
        point = window.canvas.get_selected_point()
        if point is None:
            return
        old_pos = point.point_pos
        new_pos = QPointF(old_pos.x(), val)
        if new_pos == old_pos:
            return
        point.set_pos(old_pos)  # revert for consistent redo
        cmd = MovePointCommand(point, old_pos, new_pos)
        undo_stack.push(cmd)

    def on_label_text_changed():
        if _updating_panel:
            return
        item = _get_selected_item()
        if item is None:
            return
        new_text = window.labelTextLineEdit.text()
        if new_text == item.label_text:
            return
        old_text = item.label_text
        item.label_text = old_text  # revert for consistent redo
        cmd = ChangeLabelTextCommand(item, old_text, new_text)
        undo_stack.push(cmd)

    def on_show_label_toggled(checked):
        if _updating_panel:
            return
        item = _get_selected_item()
        if item is None:
            return
        if checked == item.label_visible:
            return
        old_vis = item.label_visible
        item.label_visible = old_vis  # revert for consistent redo
        cmd = ChangeLabelVisibilityCommand(item, old_vis, checked)
        undo_stack.push(cmd)

    def on_magnitude_changed():
        if _updating_panel:
            return
        vec = window.canvas.get_selected_vector()
        if vec is None:
            return
        new_mag = window.magnitudeLineEdit.text()
        if new_mag == vec.magnitude:
            return
        old_mag = vec.magnitude
        vec.magnitude = old_mag  # revert for consistent redo
        cmd = ChangeMagnitudeCommand(vec, old_mag, new_mag)
        undo_stack.push(cmd)

    def on_show_magnitude_toggled(checked):
        if _updating_panel:
            return
        vec = window.canvas.get_selected_vector()
        if vec is None:
            return
        if checked == vec.show_magnitude:
            return
        old_val = vec.show_magnitude
        vec.show_magnitude = old_val  # revert for consistent redo
        cmd = ChangeShowMagnitudeCommand(vec, old_val, checked)
        undo_stack.push(cmd)

    def on_font_size_changed(val):
        if _updating_panel:
            return
        item = _get_selected_item()
        if item is None:
            return
        if val == item.font_size:
            return
        old_size = item.font_size
        item.font_size = old_size  # revert for consistent redo
        cmd = ChangeFontSizeCommand(item, old_size, val)
        undo_stack.push(cmd)

    def on_bold_toggled(checked):
        if _updating_panel:
            return
        item = _get_selected_item()
        if item is None:
            return
        if checked == item.label_bold:
            return
        old_val = item.label_bold
        item.label_bold = old_val  # revert for consistent redo
        cmd = ChangeLabelBoldCommand(item, old_val, checked)
        undo_stack.push(cmd)

    def on_italic_toggled(checked):
        if _updating_panel:
            return
        item = _get_selected_item()
        if item is None:
            return
        if checked == item.label_italic:
            return
        old_val = item.label_italic
        item.label_italic = old_val  # revert for consistent redo
        cmd = ChangeLabelItalicCommand(item, old_val, checked)
        undo_stack.push(cmd)

    def on_show_arrowhead_toggled(checked):
        if _updating_panel:
            return
        direction = window.canvas.get_selected_direction()
        if direction is None:
            return
        if checked == direction.show_arrowhead:
            return
        old_val = direction.show_arrowhead
        direction.show_arrowhead = old_val  # revert for consistent redo
        cmd = ChangeShowArrowheadCommand(direction, old_val, checked)
        undo_stack.push(cmd)

    window.startXSpinBox.valueChanged.connect(on_start_x_changed)
    window.startYSpinBox.valueChanged.connect(on_start_y_changed)
    window.endXSpinBox.valueChanged.connect(on_end_x_changed)
    window.endYSpinBox.valueChanged.connect(on_end_y_changed)
    window.posXSpinBox.valueChanged.connect(on_pos_x_changed)
    window.posYSpinBox.valueChanged.connect(on_pos_y_changed)
    window.magnitudeLineEdit.editingFinished.connect(on_magnitude_changed)
    window.showMagnitudeCheckBox.toggled.connect(on_show_magnitude_toggled)
    window.labelTextLineEdit.editingFinished.connect(on_label_text_changed)
    window.showLabelCheckBox.toggled.connect(on_show_label_toggled)
    window.fontSizeSpinBox.valueChanged.connect(on_font_size_changed)
    window.boldButton.toggled.connect(on_bold_toggled)
    window.italicButton.toggled.connect(on_italic_toggled)
    def on_body_thickness_changed(val):
        if _updating_panel:
            return
        line = window.canvas.get_selected_line()
        if line is None:
            return
        if val == line.body_thickness:
            return
        old_val = line.body_thickness
        line.body_thickness = old_val  # revert for consistent redo
        cmd = ChangeBodyThicknessCommand(line, old_val, val)
        undo_stack.push(cmd)

    def on_outline_thickness_changed(val):
        if _updating_panel:
            return
        line = window.canvas.get_selected_line()
        if line is None:
            return
        if val == line.outline_thickness:
            return
        old_val = line.outline_thickness
        line.outline_thickness = old_val  # revert for consistent redo
        cmd = ChangeOutlineThicknessCommand(line, old_val, val)
        undo_stack.push(cmd)

    def on_center_x_changed(val):
        if _updating_panel:
            return
        moment = window.canvas.get_selected_moment()
        if moment is None:
            return
        old_center = moment.center
        new_center = QPointF(val, old_center.y())
        if new_center == old_center:
            return
        moment.set_center(old_center)  # revert for consistent redo
        cmd = MoveMomentCommand(moment, old_center, new_center)
        undo_stack.push(cmd)

    def on_center_y_changed(val):
        if _updating_panel:
            return
        moment = window.canvas.get_selected_moment()
        if moment is None:
            return
        old_center = moment.center
        new_center = QPointF(old_center.x(), val)
        if new_center == old_center:
            return
        moment.set_center(old_center)  # revert for consistent redo
        cmd = MoveMomentCommand(moment, old_center, new_center)
        undo_stack.push(cmd)

    def on_radius_changed(val):
        if _updating_panel:
            return
        moment = window.canvas.get_selected_moment()
        if moment is None:
            return
        if val == moment.radius:
            return
        old_radius = moment.radius
        moment.set_radius(old_radius)  # revert for consistent redo
        cmd = ChangeRadiusCommand(moment, old_radius, val)
        undo_stack.push(cmd)

    def on_start_angle_changed(val):
        if _updating_panel:
            return
        moment = window.canvas.get_selected_moment()
        if moment is None:
            return
        old_start = moment.start_angle
        old_span = moment.span_angle
        if val == old_start:
            return
        moment.set_angles(old_start, old_span)  # revert for consistent redo
        cmd = ChangeAnglesCommand(moment, old_start, old_span, val, old_span)
        undo_stack.push(cmd)

    def on_span_angle_changed(val):
        if _updating_panel:
            return
        moment = window.canvas.get_selected_moment()
        if moment is None:
            return
        old_start = moment.start_angle
        old_span = moment.span_angle
        if val == old_span:
            return
        moment.set_angles(old_start, old_span)  # revert for consistent redo
        cmd = ChangeAnglesCommand(moment, old_start, old_span, old_start, val)
        undo_stack.push(cmd)

    def _get_selected_shape():
        """Return the selected rectangle, polygon, or ellipse."""
        return (window.canvas.get_selected_rectangle()
                or window.canvas.get_selected_polygon()
                or window.canvas.get_selected_ellipse())

    def on_fill_color_clicked():
        if _updating_panel:
            return
        shape = _get_selected_shape()
        if shape is None:
            return
        color = QColorDialog.getColor(shape.fill_color, window, "Fill Color")
        if not color.isValid():
            return
        old_val = shape.fill_color
        shape.fill_color = old_val  # revert for consistent redo
        cmd = ChangeShapePropertyCommand(shape, "fill_color", old_val, color, "Change Fill Color")
        undo_stack.push(cmd)
        _set_button_color(_fill_color_btn, color)

    def on_fill_opacity_changed(val):
        if _updating_panel:
            return
        shape = _get_selected_shape()
        if shape is None:
            return
        if val == shape.fill_opacity:
            return
        old_val = shape.fill_opacity
        shape.fill_opacity = old_val  # revert for consistent redo
        cmd = ChangeShapePropertyCommand(shape, "fill_opacity", old_val, val, "Change Fill Opacity")
        undo_stack.push(cmd)

    def on_edge_color_clicked():
        if _updating_panel:
            return
        shape = _get_selected_shape()
        if shape is None:
            return
        color = QColorDialog.getColor(shape.edge_color, window, "Edge Color")
        if not color.isValid():
            return
        old_val = shape.edge_color
        shape.edge_color = old_val  # revert for consistent redo
        cmd = ChangeShapePropertyCommand(shape, "edge_color", old_val, color, "Change Edge Color")
        undo_stack.push(cmd)
        _set_button_color(_edge_color_btn, color)

    def on_edge_opacity_changed(val):
        if _updating_panel:
            return
        shape = _get_selected_shape()
        if shape is None:
            return
        if val == shape.edge_opacity:
            return
        old_val = shape.edge_opacity
        shape.edge_opacity = old_val  # revert for consistent redo
        cmd = ChangeShapePropertyCommand(shape, "edge_opacity", old_val, val, "Change Edge Opacity")
        undo_stack.push(cmd)

    def on_edge_thickness_changed(val):
        if _updating_panel:
            return
        shape = _get_selected_shape()
        if shape is None:
            return
        if val == shape.outline_thickness:
            return
        old_val = shape.outline_thickness
        shape.outline_thickness = old_val  # revert for consistent redo
        cmd = ChangeShapePropertyCommand(shape, "outline_thickness", old_val, val, "Change Edge Thickness")
        undo_stack.push(cmd)

    # --- Item color/opacity handlers (vector, direction, point, moment) ---

    def _get_selected_color_item():
        return (window.canvas.get_selected_vector()
                or window.canvas.get_selected_direction()
                or window.canvas.get_selected_point()
                or window.canvas.get_selected_moment()
                or window.canvas.get_selected_text()
                or window.canvas.get_selected_spring()
                or window.canvas.get_selected_squiggle())

    def on_item_color_clicked():
        if _updating_panel:
            return
        item = _get_selected_color_item()
        if item is None:
            return
        color = QColorDialog.getColor(item.item_color, window, "Item Color")
        if not color.isValid():
            return
        old_val = item.item_color
        item.item_color = old_val
        cmd = ChangeShapePropertyCommand(item, "item_color", old_val, color, "Change Color")
        undo_stack.push(cmd)
        _set_button_color(_item_color_btn, color)

    def on_item_opacity_changed(val):
        if _updating_panel:
            return
        item = _get_selected_color_item()
        if item is None:
            return
        if val == item.item_opacity:
            return
        old_val = item.item_opacity
        item.item_opacity = old_val
        cmd = ChangeShapePropertyCommand(item, "item_opacity", old_val, val, "Change Opacity")
        undo_stack.push(cmd)

    _item_color_btn.clicked.connect(on_item_color_clicked)
    _item_opacity_spin.valueChanged.connect(on_item_opacity_changed)

    _fill_color_btn.clicked.connect(on_fill_color_clicked)
    _fill_opacity_spin.valueChanged.connect(on_fill_opacity_changed)
    _edge_color_btn.clicked.connect(on_edge_color_clicked)
    _edge_opacity_spin.valueChanged.connect(on_edge_opacity_changed)
    _edge_thickness_spin.valueChanged.connect(on_edge_thickness_changed)

    # --- Rectangle-only property handlers ---

    def on_rect_angle_changed(val):
        if _updating_panel:
            return
        item = window.canvas.get_selected_rectangle() or window.canvas.get_selected_ellipse()
        if item is None:
            return
        if abs(val - item.angle_ccw) < 0.05:
            return
        old_rotation = item.rotation()
        new_rotation = -val  # CCW display → CW internal
        item.setRotation(old_rotation)  # revert for consistent redo
        cmd = ChangeRotationCommand(item, old_rotation, new_rotation)
        undo_stack.push(cmd)

    def on_show_cog_toggled(checked):
        if _updating_panel:
            return
        rect = window.canvas.get_selected_rectangle()
        if rect is None:
            return
        if checked == rect.show_cog:
            return
        old_val = rect.show_cog
        rect.show_cog = old_val
        cmd = ChangeShapePropertyCommand(rect, "show_cog", old_val, checked, "Toggle COG")
        undo_stack.push(cmd)

    def on_show_cs_toggled(checked):
        if _updating_panel:
            return
        rect = window.canvas.get_selected_rectangle()
        if rect is None:
            return
        if checked == rect.show_local_cs:
            return
        old_val = rect.show_local_cs
        rect.show_local_cs = old_val
        cmd = ChangeShapePropertyCommand(rect, "show_local_cs", old_val, checked, "Toggle Local CS")
        undo_stack.push(cmd)

    def on_show_cs_labels_toggled(checked):
        if _updating_panel:
            return
        rect = window.canvas.get_selected_rectangle()
        if rect is None:
            return
        if checked == rect.show_cs_labels:
            return
        old_val = rect.show_cs_labels
        rect.show_cs_labels = old_val
        cmd = ChangeShapePropertyCommand(rect, "show_cs_labels", old_val, checked, "Toggle CS Labels")
        undo_stack.push(cmd)

    def on_n_label_changed():
        if _updating_panel:
            return
        rect = window.canvas.get_selected_rectangle()
        if rect is None:
            return
        new_text = _n_label_edit.text()
        if new_text == rect.n_label_text:
            return
        old_text = rect.n_label_text
        rect.n_label_text = old_text
        cmd = ChangeShapePropertyCommand(rect, "n_label_text", old_text, new_text, "Change n Label")
        undo_stack.push(cmd)

    def on_t_label_changed():
        if _updating_panel:
            return
        rect = window.canvas.get_selected_rectangle()
        if rect is None:
            return
        new_text = _t_label_edit.text()
        if new_text == rect.t_label_text:
            return
        old_text = rect.t_label_text
        rect.t_label_text = old_text
        cmd = ChangeShapePropertyCommand(rect, "t_label_text", old_text, new_text, "Change t Label")
        undo_stack.push(cmd)

    def on_fade_toggled(checked):
        if _updating_panel:
            return
        rect = window.canvas.get_selected_rectangle()
        if rect is None:
            return
        if checked == rect.fade:
            return
        old_val = rect.fade
        rect.fade = old_val
        cmd = ChangeShapePropertyCommand(rect, "fade", old_val, checked, "Toggle Fade")
        undo_stack.push(cmd)

    _rect_angle_spin.valueChanged.connect(on_rect_angle_changed)
    _fade_check.toggled.connect(on_fade_toggled)
    _show_cog_check.toggled.connect(on_show_cog_toggled)
    _show_cs_check.toggled.connect(on_show_cs_toggled)
    _show_cs_labels_check.toggled.connect(on_show_cs_labels_toggled)
    _n_label_edit.editingFinished.connect(on_n_label_changed)
    _t_label_edit.editingFinished.connect(on_t_label_changed)

    window.showArrowheadCheckBox.toggled.connect(on_show_arrowhead_toggled)
    window.bodyThicknessSpinBox.valueChanged.connect(on_body_thickness_changed)
    window.outlineThicknessSpinBox.valueChanged.connect(on_outline_thickness_changed)

    def _line_bool_handler(prop_name, description):
        def handler(checked):
            if _updating_panel:
                return
            line = window.canvas.get_selected_line()
            if line is None:
                return
            if checked == getattr(line, prop_name):
                return
            old_val = getattr(line, prop_name)
            setattr(line, prop_name, old_val)
            cmd = ChangeShapePropertyCommand(line, prop_name, old_val, checked, description)
            undo_stack.push(cmd)
        return handler

    _line_arrow_tail_check.toggled.connect(_line_bool_handler("show_arrow_tail", "Toggle Tail Arrow"))
    _line_arrow_head_check.toggled.connect(_line_bool_handler("show_arrow_head", "Toggle Head Arrow"))
    _line_dashed_check.toggled.connect(_line_bool_handler("dashed", "Toggle Dashed"))

    def _spring_prop_handler(prop_name, sq_prop_name, description):
        def handler(val):
            if _updating_panel:
                return
            item = window.canvas.get_selected_spring() or window.canvas.get_selected_squiggle()
            if item is None:
                return
            # Use sq_prop_name for squiggles (e.g. "waves" instead of "coils")
            actual_prop = sq_prop_name if isinstance(item, __import__('squiggle_item', fromlist=['SquiggleItem']).SquiggleItem) else prop_name
            if val == getattr(item, actual_prop):
                return
            old_val = getattr(item, actual_prop)
            setattr(item, actual_prop, old_val)
            cmd = ChangeShapePropertyCommand(item, actual_prop, old_val, val, description)
            undo_stack.push(cmd)
        return handler

    _spring_coils_spin.valueChanged.connect(_spring_prop_handler("coils", "waves", "Change Coils/Waves"))
    _spring_amplitude_spin.valueChanged.connect(_spring_prop_handler("amplitude", "amplitude", "Change Amplitude"))
    _spring_thickness_spin.valueChanged.connect(_spring_prop_handler("thickness", "thickness", "Change Thickness"))

    def on_label_bg_toggled(checked):
        if _updating_panel:
            return
        item = _get_selected_item()
        if item is None:
            return
        if checked == item.label_background:
            return
        old_val = item.label_background
        item.label_background = old_val
        cmd = ChangeShapePropertyCommand(item, "label_background", old_val, checked, "Toggle Label Background")
        undo_stack.push(cmd)

    _label_bg_check.toggled.connect(on_label_bg_toggled)

    window.centerXSpinBox.valueChanged.connect(on_center_x_changed)
    window.centerYSpinBox.valueChanged.connect(on_center_y_changed)
    window.radiusSpinBox.valueChanged.connect(on_radius_changed)
    window.startAngleSpinBox.valueChanged.connect(on_start_angle_changed)
    window.spanAngleSpinBox.valueChanged.connect(on_span_angle_changed)

    def on_reverse_moment_toggled(checked):
        if _updating_panel:
            return
        moment = window.canvas.get_selected_moment()
        if moment is None:
            return
        if checked == moment.reversed:
            return
        old_val = moment.reversed
        moment.reversed = old_val  # revert for consistent redo
        cmd = ChangeShapePropertyCommand(moment, "reversed", old_val, checked, "Reverse Moment")
        undo_stack.push(cmd)

    _reverse_moment_check.toggled.connect(on_reverse_moment_toggled)

    # --- Identifier ---
    def _on_identifier_changed(text: str):
        window.canvas.identifier = text
        mark_dirty()
    window.identifierLineEdit.textChanged.connect(_on_identifier_changed)

    # --- Layer visibility checkboxes ---
    window.backgroundLayerCheckBox.toggled.connect(window.canvas.set_background_visible)
    window.vectorsLayerCheckBox.toggled.connect(window.canvas.set_vectors_visible)
    window.pointsLayerCheckBox.toggled.connect(window.canvas.set_points_visible)
    window.directionsLayerCheckBox.toggled.connect(window.canvas.set_directions_visible)
    window.linesLayerCheckBox.toggled.connect(window.canvas.set_lines_visible)
    window.momentsLayerCheckBox.toggled.connect(window.canvas.set_moments_visible)
    window.rectanglesLayerCheckBox.toggled.connect(window.canvas.set_rectangles_visible)
    window.polygonsLayerCheckBox.toggled.connect(window.canvas.set_polygons_visible)
    window.ellipsesLayerCheckBox.toggled.connect(window.canvas.set_ellipses_visible)
    window.textsLayerCheckBox.toggled.connect(window.canvas.set_texts_visible)
    window.springsLayerCheckBox.toggled.connect(window.canvas.set_springs_visible)
    window.squigglesLayerCheckBox.toggled.connect(window.canvas.set_squiggles_visible)
    window.cogsLayerCheckBox.toggled.connect(window.canvas.set_cogs_visible)

    # Sync panel after undo/redo and modifications (e.g. drag) so it reflects current state
    undo_stack.indexChanged.connect(lambda _: sync_panel())
    window.canvas.modified.connect(sync_panel)

    # --- Dirty tracking ---
    window.canvas.modified.connect(mark_dirty)

    # --- Close event ---
    def on_close(event):
        if check_unsaved_changes():
            event.accept()
        else:
            event.ignore()

    window.closeEvent = on_close

    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
