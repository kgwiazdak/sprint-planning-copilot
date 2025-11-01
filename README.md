# AI Scrum Co-Pilot — MVP (Faza 1)
Transkrypcja → Ekstrakcja zadań (LLM/RAG-ready), z walidacją JSON i artefaktami.

## Jak uruchomić lokalnie (MVP)
Wymagania: Python 3.11+, [FFmpeg](https://ffmpeg.org/) (np. `sudo apt install ffmpeg`)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
export MOCK_LLM=1   # deterministyczny tryb bez kluczy i modeli
uvicorn backend.app:app --reload
```

> Opcjonalnie ustaw `WHISPER_MODEL` (np. `base`, `small`, `medium`) aby wybrać wariant modelu Whisper używanego do transkrypcji.

## Użycie (curl)
```bash
curl -X POST http://127.0.0.1:8000/extract \
  -F "file=@samples/sample_transcript.txt"
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
