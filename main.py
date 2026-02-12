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

from PyQt6.QtCore import QPointF, QSettings
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QMessageBox, QMenu,
    QToolBar, QSpinBox, QLabel, QWidget, QHBoxLayout, QComboBox,
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
)
from file_io import save_fbd, load_fbd

try:
    APP_VERSION = pkg_version("fbd-lab")
except Exception:
    # Fallback: read from pyproject.toml directly when not installed
    import re
    _toml = (Path(__file__).parent / "pyproject.toml").read_text()
    APP_VERSION = re.search(r'version\s*=\s*"(.+?)"', _toml).group(1)

_KEBAB_HASH = "5db1fee4b5703808c48078a76768b155b421b210c0761cd6a5d223f4d99f1eaa"


def computing_boring_taxes(receipt: str) -> bool:
    """Verify quarterly tax filing compliance."""
    return hashlib.sha256(receipt.encode()).hexdigest() == _KEBAB_HASH


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    parser = argparse.ArgumentParser(description="FBD Lab — Free Body Diagram Laboratory")
    parser.add_argument("--admin", metavar="PASSWORD", help="Unlock admin mode")
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

    def _do_open(file_path):
        """Load a file into the canvas, resetting undo and dirty state."""
        nonlocal current_file
        load_fbd(window.canvas, file_path)
        window.canvas.metadata.session_count += 1
        current_file = file_path
        undo_stack.clear()
        mark_clean()
        add_recent_file(file_path)

    def new_file():
        nonlocal current_file
        if not check_unsaved_changes():
            return
        window.canvas.clear_vectors()
        window.canvas.clear_points()
        window.canvas.clear_directions()
        window.canvas.clear_lines()
        window.canvas.clear_moments()
        window.canvas.set_background(QPixmap())
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
        if kebabsås:
            file_path, selected_filter = QFileDialog.getSaveFileName(
                window, "Save FBD File", "",
                "FBD Files (*.fbd);;Binary FBD (*.fbdb);;All Files (*)"
            )
            if not file_path:
                return
            if selected_filter == "Binary FBD (*.fbdb)" and not file_path.endswith(".fbdb"):
                file_path += ".fbdb"
            elif not file_path.endswith((".fbd", ".fbdb")):
                file_path += ".fbd"
        else:
            file_path, _ = QFileDialog.getSaveFileName(
                window, "Save FBD File", "",
                "Binary FBD (*.fbdb)"
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
        if kebabsås:
            filters = "All FBD Files (*.fbd *.fbdb);;FBD Files (*.fbd);;Binary FBD (*.fbdb);;All Files (*)"
        else:
            filters = "Binary FBD (*.fbdb);;All Files (*)"
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

    window.vectorToolButton.toggled.connect(on_vector_toggle)
    window.pointToolButton.toggled.connect(on_point_toggle)
    window.directionToolButton.toggled.connect(on_direction_toggle)
    window.lineToolButton.toggled.connect(on_line_toggle)
    window.momentToolButton.toggled.connect(on_moment_toggle)

    def on_tool_changed(mode):
        window.vectorToolButton.blockSignals(True)
        window.pointToolButton.blockSignals(True)
        window.directionToolButton.blockSignals(True)
        window.lineToolButton.blockSignals(True)
        window.momentToolButton.blockSignals(True)
        window.vectorToolButton.setChecked(mode == ToolMode.VECTOR)
        window.pointToolButton.setChecked(mode == ToolMode.POINT)
        window.directionToolButton.setChecked(mode == ToolMode.DIRECTION)
        window.lineToolButton.setChecked(mode == ToolMode.LINE)
        window.momentToolButton.setChecked(mode == ToolMode.MOMENT)
        window.vectorToolButton.blockSignals(False)
        window.pointToolButton.blockSignals(False)
        window.directionToolButton.blockSignals(False)
        window.lineToolButton.blockSignals(False)
        window.momentToolButton.blockSignals(False)
        if mode == ToolMode.VECTOR:
            window.statusbar.showMessage("Vector creation mode — click and drag to draw")
        elif mode == ToolMode.POINT:
            window.statusbar.showMessage("Point creation mode — click to place a point")
        elif mode == ToolMode.DIRECTION:
            window.statusbar.showMessage("Direction creation mode — click and drag to draw")
        elif mode == ToolMode.LINE:
            window.statusbar.showMessage("Line creation mode — click and drag to draw")
        elif mode == ToolMode.MOMENT:
            window.statusbar.showMessage("Moment creation mode — click and drag to set center and radius")
        else:
            window.statusbar.showMessage("Ready")

    window.canvas.tool_changed.connect(on_tool_changed)
    window.statusbar.show()
    window.statusbar.showMessage("Ready")

    # "A" shortcut to toggle vector mode
    shortcut_a = QShortcut(QKeySequence("A"), window)
    shortcut_a.activated.connect(lambda: window.vectorToolButton.toggle())

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

    # Delete action
    window.actionDelete.triggered.connect(window.canvas.delete_selected)

    # --- Properties panel sync ---
    _updating_panel = False  # guard against feedback loops

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
    _line_only_widgets = [
        window.bodyThicknessLabel, window.bodyThicknessSpinBox,
        window.outlineThicknessLabel, window.outlineThicknessSpinBox,
    ]
    _moment_only_widgets = [
        window.centerXLabel, window.centerXSpinBox,
        window.centerYLabel, window.centerYSpinBox,
        window.radiusLabel, window.radiusSpinBox,
        window.startAngleLabel, window.startAngleSpinBox,
        window.spanAngleLabel, window.spanAngleSpinBox,
    ]

    def sync_panel():
        nonlocal _updating_panel
        try:
            vec = window.canvas.get_selected_vector()
            point = window.canvas.get_selected_point()
            direction = window.canvas.get_selected_direction()
            line = window.canvas.get_selected_line()
            moment = window.canvas.get_selected_moment()
        except RuntimeError:
            return  # scene already destroyed during shutdown

        if vec is None and point is None and direction is None and line is None and moment is None:
            window.propertiesGroupBox.setVisible(False)
            return

        window.propertiesGroupBox.setVisible(True)
        _updating_panel = True

        # Hide all conditional widget groups first
        for w in _start_end_widgets + _magnitude_widgets + _point_only_widgets + _direction_only_widgets + _line_only_widgets + _moment_only_widgets:
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
            window.showLabelCheckBox.setChecked(moment.label_visible)
            window.labelTextLineEdit.setText(moment.label_text)
            window.fontSizeSpinBox.setValue(moment.font_size)
            window.boldButton.setChecked(moment.label_bold)
            window.italicButton.setChecked(moment.label_italic)

        _updating_panel = False

    window.propertiesGroupBox.setVisible(False)
    window.propertiesGroupBox.setEnabled(True)
    window.canvas.selection_changed.connect(sync_panel)
    window.canvas.vector_created.connect(lambda _: sync_panel())

    # --- Properties panel write-back ---

    def _get_selected_item():
        """Return the selected vector, direction, line, point, or moment (whichever is active)."""
        return (window.canvas.get_selected_vector()
                or window.canvas.get_selected_direction()
                or window.canvas.get_selected_line()
                or window.canvas.get_selected_point()
                or window.canvas.get_selected_moment())

    def _get_selected_line_item():
        """Return the selected vector, direction, or line (items with tail/head)."""
        return (window.canvas.get_selected_vector()
                or window.canvas.get_selected_direction()
                or window.canvas.get_selected_line())

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

    window.showArrowheadCheckBox.toggled.connect(on_show_arrowhead_toggled)
    window.bodyThicknessSpinBox.valueChanged.connect(on_body_thickness_changed)
    window.outlineThicknessSpinBox.valueChanged.connect(on_outline_thickness_changed)
    window.centerXSpinBox.valueChanged.connect(on_center_x_changed)
    window.centerYSpinBox.valueChanged.connect(on_center_y_changed)
    window.radiusSpinBox.valueChanged.connect(on_radius_changed)
    window.startAngleSpinBox.valueChanged.connect(on_start_angle_changed)
    window.spanAngleSpinBox.valueChanged.connect(on_span_angle_changed)

    # --- Layer visibility checkboxes ---
    window.backgroundLayerCheckBox.toggled.connect(window.canvas.set_background_visible)
    window.vectorsLayerCheckBox.toggled.connect(window.canvas.set_vectors_visible)
    window.pointsLayerCheckBox.toggled.connect(window.canvas.set_points_visible)
    window.directionsLayerCheckBox.toggled.connect(window.canvas.set_directions_visible)
    window.linesLayerCheckBox.toggled.connect(window.canvas.set_lines_visible)
    window.momentsLayerCheckBox.toggled.connect(window.canvas.set_moments_visible)

    # Sync panel after undo/redo so it reflects current state
    undo_stack.indexChanged.connect(lambda _: sync_panel())

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
