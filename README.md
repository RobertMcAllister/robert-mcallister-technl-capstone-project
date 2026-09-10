# Voice Transcription Pipeline — Capstone Project

AWS serverless pipeline that processes audio files through 5 AI models (Demucs, Whisper, pyannote, ModernBERT, emotion2vec), producing speaker-labeled training segments with emotion classification, queryable via Athena.

## How It Works

1. Upload audio via API Gateway (returns presigned S3 URL) or `aws s3 cp`
2. S3 event triggers a Step Function with 6 stages:
   - **Clean** — Demucs removes background music/noise
   - **Transcribe** — Whisper transcribes with word-level timestamps
   - **Diarize** — pyannote identifies speakers ("who spoke when")
   - **Segment** — Cuts audio into 5-15s training clips at natural boundaries
   - **Classify Emotions** — Dual-signal: ModernBERT (text) + emotion2vec (audio)
   - **Process** — Combines all results into structured JSONL
3. Query results with Athena SQL (7 demo queries)

5 AI models run locally on an RTX 5090, connected to AWS via Cloudflare tunnel.

## Quick Start

### Prerequisites
- AWS CLI configured (account <AWS_ACCOUNT_ID>, us-east-1)
- FastAPI GPU service running on AIDevRig
- Cloudflare tunnel active (islandHermitTunnel on NAS)
- GPU credentials set in Secrets Manager

### Start the GPU service
```bash
bash services/transcription/run.sh
```

### Upload via API Gateway
```bash
# Get presigned URL
curl -X POST https://<YOUR_API_ID>.execute-api.us-east-1.amazonaws.com/prod/upload \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_API_KEY" \
  -d '{"filename":"audio.webm"}'

# Upload file to returned URL
curl -X PUT "PRESIGNED_URL" -H "Content-Type: audio/webm" --data-binary @audio.webm
```

### Or upload directly via CLI
```bash
aws s3 cp audio.webm s3://robert-mcallister-raw-audio/raw/
```

### Monitor execution
```bash
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:<AWS_ACCOUNT_ID>:stateMachine:Robert-McAllister-TranscriptionPipeline \
  --max-results 5 --query "executions[*].[name,status]" --output table
```

### Check output
```bash
aws s3 cp s3://robert-mcallister-processed/transcripts/audio.jsonl - | python3 -m json.tool
```

## Project Structure

```
.
├── services/transcription/
│   ├── app.py                    # FastAPI service (Whisper + Demucs, CUDA)
│   └── run.sh                    # Start script (uses lana pipeline venv)
├── lambdas/
│   ├── presigned_url_generator/  # API Gateway → presigned S3 URL
│   ├── dispatcher/               # S3 → Step Function
│   ├── audio_cleaner/            # GPU /clean (Demucs)
│   ├── transcribe_starter/       # GPU /transcribe (Whisper)
│   ├── diarize_starter/          # GPU /diarize (pyannote)
│   ├── segment_starter/          # GPU /segment (boundary + cut)
│   ├── emotion_classifier/       # GPU /classify-emotions (ModernBERT + emotion2vec)
│   └── transcript_processor/     # Parse → JSONL
├── terraform/                    # Infrastructure as Code (source of truth)
├── step-function/
│   └── definition.json           # Step Function state machine
├── athena/
│   ├── create-database.sql
│   ├── create-table.sql
│   └── queries/                  # Demo queries (4 SQL files)
├── iam/                          # IAM policy JSON files
├── s3-notifications/             # S3 event notification config
├── ARCHITECTURE.md               # Detailed architecture + Cloudflare setup
├── DEMO-GUIDE.md                 # Demo recording checklist
└── CLAUDE.md                     # Claude Code context
```

## Infrastructure

Managed via Terraform (`terraform/`). See `terraform/outputs.tf` for all resource ARNs.

| Service | Resource | Purpose |
|---------|----------|---------|
| S3 | robert-mcallister-raw-audio | Raw audio, cleaned audio, transcript JSON |
| S3 | robert-mcallister-processed | Processed JSONL + Athena results |
| API Gateway | Robert-McAllister-UploadAPI | POST /upload (presigned URL, API key required) |
| Lambda x8 | Robert-McAllister-* | PresignedUrlGenerator, Dispatcher, AudioCleaner, TranscribeStarter, DiarizeStarter, SegmentStarter, EmotionClassifier, TranscriptProcessor |
| Step Functions | Robert-McAllister-TranscriptionPipeline | Orchestrates 6 states: Clean → Transcribe → Diarize → Segment → Emotions → Process |
| Secrets Manager | Robert-McAllister-GPU-Credentials | Cloudflare Access credentials |
| Glue/Athena | robert_mcallister_capstone | SQL analytics over processed data |

## Network

```
Client → API Gateway → Lambda (presigned URL) → S3
AWS Lambda → Cloudflare Edge → NAS (192.168.0.x) → AIDevRig (192.168.0.x:9129)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for Cloudflare tunnel details.

## Course

AI for Data Engineering (Cohort B) — Instructor: Ruben Chevez
