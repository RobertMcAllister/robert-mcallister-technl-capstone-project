# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AWS serverless pipeline for processing audio files through transcription and analytics. Built for the "AI for Data Engineering (Cohort B)" capstone. Instructor: Ruben Chevez. Due 2026-03-28 9AM Newfoundland time.

**Core flow:** Audio uploaded to S3 → Step Functions orchestrates 6 stages: Demucs cleaning → Whisper transcription → pyannote speaker diarization → boundary-based segmentation → dual-signal emotion classification → structured JSONL processing → Athena queries. All GPU calls go through a Cloudflare tunnel to a local RTX 5090.

## Architecture (What's Actually Built)

```
S3 upload (raw/) → Lambda #0 (Dispatcher)
  → Step Function: Robert-McAllister-TranscriptionPipeline
    → State 1: Lambda AudioCleaner
        POSTs {bucket, key} to local GPU /clean endpoint
        Demucs removes music/noise, normalizes volume
        Uploads cleaned WAV to S3 cleaned/
    → State 2: Lambda TranscribeStarter
        POSTs {bucket, key} to local GPU /transcribe endpoint
        Whisper medium transcribes cleaned audio
        Writes transcript JSON to S3 transcripts/
    → State 3: Lambda DiarizeStarter
        POSTs {bucket, key} to local GPU /diarize endpoint
        pyannote identifies speakers and their time segments
    → State 4: Lambda SegmentStarter
        POSTs to local GPU /segment endpoint
        Cuts audio into 5-15s training clips at natural boundaries
        Uploads WAV segments to S3 training-segments/{file_id}/
    → State 5: Lambda EmotionClassifier
        POSTs to local GPU /classify-emotions endpoint
        ModernBERT (text, 28 emotions) + emotion2vec (audio, 9 emotions)
        Merges with weighted strategy, writes segment metadata JSONL
    → State 6: Lambda TranscriptProcessor
        Reads transcript JSON from S3
        Parses words/speakers/metrics
        Writes JSONL to robert-mcallister-processed bucket
          → Athena queries over processed JSONL + segment metadata
```

**Why local GPU instead of AWS Transcribe:** New AWS account — Transcribe throws SubscriptionRequiredException (account-level activation delay). Local Whisper via Cloudflare tunnel is the working solution and satisfies the "AI integration" rubric item.

## AWS Account & Resources

- **Account ID:** <AWS_ACCOUNT_ID>
- **IAM user:** admin user with AdministratorAccess (name not recorded here)
- **Region:** us-east-1
- **Naming convention:** `Robert-McAllister-ResourceName`

### Deployed Resources
| Resource | Name | Purpose |
|----------|------|---------|
| S3 Bucket | `robert-mcallister-raw-audio` | Raw audio, cleaned audio, transcript JSON |
| S3 Bucket | `robert-mcallister-processed` | Processed JSONL output + Athena results |
| Lambda | `Robert-McAllister-Dispatcher` | S3 trigger → starts Step Function |
| Lambda | `Robert-McAllister-AudioCleaner` | Calls GPU /clean (Demucs), writes cleaned WAV to S3 |
| Lambda | `Robert-McAllister-TranscribeStarter` | Calls GPU /transcribe (Whisper), writes JSON to S3 |
| Lambda | `Robert-McAllister-DiarizeStarter` | Calls GPU /diarize (pyannote speaker ID) |
| Lambda | `Robert-McAllister-SegmentStarter` | Calls GPU /segment (cuts training clips) |
| Lambda | `Robert-McAllister-EmotionClassifier` | Calls GPU /classify-emotions (text+audio) |
| Lambda | `Robert-McAllister-TranscriptProcessor` | Parses transcript, writes JSONL |
| Lambda | `Robert-McAllister-PresignedUrlGenerator` | API Gateway → generates presigned S3 upload URLs |
| Step Function | `Robert-McAllister-TranscriptionPipeline` | Chains 6 states: Clean → Transcribe → Diarize → Segment → Emotions → Process |
| API Gateway | `Robert-McAllister-UploadAPI` | POST /upload endpoint (requires API key) |
| Secrets Manager | `Robert-McAllister-GPU-Credentials` | CF Access credentials for GPU endpoint |
| IAM Role | `Robert-McAllister-LambdaTranscriptionRole` | Shared Lambda execution role |
| IAM Role | `Robert-McAllister-StepFunctionRole` | Step Function execution role |
| Glue Database | `robert_mcallister_capstone` | Athena database |
| Glue Table | `robert_mcallister_capstone.transcripts` | External table over processed JSONL |
| Glue Table | `robert_mcallister_capstone.training_segments` | External table over segment metadata JSONL |

### Lambda Environment Variables (AudioCleaner + TranscribeStarter + DiarizeStarter + SegmentStarter + EmotionClassifier)
- `SECRET_NAME` = `Robert-McAllister-GPU-Credentials` (reads CF credentials from Secrets Manager at cold start)

### API Gateway
- **URL:** `https://<YOUR_API_ID>.execute-api.us-east-1.amazonaws.com/prod/upload`
- **Method:** POST (requires `x-api-key` header)
- **Rate limit:** 2 req/s, burst 5
- **Flow:** Returns presigned S3 PUT URL → client uploads directly to S3 (bypasses 10MB API Gateway limit)

## Cloudflare Tunnel Setup

