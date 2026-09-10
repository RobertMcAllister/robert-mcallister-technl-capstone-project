"""Lambda: Segment Starter

Invoked by Step Function. Downloads transcript from S3, calls GPU /segment
to cut audio into training-ready clips respecting speaker boundaries.
"""

import json
import logging
import os
from urllib import request, error

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3", region_name="us-east-1")

_secrets = None


def _get_secrets():
    global _secrets
    if _secrets is None:
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        resp = sm.get_secret_value(SecretId=os.environ["SECRET_NAME"])
        _secrets = json.loads(resp["SecretString"])
        logger.info("Loaded GPU credentials from Secrets Manager")
    return _secrets


def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

    bucket = event["bucket"]
    cleaned_key = event["cleaned_key"]
    transcript_key = event["transcript_key"]
    speaker_segments = event["speaker_segments"]

    # Download transcript from S3
    resp = s3.get_object(Bucket=bucket, Key=transcript_key)
    transcript = json.loads(resp["Body"].read().decode("utf-8"))
    logger.info(f"Downloaded transcript: {transcript_key}")

    secrets = _get_secrets()
    url = f"{secrets['GPU_ENDPOINT']}/segment"
    payload = json.dumps({
        "bucket": bucket,
        "key": cleaned_key,
        "transcript": transcript,
        "speaker_segments": speaker_segments,
    }).encode("utf-8")

    req = request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "CF-Access-Client-Id": secrets["CF_ACCESS_CLIENT_ID"],
        "CF-Access-Client-Secret": secrets["CF_ACCESS_CLIENT_SECRET"],
        "User-Agent": "Robert-McAllister-SegmentLambda/1.0",
    }, method="POST")

    logger.info(f"Calling GPU: {url}")
    try:
        with request.urlopen(req, timeout=840) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"GPU returned {e.code}: {body[:1000]}")
        raise

    logger.info(f"Segmented: {len(result.get('segments', []))} clips")

    return {
        "bucket": bucket,
        "transcript_key": transcript_key,
        "file_id": result.get("file_id"),
        "segments": result["segments"],
    }
