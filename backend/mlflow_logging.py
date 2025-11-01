import json
def log_extraction_run(meeting_id: str, run_id: str, transcript: str, result):
    try:
        import mlflow
        mlflow.set_experiment("ai-scrum-copilot-mvp")
        with mlflow.start_run(run_name=run_id):
            mlflow.log_param("meeting_id", meeting_id)
            mlflow.log_param("transcript_chars", len(transcript))
            mlflow.log_param("tasks_count", len(result.tasks))
            mlflow.log_text(transcript, "artifacts/transcript.txt")
            mlflow.log_text(json.dumps(result.dict(), ensure_ascii=False, indent=2), "artifacts/extraction.json")
    except Exception:
        return
