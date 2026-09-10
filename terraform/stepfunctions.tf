# Step Functions State Machine

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.prefix}-TranscriptionPipeline"
  role_arn = aws_iam_role.step_function_role.arn

  definition = jsonencode({
    Comment = "Audio pipeline: Clean -> Transcribe -> Diarize -> Segment -> Emotions -> Process"
    StartAt = "CleanAudio"
    States = {
      CleanAudio = {
        Type           = "Task"
        Resource       = aws_lambda_function.audio_cleaner.arn
        TimeoutSeconds = 900
        Next           = "Transcribe"
      }
      Transcribe = {
        Type           = "Task"
        Resource       = aws_lambda_function.transcribe_starter.arn
        TimeoutSeconds = 900
        Next           = "Diarize"
      }
      Diarize = {
        Type           = "Task"
        Resource       = aws_lambda_function.diarize_starter.arn
        TimeoutSeconds = 900
        Next           = "Segment"
      }
      Segment = {
        Type           = "Task"
        Resource       = aws_lambda_function.segment_starter.arn
        TimeoutSeconds = 900
        Next           = "ClassifyEmotions"
      }
      ClassifyEmotions = {
        Type           = "Task"
        Resource       = aws_lambda_function.emotion_classifier.arn
        TimeoutSeconds = 900
        Next           = "Process"
      }
      Process = {
        Type           = "Task"
        Resource       = aws_lambda_function.transcript_processor.arn
        TimeoutSeconds = 120
        End            = true
      }
    }
  })
}
