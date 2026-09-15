# Scheduled data-refresh pipeline: EventBridge → Lambda → SQS → Lambda.

# --- secrets ----------------------------------------------------------------

resource "aws_secretsmanager_secret" "database_url" {
  name = "${local.name}/database-url"
  # Short window so a mistaken delete can be undone but a rotation isn't
  # blocked for a week during development.
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = var.database_url
}

# --- queues -----------------------------------------------------------------

resource "aws_sqs_queue" "embedding_dlq" {
  name = "${local.name}-embedding-dlq"
  # 14 days: a failure that happens Friday night must still be inspectable the
  # following week. The DLQ is a debugging artifact, not a hot path.
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "embedding" {
  name = "${local.name}-embedding"

  # Must be >= the consumer's timeout, or SQS redelivers a message that is
  # still being processed and the work is done twice. This is the single most
  # common SQS misconfiguration.
  visibility_timeout_seconds = 360

  message_retention_seconds = 86400

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.embedding_dlq.arn
    # 3 attempts, then park it. Retrying forever turns one poison message into
    # an infinite bill and hides the failure behind a queue that never drains.
    maxReceiveCount = 3
  })
}

# --- IAM --------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "refresh" {
  name               = "${local.name}-refresh"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "refresh" {
  statement {
    sid    = "ReadDatabaseSecret"
    effect = "Allow"
    # Scoped to this one secret, not secretsmanager:* — a compromised refresh
    # function should not be able to read every secret in the account.
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.database_url.arn]
  }

  statement {
    sid       = "EnqueueEmbeddingWork"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.embedding.arn]
  }

  statement {
    sid    = "PublishCustomMetrics"
    effect = "Allow"
    # CloudWatch's PutMetricData cannot be resource-scoped; the condition below
    # is the only available restriction.
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["JobEngine"]
    }
  }
}

resource "aws_iam_role_policy" "refresh" {
  role   = aws_iam_role.refresh.id
  policy = data.aws_iam_policy_document.refresh.json
}

resource "aws_iam_role_policy_attachment" "refresh_basic" {
  role       = aws_iam_role.refresh.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "refresh_vpc" {
  role       = aws_iam_role.refresh.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role" "embedding_worker" {
  name               = "${local.name}-embedding-worker"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "embedding_worker" {
  statement {
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.database_url.arn]
  }
  statement {
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.embedding.arn]
  }
}

resource "aws_iam_role_policy" "embedding_worker" {
  role   = aws_iam_role.embedding_worker.id
  policy = data.aws_iam_policy_document.embedding_worker.json
}

resource "aws_iam_role_policy_attachment" "embedding_worker_basic" {
  role       = aws_iam_role.embedding_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "embedding_worker_vpc" {
  role       = aws_iam_role.embedding_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# --- security group ---------------------------------------------------------

resource "aws_security_group" "lambda" {
  name        = "${local.name}-lambda"
  description = "Outbound only: HTTPS to GitHub, Postgres to RDS"
  vpc_id      = var.vpc_id

  egress {
    description = "HTTPS to upstream job feeds"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "PostgreSQL"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # No ingress rules at all. Nothing should ever connect *to* a Lambda.
}

# --- functions --------------------------------------------------------------

# Placeholder package. The real artifact is built in CI:
#   pip install -t build/ . && cd build && zip -r ../refresh.zip .
data "archive_file" "placeholder" {
  type        = "zip"
  output_path = "${path.module}/placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise NotImplementedError('replace with the CI-built artifact')\n"
    filename = "handler.py"
  }
}

resource "aws_lambda_function" "refresh" {
  function_name = "${local.name}-refresh"
  role          = aws_iam_role.refresh.arn
  runtime       = "python3.12"
  handler       = "jobengine.aws_handlers.refresh_handler"

  filename         = data.archive_file.placeholder.output_path
  source_code_hash = data.archive_file.placeholder.output_base64sha256

  # The build+dedup stage measured ~5s for 32k records locally; 300s leaves
  # headroom for a slow upstream fetch without letting a hung run bill for
  # 15 minutes. See docs/measurements.md.
  timeout = 300

  # 1GB: this stage is dominated by parsing ~23MB of JSON and building dicts,
  # and Lambda scales CPU with memory, so the larger size is often *cheaper*
  # per invocation despite the higher per-ms rate.
  memory_size = 1024

  environment {
    variables = {
      DATABASE_SECRET_ARN = aws_secretsmanager_secret.database_url.arn
      EMBEDDING_QUEUE_URL = aws_sqs_queue.embedding.url
      JOBENGINE_LOG_LEVEL = "INFO"
    }
  }

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  lifecycle {
    # CI publishes new code; Terraform owns the infrastructure. Without this,
    # every terraform apply would revert the deployed artifact to the
    # placeholder above.
    ignore_changes = [filename, source_code_hash]
  }
}

resource "aws_lambda_function" "embedding_worker" {
  function_name = "${local.name}-embedding-worker"
  role          = aws_iam_role.embedding_worker.arn
  runtime       = "python3.12"
  handler       = "jobengine.aws_handlers.embedding_handler"

  filename         = data.archive_file.placeholder.output_path
  source_code_hash = data.archive_file.placeholder.output_base64sha256

  # Must stay below the queue's visibility_timeout_seconds (360).
  timeout     = 300
  memory_size = 2048

  environment {
    variables = {
      DATABASE_SECRET_ARN = aws_secretsmanager_secret.database_url.arn
      JOBENGINE_LOG_LEVEL = "INFO"
    }
  }

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }
}

resource "aws_lambda_event_source_mapping" "embedding" {
  event_source_arn = aws_sqs_queue.embedding.arn
  function_id      = aws_lambda_function.embedding_worker.arn

  batch_size = 10

  # Without this, one bad record fails the whole batch and all 10 are retried —
  # including the 9 that succeeded. Partial batch responses let the function
  # report exactly which message ids failed.
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    # Cap concurrency so a large backlog can't open more database connections
    # than Postgres has. This is the same reasoning as the API's bounded pool,
    # applied to the consumer side.
    maximum_concurrency = 5
  }
}

# --- log retention ----------------------------------------------------------

# Lambda creates these implicitly with retention "never expire", which is a
# slow, silent cost leak. Declaring them makes retention explicit.
resource "aws_cloudwatch_log_group" "refresh" {
  name              = "/aws/lambda/${aws_lambda_function.refresh.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "embedding_worker" {
  name              = "/aws/lambda/${aws_lambda_function.embedding_worker.function_name}"
  retention_in_days = 14
}

# --- schedule ---------------------------------------------------------------

resource "aws_iam_role" "scheduler" {
  name = "${local.name}-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "scheduler.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.refresh.arn
    }]
  })
}

resource "aws_scheduler_schedule" "refresh" {
  name                = "${local.name}-refresh"
  schedule_expression = var.refresh_schedule

  flexible_time_window {
    # 15-minute jitter window. Every scheduled job in the world firing exactly
    # on the hour is how upstreams get thundering-herded; there is no reason
    # this refresh needs to start at a precise instant.
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 15
  }

  target {
    arn      = aws_lambda_function.refresh.arn
    role_arn = aws_iam_role.scheduler.arn

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}
