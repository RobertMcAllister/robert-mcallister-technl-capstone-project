# Lambda Functions
# Code is deployed via zip files from lambdas/ directory

# Dispatcher — S3 trigger → starts Step Function
resource "aws_lambda_function" "dispatcher" {
  function_name = "${var.prefix}-Dispatcher"
  description   = "Dispatches S3 uploads to Step Function pipeline"
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"
  role          = aws_iam_role.lambda_role.arn
  filename      = "${path.module}/../lambdas/dispatcher/lambda_function.zip"
  timeout       = 30
  memory_size   = 128

  environment {
    variables = {
      STATE_MACHINE_ARN = aws_sfn_state_machine.pipeline.arn
    }
  }
}

# Audio Cleaner — calls GPU /clean endpoint (Demucs)
resource "aws_lambda_function" "audio_cleaner" {
  function_name = "${var.prefix}-AudioCleaner"
  description   = "Calls local GPU for Demucs audio cleaning"
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"
  role          = aws_iam_role.lambda_role.arn
  filename      = "${path.module}/../lambdas/audio_cleaner/lambda_function.zip"
  timeout       = 900
  memory_size   = 256

  environment {
    variables = {
      SECRET_NAME = aws_secretsmanager_secret.gpu_credentials.name
    }
  }
}

# Transcribe Starter — calls GPU /transcribe endpoint (Whisper)
resource "aws_lambda_function" "transcribe_starter" {
  function_name = "${var.prefix}-TranscribeStarter"
  description   = "Calls local GPU for Whisper transcription"
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"
  role          = aws_iam_role.lambda_role.arn
  filename      = "${path.module}/../lambdas/transcribe_starter/lambda_function.zip"
  timeout       = 900
  memory_size   = 256

  environment {
    variables = {
      SECRET_NAME = aws_secretsmanager_secret.gpu_credentials.name
    }
  }
}

# Diarize Starter — calls GPU /diarize endpoint (pyannote)
resource "aws_lambda_function" "diarize_starter" {
  function_name = "${var.prefix}-DiarizeStarter"
  description   = "DiarizeStarter for audio pipeline"
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"
  role          = aws_iam_role.lambda_role.arn
  filename      = "${path.module}/../lambdas/diarize_starter/lambda_function.zip"
  timeout       = 900
  memory_size   = 256

  environment {
    variables = {
      SECRET_NAME = aws_secretsmanager_secret.gpu_credentials.name
    }
  }
}

# Segment Starter — calls GPU /segment endpoint (boundary detection + audio cutting)
resource "aws_lambda_function" "segment_starter" {
  function_name = "${var.prefix}-SegmentStarter"
  description   = "SegmentStarter for audio pipeline"
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"
  role          = aws_iam_role.lambda_role.arn
  filename      = "${path.module}/../lambdas/segment_starter/lambda_function.zip"
  timeout       = 900
  memory_size   = 256

  environment {
    variables = {
      SECRET_NAME = aws_secretsmanager_secret.gpu_credentials.name
    }
  }
}

# Emotion Classifier — calls GPU /classify-emotions endpoint (ModernBERT + emotion2vec)
resource "aws_lambda_function" "emotion_classifier" {
  function_name = "${var.prefix}-EmotionClassifier"
  description   = "EmotionClassifier for audio pipeline"
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"
  role          = aws_iam_role.lambda_role.arn
  filename      = "${path.module}/../lambdas/emotion_classifier/lambda_function.zip"
  timeout       = 900
  memory_size   = 256

  environment {
    variables = {
      SECRET_NAME = aws_secretsmanager_secret.gpu_credentials.name
    }
  }
}

# Transcript Processor — parses transcript JSON, writes JSONL
resource "aws_lambda_function" "transcript_processor" {
  function_name = "${var.prefix}-TranscriptProcessor"
  description   = "Parses Transcribe JSON and writes structured JSONL to processed bucket"
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"
  role          = aws_iam_role.lambda_role.arn
  filename      = "${path.module}/../lambdas/transcript_processor/lambda_function.zip"
  timeout       = 60
  memory_size   = 256
}

# Presigned URL Generator — API Gateway → generates S3 upload URLs
resource "aws_lambda_function" "presigned_url_generator" {
  function_name = "${var.prefix}-PresignedUrlGenerator"
  description   = "Generates presigned S3 URLs for audio upload"
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"
  role          = aws_iam_role.lambda_role.arn
  filename      = "${path.module}/../lambdas/presigned_url_generator/lambda_function.zip"
  timeout       = 10
  memory_size   = 128
}

# S3 permission to invoke Dispatcher
resource "aws_lambda_permission" "s3_invoke_dispatcher" {
  statement_id   = "S3InvokeDispatcher"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.dispatcher.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.raw_audio.arn
  source_account = var.account_id
}

# API Gateway permission to invoke Presigned URL Generator
resource "aws_lambda_permission" "apigateway_invoke_presigned" {
  statement_id  = "APIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.presigned_url_generator.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.upload_api.execution_arn}/*/POST/upload"
}
