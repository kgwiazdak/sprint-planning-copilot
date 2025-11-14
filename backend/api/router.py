from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from backend.api.dependencies import get_workflow
from backend.application.workflow import ExtractionWorkflow, WorkflowError
from backend.schemas import ExtractionResult

router = APIRouter(prefix="", tags=["extraction"])


@router.post("/extract", response_model=ExtractionResult)
async def extract_endpoint(
    file: UploadFile = File(...),
    workflow: ExtractionWorkflow = Depends(get_workflow),
):
    try:
        result = await workflow.run(file)
    except WorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return JSONResponse(content=result.dict())
