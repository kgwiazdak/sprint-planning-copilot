from __future__ import annotations

from functools import lru_cache
import os
from pydantic import BaseModel


class BlobStorageSettings(BaseModel):
    container_name: str | None = None
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


class AppConfig(BaseModel):
    blob_storage: BlobStorageSettings = BlobStorageSettings()
    azure_speech: AzureSpeechSettings = AzureSpeechSettings()
    llm: LLMSettings = LLMSettings()
    database: DatabaseSettings = DatabaseSettings()

    @classmethod
    def load(cls) -> "AppConfig":
        return cls(
            blob_storage=BlobStorageSettings(
                container_name=os.getenv("AZURE_STORAGE_CONTAINER_NAME"),
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
            ),
        )


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    return AppConfig.load()


# Backwards compatibility for modules importing get_config directly.
get_config = get_settings
