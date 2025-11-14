from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

import anyio
from fastapi import UploadFile

from backend.domain.ports import (
    BlobStoragePort,
    ExtractionPort,
    MeetingsRepositoryPort,
    TelemetryPort,
    TranscriptionPort,
)
from backend.schemas import ExtractionResult


class ExtractionError(RuntimeError):
    """Raised when the extract workflow fails."""

    def __init__(self, message: str, *, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class IngestedFile:
    meeting_id: str
    filename: str
    content_type: str | None
    payload: bytes


class ExtractMeetingUseCase:
    """Coordinates ingestion, transcription, extraction, persistence and telemetry."""

    def __init__(
        self,
        *,
        blob_storage: BlobStoragePort | None,
        transcription: TranscriptionPort | None,
        extractor: ExtractionPort,
        meetings_repo: MeetingsRepositoryPort,
        telemetry: TelemetryPort | None,
        audio_extensions: tuple[str, ...] | None = None,
    ) -> None:
        self._blob_storage = blob_storage
        self._transcription = transcription
        self._extractor = extractor
        self._meetings_repo = meetings_repo
        self._telemetry = telemetry
        if audio_extensions is not None:
            self._audio_extensions = audio_extensions
        elif transcription is not None:
            self._audio_extensions = tuple(transcription.SUPPORTED_AUDIO_EXTENSIONS)
        else:
            self._audio_extensions = tuple()

    async def __call__(self, upload: UploadFile) -> ExtractionResult:
        if not (content := await upload.read()):
            raise ExtractionError("Uploaded file is empty.", status_code=400)

        context = IngestedFile(
            meeting_id=str(uuid.uuid4()),
            filename=upload.filename or "uploaded_file",
            content_type=upload.content_type,
            payload=content,
        )

        transcript_blob_uri = await self._persist_original_file(context)
        transcript = await self._resolve_transcript(context)
        result = await self._extract(transcript)
        meeting_id, run_id = await self._store(context, transcript, result)
        await self._log(meeting_id, run_id, transcript, result, transcript_blob_uri)
        return result

    async def _persist_original_file(self, ctx: IngestedFile) -> str | None:
        if not self._blob_storage:
            return None
        return await self._blob_storage.save_file(
            meeting_id=ctx.meeting_id,
            original_filename=ctx.filename,
            content=ctx.payload,
            content_type=ctx.content_type,
        )

    async def _resolve_transcript(self, ctx: IngestedFile) -> str:
        name_lower = ctx.filename.lower()
        if name_lower.endswith((".txt", ".json")):
            return ctx.payload.decode("utf-8", errors="ignore")

        transcription = self._transcription
        audio_exts = self._audio_extensions
        if transcription and audio_exts and name_lower.endswith(audio_exts):
            return await anyio.to_thread.run_sync(transcription.transcribe, ctx.payload, name_lower)
        if audio_exts and name_lower.endswith(audio_exts):
            raise ExtractionError("Transcription service is not configured.", status_code=500)

        raise ExtractionError("Unsupported file type. Upload .txt, .json, or supported audio.", status_code=400)

    async def _extract(self, transcript: str) -> ExtractionResult:
        try:
            return await anyio.to_thread.run_sync(self._extractor.extract, transcript)
        except Exception as exc:  # pragma: no cover - defensive
            raise ExtractionError(f"Extraction failed: {exc}", status_code=500) from exc

    async def _store(
        self,
        ctx: IngestedFile,
        transcript: str,
        result: ExtractionResult,
    ) -> tuple[str, str]:
        def _persist() -> tuple[str, str]:
            return self._meetings_repo.store_meeting_and_result(
                ctx.filename,
                transcript,
                result,
                meeting_id=ctx.meeting_id,
            )

        try:
            return await anyio.to_thread.run_sync(_persist)
        except Exception as exc:  # pragma: no cover - defensive
            raise ExtractionError(f"Failed to persist results: {exc}", status_code=500) from exc

    async def _log(
        self,
        meeting_id: str,
        run_id: str,
        transcript: str,
        result: ExtractionResult,
        transcript_blob_uri: str | None,
    ) -> None:
        if not self._telemetry:
            return

        def _emit_telemetry() -> None:
            meeting_date = datetime.datetime.utcnow().date().isoformat()
            self._telemetry.log_extraction_run(
                meeting_id=meeting_id,
                run_id=run_id,
                transcript=transcript,
                result=result,
                meeting_date=meeting_date,
                transcript_blob_uri=transcript_blob_uri,
            )

        await anyio.to_thread.run_sync(_emit_telemetry)
