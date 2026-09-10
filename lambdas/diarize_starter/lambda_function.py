"""Lambda: Diarize Starter

Invoked by Step Function. Calls GPU /diarize endpoint (pyannote)
to identify speaker segments in the cleaned audio.
"""

import json
import logging
import os
from urllib import request, error

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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
    cleaned_key = event.get("cleaned_key") or event.get("key")
    transcript_key = event["transcript_key"]

    secrets = _get_secrets()
    url = f"{secrets['GPU_ENDPOINT']}/diarize"
    payload = json.dumps({"bucket": bucket, "key": cleaned_key}).encode("utf-8")

    req = request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "CF-Access-Client-Id": secrets["CF_ACCESS_CLIENT_ID"],
        "CF-Access-Client-Secret": secrets["CF_ACCESS_CLIENT_SECRET"],
        "User-Agent": "Robert-McAllister-DiarizeLambda/1.0",
    }, method="POST")

    logger.info(f"Calling GPU: {url}")
    try:
        with request.urlopen(req, timeout=840) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"GPU returned {e.code}: {body[:1000]}")
        raise

    logger.info(f"Diarized: {len(result.get('segments', []))} turns, "
                f"{len(result.get('speakers', []))} speakers")

    return {
        "bucket": bucket,
        "cleaned_key": cleaned_key,
        "transcript_key": transcript_key,
        "speaker_segments": result["segments"],
    }
