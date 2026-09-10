"""Lambda: Emotion Classifier

Invoked by Step Function. Calls GPU /classify-emotions in batches,
then writes enriched segment metadata to S3 as JSONL for Athena.
"""

import json
import logging
import os
from urllib import request, error

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3", region_name="us-east-1")

PROCESSED_BUCKET = "robert-mcallister-processed"
BATCH_SIZE = 20

_secrets = None


def _get_secrets():
    global _secrets
    if _secrets is None:
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        resp = sm.get_secret_value(SecretId=os.environ["SECRET_NAME"])
        _secrets = json.loads(resp["SecretString"])
        logger.info("Loaded GPU credentials from Secrets Manager")
    return _secrets


def _call_gpu(url, payload, secrets):
    """POST to GPU endpoint with CF tunnel headers."""
    req = request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "CF-Access-Client-Id": secrets["CF_ACCESS_CLIENT_ID"],
        "CF-Access-Client-Secret": secrets["CF_ACCESS_CLIENT_SECRET"],
        "User-Agent": "Robert-McAllister-EmotionLambda/1.0",
    }, method="POST")

    with request.urlopen(req, timeout=840) as resp:
        return json.loads(resp.read().decode("utf-8"))


def lambda_handler(event, context):
    logger.info(f"Received event keys: {list(event.keys())}")

    bucket = event["bucket"]
    transcript_key = event["transcript_key"]
    file_id = event.get("file_id", "unknown")
    segments = event["segments"]

    secrets = _get_secrets()
    url = f"{secrets['GPU_ENDPOINT']}/classify-emotions"

    # Process in batches
    all_emotion_results = {}
    total_batches = (len(segments) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(segments), BATCH_SIZE):
        batch = segments[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} segments)")

        try:
            payload = json.dumps({
                "bucket": PROCESSED_BUCKET,
                "segments": batch,
            }).encode("utf-8")
            result = _call_gpu(url, payload, secrets)
            for e in result.get("segments", []):
                all_emotion_results[e["segment_id"]] = e
        except (error.HTTPError, error.URLError) as e:
            logger.error(f"Batch {batch_num} failed: {e}")
            # Continue with remaining batches — failed segments get default "neutral"

    logger.info(f"Classified {len(all_emotion_results)}/{len(segments)} segments")

    # Merge emotion data into segment metadata
    enriched_segments = []
    for seg in segments:
        emo = all_emotion_results.get(seg["segment_id"], {})
        enriched = {
            "file_id": file_id,
            **seg,
            "emotion": emo.get("emotion", "neutral"),
            "emotion_confidence": emo.get("emotion_confidence", 0),
            "text_emotion": emo.get("text_emotion", "neutral"),
            "audio_emotion": emo.get("audio_emotion", "neutral"),
        }
        enriched_segments.append(enriched)

    # Write segment metadata JSONL to S3
    metadata_key = f"segment-metadata/{file_id}.jsonl"
    jsonl_body = "\n".join(json.dumps(s) for s in enriched_segments) + "\n"
    s3.put_object(
        Bucket=PROCESSED_BUCKET,
        Key=metadata_key,
        Body=jsonl_body,
        ContentType="application/json",
    )

    logger.info(f"Wrote {len(enriched_segments)} segments to s3://{PROCESSED_BUCKET}/{metadata_key}")

    return {
        "bucket": bucket,
        "transcript_key": transcript_key,
        "segments_metadata_key": metadata_key,
        "segment_count": len(enriched_segments),
    }
