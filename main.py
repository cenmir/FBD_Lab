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
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox, QMenu
from PyQt6.QtGui import (
    QPalette, QColor, QKeySequence, QShortcut, QAction, QPixmap, QIcon,
    QUndoStack, QImage, QPainter,
)
from PyQt6 import uic

from canvas import FBDCanvas, ToolMode, SessionMetadata  # noqa: F401 — FBDCanvas needed for uic promotion
from commands import (
    ResizeArrowCommand, ChangeLabelTextCommand, ChangeLabelVisibilityCommand,
    ChangeMagnitudeCommand, ChangeShowMagnitudeCommand, ChangeFontSizeCommand,
    ChangeLabelBoldCommand, ChangeLabelItalicCommand,
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
        window.canvas.clear_arrows()
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

    # --- Arrow creation toggle ---
    def on_arrow_toggle(checked):
        if checked:
            window.canvas.set_tool(ToolMode.ARROW)
        else:
            window.canvas.set_tool(ToolMode.SELECT)

    window.arrowToolButton.toggled.connect(on_arrow_toggle)

    def on_tool_changed(mode):
        window.arrowToolButton.blockSignals(True)
        window.arrowToolButton.setChecked(mode == ToolMode.ARROW)
        window.arrowToolButton.blockSignals(False)
        if mode == ToolMode.ARROW:
            window.statusbar.showMessage("Arrow creation mode — click and drag to draw")
        else:
            window.statusbar.showMessage("Ready")

    window.canvas.tool_changed.connect(on_tool_changed)
    window.statusbar.show()
    window.statusbar.showMessage("Ready")

    # "A" shortcut to toggle arrow mode
    shortcut_a = QShortcut(QKeySequence("A"), window)
    shortcut_a.activated.connect(lambda: window.arrowToolButton.toggle())

    # Delete action
    window.actionDelete.triggered.connect(window.canvas.delete_selected)

    # --- Properties panel sync ---
    _updating_panel = False  # guard against feedback loops

    def sync_panel():
        nonlocal _updating_panel
        try:
            arrow = window.canvas.get_selected_arrow()
        except RuntimeError:
            return  # scene already destroyed during shutdown
        if arrow is None:
            window.propertiesGroupBox.setVisible(False)
            return

        window.propertiesGroupBox.setVisible(True)
        _updating_panel = True
        window.startXSpinBox.setValue(arrow.tail.x())
        window.startYSpinBox.setValue(arrow.tail.y())
        window.endXSpinBox.setValue(arrow.head.x())
        window.endYSpinBox.setValue(arrow.head.y())
        window.magnitudeSpinBox.setValue(arrow.magnitude)
        window.showMagnitudeCheckBox.setChecked(arrow.show_magnitude)
        window.showLabelCheckBox.setChecked(arrow.label_visible)
        window.labelTextLineEdit.setText(arrow.label_text)
        window.fontSizeSpinBox.setValue(arrow.font_size)
        window.boldButton.setChecked(arrow.label_bold)
        window.italicButton.setChecked(arrow.label_italic)
        _updating_panel = False

    window.propertiesGroupBox.setVisible(False)
    window.propertiesGroupBox.setEnabled(True)
    window.canvas.selection_changed.connect(sync_panel)
    window.canvas.arrow_created.connect(lambda _: sync_panel())

    # --- Properties panel write-back ---

    def _push_resize(arrow, old_tail, old_head, new_tail, new_head):
        """Push a resize command, reverting arrow first for consistent redo."""
        arrow.set_tail(old_tail)
        arrow.set_head(old_head)
        cmd = ResizeArrowCommand(arrow, old_tail, old_head, new_tail, new_head)
        undo_stack.push(cmd)

    def on_start_x_changed(val):
        if _updating_panel:
            return
        arrow = window.canvas.get_selected_arrow()
        if arrow is None:
            return
        old_tail, old_head = arrow.tail, arrow.head
        new_tail = QPointF(val, old_tail.y())
        _push_resize(arrow, old_tail, old_head, new_tail, old_head)

    def on_start_y_changed(val):
        if _updating_panel:
            return
        arrow = window.canvas.get_selected_arrow()
        if arrow is None:
            return
        old_tail, old_head = arrow.tail, arrow.head
        new_tail = QPointF(old_tail.x(), val)
        _push_resize(arrow, old_tail, old_head, new_tail, old_head)

    def on_end_x_changed(val):
        if _updating_panel:
            return
        arrow = window.canvas.get_selected_arrow()
        if arrow is None:
            return
        old_tail, old_head = arrow.tail, arrow.head
        new_head = QPointF(val, old_head.y())
        _push_resize(arrow, old_tail, old_head, old_tail, new_head)

    def on_end_y_changed(val):
        if _updating_panel:
            return
        arrow = window.canvas.get_selected_arrow()
        if arrow is None:
            return
        old_tail, old_head = arrow.tail, arrow.head
        new_head = QPointF(old_head.x(), val)
        _push_resize(arrow, old_tail, old_head, old_tail, new_head)

    def on_label_text_changed():
        if _updating_panel:
            return
        arrow = window.canvas.get_selected_arrow()
        if arrow is None:
            return
        new_text = window.labelTextLineEdit.text()
        if new_text == arrow.label_text:
            return
        old_text = arrow.label_text
        arrow.label_text = old_text  # revert for consistent redo
        cmd = ChangeLabelTextCommand(arrow, old_text, new_text)
        undo_stack.push(cmd)

    def on_show_label_toggled(checked):
        if _updating_panel:
            return
        arrow = window.canvas.get_selected_arrow()
        if arrow is None:
            return
        if checked == arrow.label_visible:
            return
        old_vis = arrow.label_visible
        arrow.label_visible = old_vis  # revert for consistent redo
        cmd = ChangeLabelVisibilityCommand(arrow, old_vis, checked)
        undo_stack.push(cmd)

    def on_magnitude_changed(val):
        if _updating_panel:
            return
        arrow = window.canvas.get_selected_arrow()
        if arrow is None:
            return
        if val == arrow.magnitude:
            return
        old_mag = arrow.magnitude
        arrow.magnitude = old_mag  # revert for consistent redo
        cmd = ChangeMagnitudeCommand(arrow, old_mag, val)
        undo_stack.push(cmd)

    def on_show_magnitude_toggled(checked):
        if _updating_panel:
            return
        arrow = window.canvas.get_selected_arrow()
        if arrow is None:
            return
        if checked == arrow.show_magnitude:
            return
        old_val = arrow.show_magnitude
        arrow.show_magnitude = old_val  # revert for consistent redo
        cmd = ChangeShowMagnitudeCommand(arrow, old_val, checked)
        undo_stack.push(cmd)

    def on_font_size_changed(val):
        if _updating_panel:
            return
        arrow = window.canvas.get_selected_arrow()
        if arrow is None:
            return
        if val == arrow.font_size:
            return
        old_size = arrow.font_size
        arrow.font_size = old_size  # revert for consistent redo
        cmd = ChangeFontSizeCommand(arrow, old_size, val)
        undo_stack.push(cmd)

    def on_bold_toggled(checked):
        if _updating_panel:
            return
        arrow = window.canvas.get_selected_arrow()
        if arrow is None:
            return
        if checked == arrow.label_bold:
            return
        old_val = arrow.label_bold
        arrow.label_bold = old_val  # revert for consistent redo
        cmd = ChangeLabelBoldCommand(arrow, old_val, checked)
        undo_stack.push(cmd)

    def on_italic_toggled(checked):
        if _updating_panel:
            return
        arrow = window.canvas.get_selected_arrow()
        if arrow is None:
            return
        if checked == arrow.label_italic:
            return
        old_val = arrow.label_italic
        arrow.label_italic = old_val  # revert for consistent redo
        cmd = ChangeLabelItalicCommand(arrow, old_val, checked)
        undo_stack.push(cmd)

    window.startXSpinBox.valueChanged.connect(on_start_x_changed)
    window.startYSpinBox.valueChanged.connect(on_start_y_changed)
    window.endXSpinBox.valueChanged.connect(on_end_x_changed)
    window.endYSpinBox.valueChanged.connect(on_end_y_changed)
    window.magnitudeSpinBox.valueChanged.connect(on_magnitude_changed)
    window.showMagnitudeCheckBox.toggled.connect(on_show_magnitude_toggled)
    window.labelTextLineEdit.editingFinished.connect(on_label_text_changed)
    window.showLabelCheckBox.toggled.connect(on_show_label_toggled)
    window.fontSizeSpinBox.valueChanged.connect(on_font_size_changed)
    window.boldButton.toggled.connect(on_bold_toggled)
    window.italicButton.toggled.connect(on_italic_toggled)

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
