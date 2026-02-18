from __future__ import annotations

import asyncio
import datetime
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from backend import audit
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
from backend.application.services.rag_estimator import RAGEstimator, write_stats


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
            rag_estimator: RAGEstimator | None = None,
            audio_extensions: tuple[str, ...] | None = None,
    ) -> None:
        self._blob_storage = blob_storage
        self._transcription = transcription
        self._extractor = extractor
        self._meetings_repo = meetings_repo
        self._telemetry = telemetry
        self._rag = rag_estimator
        self._worker_actor = os.getenv("MEETING_WORKER_ACTOR", "meeting-worker")
        self._last_extraction_metrics: dict = {}
        self._last_rag_stats: dict = {}
        self._last_diarization_payload: dict = {}
        if audio_extensions is not None:
            self._audio_extensions = audio_extensions
        elif transcription is not None:
            self._audio_extensions = tuple(transcription.SUPPORTED_AUDIO_EXTENSIONS)
        else:
            self._audio_extensions = tuple()

    async def process_job(self, job: MeetingImportJob) -> None:
        token = audit.bind_actor(f"{self._worker_actor}:{job.meeting_id}")
        try:
            await self(
                title=job.title,
                started_at=job.started_at,
                blob_url=job.blob_url,
                project_key=getattr(job, "project_key", None),
                original_filename=job.original_filename,
                meeting_id=job.meeting_id,
                owner_id=job.owner_id,
                atlassian_access_token=getattr(job, "atlassian_access_token", None),
            )
        finally:
            audit.reset_actor(token)

    async def __call__(
            self,
            *,
            title: str,
            started_at: str,
            blob_url: str,
            original_filename: str | None = None,
            meeting_id: str | None = None,
            owner_id: str | None = None,
            project_key: str | None = None,
            atlassian_access_token: str | None = None,
    ) -> ExtractionResult:
        self._last_extraction_metrics = {}
        self._last_rag_stats = {}
        effective_owner = owner_id or None
        context_meeting_id = meeting_id or str(uuid.uuid4())
        if context_meeting_id:
            self._meetings_repo.update_meeting_status(
                context_meeting_id, MeetingStatus.PROCESSING.value, owner_id=effective_owner
            )

        try:
            if not blob_url:
                raise ExtractionError("blob_url is required.", status_code=400)
            if not self._blob_storage:
                raise ExtractionError("Blob storage is not configured.", status_code=500)

            payload = await self._blob_storage.download_blob(blob_url)
            if not payload:
                raise ExtractionError("Referenced blob is empty.", status_code=400)

            context = IngestedFile(
                meeting_id=context_meeting_id,
                filename=original_filename or Path(blob_url).name or "uploaded_file",
                content_type=None,
                payload=payload,
                title=title,
                started_at=started_at,
                blob_url=blob_url,
            )

            transcript_blob_uri = await self._persist_original_file(context)
            transcript = await self._resolve_transcript(context, owner_id=effective_owner)
            result = await self._extract(transcript)
            result = await self._apply_rag(
                context,
                transcript,
                result,
                project_key=project_key,
                owner_id=effective_owner,
                atlassian_access_token=atlassian_access_token,
            )
            run_meeting_id, run_id = await self._store(
                context,
                transcript,
                result,
                owner_id=effective_owner,
                project_key=project_key,
            )
            await self._log(run_meeting_id, run_id, transcript, result, transcript_blob_uri)
        except ExtractionError:
            if context_meeting_id:
                self._meetings_repo.update_meeting_status(
                    context_meeting_id, MeetingStatus.FAILED.value, owner_id=effective_owner
                )
            raise
        except Exception as exc:
            if context_meeting_id:
                self._meetings_repo.update_meeting_status(
                    context_meeting_id, MeetingStatus.FAILED.value, owner_id=effective_owner
                )
            raise ExtractionError(f"Unexpected failure: {exc}", status_code=500) from exc
        else:
            if context_meeting_id:
                self._meetings_repo.update_meeting_status(
                    context_meeting_id, MeetingStatus.COMPLETED.value, owner_id=effective_owner
                )
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

    async def _resolve_transcript(self, ctx: IngestedFile, *, owner_id: str | None) -> str:
        # Reset diarization context for each resolve
        self._last_diarization_payload = {}
        name_lower = ctx.filename.lower()
        if name_lower.endswith((".txt", ".json")):
            return ctx.payload.decode("utf-8", errors="ignore")

        transcription = self._transcription
        audio_exts = self._audio_extensions
        if transcription and audio_exts and name_lower.endswith(audio_exts):
            try:
                transcription.set_owner(owner_id)
            except Exception:
                pass
            text = await asyncio.to_thread(transcription.transcribe, ctx.payload, name_lower)
            self._last_diarization_payload = self._build_diarization_payload(transcription, owner_id)
            return text
        if audio_exts and name_lower.endswith(audio_exts):
            raise ExtractionError("Transcription service is not configured.", status_code=500)

        raise ExtractionError("Unsupported file type. Upload .txt, .json, or supported audio.", status_code=400)

    async def _extract(self, transcript: str) -> ExtractionResult:
        start = asyncio.get_event_loop().time()
        try:
            result = await asyncio.to_thread(self._extractor.extract, transcript)
            end = asyncio.get_event_loop().time()
            timings = getattr(self._extractor, "last_timings", {}) or {}
            timings.setdefault("latency_ms_llm", (end - start) * 1000)
            self._last_extraction_metrics = timings
            return result
        except Exception as exc:  # pragma: no cover - defensive
            raise ExtractionError(f"Extraction failed: {exc}", status_code=500) from exc

    async def _apply_rag(
            self,
            ctx: IngestedFile,
            transcript: str,
            result: ExtractionResult,
            *,
            project_key: str | None,
            owner_id: str | None,
            atlassian_access_token: str | None,
    ) -> ExtractionResult:
        if not self._rag:
            return result
        history_tasks = []
        try:
            history_tasks = self._meetings_repo.list_tasks(status="approved", owner_id=owner_id or "")  # type: ignore[arg-type]
        except Exception:
            history_tasks = []
        try:
            updated, stats = await asyncio.to_thread(
                self._rag.enrich,
                transcript=transcript,
                result=result,
                history_tasks=history_tasks,
                meeting_id=ctx.meeting_id,
                project_key=project_key,
                owner_id=owner_id,
                confluence_access_token=atlassian_access_token,
            )
            self._last_rag_stats = stats
            try:
                stats_path = Path(os.getenv("RAG_STATS_PATH", "data/rag_stats.json"))
                write_stats({**stats, "meeting_id": ctx.meeting_id, "project_key": project_key}, stats_path)
            except Exception:
                pass
            return updated
        except Exception:
            # Never fail the pipeline due to RAG; log best-effort telemetry.
            self._last_rag_stats = {"error": "rag_failed"}
            return result

    async def _store(
            self,
            ctx: IngestedFile,
            transcript: str,
            result: ExtractionResult,
            *,
            owner_id: str | None,
            project_key: str | None,
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
                project_key=project_key,
                owner_id=owner_id,
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
                telemetry={
                    "extraction": self._last_extraction_metrics,
                    "rag": self._last_rag_stats,
                },
                diarization_payload=self._last_diarization_payload or {},
            )

        await asyncio.to_thread(_emit_telemetry)

    @staticmethod
    def _build_diarization_payload(transcription: TranscriptionPort, owner_id: str | None) -> dict:
        context = {}
        try:
            context = transcription.get_last_intro_context()  # type: ignore[attr-defined]
        except Exception:
            context = {}
        if not isinstance(context, dict):
            context = {}
        clips = context.get("clips")
        if not isinstance(clips, list):
            clips = []
        count = context.get("count")
        if not isinstance(count, int):
            count = len(clips)
        payload = {
            "owner_id": owner_id,
            "intros": clips,
            "intro_count": count,
        }
        return payload
