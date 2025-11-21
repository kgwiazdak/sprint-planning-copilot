# Sprint Planning Copilot

AI-driven assistant that ingests meeting recordings or transcripts, extracts structured Jira-ready tasks, and logs
ML/telemetry data for later auditing. The system is event-driven: uploads happen straight to blob storage, the API
enqueues work, and a worker processes meetings asynchronously.

## High-Level Architecture

```
+-------------+      +----------------+      +--------------------+      +------------------+
| Frontend    | ---> | FastAPI API    | ---> | Async Queue/Worker | ---> | Persistence/MLflow|
| (React/Vite)|      | (uploads/import)|      | (ExtractMeeting)   |      | SQLite + MLflow   |
+-------------+      +----------------+      +--------------------+      +------------------+
      |                        |                       |                        |
  SAS upload              Store stub            Download from blob        Write tasks & log runs
  to Azure Blob           enqueue job           transcribe/extract        return status/tag data
```

### Key Components

- **Frontend (`frontend/`)** – React + Vite UI. Users pick meeting metadata, upload files (via SAS URL), and watch
  statuses (`queued`, `processing`, `completed`, `failed`). React Query handles polling.
- **API (`backend/presentation/http/ui_router.py`)** – Issues SAS upload tokens, accepts import requests, exposes
  meeting/task CRUD. Imports call `SubmitMeetingImportCommand` and immediately return 202.
- **Queue & Worker** – `BackgroundMeetingImportQueue` (asyncio) plus `ExtractMeetingUseCase`. In production you can swap
  for Redis/Azure queue.
- **Domain & Application** – Ports define contracts (`backend/domain/ports.py`, `backend/domain/status.py`).
  Commands/use cases orchestrate
  ingestion (`backend/application/commands/meeting_import.py`, `backend/application/use_cases/extract_meeting.py`).
- **Infrastructure** – SQLite repository, blob storage adapter, transcription/LLM adapters, MLflow logger.

## Workflow Example

1. **Generate SAS** – UI calls `POST /api/uploads/blob` with filename. API returns `uploadUrl`, `blobUrl`,
   and `meetingId`.
2. **Upload File** – Browser performs `PUT` to Azure Blob Storage using `uploadUrl`. (Ensure Azure Storage CORS
   allows `http://localhost:4173`).
3. **Import Meeting** – UI sends `POST /api/meetings/import`
   with `{ title, startedAt, blobUrl, meetingId, originalFilename }`. API stores a stub row (`queued`) and enqueues the
   job.
4. **Background Processing** – Worker downloads the blob, runs transcription/LLM extraction, stores transcript/tasks,
   and logs MLflow metrics/artifacts. Meeting status transitions `queued → processing → completed` (or `failed` on
   error).
5. **Monitoring** – Frontend polls `/api/meetings` every few seconds when any meeting is queued/processing; tasks become
   available once status is completed.

## Important Files

| Path                                                      | Role                                                                   |
|-----------------------------------------------------------|------------------------------------------------------------------------|
| `backend/presentation/http/ui_router.py`                  | All API endpoints (uploads, import, meetings/tasks).                   |
| `backend/application/commands/meeting_import.py`          | Submission command: persist stub + enqueue queue job.                  |
| `backend/application/use_cases/extract_meeting.py`        | Worker logic: download blob, transcribe, extract, persist, log MLflow. |
| `backend/domain/ports.py`                                 | Contracts for blob storage, queue, repository, telemetry.              |
| `backend/domain/status.py`                                | Enum for meeting statuses shared with frontend.                        |
| `backend/infrastructure/persistence/sqlite/repository.py` | SQLite repository, meeting/task CRUD, status updates.                  |
| `backend/mlflow_logging.py`                               | MLflow integration: metrics, artifacts, summaries.                     |
| `frontend/src/api/hooks.ts`                               | React Query hooks for SAS upload and meeting import.                   |
| `frontend/src/features/meetings/MeetingsList.tsx`         | Meeting list view, status chips, auto-polling.                         |

## Running Locally

### Prerequisites

- Python 3.11+
- Poetry 2.x
- FFmpeg (if using audio transcription)
- Node.js 18+
- Azure Blob Storage account (for SAS uploads)

### Backend Setup

```bash
poetry install --with dev
cp .env.sample .env  # configure Azure storage, MLflow, etc.
poetry run uvicorn backend.app:app --reload
```

Key env vars:

- `AZURE_STORAGE_CONNECTION_STRING`, `AZURE_STORAGE_CONTAINER_NAME`
- `MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT_NAME`
- `MOCK_LLM=1` for deterministic extraction during local dev

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Ensure `.env.development` contains `VITE_API_URL=http://localhost:8000/api`.

### Docker Compose

```
docker compose up --build
```

This starts API (8000), MLflow (5000), and Nginx-served frontend (4173). Frontend talks to API via `/api`.

## Testing

Run all backend unit tests (including queue submission + MLflow metrics) via:

```
poetry run pytest backend/tests
```

## Tips for New Contributors

1. **Follow the flow** – Start
   at `frontend/src/api/hooks.ts` → `ui_router.py` → `meeting_import.py` → `extract_meeting.py`. Understanding this path
   makes debugging easy.
2. **Use statuses** – Meeting cards depend on `MeetingStatus` values. When adding features,
   update `backend/domain/status.py` and `frontend/src/types/index.ts` together.
3. **Queue swaps** – `BackgroundMeetingImportQueue` is intentionally simple. To use Redis/Azure queue,
   implement `MeetingImportQueuePort.enqueue` and wire it in `backend/container.py`.
4. **Telemetry** – MLflow artifacts live in `data/mlflow/artifacts`. Ensure MLflow service is running; failures usually
   come from missing env vars.
5. **CORS for blobs** – Configure Azure Storage CORS to allow `http://localhost:4173` (methods `PUT,OPTIONS`). Without
   it uploads fail.

This README replaces older documentation; consult `architecture_plan.md` for ongoing refactors.
