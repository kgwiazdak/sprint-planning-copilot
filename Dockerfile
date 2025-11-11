FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends libasound2 ca-certificates ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements.txt
RUN python -m pip install --upgrade pip \
 && pip install -r requirements.txt

COPY backend backend
COPY data data

EXPOSE 8000
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
