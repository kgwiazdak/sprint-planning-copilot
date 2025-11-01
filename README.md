# AI Scrum Co-Pilot — MVP (Faza 1)
Transkrypcja → Ekstrakcja zadań (LLM/RAG-ready), z walidacją JSON i artefaktami.

## Jak uruchomić lokalnie (MVP)
Wymagania: Python 3.11+

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
export MOCK_LLM=1   # deterministyczny tryb bez kluczy i modeli
uvicorn backend.app:app --reload
```

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
- `backend/stt.py` — stub STT (Whisper/Azure w F2)
- `backend/storage.py` — SQLite artefakty (meetings + extraction_runs) — w F2 zamień na Postgres
- `backend/mlflow_logging.py` — best-effort log do MLflow (opcjonalnie)

## Próbka
`samples/sample_transcript.txt` → wynik przez `curl`.

## Przejście do F2
- Wyłącz `MOCK_LLM` i skonfiguruj Azure OpenAI (`LLM_PROVIDER=azure`, itd.)
- Podmień `stt.py` na Whisper/Azure Speech
- Zamień SQLite na Postgres (SQLAlchemy) + dodaj RAG (Azure AI Search/pgvector)
