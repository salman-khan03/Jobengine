terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "jobengine"
      ManagedBy = "terraform"
      # Makes it obvious in the console and on the bill that these resources
      # belong to a side project, so nothing here gets mistaken for production
      # and left running.
      Env = var.environment
    }
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "portfolio"
}

variable "vpc_id" {
  type        = string
  description = "Existing VPC. This config does not create networking."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Subnets with NAT egress — Lambda needs outbound HTTPS to reach GitHub."
}

variable "database_url" {
  type        = string
  sensitive   = true
  description = "SQLAlchemy URL for the refresh job. Stored in Secrets Manager, never inlined into the function's environment."
}

variable "alert_email" {
  type        = string
  description = "Where CloudWatch alarms are delivered. Requires confirming the SNS subscription by email."
}

variable "refresh_schedule" {
  type    = string
  default = "rate(6 hours)"

  # 6 hours, not hourly: the upstream SimplifyJobs feeds update a few times a
  # day, so hourly runs would do 4x the work for the same data and 4x the
  # chance of tripping GitHub's rate limits. Staleness is bounded at 6h, which
  # is well inside how fast these listings actually change.
}

locals {
  name = "jobengine-${var.environment}"
}

output "refresh_function_name" {
  value = aws_lambda_function.refresh.function_name
}

output "dashboard_url" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}

output "dead_letter_queue_url" {
  value = aws_sqs_queue.embedding_dlq.url
}
