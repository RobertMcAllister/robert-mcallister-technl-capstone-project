"""Lambda #0: Dispatcher

Triggered by S3 event when audio uploaded to raw/ prefix.
Starts a Step Function execution to orchestrate the pipeline.
"""

import json
import logging
import os
import re
from urllib.parse import unquote_plus

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sfn = boto3.client("stepfunctions", region_name="us-east-1")

STATE_MACHINE_ARN = os.environ["STATE_MACHINE_ARN"]


def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])

        if not key.startswith("raw/"):
            logger.warning(f"Skipping non-raw key: {key}")
            continue

        sfn_input = json.dumps({"bucket": bucket, "key": key})
        filename = key.split("/")[-1]

        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "-", filename.replace(".", "-"))[:60]
        execution_name = f"{safe_name}-{context.aws_request_id[:8]}"

        logger.info(f"Starting Step Function for {filename}")
        response = sfn.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=execution_name,
            input=sfn_input,
        )
        logger.info(f"Execution started: {response['executionArn']}")

    return {"statusCode": 200}
