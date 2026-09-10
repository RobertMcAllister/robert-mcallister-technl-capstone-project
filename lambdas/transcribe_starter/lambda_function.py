"""Lambda #2: Transcribe via Local GPU

Invoked by Step Function. POSTs audio S3 location to local GPU endpoint
via Cloudflare tunnel, receives transcript JSON, writes to S3.
"""

import json
import logging
import os
from urllib import request, error

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3", region_name="us-east-1")

OUTPUT_BUCKET = "robert-mcallister-raw-audio"

# Cache secrets at cold start
_secrets = None


def _get_secrets():
    global _secrets
    if _secrets is None:
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        secret_name = os.environ["SECRET_NAME"]
        resp = sm.get_secret_value(SecretId=secret_name)
        _secrets = json.loads(resp["SecretString"])
        logger.info("Loaded GPU credentials from Secrets Manager")
    return _secrets


def lambda_handler(event, context):
    """Handle Step Function input: {bucket, key}."""
    logger.info(f"Received event: {json.dumps(event)}")

    bucket = event["bucket"]
    key = event["key"]
    filename = key.split("/")[-1]
    filename_stem = os.path.splitext(filename)[0]

    # Get credentials from Secrets Manager
    secrets = _get_secrets()
    gpu_endpoint = secrets["GPU_ENDPOINT"]
    cf_client_id = secrets["CF_ACCESS_CLIENT_ID"]
    cf_client_secret = secrets["CF_ACCESS_CLIENT_SECRET"]

    url = f"{gpu_endpoint}/transcribe"
    payload = json.dumps({"bucket": bucket, "key": key}).encode("utf-8")

    req = request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "CF-Access-Client-Id": cf_client_id,
            "CF-Access-Client-Secret": cf_client_secret,
            "User-Agent": "Robert-McAllister-TranscribeLambda/1.0",
        },
        method="POST",
    )

    logger.info(f"Calling GPU endpoint: {url}")
    try:
        with request.urlopen(req, timeout=840) as resp:
            transcript_json = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"GPU endpoint returned {e.code}: {body[:1000]}")
        logger.error(f"Response headers: {dict(e.headers)}")
        raise
    except error.URLError as e:
        logger.error(f"Failed to reach GPU endpoint: {e.reason}")
        raise

    logger.info(f"Transcription received: {len(transcript_json.get('results', {}).get('items', []))} items")

    # Write transcript JSON to S3
    transcript_key = f"transcripts/{filename_stem}.json"
    s3.put_object(
        Bucket=OUTPUT_BUCKET,
        Key=transcript_key,
        Body=json.dumps(transcript_json),
        ContentType="application/json",
    )
    logger.info(f"Wrote transcript to s3://{OUTPUT_BUCKET}/{transcript_key}")

    # Return to Step Function — pass through cleaned_key for diarization
    return {
        "bucket": OUTPUT_BUCKET,
        "transcript_key": transcript_key,
        "cleaned_key": key,
    }
