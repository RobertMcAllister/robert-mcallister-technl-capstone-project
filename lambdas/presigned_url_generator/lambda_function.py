"""Lambda #1: Presigned URL Generator

Invoked by API Gateway. Generates a presigned S3 PUT URL so clients
can upload audio files directly to S3 without AWS credentials.
"""

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3", region_name="us-east-1")

BUCKET = "robert-mcallister-raw-audio"
URL_EXPIRY = 300  # 5 minutes


def lambda_handler(event, context):
    """Handle API Gateway request."""
    logger.info(f"Received event: {json.dumps(event)}")

    # Parse body (API Gateway sends string body)
    body = event.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    filename = body.get("filename")
    if not filename:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": "filename is required"}),
        }

    content_type = body.get("content_type", "audio/webm")
    key = f"raw/{filename}"

    url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": BUCKET,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=URL_EXPIRY,
    )

    logger.info(f"Generated presigned URL for {key}")

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps({
            "upload_url": url,
            "key": key,
            "bucket": BUCKET,
            "expires_in": URL_EXPIRY,
        }),
    }
