# CloudWatch monitoring: dashboard + alarms.
#
# Alarm philosophy: every alarm here should mean "a human needs to look at
# this." An alarm that fires on something nobody acts on trains you to ignore
# the whole channel, which is worse than having no alarms. That is why there is
# no alarm on Lambda duration or on individual 5xx responses — those are
# dashboard lines, not pages.

resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
  # Note: AWS sends a confirmation email. Until it is clicked, this
  # subscription is "pending confirmation" and delivers nothing — an alarm
  # channel that silently drops everything is worth verifying after apply.
}

# --- alarms -----------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "refresh_failed" {
  alarm_name        = "${local.name}-refresh-failed"
  alarm_description = "The scheduled data refresh errored. Listings are going stale."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions  = { FunctionName = aws_lambda_function.refresh.function_name }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"

  # A refresh runs every 6h, so most periods have no data at all. Without this,
  # the alarm would sit in INSUFFICIENT_DATA permanently and never evaluate.
  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "refresh_did_not_run" {
  alarm_name        = "${local.name}-refresh-missing"
  alarm_description = "No refresh invocation in 12 hours (schedule is every 6h). The schedule itself may be broken."

  namespace   = "AWS/Lambda"
  metric_name = "Invocations"
  dimensions  = { FunctionName = aws_lambda_function.refresh.function_name }

  statistic           = "Sum"
  period              = 43200 # 12h — two missed runs, not one, to tolerate jitter
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "LessThanThreshold"

  # The important one: "nothing happened" is the failure mode a pure error
  # alarm cannot see. A schedule that stops firing produces no errors at all.
  treat_missing_data = "breaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name        = "${local.name}-dlq-not-empty"
  alarm_description = "Messages in the embedding dead-letter queue: work failed 3 times and was parked."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"
  dimensions  = { QueueName = aws_sqs_queue.embedding_dlq.name }

  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "queue_backlog" {
  alarm_name        = "${local.name}-queue-backlog"
  alarm_description = "Embedding queue is not draining — consumer is too slow or stuck."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateAgeOfOldestMessage"
  dimensions  = { QueueName = aws_sqs_queue.embedding.name }

  statistic = "Maximum"
  period    = 300
  # Sustained over 15 minutes, not a single spike: a burst right after a
  # refresh is normal and expected, a backlog that persists is not.
  evaluation_periods  = 3
  threshold           = 3600
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
}

# --- dashboard --------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = local.name

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "text", x = 0, y = 0, width = 24, height = 2
        properties = {
          markdown = "# JobEngine pipeline\nScheduled refresh every 6h. `JobEngine` namespace holds custom metrics emitted by the refresh function; `AWS/*` are service metrics."
        }
      },
      {
        type = "metric", x = 0, y = 2, width = 12, height = 6
        properties = {
          title  = "Refresh: invocations vs errors"
          region = var.region
          view   = "timeSeries"
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.refresh.function_name, { stat = "Sum" }],
            [".", "Errors", ".", ".", { stat = "Sum", color = "#d62728" }],
          ]
          period = 3600
        }
      },
      {
        type = "metric", x = 12, y = 2, width = 12, height = 6
        properties = {
          title  = "Refresh duration (p50 / p95 / max)"
          region = var.region
          view   = "timeSeries"
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.refresh.function_name, { stat = "p50" }],
            ["...", { stat = "p95" }],
            ["...", { stat = "Maximum" }],
          ]
          period = 3600
          # Annotated at the configured timeout so creeping duration is visible
          # against the cliff it is heading toward, not just as a rising line.
          annotations = {
            horizontal = [{ label = "timeout (300s)", value = 300000 }]
          }
        }
      },
      {
        type = "metric", x = 0, y = 8, width = 12, height = 6
        properties = {
          title  = "Listings processed per run"
          region = var.region
          view   = "timeSeries"
          metrics = [
            ["JobEngine", "ListingsProcessed", { stat = "Sum" }],
            [".", "ListingsDeduplicated", { stat = "Sum" }],
            [".", "DuplicatesRemoved", { stat = "Sum" }],
          ]
          period = 3600
        }
      },
      {
        type = "metric", x = 12, y = 8, width = 12, height = 6
        properties = {
          title  = "Embedding queue depth and age"
          region = var.region
          view   = "timeSeries"
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.embedding.name],
            [".", "ApproximateAgeOfOldestMessage", ".", ".", { yAxis = "right" }],
            [".", "ApproximateNumberOfMessagesVisible", ".", aws_sqs_queue.embedding_dlq.name, { color = "#d62728" }],
          ]
          period = 300
        }
      },
      {
        type = "log", x = 0, y = 14, width = 24, height = 6
        properties = {
          title  = "Recent refresh errors"
          region = var.region
          query  = <<-EOT
            SOURCE '${aws_cloudwatch_log_group.refresh.name}'
            | fields @timestamp, @message
            | filter @message like /ERROR|Traceback/
            | sort @timestamp desc
            | limit 50
          EOT
        }
      },
      {
        type = "metric", x = 0, y = 20, width = 12, height = 6
        properties = {
          title  = "Data refresh success rate"
          region = var.region
          view   = "timeSeries"
          metrics = [
            [{ expression = "100 * (invocations - errors) / invocations", label = "Success rate (%)", id = "success" }],
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.refresh.function_name, { stat = "Sum", id = "invocations", visible = false }],
            [".", "Errors", ".", ".", { stat = "Sum", id = "errors", visible = false }],
          ]
          period = 21600
          yAxis = { left = { min = 0, max = 100 } }
        }
      },
    ]
  })
}
