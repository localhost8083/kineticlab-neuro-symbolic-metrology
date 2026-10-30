# KineticLab — Decision Log

Append-only. One entry per decision. Newest last.

## 2026-10-27 — Implementation stack freeze

- **Decision:** Python 3.11+ core (NumPy, SciPy, OpenCV), FFmpeg/ffprobe subprocess for media, pytest for tests, `pyproject.toml` + lock for packaging. UI: FastAPI serving one local single-page HTML/CSS/JS frontend with one vendored chart library (Chart.js or uPlot). No Node toolchain, no build step.
- **Rationale:** deterministic measurement core must be Python; frontend must run offline with minimal moving parts; React+Vite deferred to cut-order.
- **Alternatives rejected:** React+Vite now (build chain cost before core proof); pure CLI-only (demo execution is 25% of judging; UI required but must stay physics-free).
- **UI law:** UI renders only fields from the JSON result contract. UI never computes, formats-in, or invents numeric values.
- **Status:** locked. Changes require Fable review.

## 2026-10-27 — Coordination system

- **Decision:** root `TASKS.md` (status source of truth), `PLAN.md` (durable phases), `WHITEBOARD.md` (append-only handoffs), `Docs/Decision_Log.md` (this file), `Docs/Review_Log.md` (Fable gate results, created at first gate).
- **Status:** locked.
