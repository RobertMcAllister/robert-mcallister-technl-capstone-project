# Secrets Manager — GPU endpoint credentials

resource "aws_secretsmanager_secret" "gpu_credentials" {
  name        = "${var.prefix}-GPU-Credentials"
  description = "Cloudflare Access credentials for GPU endpoint"
}

# Secret value is set manually by Robert (rotated keys)
# aws secretsmanager put-secret-value --secret-id Robert-McAllister-GPU-Credentials --secret-string '{"CF_ACCESS_CLIENT_ID":"...","CF_ACCESS_CLIENT_SECRET":"...","GPU_ENDPOINT":"https://capstone-local-gpu.islandhermit.com"}'
