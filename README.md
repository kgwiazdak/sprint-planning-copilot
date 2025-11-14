# AI Scrum Co-Pilot — MVP (Faza 1)

Transkrypcja → Ekstrakcja zadań (LLM/RAG-ready), z walidacją JSON i artefaktami.

## Jak uruchomić lokalnie (MVP)

Wymagania: Python 3.11+, [Poetry 2.x](https://python-poetry.org/docs/), [FFmpeg](https://ffmpeg.org/) (np. `sudo apt install ffmpeg`)

```bash
poetry install --with dev
export MOCK_LLM=1   # deterministyczny tryb bez kluczy i modeli
poetry run uvicorn backend.app:app --reload
```

Poetry automatycznie zarządza środowiskiem w `.venv`, więc nie trzeba ręcznie wywoływać `python -m venv` ani `pip install`.

> Opcjonalnie ustaw `WHISPER_MODEL` (np. `base`, `small`, `medium`) aby wybrać wariant modelu Whisper używanego do
> transkrypcji.

## Użycie (curl)

```bash
curl -X POST http://127.0.0.1:8000/extract -F "file=@samples/sample_transcript.txt"
```

Odpowiedź: STRICT JSON zgodny ze schematem.

## Pliki kluczowe

- `backend/app.py` — FastAPI endpoint `POST /extract`
- `backend/schemas.py` — Pydantic schema walidująca wynik
- `backend/extractor.py` — logika ekstrakcji (MOCK_LLM=1 → heurystyka; F2 → LLM przez LangChain)
- `backend/stt.py` — transkrypcja audio przez Whisper
- `backend/storage.py` — SQLite artefakty (meetings + extraction_runs) — w F2 zamień na Postgres
- `backend/mlflow_logging.py` — best-effort log do MLflow (opcjonalnie)

## Próbka

`samples/sample_transcript.txt` → wynik przez `curl`.

## Przejście do F2

- Wyłącz `MOCK_LLM` i skonfiguruj Azure OpenAI (`LLM_PROVIDER=azure`, itd.)
- Skonfiguruj docelową usługę STT (np. Azure Speech) według potrzeb
- Zamień SQLite na Postgres (SQLAlchemy) + dodaj RAG (Azure AI Search/pgvector)

## Frontend (React + Vite)

Interfejs użytkownika żyje w katalogu `frontend/` i jest zbudowany w oparciu o React (TypeScript), Material UI oraz React Query. Panel zawsze komunikuje się z backendem FastAPI, więc do pracy wymagany jest uruchomiony serwer API (np. `poetry run uvicorn ...` lub `docker compose up`).

### Szybki start

```bash
cd frontend
npm install
npm run dev
```

- `npm run build` — produkcyjny build Vite
- `npm run preview` — szybki podgląd statycznego buildu

Domyślnie `.env.development` ustawia `VITE_API_URL=http://localhost:8000/api`, więc panel rozmawia z FastAPI i korzysta z danych w SQLite. Jeśli potrzebujesz trybu offline, zaimplementuj go we własnym zakresie (wsparcie MSW zostało usunięte w docelowym trybie produkcyjnym).

### Architektura UI

```
frontend/src
├─ app/          # routing, theming, providers
├─ api/          # axios klient, React Query hooks
├─ components/   # współdzielone elementy (DataGridToolbar, TaskDrawer, ConfirmDialog)
├─ features/     # moduły meetings + tasks (listy, formularze, review HITL)
├─ schemas/      # walidacja Zod (task/meeting)
├─ types/        # modele domenowe
└─ utils/        # formatery dat itp.
```

Kluczowe widoki:

- `/review` — Review & Approve (DataGrid z inline edit + drawer, bulk approve/reject)
- `/meetings` — lista spotkań + edycja/usuń
- `/meetings/:id/tasks` — zadania z danego spotkania, filtry statusów, link do edycji
- `/meetings/new` — formularz nowego spotkania (React Hook Form + Zod)
- `/tasks/:id/edit` — pełna edycja zadania

### Docker Compose

`docker compose up --build` uruchamia:

- `api` na porcie `8000`
- `mlflow` na porcie `5000`
- `frontend` (statyczny build Vite serwowany przez Nginx) na porcie `4173`

Domyślnie frontend w kontenerze wskazuje na usługę backendową pod adresem `http://api:8000/api`. Własny adres można nadpisać przez zmienną `VITE_FRONTEND_API_URL`.
