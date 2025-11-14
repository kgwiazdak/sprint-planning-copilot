# Repository Guidelines

## Project Structure & Module Organization
- `backend/` – FastAPI service (app, routers, domain logic), with SQLite adapters in `backend/db` and scripts under `backend/scripts`.
- `frontend/` – React + Vite UI (providers, features, API hooks, Playwright tests in `frontend/tests`); build artefacts emit to `frontend/dist/`.
- `data/` – MLflow storage plus seed audio artifacts; `app.db` (SQLite) lives in repo root.
- `docker-compose.yml` orchestrates API, MLflow, and the static frontend; `frontend/Dockerfile` serves optimized builds via Nginx.

## Build, Test, and Development Commands
- Backend install & dev server: `poetry install` then `poetry run uvicorn backend.app:app --reload`.
- Frontend dev: `cd frontend && npm install && npm run dev` (connects to `VITE_API_URL`).
- Production preview: `npm run build` followed by `npm run preview`.
- Linting/formatting: `npm run lint` (ESLint + TypeScript) for the UI; backend code should follow standard PEP 8/black-style formatting even though no helper script is bundled.
- End-to-end verification: `cd frontend && npm run test:e2e` (builds UI, boots FastAPI via Poetry, and runs Playwright).

## Coding Style & Naming Conventions
- Python: 4-space indentation, type hints on public functions, FastAPI dependency-injection patterns, and Pydantic models in `backend/schemas.py`. Keep DB adapters pure and prefer repository classes (`SqliteMeetingsRepository`).
- TypeScript/React: Functional components, hooks-first architecture, co-locate schemas under `frontend/src/schemas`. Follow existing naming (`MeetingTasksPage`, `useReviewTasks`). Run ESLint before submitting.
- Configuration values read from environment (e.g., `DB_URL`, `VITE_API_URL`); never hardcode secrets.

## Testing Guidelines
- Python unit tests live in `backend/tests/`; run via `poetry run pytest`.
- Frontend integration tests live in `frontend/tests/` and use Playwright (`npm run test:e2e`). Tests seed data through API calls, so ensure SQLite is initialized (call `SqliteMeetingsRepository("sqlite:///./app.db")` if the file was deleted).
- Name tests descriptively (e.g., `test_list_meetings_returns_seeded_data`) and keep fixtures deterministic.

## Commit & Pull Request Guidelines
- Git history favors short, descriptive subjects (e.g., “MlFlow advanced”, “Front not working”). Keep subjects ≤50 chars, imperative mood when possible, and elaborate in the body if context is needed.
- Pull requests should summarize scope, list backend/frontend impacts, describe testing (`npm run test:e2e`, `poetry run pytest`), and attach screenshots/GIFs for UI-visible changes. Link tracking tickets or issues when applicable.

## Security & Configuration Tips
- Use `.env` (or `.env.development` in `frontend/`) to supply `DB_URL`, `AZURE_*`, and `VITE_API_URL`; never commit real credentials.
- When swapping SQLite for Postgres, update `DB_URL` and ensure migrations run before hitting `/api/*` endpoints.
