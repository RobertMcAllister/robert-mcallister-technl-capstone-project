"""Lambda: Audio Cleaner

Invoked by Step Function. POSTs audio S3 location to local GPU endpoint
for Demucs music removal + normalization. GPU service uploads cleaned
audio back to S3.
"""

import json
import logging
import os
from urllib import request, error

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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

    secrets = _get_secrets()
    gpu_endpoint = secrets["GPU_ENDPOINT"]
    cf_client_id = secrets["CF_ACCESS_CLIENT_ID"]
    cf_client_secret = secrets["CF_ACCESS_CLIENT_SECRET"]

    url = f"{gpu_endpoint}/clean"
    payload = json.dumps({"bucket": bucket, "key": key}).encode("utf-8")

    req = request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "CF-Access-Client-Id": cf_client_id,
            "CF-Access-Client-Secret": cf_client_secret,
            "User-Agent": "Robert-McAllister-CleanerLambda/1.0",
        },
        method="POST",
    )

    logger.info(f"Calling GPU endpoint: {url}")
    try:
        with request.urlopen(req, timeout=840) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"GPU endpoint returned {e.code}: {body[:1000]}")
        raise
    except error.URLError as e:
        logger.error(f"Failed to reach GPU endpoint: {e.reason}")
        raise

    logger.info(f"Cleaning complete: {result}")

    # Pass cleaned location to next Step Function state
    return {
        "bucket": result["cleaned_bucket"],
        "key": result["cleaned_key"],
        "original_key": key,
    }
