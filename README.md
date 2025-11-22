# Sprint Planning Copilot

> Transform sprint planning meeting recordings into Jira-ready backlog items with AI-powered transcription and task extraction.

[![Tests](https://github.com/kgwiazdak/sprint-planning-copilot/actions/workflows/test.yml/badge.svg)](https://github.com/kgwiazdak/sprint-planning-copilot/actions/workflows/test.yml)

## Demo

<img src="data/edited_video_optimized.gif" alt="Sprint Planning Copilot demo" width="900"/>

## What Does It Do?

Sprint Planning Copilot automates the tedious part of sprint planning:

1. **Upload** a meeting recording through the web interface
2. **Transcribe** with Azure Speech AI (with speaker diarization)
3. **Extract** structured tasks using LLM (title, description, story points, assignees, labels)
4. **Review** and edit the AI-generated tasks in a friendly UI
5. **Push** to Jira with one click

All processing happens asynchronously in the background, with full audit logging to MLflow.

## Architecture

```
Browser ──upload──▶ Azure Blob Storage
            │
            ▼
        FastAPI API ──queue──▶ Background Worker
            │                      │
            │                      ├─▶ Azure Speech (transcription)
            │                      ├─▶ LLM (task extraction)
            │                      └─▶ SQLite + MLflow
            │
            └──REST──▶ React UI (review & approve)
```

---

## Quick Start

### Prerequisites

- **Python 3.11+** with [Poetry](https://python-poetry.org/)
- **Node.js 18+** with npm
- **Azure Account** (for Blob Storage and Speech Services)
- **OpenAI API key** or Azure OpenAI endpoint
- **Jira Cloud** account with API token
- **Docker** (optional, for containerized deployment)

---

## Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/kgwiazdak/sprint-planning-copilot.git
cd sprint-planning-copilot
```

### 2. Backend Setup

```bash
# Install dependencies
poetry install --with dev

# Create environment file from template
cp .env.sample .env
```

**Edit `.env`** with your configuration (see [Critical Environment Variables](#critical-environment-variables) below).

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Create environment file from template
cp .env.development.sample .env.development
```

**Edit `.env.development`** with:
```env
VITE_API_URL=http://localhost:8000/api
VITE_AZURE_AD_CLIENT_ID=your-client-id      # Optional, for Azure AD auth
VITE_AZURE_AD_TENANT_ID=your-tenant-id      # Optional
VITE_AZURE_AD_SCOPES=api://your-api/scope   # Optional
VITE_APP_PROFILE=dev
```

---

## Critical Environment Variables

### Required for Local Development

These are the **minimum variables** you need to run the app locally:

#### **Azure Blob Storage** (for file uploads)
```env
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
AZURE_STORAGE_CONTAINER_NAME=meetings           # Main container for recordings
AZURE_STORAGE_CONTAINER_WORKERS=workers         # Container for voice samples
AZURE_STORAGE_QUEUE_NAME=meeting-imports        # Queue for background jobs
```

#### **Azure Speech Services** (for transcription)
```env
AZURE_SPEECH_KEY=your-speech-key
AZURE_SPEECH_REGION=eastus
AZURE_SPEECH_LANGUAGE=en-US
```

#### **LLM Provider** (for task extraction)

**Option A: Azure OpenAI**
```env
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_API_KEY=your-api-key
```

**Option B: OpenAI**
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-4-turbo
```

**Option C: Mock LLM (for testing)**
```env
MOCK_LLM=1  # Uses deterministic mock responses, no API calls
```

#### **Jira Integration**
```env
JIRA_BASE_URL=https://your-company.atlassian.net
JIRA_PROJECT_KEY=SCRUM
JIRA_EMAIL=your-email@company.com
JIRA_API_TOKEN=your-jira-api-token
JIRA_STORY_POINTS_FIELD=customfield_10016  # Optional, for story points
```

### Optional Variables

#### **Database**
```env
DB_PROVIDER=sqlite                # or "cosmos" for Cosmos DB
DB_URL=sqlite:///./app.db         # SQLite file path
```

#### **MLflow Telemetry**
```env
MLFLOW_TRACKING_URI=http://localhost:5000
MLFLOW_EXPERIMENT_NAME=sprint-planning-copilot
```

#### **Azure AD Authentication** (Optional)
```env
AZURE_AD_TENANT_ID=your-tenant-id
AZURE_AD_CLIENT_ID=your-client-id
AZURE_AD_AUDIENCE=api://your-api-id
AZURE_AD_REQUIRE_AUTH=true
```

#### **Development Features**
```env
APP_PROFILE=dev                   # Enables mock audio button in UI
ENABLE_MOCK_AUDIO=1               # Auto-enables mock audio
MOCK_AUDIO_BLOB_PATH=samples/demo.mp3
```

---

## Running the Application

### Option 1: Local Development (Recommended for Development)

**Terminal 1: Start the API**
```bash
poetry run uvicorn backend.app:app --reload
```
- API runs on `http://localhost:8000`
- Swagger docs at `http://localhost:8000/docs`

**Terminal 2: Start the Background Worker**
```bash
poetry run python -m backend.worker
```
- Processes queued meeting imports
- Polls Azure Storage Queue every 2 seconds

**Terminal 3: Start the Frontend**
```bash
cd frontend
npm run dev
```
- UI runs on `http://localhost:5173`

**Terminal 4: Start MLflow (Optional)**
```bash
poetry run mlflow ui
```
- MLflow UI on `http://localhost:5000`

### Option 2: Docker Compose (Recommended for Production)

```bash
docker compose up --build
```

Services:
- **API**: `http://localhost:8000`
- **Frontend**: `http://localhost:4173`
- **MLflow**: `http://localhost:5000`
- **Worker**: Background processing (no exposed port)

To rebuild after code changes:
```bash
docker compose up --build
```

To stop:
```bash
docker compose down
```

---

## Setting Up Voice Diarization

The system uses **Azure Conversation Transcriber** with speaker diarization to automatically identify who said what during meetings and assign tasks accordingly.

### How It Works

1. **Voice intro samples** are stored in Azure Blob Storage (`AZURE_STORAGE_CONTAINER_WORKERS`)
2. During transcription, these intros are prepended to establish speaker profiles
3. The LLM matches diarized speakers (Speaker1, Speaker2) to real names
4. Tasks are automatically assigned to matched speakers

### Adding Voice Profiles

#### Method 1: Manual Upload to Azure (Bulk Setup)

1. Record a short intro from each team member (10-30 seconds):
   - "Hi, my name is John Smith, and I'm a backend engineer..."

2. Save as MP3 with the naming format:
   ```
   intro_FirstName_LastName.mp3
   ```
   Examples:
   - `intro_John_Smith.mp3`
   - `intro_Sarah_Johnson.mp3`
   - `intro_Adrian_Kowalski.mp3`

3. Upload to Azure Blob Storage:
   ```bash
   # Using Azure Storage Explorer, or Azure CLI:
   az storage blob upload \
     --container-name workers \
     --file intro_John_Smith.mp3 \
     --name intro_John_Smith.mp3 \
     --connection-string "YOUR_CONNECTION_STRING"
   ```

4. Restart the backend to sync:
   ```bash
   # The backend automatically downloads missing samples on startup
   poetry run uvicorn backend.app:app --reload
   ```

#### Method 2: Upload via UI (Individual Setup)

1. Navigate to **Voice Profiles** page in the UI (`/voices`)
2. Select an existing user or enter a new display name
3. Choose an audio file (WAV, MP3, or M4A)
4. Click **Upload & sync**
5. The file is automatically saved as `intro_DisplayName.mp3` in both local storage and Azure

### File Naming Rules

- **Format**: `intro_FirstName_LastName.mp3`
- **Replace spaces** with underscores in names
- **Case-sensitive**: Use exact capitalization as it appears in Jira
- **Examples**:
  - ✅ `intro_Jane_Doe.mp3`
  - ✅ `intro_John_van_Der_Berg.mp3`
  - ❌ `intro-jane-doe.mp3` (wrong format)
  - ❌ `Jane_Doe_intro.mp3` (wrong order)

### Verifying Voice Profiles

Check if profiles are loaded:
```bash
# View local voice samples
ls data/voices/

# Or check via API
curl http://localhost:8000/api/users
```

You should see users with `voiceSamplePath` populated.

---

## Usage Workflow

### 1. Upload a Meeting Recording

1. Go to **New Meeting** page
2. Enter meeting details (title, date, participants)
3. Upload an audio file (MP3, WAV, M4A)
4. Click **Import Meeting**

The file uploads directly to Azure Blob Storage, and a background job is queued.

### 2. Monitor Processing

- Meeting status shows: `queued` → `processing` → `completed`
- The UI auto-refreshes every 5 seconds
- Processing time: ~2-5 minutes for a 30-minute meeting

### 3. Review Generated Tasks

1. Click on the completed meeting
2. Review AI-extracted tasks:
   - Title, description, story points
   - Assignees (auto-assigned via voice diarization)
   - Labels, acceptance criteria
3. Edit any tasks inline if needed

### 4. Push to Jira

1. Go to **Review & Approve** tab
2. Select tasks to push
3. Click **Approve & Push to Jira**
4. Tasks are created in Jira and marked as approved

---

## Development Commands

### Backend

```bash
# Run API server (auto-reload on changes)
poetry run uvicorn backend.app:app --reload

# Start background worker
poetry run python -m backend.worker

# Run tests
poetry run pytest backend/tests -v

# Run linting
poetry run ruff check backend/
```

### Frontend

```bash
cd frontend

# Development server (hot reload)
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Linting
npm run lint

# Type checking
npm run type-check
```

---

## Testing

### Backend Tests

```bash
poetry run pytest backend/tests -v
```

Test coverage includes:
- Meeting import use cases
- MLflow telemetry logging
- Jira integration
- Voice profile sync
- Azure queue processing

### Frontend Tests

```bash
cd frontend
npm run test:e2e
```

---

## Architecture Details

### Hexagonal Architecture (Backend)

The backend follows **hexagonal (ports and adapters)** architecture:

```
backend/
├── domain/           # Core entities and port interfaces
├── application/      # Use cases and services (business logic)
├── infrastructure/   # Adapters (Azure, SQLite, LLM, Jira)
└── presentation/     # HTTP routers (FastAPI)
```

**Key Ports** (`backend/domain/ports.py`):
- `BlobStoragePort` - File storage operations
- `TranscriptionPort` - Audio → text
- `ExtractionPort` - Text → structured tasks
- `MeetingsRepositoryPort` - Data persistence
- `TelemetryPort` - MLflow logging

### Frontend Architecture

```
frontend/src/
├── app/              # Root app, routing, auth provider
├── features/         # Domain-specific components (meetings, tasks, review)
├── api/              # React Query hooks + Axios client
├── components/       # Shared UI components
└── types/            # TypeScript type definitions
```

---

## CI/CD with GitHub Actions

The repository includes GitHub Actions workflows:

### Workflows

1. **Tests** (`.github/workflows/test.yml`)
   - Runs on every push and PR
   - Backend: pytest
   - Frontend: eslint + type check

2. **Deploy Backend** (`.github/workflows/deploy-backend.yml`)
   - Builds and pushes Docker image to Azure Container Registry
   - Deploys to Azure Container Apps
   - Runs only after tests pass

3. **Deploy Frontend** (`.github/workflows/deploy-frontend.yml`)
   - Builds production frontend with Vite
   - Deploys to Azure Container Apps
   - Runs only after tests pass

### Required GitHub Secrets

Set these in **Settings → Secrets and variables → Actions**:

- `AZURE_CREDENTIALS` - Service principal JSON
- `AZURE_SUBSCRIPTION_ID`
- `ACR_NAME`, `ACR_USERNAME`, `ACR_PASSWORD` - Azure Container Registry
- `VITE_AZURE_AD_CLIENT_ID`, `VITE_AZURE_AD_TENANT_ID`, `VITE_AZURE_AD_SCOPES`

See [`GITHUB_ACTIONS_SETUP.md`](./GITHUB_ACTIONS_SETUP.md) for detailed setup instructions.

---

## Troubleshooting

### Problem: Browser upload fails

**Cause**: Azure Blob Storage CORS not configured

**Solution**: Add CORS rule to your storage account:
```bash
az storage cors add \
  --services b \
  --methods PUT OPTIONS \
  --origins http://localhost:5173 http://localhost:4173 \
  --allowed-headers "*" \
  --exposed-headers "*" \
  --max-age 3600 \
  --account-name YOUR_STORAGE_ACCOUNT
```

### Problem: Worker not processing jobs

**Cause**: Queue not configured or connection string incorrect

**Solution**:
1. Verify `AZURE_STORAGE_QUEUE_NAME` is set in `.env`
2. Check queue exists in Azure Storage Account
3. Check worker logs for connection errors

### Problem: Speaker diarization not working

**Cause**: Missing or incorrectly named voice intro files

**Solution**:
1. Check files exist: `ls data/voices/`
2. Verify naming format: `intro_FirstName_LastName.mp3`
3. Check API: `curl http://localhost:8000/api/users`
4. Restart backend to sync new files

### Problem: Jira push fails

**Cause**: Invalid credentials, missing fields, or custom field mismatch

**Solution**:
1. Verify `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`
2. Check project key exists: `JIRA_PROJECT_KEY`
3. Verify story points field ID (if used): `JIRA_STORY_POINTS_FIELD`
4. Check API error response for detailed Jira error message

### Problem: "Duplicate column" warnings on startup

**Cause**: Auto-migration checks for missing columns

**Solution**: This is harmless. The system automatically adds missing columns idempotently.

---

## Configuration Examples

### Minimal .env (Local Development with Mocks)

```env
# Minimal setup for local testing with mock LLM
MOCK_LLM=1
ENABLE_MOCK_AUDIO=1

# Azure Storage (required even with mocks)
AZURE_STORAGE_CONNECTION_STRING=UseDevelopmentStorage=true  # Azurite emulator
AZURE_STORAGE_CONTAINER_NAME=meetings
AZURE_STORAGE_CONTAINER_WORKERS=workers
AZURE_STORAGE_QUEUE_NAME=meeting-imports

# Azure Speech (still required for real transcription)
AZURE_SPEECH_KEY=your-key
AZURE_SPEECH_REGION=eastus

# Jira (required for approval step)
JIRA_BASE_URL=https://your-company.atlassian.net
JIRA_PROJECT_KEY=TEST
JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=your-token
```

### Production .env

```env
APP_PROFILE=prod

# Azure Storage
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
AZURE_STORAGE_CONTAINER_NAME=meetings-prod
AZURE_STORAGE_CONTAINER_WORKERS=workers-prod
AZURE_STORAGE_QUEUE_NAME=meeting-imports-prod

# Azure Speech
AZURE_SPEECH_KEY=your-prod-key
AZURE_SPEECH_REGION=eastus

# Azure OpenAI
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-prod.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_API_KEY=your-prod-key

# Cosmos DB (production database)
DB_PROVIDER=cosmos
COSMOS_ACCOUNT_URI=https://your-account.documents.azure.com:443/
COSMOS_KEY=your-cosmos-key
COSMOS_DB_NAME=sprint-copilot-prod
COSMOS_MEETINGS_CONTAINER=meetings
COSMOS_TASKS_CONTAINER=tasks
COSMOS_USERS_CONTAINER=users
COSMOS_RUNS_CONTAINER=runs

# Jira
JIRA_BASE_URL=https://your-company.atlassian.net
JIRA_PROJECT_KEY=SCRUM
JIRA_EMAIL=bot@company.com
JIRA_API_TOKEN=your-prod-token
JIRA_STORY_POINTS_FIELD=customfield_10016

# Azure AD Authentication
AZURE_AD_TENANT_ID=your-tenant
AZURE_AD_CLIENT_ID=your-client
AZURE_AD_AUDIENCE=api://your-api
AZURE_AD_REQUIRE_AUTH=true

# MLflow
MLFLOW_TRACKING_URI=https://mlflow.yourcompany.com
MLFLOW_EXPERIMENT_NAME=sprint-copilot-prod
```

---

## Project Structure

```
sprint-planning-copilot/
├── backend/
│   ├── app.py                    # FastAPI application entry point
│   ├── worker.py                 # Background worker entry point
│   ├── settings.py               # Configuration management
│   ├── container.py              # Dependency injection
│   ├── domain/                   # Core business entities & ports
│   ├── application/              # Use cases & services
│   ├── infrastructure/           # External adapters (Azure, DB, LLM)
│   ├── presentation/             # HTTP routers
│   └── tests/                    # Backend tests
├── frontend/
│   ├── src/
│   │   ├── app/                  # App shell, routing, auth
│   │   ├── features/             # Feature modules
│   │   ├── api/                  # API client & React Query hooks
│   │   ├── components/           # Shared components
│   │   └── types/                # TypeScript types
│   ├── index.html
│   └── vite.config.ts
├── .github/
│   └── workflows/                # GitHub Actions CI/CD
├── docker-compose.yml            # Local containerized stack
├── Dockerfile                    # Backend container image
├── frontend/Dockerfile           # Frontend container image
├── pyproject.toml                # Python dependencies
├── poetry.lock
└── README.md                     # This file
```

---

## Contributing

1. **Fork and clone** the repository
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Make your changes** and ensure tests pass
4. **Commit**: `git commit -m "Add amazing feature"`
5. **Push**: `git push origin feature/amazing-feature`
6. **Open a Pull Request**

### Code Quality Checks

Before submitting a PR:

```bash
# Backend
poetry run pytest backend/tests -v
poetry run ruff check backend/

# Frontend
cd frontend
npm run lint
npm run type-check
npm run build  # Ensure it builds
```

---

## License

[Add your license here]

---

## Support & Documentation

- **Bug Reports**: [GitHub Issues](https://github.com/kgwiazdak/sprint-planning-copilot/issues)
- **Architecture Details**: See [`CLAUDE.md`](./CLAUDE.md)
- **Azure Setup**: See [`AZURE_RESOURCES_EXPLAINED.md`](./AZURE_RESOURCES_EXPLAINED.md)
- **GitHub Actions Setup**: See [`GITHUB_ACTIONS_SETUP.md`](./GITHUB_ACTIONS_SETUP.md)

---
