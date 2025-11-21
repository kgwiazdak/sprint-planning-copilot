from __future__ import annotations

import os
from functools import lru_cache
from pydantic import BaseModel


class BlobStorageSettings(BaseModel):
    container_name: str | None = None
    container_workers_name: str | None = None
    connection_string: str | None = None


class AzureSpeechSettings(BaseModel):
    key: str | None = None
    region: str | None = None
    language: str = "en-US"
    sample_rate: int = 16000


class LLMSettings(BaseModel):
    provider: str = "azure"
    azure_api_version: str = "2024-02-15-preview"
    azure_deployment: str | None = None
    azure_endpoint: str | None = None
    openai_model: str = "gpt-4o-mini"
    temperature: float = 0.1


class DatabaseSettings(BaseModel):
    url: str = os.getenv("DB_URL", "sqlite:///./app.db")
    provider: str = os.getenv("DB_PROVIDER", "sqlite").lower()


class CosmosSettings(BaseModel):
    account_uri: str | None = None
    key: str | None = None
    database: str = os.getenv("COSMOS_DB_NAME", "sprint-planning-copilot")
    meetings_container: str = os.getenv("COSMOS_MEETINGS_CONTAINER", "meetings")
    tasks_container: str = os.getenv("COSMOS_TASKS_CONTAINER", "tasks")
    users_container: str = os.getenv("COSMOS_USERS_CONTAINER", "users")
    runs_container: str = os.getenv("COSMOS_RUNS_CONTAINER", "extraction_runs")


class MockAudioSettings(BaseModel):
    enabled: bool = False
    blob_path: str = "mock/team_meeting.mp3"
    local_dir: str = "data"
    local_filename: str | None = None


class JiraSettings(BaseModel):
    base_url: str | None = None
    email: str | None = None
    api_token: str | None = None
    project_key: str | None = None
    story_points_field: str | None = None


class QueueSettings(BaseModel):
    connection_string: str | None = None
    queue_name: str | None = None
    visibility_timeout: int = 300
    poll_interval_seconds: float = 2.0
    max_batch_size: int = 16


class AzureADSettings(BaseModel):
    tenant_id: str | None = None
    client_id: str | None = None
    audience: str | None = None
    issuer: str | None = None
    jwks_url: str | None = None
    jwks: str | None = None
    scopes: list[str] = []
    require_auth: bool = False

    @property
    def enabled(self) -> bool:
        return bool((self.tenant_id and self.client_id) or self.require_auth)


class AppConfig(BaseModel):
    profile: str = "prod"
    blob_storage: BlobStorageSettings = BlobStorageSettings()
    azure_speech: AzureSpeechSettings = AzureSpeechSettings()
    llm: LLMSettings = LLMSettings()
    database: DatabaseSettings = DatabaseSettings()
    cosmos: CosmosSettings = CosmosSettings()
    mock_audio: MockAudioSettings = MockAudioSettings()
    jira: JiraSettings = JiraSettings()
    queue: QueueSettings = QueueSettings()
    azure_ad: AzureADSettings = AzureADSettings()

    @classmethod
    def load(cls) -> "AppConfig":
        profile = os.getenv("APP_PROFILE", "prod").lower()
        mock_enabled_env = os.getenv("ENABLE_MOCK_AUDIO")
        if mock_enabled_env is None:
            mock_enabled = profile == "dev"
        else:
            mock_enabled = mock_enabled_env.lower() in {"1", "true", "yes", "on"}
        return cls(
            profile=profile,
            blob_storage=BlobStorageSettings(
                container_name=os.getenv("AZURE_STORAGE_CONTAINER_NAME"),
                container_workers_name=os.getenv("AZURE_STORAGE_CONTAINER_WORKERS"),
                connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
            ),
            azure_speech=AzureSpeechSettings(
                key=os.getenv("AZURE_SPEECH_KEY"),
                region=os.getenv("AZURE_SPEECH_REGION"),
                language=os.getenv("AZURE_SPEECH_LANGUAGE", "en-US"),
                sample_rate=int(os.getenv("TRANSCRIBER_SAMPLE_RATE", "16000")),
            ),
            llm=LLMSettings(
                provider=os.getenv("LLM_PROVIDER", "azure").lower(),
                azure_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
                azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
            ),
            database=DatabaseSettings(
                url=os.getenv("DB_URL", "sqlite:///./app.db"),
                provider=os.getenv("DB_PROVIDER", "sqlite").lower(),
            ),
            cosmos=CosmosSettings(
                account_uri=os.getenv("COSMOS_ACCOUNT_URI"),
                key=os.getenv("COSMOS_KEY"),
                database=os.getenv("COSMOS_DB_NAME", "sprint-planning-copilot"),
                meetings_container=os.getenv("COSMOS_MEETINGS_CONTAINER", "meetings"),
                tasks_container=os.getenv("COSMOS_TASKS_CONTAINER", "tasks"),
                users_container=os.getenv("COSMOS_USERS_CONTAINER", "users"),
                runs_container=os.getenv("COSMOS_RUNS_CONTAINER", "extraction_runs"),
            ),
            mock_audio=MockAudioSettings(
                enabled=mock_enabled,
                blob_path=os.getenv("MOCK_AUDIO_BLOB_PATH", "mock/team_meeting.mp3"),
                local_dir=os.getenv("MOCK_AUDIO_LOCAL_DIR", "data"),
                local_filename=os.getenv("MOCK_AUDIO_LOCAL_FILENAME"),
            ),
            jira=JiraSettings(
                base_url=os.getenv("JIRA_BASE_URL"),
                email=os.getenv("JIRA_EMAIL"),
                api_token=os.getenv("JIRA_API_TOKEN"),
                project_key=os.getenv("JIRA_PROJECT_KEY"),
                story_points_field=os.getenv("JIRA_STORY_POINTS_FIELD"),
            ),
            queue=QueueSettings(
                connection_string=os.getenv("AZURE_STORAGE_QUEUE_CONNECTION_STRING",
                                            os.getenv("AZURE_STORAGE_CONNECTION_STRING")),
                queue_name=os.getenv("AZURE_STORAGE_QUEUE_NAME"),
                visibility_timeout=int(os.getenv("MEETING_QUEUE_VISIBILITY_TIMEOUT", "300")),
                poll_interval_seconds=float(os.getenv("MEETING_QUEUE_POLL_INTERVAL", "2.0")),
                max_batch_size=int(os.getenv("MEETING_QUEUE_MAX_BATCH", "16")),
            ),
            azure_ad=AzureADSettings(
                tenant_id=os.getenv("AZURE_AD_TENANT_ID"),
                client_id=os.getenv("AZURE_AD_CLIENT_ID"),
                audience=os.getenv("AZURE_AD_AUDIENCE"),
                issuer=os.getenv("AZURE_AD_ISSUER"),
                jwks_url=os.getenv("AZURE_AD_JWKS_URL"),
                jwks=os.getenv("AZURE_AD_JWKS"),
                scopes=[scope.strip() for scope in os.getenv("AZURE_AD_SCOPES", "").split(",") if scope.strip()],
                require_auth=os.getenv("AZURE_AD_REQUIRE_AUTH", "false").lower() in {"1", "true", "yes", "on"},
            ),
        )


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    return AppConfig.load()


# Backwards compatibility for modules importing get_config directly.
get_config = get_settings
