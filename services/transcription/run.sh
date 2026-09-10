#!/bin/bash
# Start the local GPU transcription service.
# Listens on 0.0.0.0:9129 for requests from AWS Lambda via Cloudflare tunnel.
#
# Dependencies (install into your venv):
#   pip install fastapi uvicorn boto3 faster-whisper demucs pyannote.audio \
#               transformers funasr torch torchaudio pydub
#
# Requires: CUDA-capable GPU, HF_TOKEN env var (for pyannote model access)

VENV="${VENV:-./venv}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

exec "$VENV/bin/python" -m uvicorn app:app \
    --host 0.0.0.0 \
    --port 9129 \
    --app-dir "$SCRIPT_DIR" \
    --log-level info
