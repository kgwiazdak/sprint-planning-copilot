from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from backend.application.use_cases.extract_meeting import ExtractMeetingUseCase, ExtractionError
from backend.presentation.http.dependencies import extraction_workflow
from backend.schemas import ExtractionResult

router = APIRouter(tags=["extraction"])


@router.post("/extract", response_model=ExtractionResult)
async def extract_endpoint(
    file: UploadFile = File(...),
    workflow: ExtractMeetingUseCase = Depends(extraction_workflow),
):
    try:
        result = await workflow(file)
    except ExtractionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return JSONResponse(content=result.dict())
