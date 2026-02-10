import signal
import sys
from importlib.metadata import version as pkg_version
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PyQt6.QtGui import QPalette, QColor, QKeySequence, QShortcut
from PyQt6 import uic

from canvas import FBDCanvas, ToolMode  # noqa: F401 — FBDCanvas needed for uic promotion
from file_io import save_fbd, load_fbd

try:
    APP_VERSION = pkg_version("fbd-lab")
except Exception:
    # Fallback: read from pyproject.toml directly when not installed
    import re
    _toml = (Path(__file__).parent / "pyproject.toml").read_text()
    APP_VERSION = re.search(r'version\s*=\s*"(.+?)"', _toml).group(1)

APP_TITLE = f"FBD Lab v{APP_VERSION}"


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
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

    # Load default background
    default_image = Path(__file__).parent / "FBD1.png"
    if default_image.exists():
        window.canvas.load_background_from_file(default_image)

    # --- Menu actions ---

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
            "FBD Files (*.fbd);;All Files (*)"
        )
        if file_path:
            if not file_path.endswith(".fbd"):
                file_path += ".fbd"
            save_fbd(window.canvas, file_path)
            current_file = file_path
            mark_clean()

    def save():
        nonlocal current_file
        if current_file:
            save_fbd(window.canvas, current_file)
            mark_clean()
        else:
            save_as()

    def open_file():
        nonlocal current_file
        file_path, _ = QFileDialog.getOpenFileName(
            window, "Open FBD File", "",
            "FBD Files (*.fbd);;All Files (*)"
        )
        if file_path:
            load_fbd(window.canvas, file_path)
            current_file = file_path
            mark_clean()

    window.actionImportBackground.triggered.connect(import_background)
    window.actionSave.triggered.connect(save)
    window.actionSaveAs.triggered.connect(save_as)
    window.actionOpen.triggered.connect(open_file)

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

    # --- Properties panel sync ---
    _updating_panel = False  # guard against feedback loops

    def sync_panel():
        nonlocal _updating_panel
        arrow = window.canvas.get_selected_arrow()
        if arrow is None:
            window.propertiesGroupBox.setVisible(False)
            return

        window.propertiesGroupBox.setVisible(True)
        _updating_panel = True
        window.startXSpinBox.setValue(arrow.tail.x())
        window.startYSpinBox.setValue(arrow.tail.y())
        window.endXSpinBox.setValue(arrow.head.x())
        window.endYSpinBox.setValue(arrow.head.y())
        window.magnitudeLineEdit.setText(f"{arrow.magnitude:.1f}")
        window.showLabelCheckBox.setChecked(arrow.label_visible)
        window.labelTextLineEdit.setText(arrow.label_text)
        _updating_panel = False

    window.propertiesGroupBox.setVisible(False)
    window.propertiesGroupBox.setEnabled(True)
    window.canvas.selection_changed.connect(sync_panel)
    window.canvas.arrow_created.connect(lambda _: sync_panel())

    # --- Dirty tracking ---
    window.canvas.modified.connect(mark_dirty)

    # --- Close event ---
    def on_close(event):
        if dirty:
            reply = QMessageBox.question(
                window, "Unsaved Changes",
                "You have unsaved changes. Do you want to save before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Save:
                save()
                event.accept()
            elif reply == QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    window.closeEvent = on_close

    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
