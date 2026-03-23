# FBD Lab

A desktop application for drawing **free body diagrams**. Students draw force vectors on a canvas — over a background image of a mechanics problem — and save their work for grading.

![FBD Lab](FBD_Lab.png)

## Features

- **Draw force vectors** — click and drag to create arrows on the canvas
- **Draggable labels** — labels render physics notation (`F_1` → **F**<sub>1</sub>) and can be repositioned independently
- **Auto-labeling** — new arrows are automatically labeled F₁, F₂, etc.
- **Select and edit** — click arrows to select, drag control points to resize/reposition
- **Properties panel** — edit endpoints, magnitude, label text, visibility, font size, bold/italic
- **Undo/Redo** — full history for all operations (Ctrl+Z / Ctrl+Y)
- **Background images** — import via File menu, drag-and-drop, or paste from clipboard
- **Save/Load** — `.fbdb` binary format
- **Dirty tracking** — unsaved changes shown with `*` in the title bar, with a save prompt on close
- **Dark mode** — Fusion palette for comfortable use

## Quickstart

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv run main.py
```

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `A` | Toggle arrow creation mode |
| `Delete` | Delete selected arrow |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Ctrl+S` | Save |
| `Ctrl+Shift+S` | Save As |
| `Ctrl+O` | Open |
| `Ctrl+N` | New |
| `Ctrl+Q` | Quit |

## File Association (Windows)

To open `.fbd` and `.fbdb` files by double-clicking:

1. Download and run `FBD Lab v*.exe` from the [Releases](https://github.com/cenmir/FBD_Lab/releases) page
2. Go to **File → Register File Types (.fbd, .fbdb)**
3. Done — double-clicking any `.fbd` or `.fbdb` file will now open it in FBD Lab

> **Note:** This only works when running the standalone `.exe`, not from a Python script.

## Grading Workflow

1. Instructor provides a problem image
2. Student opens the image in FBD Lab, draws their free body diagram, and saves
3. The submission is graded — either automatically by comparing vectors against a solution key, or manually by an instructor

## Project Structure

| File | Purpose |
|---|---|
| `main.py` | Entry point, dark palette, signal wiring |
| `canvas.py` | `FBDCanvas` (QGraphicsView) — tools, arrow creation, dragging |
| `arrow_item.py` | `ArrowItem` + `ArrowLabel` + `ControlPoint` graphics items |
| `commands.py` | `QUndoCommand` subclasses for all undoable operations |
| `file_io.py` | `.fbdb` save/load |
| `ui/mainwindow.ui` | Qt Designer layout with promoted FBDCanvas |
| `fonts/` | Bundled Computer Modern Unicode fonts for label rendering |
