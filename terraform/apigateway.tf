# API Gateway — Upload endpoint with presigned S3 URLs

resource "aws_api_gateway_rest_api" "upload_api" {
  name        = "${var.prefix}-UploadAPI"
  description = "Audio upload API - generates presigned S3 URLs"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_resource" "upload" {
  rest_api_id = aws_api_gateway_rest_api.upload_api.id
  parent_id   = aws_api_gateway_rest_api.upload_api.root_resource_id
  path_part   = "upload"
}

# POST /upload — requires API key
resource "aws_api_gateway_method" "upload_post" {
  rest_api_id      = aws_api_gateway_rest_api.upload_api.id
  resource_id      = aws_api_gateway_resource.upload.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "upload_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.upload_api.id
  resource_id             = aws_api_gateway_resource.upload.id
  http_method             = aws_api_gateway_method.upload_post.http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = aws_lambda_function.presigned_url_generator.invoke_arn
}

# OPTIONS /upload — CORS preflight
resource "aws_api_gateway_method" "upload_options" {
  rest_api_id   = aws_api_gateway_rest_api.upload_api.id
  resource_id   = aws_api_gateway_resource.upload.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "upload_options_mock" {
  rest_api_id = aws_api_gateway_rest_api.upload_api.id
  resource_id = aws_api_gateway_resource.upload.id
  http_method = aws_api_gateway_method.upload_options.http_method
  type        = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

# Deployment
resource "aws_api_gateway_deployment" "prod" {
  rest_api_id = aws_api_gateway_rest_api.upload_api.id

  depends_on = [
    aws_api_gateway_integration.upload_lambda,
    aws_api_gateway_integration.upload_options_mock,
  ]
}

resource "aws_api_gateway_stage" "prod" {
  rest_api_id   = aws_api_gateway_rest_api.upload_api.id
  deployment_id = aws_api_gateway_deployment.prod.id
  stage_name    = "prod"
}

# API Key + Usage Plan (rate limiting)
resource "aws_api_gateway_api_key" "upload_key" {
  name    = "${var.prefix}-UploadKey"
  enabled = true
}

resource "aws_api_gateway_usage_plan" "upload_plan" {
  name = "${var.prefix}-UsagePlan"

  api_stages {
    api_id = aws_api_gateway_rest_api.upload_api.id
    stage  = aws_api_gateway_stage.prod.stage_name
  }

  throttle_settings {
    burst_limit = 5
    rate_limit  = 2
  }
}

resource "aws_api_gateway_usage_plan_key" "upload_plan_key" {
  key_id        = aws_api_gateway_api_key.upload_key.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.upload_plan.id
}
