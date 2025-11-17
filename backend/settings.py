from __future__ import annotations

from functools import lru_cache
import os
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


class AppConfig(BaseModel):
    profile: str = "prod"
    blob_storage: BlobStorageSettings = BlobStorageSettings()
    azure_speech: AzureSpeechSettings = AzureSpeechSettings()
    llm: LLMSettings = LLMSettings()
    database: DatabaseSettings = DatabaseSettings()
    cosmos: CosmosSettings = CosmosSettings()
    mock_audio: MockAudioSettings = MockAudioSettings()
    jira: JiraSettings = JiraSettings()

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
        )


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    return AppConfig.load()


# Backwards compatibility for modules importing get_config directly.
get_config = get_settings
