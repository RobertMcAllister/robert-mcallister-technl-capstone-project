variable "aws_region" {
  default = "us-east-1"
}

variable "account_id" {
  description = "AWS account ID. Set in terraform.tfvars (gitignored) or via TF_VAR_account_id."
  type        = string
}

variable "prefix" {
  default = "Robert-McAllister"
}
