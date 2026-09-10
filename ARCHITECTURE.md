# Architecture

## Pipeline Overview

```
  Client                 +-----------------------+
    |                    |   API Gateway          |
    | POST /upload       |   POST /upload         |
    | (x-api-key)        |   → Lambda #1          |
    +-------------------->   PresignedUrlGenerator |
    |                    |   Returns presigned URL |
    |                    +-----------+-------------+
    |                                |
    | PUT (presigned URL)            | (presigned S3 URL)
    +------------------------------->|
                         +-----------v-----------+
                         |   S3: raw-audio/raw/  |
                         |   (audio upload)      |
                         +-----------+-----------+
                                     |
                              S3 Event Trigger
                                     |
                         +-----------v-----------+
                         |   Lambda #0            |
                         |   Dispatcher           |
                         |   Starts Step Function |
                         +-----------+-----------+
                                     |
                    +----------------v-----------------+
                    |  Step Function:                   |
                    |  Robert-McAllister-               |
                    |  TranscriptionPipeline            |
                    |                                   |
                    |  +-----------------------------+  |
                    |  | State 1: CleanAudio         |  |
                    |  | Lambda: AudioCleaner        |  |
                    |  | POST → GPU /clean           |  |
                    |  | Demucs removes music/noise  |  |
                    |  | Uploads cleaned WAV to S3   |  |
                    |  +-------------+---------------+  |
                    |                |                   |
                    |  +-------------v---------------+  |
                    |  | State 2: Transcribe         |  |
                    |  | Lambda: TranscribeStarter   |  |
                    |  | POST → GPU /transcribe      |  |
                    |  | Whisper on cleaned audio    |  |
                    |  | Write JSON to S3 transcripts|  |
                    |  +-------------+---------------+  |
                    |                |                   |
                    |  +-------------v---------------+  |
                    |  | State 3: Process            |  |
                    |  | Lambda: TranscriptProcessor |  |
                    |  | Parse transcript JSON       |  |
                    |  | Write JSONL to processed    |  |
                    |  +-----------------------------+  |
                    +-----------------------------------+
                                     |
                         +-----------v-----------+
                         |  S3: processed/        |
                         |  transcripts/*.jsonl   |
                         |  (Athena-queryable)    |
                         +-----------+-----------+
                                     |
                         +-----------v-----------+
                         |  Athena                |
                         |  SQL queries over JSONL|
                         +------------------------+
```

## Cloudflare Tunnel Setup

This is the critical path that connects AWS Lambda to the local GPU.

### Network Topology

```
AWS Lambda (us-east-1)
    |
    | HTTPS POST with CF Access headers
    v
Cloudflare Edge (anycast)
    |
    | Cloudflare Tunnel (encrypted)
    v
NAS (192.168.0.x) — runs cloudflared container
    |
    | HTTP forward (local network)
    v
AIDevRig (192.168.0.x:9129) — runs FastAPI + Whisper
```

### Cloudflare Configuration

- **Tunnel name:** islandHermitTunnel
- **Subdomain:** capstone-local-gpu
- **Domain:** islandhermit.com
- **Full hostname:** capstone-local-gpu.islandhermit.com
- **Service type:** HTTP
- **Service URL:** 192.168.0.x:9129
- **Path matching:** `*` (all paths)

### Cloudflare Access (Authentication)

Cloudflare Access protects the tunnel endpoint. All requests must include a service token.

**Headers required on every request:**
```
CF-Access-Client-Id: <service token ID>
CF-Access-Client-Secret: <service token secret>
User-Agent: <any non-default value>
```

The `User-Agent` header is critical — Cloudflare error 1010 blocks Python's default `urllib` user-agent. Lambda #2 sets it to `Robert-McAllister-TranscribeLambda/1.0`.

Service token credentials are stored as Lambda #2 environment variables:
- `CF_ACCESS_CLIENT_ID`
- `CF_ACCESS_CLIENT_SECRET`

### Machines Involved

| Machine | IP | Role |
|---------|-----|------|
| AIDevRig | 192.168.0.x | Runs FastAPI transcription service on port 9129, has RTX 5090 GPU |
| NAS | 192.168.0.x | Runs cloudflared tunnel container, forwards to AIDevRig |

### Starting the GPU Service

```bash
# On AIDevRig:
cd "/home/robert/repos/Capstone Project"
bash services/transcription/run.sh
```

This starts uvicorn on `0.0.0.0:9129` using the lana pipeline's Python venv. The Whisper medium model loads on startup (~30s first time, downloads if not cached).

### Verifying the Chain

