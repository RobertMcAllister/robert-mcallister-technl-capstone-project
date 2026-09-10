# Lambda Execution Role

resource "aws_iam_role" "lambda_role" {
  name = "${var.prefix}-LambdaTranscriptionRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "${var.prefix}-LambdaTranscriptionPolicy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${var.account_id}:*"
      },
      {
        Sid    = "S3ReadRawBucket"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.raw_audio.arn,
          "${aws_s3_bucket.raw_audio.arn}/*"
        ]
      },
      {
        Sid    = "S3WriteTranscriptsAndProcessed"
        Effect = "Allow"
        Action = ["s3:PutObject"]
        Resource = [
          "${aws_s3_bucket.raw_audio.arn}/raw/*",
          "${aws_s3_bucket.raw_audio.arn}/transcripts/*",
          "${aws_s3_bucket.raw_audio.arn}/cleaned/*",
          "${aws_s3_bucket.processed.arn}/*"
        ]
      },
      {
        Sid      = "TranscribeJobs"
        Effect   = "Allow"
        Action   = ["transcribe:StartTranscriptionJob", "transcribe:GetTranscriptionJob"]
        Resource = "*"
      },
      {
        Sid    = "SQSForLater"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:SendMessage"
        ]
        Resource = "arn:aws:sqs:${var.aws_region}:${var.account_id}:${var.prefix}-*"
      },
      {
        Sid      = "StepFunctions"
        Effect   = "Allow"
        Action   = "states:StartExecution"
        Resource = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${var.prefix}-*"
      },
      {
        Sid      = "SecretsManager"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:${var.prefix}-*"
      }
    ]
  })
}

# Step Function Execution Role

resource "aws_iam_role" "step_function_role" {
  name = "${var.prefix}-StepFunctionRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "step_function_policy" {
  name = "${var.prefix}-StepFunctionPolicy"
  role = aws_iam_role.step_function_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "InvokeLambdas"
      Effect = "Allow"
      Action = "lambda:InvokeFunction"
      Resource = [
        aws_lambda_function.audio_cleaner.arn,
        aws_lambda_function.transcribe_starter.arn,
        aws_lambda_function.diarize_starter.arn,
        aws_lambda_function.segment_starter.arn,
        aws_lambda_function.emotion_classifier.arn,
        aws_lambda_function.transcript_processor.arn
      ]
    }]
  })
}
