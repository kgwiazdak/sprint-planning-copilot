from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from pathlib import Path

import asyncio

from backend.domain.entities import MeetingImportJob
from backend.domain.ports import (
    BlobStoragePort,
    ExtractionPort,
    MeetingsRepositoryPort,
    TelemetryPort,
    TranscriptionPort,
)
from backend.domain.status import MeetingStatus
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
    title: str | None = None
    started_at: str | None = None
    blob_url: str | None = None


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

    async def process_job(self, job: MeetingImportJob) -> None:
        await self(
            title=job.title,
            started_at=job.started_at,
            blob_url=job.blob_url,
            original_filename=job.original_filename,
            meeting_id=job.meeting_id,
        )

    async def __call__(
        self,
        *,
        title: str,
        started_at: str,
        blob_url: str,
        original_filename: str | None = None,
        meeting_id: str | None = None,
    ) -> ExtractionResult:
        if not blob_url:
            raise ExtractionError("blob_url is required.", status_code=400)
        if not self._blob_storage:
            raise ExtractionError("Blob storage is not configured.", status_code=500)

        payload = await self._blob_storage.download_blob(blob_url)
        if not payload:
            raise ExtractionError("Referenced blob is empty.", status_code=400)

        context = IngestedFile(
            meeting_id=meeting_id or str(uuid.uuid4()),
            filename=original_filename or Path(blob_url).name or "uploaded_file",
            content_type=None,
            payload=payload,
            title=title,
            started_at=started_at,
            blob_url=blob_url,
        )

        if context.meeting_id:
            self._meetings_repo.update_meeting_status(context.meeting_id, MeetingStatus.PROCESSING.value)

        try:
            transcript_blob_uri = await self._persist_original_file(context)
            transcript = await self._resolve_transcript(context)
            result = await self._extract(transcript)
            run_meeting_id, run_id = await self._store(context, transcript, result)
            await self._log(run_meeting_id, run_id, transcript, result, transcript_blob_uri)
        except ExtractionError:
            if context.meeting_id:
                self._meetings_repo.update_meeting_status(context.meeting_id, MeetingStatus.FAILED.value)
            raise
        except Exception as exc:
            if context.meeting_id:
                self._meetings_repo.update_meeting_status(context.meeting_id, MeetingStatus.FAILED.value)
            raise ExtractionError(f"Unexpected failure: {exc}", status_code=500) from exc
        else:
            if context.meeting_id:
                self._meetings_repo.update_meeting_status(context.meeting_id, MeetingStatus.COMPLETED.value)
            return result
    async def _persist_original_file(self, ctx: IngestedFile) -> str | None:
        if ctx.blob_url:
            return ctx.blob_url
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
            return await asyncio.to_thread(transcription.transcribe, ctx.payload, name_lower)
        if audio_exts and name_lower.endswith(audio_exts):
            raise ExtractionError("Transcription service is not configured.", status_code=500)

        raise ExtractionError("Unsupported file type. Upload .txt, .json, or supported audio.", status_code=400)

    async def _extract(self, transcript: str) -> ExtractionResult:
        try:
            return await asyncio.to_thread(self._extractor.extract, transcript)
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
                title=ctx.title,
                started_at=ctx.started_at,
                blob_url=ctx.blob_url,
            )

        try:
            return await asyncio.to_thread(_persist)
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

        await asyncio.to_thread(_emit_telemetry)