```bash
# 1. Local service health
curl http://localhost:9129/health

# 2. Through tunnel (from any machine)
curl -H "CF-Access-Client-Id: $CF_ID" \
     -H "CF-Access-Client-Secret: $CF_SECRET" \
     https://capstone-local-gpu.islandhermit.com/health

# 3. Test transcription locally
curl -X POST http://localhost:9129/transcribe \
  -H "Content-Type: application/json" \
  -d '{"bucket":"robert-mcallister-raw-audio","key":"raw/BigA_Sample_1min.webm"}'
```

## GPU Service Endpoints

### Endpoint: POST /clean

**Request:**
```json
{
  "bucket": "robert-mcallister-raw-audio",
  "key": "raw/BigA_Sample_1min.webm"
}
```

**Response:**
```json
{
  "cleaned_bucket": "robert-mcallister-raw-audio",
  "cleaned_key": "cleaned/BigA_Sample_1min.wav",
  "original_key": "raw/BigA_Sample_1min.webm",
  "duration_seconds": 59.84
}
```

Processing: Downloads audio from S3 → Demucs htdemucs removes music/background → peak normalization to -3dB → uploads cleaned WAV back to S3 `cleaned/` prefix.

### Endpoint: POST /transcribe

**Request:**
```json
{
  "bucket": "robert-mcallister-raw-audio",
  "key": "raw/BigA_Sample_1min.webm"
}
```

**Response:** Transcribe-compatible JSON:
```json
{
  "jobName": "local-whisper-BigA_Sample_1min",
  "accountId": "local",
  "status": "COMPLETED",
  "results": {
    "transcripts": [{"transcript": "full text..."}],
    "items": [
      {
        "type": "pronunciation",
        "alternatives": [{"confidence": "0.9907", "content": "think"}],
        "start_time": "0.16",
        "end_time": "0.34"
      }
    ],
    "language_code": "en-US"
  }
}
```

This format matches AWS Transcribe output so Lambda #3 can parse either source without changes.

### Endpoint: POST /diarize

**Request:** `{"bucket": "...", "key": "cleaned/BigA_Sample_1min.wav"}`

**Response:**
```json
{
  "speakers": ["SPEAKER_00", "SPEAKER_01"],
  "segments": [
    {"speaker": "SPEAKER_01", "start": 0.03, "end": 7.03},
    {"speaker": "SPEAKER_00", "start": 15.22, "end": 17.40}
  ]
}
```

### Endpoint: POST /segment

**Request:** `{"bucket": "...", "key": "cleaned/...", "transcript": {...}, "speaker_segments": [...]}`

**Response:**
```json
{
  "file_id": "BigA_Sample_1min",
  "segments": [
    {
      "segment_id": "5cd88e83_00000",
      "s3_key": "training-segments/BigA_Sample_1min/5cd88e83_00000.wav",
      "start": 0.031, "end": 7.28, "duration": 7.249,
      "text": "I think there's a how money works...",
      "speaker": "SPEAKER_01",
      "word_count": 25, "avg_word_confidence": 0.9221
    }
  ]
}
```

Cuts audio into 5-15s training clips at natural boundaries (sentence ends, pauses), constrained to speaker turns. Uploads WAV segments to `s3://processed/training-segments/{file_id}/`.

### Endpoint: POST /classify-emotions

**Request:** `{"bucket": "...", "segments": [{"segment_id": "...", "s3_key": "...", "text": "..."}]}`

**Response:**
```json
{
  "segments": [
    {
      "segment_id": "5cd88e83_00000",
      "emotion": "neutral",
      "emotion_confidence": 0.76,
      "text_emotion": "neutral",
      "audio_emotion": "neutral"
    }
  ]
}
```

Dual-signal classification: ModernBERT (28 GoEmotions on text, 40% weight) + emotion2vec (9 emotions on audio, 60% weight). Merged to 8 TTS tags: happy, sad, angry, fearful, surprised, excited, disgusted, neutral.

### Model Configuration

| Model | Library | VRAM | Loaded |
|-------|---------|------|--------|
| Whisper medium | faster-whisper 1.2.1 (CTranslate2) | ~5.5GB | At startup |
| Demucs htdemucs | demucs (hybrid transformer) | ~4GB | Lazy (first /clean call) |

- **Device:** CUDA (RTX 5090, 32GB VRAM) — both models fit simultaneously
- **Compute type:** float16
- **Whisper features:** word_timestamps=True, vad_filter=True, language="en"
- **Venv:** `/home/robert/repos/lana/voice-training-dataset-pipeline/venv`

Note: The lana venv has stale shebangs (scripts point to old path). Always use `$VENV/bin/python -m <module>` instead of `$VENV/bin/<command>` directly.

## Lambda Functions

### Lambda — AudioCleaner

