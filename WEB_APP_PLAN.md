# FBD Lab → Web App

## Current State

- ~9,100 lines of Python, built on PyQt6 (QGraphicsView/Scene canvas)
- 13 drawable item types: vectors, points, directions, lines, moments, rectangles, polygons, ellipses, text, springs, squiggles, COG markers, pin supports
- Full undo/redo via QUndoStack (30+ command types)
- Custom binary file format (`.fbdb` v7) with embedded images + JSON payload
- Properties panel for styling (colors, opacity, thickness, labels with LaTeX-style math)
- Mixin-based architecture for item properties (Stroke, Fill, Edge, Label)
- Item registry pattern for uniform serialization/tool handling

## Core Migration Challenges

1. **QGraphicsView/Scene** → HTML5 Canvas or SVG
2. **PyQt6 signals/slots** → web framework event system
3. **QUndoStack** → custom undo/redo implementation
4. **Properties panel** → web UI components
5. **File I/O** → server-side or client-side file handling
6. **Mouse/keyboard interaction** → DOM event handling

## Open Questions

- **Tech stack?** Python backend (FastAPI/Django) + JS frontend (React/Vue/vanilla)? Full JS? PyScript?
- **Scope** — full feature parity from day one, or start with core drawing tools and iterate?
- **Multi-user / server-side** — multiple users saving work on the server, or single-user browser tool?
- **Deployment** — self-hosted on VPS at a domain?
