import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from .schemas import ExtractionResult
from .stt import transcribe_audio_if_needed
from .extractor import Extractor
from .storage import store_meeting_and_result
from .mlflow_logging import log_extraction_run

app = FastAPI(title="AI Scrum Co-Pilot — MVP Extract API")

@app.post("/extract", response_model=ExtractionResult)
async def extract(file: UploadFile = File(...)):
    content = await get_content(file)
    transcript = await get_transcript(content, file.filename .lower())
    result = await get_result(transcript)
    await store_and_log(file, result, transcript)
    return JSONResponse(content=result.dict())


async def store_and_log(file, result, transcript):
    try:
        meeting_id, run_id = store_meeting_and_result(file.filename, transcript, result)
        log_extraction_run(meeting_id=meeting_id, run_id=run_id, transcript=transcript, result=result)
    except Exception:
        pass


async def get_result(transcript):
    try:
        extractor = Extractor()
        result = extractor.extract_tasks_llm(transcript)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")
    return result


async def get_content(file):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    return content


async def get_transcript(content, name_lower):
    if name_lower.endswith((".txt", ".json")):
        transcript = content.decode("utf-8", errors="ignore")
    elif name_lower.endswith((".mp3", ".wav", ".m4a", ".flac", ".ogg")):
        transcript = transcribe_audio_if_needed(content, filename=name_lower)
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    return transcript