- **Name:** Robert-McAllister-AudioCleaner
- **Trigger:** Step Function (State 1: CleanAudio)
- **Input:** `{"bucket": "...", "key": "raw/file.webm"}`
- **Action:** POST to GPU /clean endpoint, Demucs processes audio, GPU service uploads cleaned WAV to S3
- **Output:** `{"bucket": "...", "key": "cleaned/file.wav", "original_key": "raw/file.webm"}`
- **Timeout:** 900s (15 min) | **Memory:** 256MB
- **Env vars:** `SECRET_NAME` (reads credentials from Secrets Manager)

### Lambda #1 — PresignedUrlGenerator

- **Name:** Robert-McAllister-PresignedUrlGenerator
- **Trigger:** API Gateway POST /upload
- **Input:** `{"filename": "file.webm", "content_type": "audio/webm"}`
- **Action:** Generates presigned S3 PUT URL for direct upload to `raw/` prefix
- **Output:** `{"upload_url": "https://s3...", "key": "raw/file.webm", "expires_in": 300}`
- **Timeout:** 10s | **Memory:** 128MB

### Lambda #0 — Dispatcher

- **Name:** Robert-McAllister-Dispatcher
- **Trigger:** S3 event on `robert-mcallister-raw-audio`, prefix `raw/`
- **Action:** Starts Step Function execution with `{bucket, key}`
- **Timeout:** 30s | **Memory:** 128MB
- **Env vars:** `STATE_MACHINE_ARN`

### Lambda #2 — TranscribeStarter

- **Name:** Robert-McAllister-TranscribeStarter
- **Trigger:** Step Function (State 2: Transcribe)
- **Input:** `{"bucket": "...", "key": "cleaned/file.wav"}` (from AudioCleaner output)
- **Action:** POST to GPU endpoint, write returned JSON to `s3://raw-audio/transcripts/{stem}.json`
- **Output:** `{"bucket": "...", "transcript_key": "transcripts/{stem}.json"}`
- **Timeout:** 900s (15 min) | **Memory:** 256MB
- **Env vars:** `SECRET_NAME` (reads credentials from Secrets Manager)

### Lambda — DiarizeStarter

- **Name:** Robert-McAllister-DiarizeStarter
- **Trigger:** Step Function (State 3: Diarize)
- **Input:** `{"bucket": "...", "cleaned_key": "...", "transcript_key": "..."}`
- **Action:** POST to GPU /diarize endpoint, returns speaker segments
- **Output:** `{"bucket": "...", "cleaned_key": "...", "transcript_key": "...", "speaker_segments": [...]}`
- **Timeout:** 900s (15 min) | **Memory:** 256MB
- **Env vars:** `SECRET_NAME`

### Lambda — SegmentStarter

- **Name:** Robert-McAllister-SegmentStarter
- **Trigger:** Step Function (State 4: Segment)
- **Input:** Previous state output (cleaned_key, transcript_key, speaker_segments)
- **Action:** Downloads transcript from S3, POST to GPU /segment, which cuts audio and uploads segments to S3
- **Output:** `{"bucket": "...", "transcript_key": "...", "file_id": "...", "segments": [...]}`
- **Timeout:** 900s (15 min) | **Memory:** 256MB
- **Env vars:** `SECRET_NAME`

### Lambda — EmotionClassifier

- **Name:** Robert-McAllister-EmotionClassifier
- **Trigger:** Step Function (State 5: ClassifyEmotions)
- **Input:** Previous state output (segments list with s3_key + text)
- **Action:** POST to GPU /classify-emotions, writes segment metadata JSONL to S3
- **Output:** `{"bucket": "...", "transcript_key": "...", "segments_metadata_key": "segment-metadata/{file_id}.jsonl"}`
- **Timeout:** 900s (15 min) | **Memory:** 256MB
- **Env vars:** `SECRET_NAME`

### Lambda — TranscriptProcessor

- **Name:** Robert-McAllister-TranscriptProcessor
- **Trigger:** Step Function (State 2)
- **Input:** `{"bucket": "...", "transcript_key": "transcripts/..."}` (also accepts S3 event format)
- **Action:** Download transcript JSON, parse words/speakers/metrics, write JSONL to processed bucket
- **Output:** `{"statusCode": 200, "files_processed": 1, "total_words": 198}`
- **Timeout:** 60s | **Memory:** 256MB
- **Handles two JSON formats:**
  - Transcribe-compatible (from local Whisper or future AWS Transcribe)
  - Whisper-native (raw faster-whisper output, if someone uploads directly)

## IAM Roles