See ARCHITECTURE.md for full details. Critical points:
- Tunnel name: `islandHermitTunnel`
- Tunnel runs on NAS (192.168.0.x), forwards to AIDevRig (192.168.0.x:9129)
- FastAPI service MUST listen on `0.0.0.0:9129` (not localhost)
- Cloudflare Access requires `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers
- Lambda also needs `User-Agent` header (Cloudflare error 1010 blocks Python urllib default)

## Local GPU Service

Located at `services/transcription/`. Uses the lana pipeline's venv.
```bash
bash services/transcription/run.sh   # Start the service
curl http://localhost:9129/health     # Verify it's running
```

- **Endpoints:** `/health`, `/clean`, `/transcribe`, `/diarize`, `/segment`, `/classify-emotions`
- **Venv:** `/home/robert/repos/lana/voice-training-dataset-pipeline/venv`
- **Dependencies added to lana venv:** `boto3` (installed via `python -m pip`)
- Stale shebangs in lana venv — always use `python -m` to run tools

### GPU Models (all cached in `~/.cache/huggingface/hub/`)

| Model | Library | HF Repo / Name | VRAM | Loaded |
|-------|---------|----------------|------|--------|
| Whisper medium | faster-whisper | `Systran/faster-whisper-medium` | ~5.5GB | At startup |
| Demucs htdemucs | demucs | `htdemucs` | ~4GB | Lazy (first /clean) |
| Speaker diarization | pyannote.audio | `pyannote/speaker-diarization-community-1` | ~2GB | Lazy (first /diarize) |
| Text emotion | transformers | `cirimus/modernbert-large-go-emotions` | ~400MB | Lazy (first /classify-emotions) |
| Audio emotion | funasr | `iic/emotion2vec_plus_large` | ~5GB | Lazy (first /classify-emotions) |

Total when all loaded: ~17GB. RTX 5090 has 32GB — fits comfortably.
Requires `HF_TOKEN` env var for pyannote model access.

## S3 Key Structure

| Bucket | Prefix | Contents |
|--------|--------|----------|
| `raw-audio` | `raw/` | Original uploaded audio files |
| `raw-audio` | `cleaned/` | Demucs-cleaned WAV files (vocals only, normalized) |
| `raw-audio` | `transcripts/` | Whisper transcript JSON (Transcribe-compatible format) |
| `processed` | `transcripts/` | Processed JSONL (Athena-queryable) |
| `processed` | `segment-metadata/` | Per-segment JSONL with speaker + emotion data |
| `processed` | `training-segments/{file_id}/` | Cut audio clips (5-15s WAV, speaker-separated) |
| `processed` | `athena-results/` | Athena query output |

## Processed Output Schema

```json
{
  "file_id": "BigA_Sample_1min",
  "source_file": "BigA_Sample_1min.webm",
  "transcript_text": "full text...",
  "word_count": 198,
  "duration_seconds": 59.84,
  "language_code": "en-US",
  "words": [{"word": "hello", "start_time": 0.5, "end_time": 0.8, "confidence": 0.99}],
  "segments": [{"speaker": "spk_0", "start_time": 0.0, "end_time": 59.84, "text": "..."}],
  "processed_at": "2026-03-28T04:30:00Z"
}
```

## Deploying Lambda Changes

```bash
cd lambdas/<function_dir>
zip lambda_function.zip lambda_function.py
aws lambda update-function-code --function-name Robert-McAllister-<FunctionName> --zip-file fileb://lambda_function.zip
```

## Testing End-to-End

1. Ensure FastAPI service is running: `bash services/transcription/run.sh`
2. Upload audio: `aws s3 cp file.webm s3://robert-mcallister-raw-audio/raw/`
3. Monitor: `aws stepfunctions list-executions --state-machine-arn arn:aws:states:us-east-1:<AWS_ACCOUNT_ID>:stateMachine:Robert-McAllister-TranscriptionPipeline`
4. Check output: `aws s3 cp s3://robert-mcallister-processed/transcripts/file.jsonl -`

## Cost Constraints

**DO NOT create:** EC2 instances, RDS databases, SageMaker endpoints, NAT gateways

Budget: $10/month guard with email alerts at $5 and $8.

## Athena

- **Database:** `robert_mcallister_capstone`
- **Table:** `transcripts` — external table over `s3://robert-mcallister-processed/transcripts/`
- **Table:** `training_segments` — external table over `s3://robert-mcallister-processed/segment-metadata/`
- **Queries saved in:** `athena/queries/` (01-file-overview, 02-avg-confidence, 03-low-confidence-words, 04-speaker-breakdown, 05-segments-per-speaker, 06-emotion-distribution, 07-training-ready)
- **Results bucket:** `s3://robert-mcallister-processed/athena-results/`

## Infrastructure as Code

All AWS infrastructure is defined in `terraform/`. This is the source of truth for what's deployed.

```bash
cd terraform/
terraform plan    # Preview changes
terraform apply   # Deploy changes
```

Before making AWS CLI changes, check the .tf files first. After any manual AWS changes, update the .tf files to stay in sync.

Key files: `lambda.tf` (all Lambdas), `apigateway.tf` (API Gateway + API key), `iam.tf` (roles + policies), `secrets.tf` (Secrets Manager), `stepfunctions.tf` (state machine), `outputs.tf` (all ARNs).

## Status

All pipeline stages complete and tested. 6-state Step Function, API Gateway, Secrets Manager, Athena.

Remaining optional:
- Presentation slides
- Terraform `terraform apply` to sync state (imports done, minor drift to resolve)

## Reference Codebase

`/home/robert/repos/lana/voice-training-dataset-pipeline/` — local GPU audio pipeline. Used as reference for Whisper model loading patterns. Code is standalone, not imported.
