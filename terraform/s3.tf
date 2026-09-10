# S3 Buckets

resource "aws_s3_bucket" "raw_audio" {
  bucket = "robert-mcallister-raw-audio"
}

resource "aws_s3_bucket" "processed" {
  bucket = "robert-mcallister-processed"
}

# S3 Event Notification — triggers Dispatcher Lambda on raw/ uploads

resource "aws_s3_bucket_notification" "raw_audio" {
  bucket = aws_s3_bucket.raw_audio.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.dispatcher.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "raw/"
    id                  = "DispatcherTrigger"
  }

  depends_on = [aws_lambda_permission.s3_invoke_dispatcher]
}