### Robert-McAllister-LambdaTranscriptionRole
Used by all Lambdas. Permissions:
- CloudWatch Logs (create/write)
- S3 read on raw-audio bucket
- S3 write on raw-audio/raw/*, transcripts/*, cleaned/* and processed/*
- Transcribe (StartTranscriptionJob, GetTranscriptionJob) — for future use
- SQS on Robert-McAllister-*
- Step Functions StartExecution on Robert-McAllister-*
- Secrets Manager GetSecretValue on Robert-McAllister-*

### Robert-McAllister-StepFunctionRole
Used by Step Function. Permissions:
- lambda:InvokeFunction on AudioCleaner, TranscribeStarter, DiarizeStarter, SegmentStarter, EmotionClassifier, and TranscriptProcessor

## S3 Event Notifications

Only one notification configured on `robert-mcallister-raw-audio`:
- Prefix `raw/` → invokes Lambda #0 (Dispatcher)

No `transcripts/` trigger — Step Function handles the Lambda #2 → #3 chain directly. Having both would cause Lambda #3 to run twice.

## Athena Analytics Layer

Athena queries the processed JSONL directly from S3 — no database server needed.

- **Database:** `robert_mcallister_capstone`
- **Table:** `transcripts` — external table using JSON SerDe
- **Data location:** `s3://robert-mcallister-processed/transcripts/`
- **Query results:** `s3://robert-mcallister-processed/athena-results/`

### Table Schema
Supports nested arrays for word-level and speaker-level data:
- `words` — `ARRAY<STRUCT<word, start_time, end_time, confidence>>`
- `segments` — `ARRAY<STRUCT<speaker, start_time, end_time, text>>`

Queries use `CROSS JOIN UNNEST()` to flatten these arrays for analysis (e.g., finding low-confidence words, speaker duration breakdowns).

**Table: `training_segments`** over `s3://robert-mcallister-processed/segment-metadata/`

Stores per-segment metadata with speaker labels and dual-signal emotion classification. Each row is one 5-15s training clip.

### Demo Queries (saved in `athena/queries/`)
1. File overview — word count and duration per file
2. Average word confidence — transcription quality metric
3. Low-confidence words — potential transcription errors (confidence < 0.5)
4. Speaker breakdown — who spoke, how long, what they said
5. Segments per speaker — count, total duration, avg confidence
6. Emotion distribution — emotion counts and avg confidence across segments
7. Training-ready segments — high confidence, good duration, with emotion labels

## API Gateway

Provides a REST endpoint for uploading audio files without needing AWS CLI credentials.

- **API ID:** `<YOUR_API_ID>`
- **URL:** `https://<YOUR_API_ID>.execute-api.us-east-1.amazonaws.com/prod/upload`
- **Auth:** API key required (`x-api-key` header)
- **Rate limit:** 2 requests/second, burst 5

### Upload Flow
```
1. POST /upload {"filename": "file.webm"} → returns presigned S3 URL
2. PUT file to presigned URL → lands in s3://raw-audio/raw/
3. S3 event triggers pipeline automatically
```

Audio files never pass through API Gateway (10MB limit). Only the small JSON request/response goes through. The presigned URL lets the client upload directly to S3 with no size limit.

## Secrets Manager

GPU endpoint credentials (Cloudflare Access service token) are stored in AWS Secrets Manager instead of Lambda environment variables.

- **Secret name:** `Robert-McAllister-GPU-Credentials`
- **Contents:** `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`, `GPU_ENDPOINT`
- **Used by:** AudioCleaner + TranscribeStarter Lambdas
- **Caching:** Secret is fetched once at Lambda cold start and cached in memory

Lambdas reference the secret via `SECRET_NAME` env var. Values are set by Robert (rotated keys not stored in code or Terraform).

## Infrastructure as Code

All AWS infrastructure is defined in `terraform/`. This is the machine-readable source of truth.

```bash
cd terraform/
terraform plan    # Preview what would change
terraform apply   # Apply changes
```

Key files:
- `lambda.tf` — All Lambda functions
- `apigateway.tf` — API Gateway, API key, usage plan
- `iam.tf` — IAM roles + policies
- `secrets.tf` — Secrets Manager
- `stepfunctions.tf` — State machine definition
- `s3.tf` — Buckets + event notifications
- `glue.tf` — Athena database + table
- `outputs.tf` — All resource ARNs

## Why Not AWS Transcribe

AWS Transcribe throws `SubscriptionRequiredException` — the AWS account is new and AI services haven't activated yet (can take up to 24 hours). AWS Comprehend has the same issue. Core infrastructure services (S3, Lambda, SQS, Athena, Step Functions) all work fine.

The local Whisper approach is arguably better for the demo:
- Shows custom AI integration (not just calling a managed service)
- Demonstrates Cloudflare tunnel for hybrid cloud/local architecture
- Uses Step Functions orchestration (another AWS service on the rubric)
- Can swap to Transcribe later by updating Lambda #2 (same output format)
