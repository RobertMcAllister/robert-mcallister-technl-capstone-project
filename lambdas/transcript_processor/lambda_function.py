"""Lambda #3: Transcript Processor

Invoked by Step Function (or S3 event as fallback).
Parses transcript JSON, extracts words with timestamps/confidence,
extracts speaker segments, computes metrics, writes JSONL to processed bucket.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3", region_name="us-east-1")

PROCESSED_BUCKET = "robert-mcallister-processed"


def lambda_handler(event, context):
    """Handle Step Function input or S3 event."""
    logger.info(f"Received event: {json.dumps(event)}")

    # Determine input format
    if "transcript_key" in event:
        # Step Function input from Lambda #2
        bucket = event["bucket"]
        key = event["transcript_key"]
        entries = [(bucket, key)]
    elif "Records" in event:
        # S3 event (fallback)
        entries = []
        for record in event["Records"]:
            b = record["s3"]["bucket"]["name"]
            k = record["s3"]["object"]["key"]
            if k.startswith("transcripts/"):
                entries.append((b, k))
    else:
        logger.error(f"Unknown event format: {list(event.keys())}")
        raise ValueError("Expected Step Function input or S3 event")

    results = []
    for bucket, key in entries:
        logger.info(f"Processing transcript: s3://{bucket}/{key}")

        response = s3.get_object(Bucket=bucket, Key=key)
        transcript_data = json.loads(response["Body"].read().decode("utf-8"))

        result = parse_transcribe_output(transcript_data, key)

        filename_stem = os.path.splitext(key.split("/")[-1])[0]
        output_key = f"transcripts/{filename_stem}.jsonl"

        s3.put_object(
            Bucket=PROCESSED_BUCKET,
            Key=output_key,
            Body=json.dumps(result) + "\n",
            ContentType="application/json",
        )

        logger.info(f"Wrote processed output: s3://{PROCESSED_BUCKET}/{output_key}")
        logger.info(
            f"Stats: {result['word_count']} words, "
            f"{result['duration_seconds']:.1f}s, "
            f"{len(result['segments'])} speaker segments"
        )
        results.append(result)

    return {
        "statusCode": 200,
        "files_processed": len(results),
        "total_words": sum(r["word_count"] for r in results),
    }


def detect_format(data):
    """Detect whether JSON is AWS Transcribe format or Whisper-native format.

    AWS Transcribe: has results.items[] with type/alternatives structure
    Whisper-native: has words[] with text/start/end/confidence directly
    """
    if "results" in data and "items" in data.get("results", {}):
        return "transcribe"
    if "words" in data and isinstance(data["words"], list):
        if data["words"] and "text" in data["words"][0]:
            return "whisper"
    return "transcribe"  # default — Transcribe-compatible (local script output)


def parse_transcribe_output(data, source_key):
    """Parse transcript JSON into structured output.

    Handles two formats:
    1. AWS Transcribe / Transcribe-compatible (from local_transcribe.py)
    2. Whisper-native (raw faster-whisper output with words[].text/start/end/confidence)
    """
    fmt = detect_format(data)
    logger.info(f"Detected transcript format: {fmt}")

    if fmt == "whisper":
        return _parse_whisper_native(data, source_key)
    return _parse_transcribe_format(data, source_key)


def _parse_transcribe_format(data, source_key):
    """Parse AWS Transcribe JSON (also handles local Whisper in Transcribe format)."""
    results = data.get("results", {})

    # Full transcript text
    transcript_text = ""
    transcripts = results.get("transcripts", [])
    if transcripts:
        transcript_text = transcripts[0].get("transcript", "")

    # Word-level data (pronunciation items only)
    words = []
    all_items = results.get("items", [])
    for item in all_items:
        if item.get("type") != "pronunciation":
            continue

        alternatives = item.get("alternatives", [])
        if not alternatives:
            continue

        words.append({
            "word": alternatives[0].get("content", ""),
            "start_time": float(item.get("start_time", "0.0")),
            "end_time": float(item.get("end_time", "0.0")),
            "confidence": float(alternatives[0].get("confidence", "0.0")),
        })

    # Speaker segments (may not exist for local Whisper output)
    segments = []
    speaker_labels = results.get("speaker_labels", {})
    for seg in speaker_labels.get("segments", []):
        speaker = seg.get("speaker_label", "unknown")
        start_time = float(seg.get("start_time", "0.0"))
        end_time = float(seg.get("end_time", "0.0"))

        # Build text by matching segment items to main items by timing
        seg_word_texts = []
        for seg_item in seg.get("items", []):
            si_start = seg_item.get("start_time", "")
            si_end = seg_item.get("end_time", "")
            for main_item in all_items:
                if (main_item.get("start_time") == si_start
                        and main_item.get("end_time") == si_end
                        and main_item.get("type") == "pronunciation"):
                    alts = main_item.get("alternatives", [])
                    if alts:
                        seg_word_texts.append(alts[0].get("content", ""))
                    break

        segments.append({
            "speaker": speaker,
            "start_time": start_time,
            "end_time": end_time,
            "text": " ".join(seg_word_texts),
        })

    # If no speaker segments, create a single segment from all words
    if not segments and words:
        segments.append({
            "speaker": "spk_0",
            "start_time": words[0]["start_time"],
            "end_time": words[-1]["end_time"],
            "text": transcript_text,
        })

    return _build_result(words, segments, transcript_text, data, source_key)


def _parse_whisper_native(data, source_key):
    """Parse raw faster-whisper JSON output (words[].text/start/end/confidence)."""
    raw_words = data.get("words", [])

    words = []
    word_texts = []
    for w in raw_words:
        words.append({
            "word": w["text"],
            "start_time": float(w["start"]),
            "end_time": float(w["end"]),
            "confidence": float(w["confidence"]),
        })
        word_texts.append(w["text"])

    transcript_text = " ".join(word_texts)

    # No speaker info in Whisper output — create single segment
    segments = []
    if words:
        segments.append({
            "speaker": "spk_0",
            "start_time": words[0]["start_time"],
            "end_time": words[-1]["end_time"],
            "text": transcript_text,
        })

    return _build_result(words, segments, transcript_text, data, source_key)


def _build_result(words, segments, transcript_text, data, source_key):
    """Build the final output dict from parsed components."""
    duration_seconds = 0.0
    if words:
        duration_seconds = max(w["end_time"] for w in words)
    elif segments:
        duration_seconds = max(s["end_time"] for s in segments)

    filename = source_key.split("/")[-1]
    filename_stem = os.path.splitext(filename)[0]

    # Try to get language from either format
    language_code = (
        data.get("results", {}).get("language_code")
        or data.get("language")
        or "en-US"
    )

    return {
        "file_id": filename_stem,
        "source_file": f"{filename_stem}.webm",
        "transcript_text": transcript_text,
        "word_count": len(words),
        "duration_seconds": round(duration_seconds, 2),
        "language_code": language_code,
        "words": words,
        "segments": segments,
        "processed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
