output "raw_audio_bucket" {
  value = aws_s3_bucket.raw_audio.id
}

output "processed_bucket" {
  value = aws_s3_bucket.processed.id
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}

output "dispatcher_arn" {
  value = aws_lambda_function.dispatcher.arn
}

output "audio_cleaner_arn" {
  value = aws_lambda_function.audio_cleaner.arn
}

output "transcribe_starter_arn" {
  value = aws_lambda_function.transcribe_starter.arn
}

output "transcript_processor_arn" {
  value = aws_lambda_function.transcript_processor.arn
}

output "lambda_role_arn" {
  value = aws_iam_role.lambda_role.arn
}

output "step_function_role_arn" {
  value = aws_iam_role.step_function_role.arn
}

output "glue_database" {
  value = aws_glue_catalog_database.capstone.name
}

output "diarize_starter_arn" {
  value = aws_lambda_function.diarize_starter.arn
}

output "segment_starter_arn" {
  value = aws_lambda_function.segment_starter.arn
}

output "emotion_classifier_arn" {
  value = aws_lambda_function.emotion_classifier.arn
}

output "presigned_url_generator_arn" {
  value = aws_lambda_function.presigned_url_generator.arn
}

output "api_gateway_url" {
  value = "${aws_api_gateway_stage.prod.invoke_url}/upload"
}

output "secrets_manager_arn" {
  value = aws_secretsmanager_secret.gpu_credentials.arn
}
