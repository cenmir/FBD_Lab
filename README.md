# FBD Lab

A desktop application for drawing **free body diagrams**. Students draw force vectors on a canvas — over a background image of a mechanics problem — and save their work for grading.

![FBD Lab](FBD_Lab.png)

## Features

### Drawing Tools

| Tool | Shortcut | Description |
|---|---|---|
| **Force** | `F` | Click and drag to create force vectors with arrowheads |
| **Point** | `P` | Click to place point markers |
| **Direction** | `D` | Dashed line with optional open-triangle arrowhead |
| **Line** | `L` | Thick line with optional arrows on either end and dashed style |
| **Moment** | `M` | Curved arc arrow with reversible direction |
| **Rectangle** | `R` | Click-drag to create; supports trapezoid (Ctrl+Alt+drag corner), COG symbol, local n-t coordinate system, fade mode |
| **Polygon** | `G` | Click to add vertices, click near first vertex to close |
| **Ellipse** | `E` | Click-drag to create; hold Ctrl for circle, Ctrl-resize for isometric |
| **Text** | `T` | Click to place a text label |
| **Spring** | `S` | Smooth Bezier coil between two points |
| **Squiggle** | `W` | Smooth sine-wave denotation/break line |

### Styling and Properties

- **Per-item color and opacity** — every item type has configurable color and opacity
- **Rectangle/Polygon/Ellipse** — fill color, fill opacity, edge color, edge opacity, edge thickness
- **Rectangle extras** — rotation angle (CCW), COG symbol (quadrant circle), toggleable local n-t coordinate system with draggable axes and editable labels, fade mode (gradient to transparent), symmetric trapezoid via Ctrl+Alt corner drag
- **Line extras** — arrow heads on either/both ends, dashed line style, body and outline thickness
- **Moment extras** — reverse direction checkbox
- **Spring/Squiggle** — configurable coils/waves, amplitude, thickness
- **Label background** — white background behind any label for readability over lines/shapes
- **LaTeX-style labels** — subscripts (`F_1`), superscripts (`15^\circ`), Greek letters (`\alpha`, `\theta`), and symbols (`\circ`, `\pm`, `\times`, `\perp`, `\infty`, `\approx`, etc.)

### Editing

- **Drag-to-scrub spinboxes** — click and drag up/down on any spinbox to quickly change values
- **Arrow key movement** — move selected items with arrow keys (1px), Shift+arrow (10px)
- **Copy/Paste** — Ctrl+C / Ctrl+V, pastes at current mouse position with full property preservation
- **Bring to Front / Send to Back** — Ctrl+] or Ctrl++ / Ctrl+[ or Ctrl+-, also via right-click menu
- **Undo/Redo** — full history for all operations (Ctrl+Z / Ctrl+Y)
- **Background images** — import via File menu, drag-and-drop, or paste from clipboard
- **Layer visibility** — toggle visibility per item type, saved/loaded with files

### File Format

- **v7 binary format** (`.fbdb`) — hybrid binary+JSON: efficient image storage with JSON item data that automatically handles all properties
- **Embedded PNG snapshot** — every save includes a rendered snapshot of the canvas
- **Backward compatible** — loads legacy v1-v6 binary files and old JSON `.fbd` files

### Other

- **Dirty tracking** — unsaved changes shown with `*` in the title bar, with a save prompt on close
- **Dark mode** — Fusion palette for comfortable use
- **Export PNG** — respects currently visible layers

## Quickstart

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv run main.py
```

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `F` | Toggle force creation mode |
| `P` | Toggle point creation mode |
| `D` | Toggle direction creation mode |
| `L` | Toggle line creation mode |
| `M` | Toggle moment creation mode |
| `R` | Toggle rectangle creation mode |
| `G` | Toggle polygon creation mode |
| `E` | Toggle ellipse creation mode |
| `T` | Toggle text creation mode |
| `S` | Toggle spring creation mode |
| `W` | Toggle squiggle creation mode |
| `Backspace` | Delete selected item |
| `Arrow keys` | Move selected item (1px) |
| `Shift+Arrow` | Move selected item (10px) |
| `Ctrl+C` | Copy selected item(s) |
| `Ctrl+V` | Paste at mouse position |
| `Ctrl+]` or `Ctrl++` | Bring to front |
| `Ctrl+[` or `Ctrl+-` | Send to back |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Ctrl+S` | Save |
| `Ctrl+Shift+S` | Save As |
| `Ctrl+O` | Open |
| `Ctrl+N` | New |

## File Association (Windows)

To open `.fbdb` files by double-clicking:

1. Download and run `FBD Lab v*.exe` from the [Releases](https://github.com/cenmir/FBD_Lab/releases) page
2. Go to **File > Register File Type (.fbdb)**
3. Done — double-clicking any `.fbdb` file will now open it in FBD Lab

> **Note:** This only works when running the standalone `.exe`, not from a Python script.

## Grading Workflow

1. Instructor provides a problem image
2. Student opens the image in FBD Lab, draws their free body diagram, and saves
3. The submission is graded — either automatically by comparing vectors against a solution key, or manually by an instructor

## Project Structure

| File | Purpose |
|---|---|
| `main.py` | Entry point, dark palette, signal wiring, properties panel |
| `canvas.py` | `FBDCanvas` (QGraphicsView) — tools, item creation, dragging, copy/paste |
| `vector_item.py` | Force vector with arrowhead |
| `point_item.py` | Point marker |
| `direction_item.py` | Dashed direction line with optional arrowhead |
| `line_item.py` | Thick line with optional arrows and dashed style |
| `moment_item.py` | Curved arc arrow (moment) |
| `rectangle_item.py` | Rectangle with COG, local CS, fade, trapezoid |
| `polygon_item.py` | Editable polygon |
| `ellipse_item.py` | Ellipse/circle |
| `text_item.py` | Standalone text label |
| `spring_item.py` | Spring coil line |
| `squiggle_item.py` | Denotation/break line |
| `base_item.py` | `LabelPropertiesMixin`, `BaseLabel`, `BaseControlPoint` |
| `rotation_handle.py` | Draggable rotation handle for rectangles/ellipses |
| `commands.py` | `QUndoCommand` subclasses for all undoable operations |
| `file_io.py` | v7 binary save/load with legacy format support |
| `build_release.py` | Build standalone `.exe` and create GitHub release |
| `ui/mainwindow.ui` | Qt Designer layout with promoted FBDCanvas |
| `fonts/` | Bundled Computer Modern Unicode fonts for label rendering |
