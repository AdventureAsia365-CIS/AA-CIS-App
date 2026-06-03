# =============================================================================
# AA-143 — Synthetic Canary: EventBridge Scheduler (skeleton)
# =============================================================================
# State: DISABLED — enable after Lambda deployed + manual test passes.
# Lambda ARN is a placeholder; set to real ARN after first deploy.
# Schedule: rate(7 days) — Wave 0 weekly smoke test (S0→S1 only).
# =============================================================================

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

locals {
  name_prefix = "aa-cis-dev"
  region      = "us-west-1"
  account_id  = "867490540162"
}

# IAM role for EventBridge Scheduler to invoke the Lambda
resource "aws_iam_role" "canary_scheduler" {
  name = "${local.name_prefix}-canary-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = local.account_id
        }
      }
    }]
  })

  tags = {
    Project = "aa-cis"
    Ticket  = "AA-143"
  }
}

resource "aws_iam_role_policy" "canary_scheduler_invoke" {
  name = "invoke-canary-lambda"
  role = aws_iam_role.canary_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      # Placeholder ARN — replace after Lambda is deployed
      Resource = "arn:aws:lambda:${local.region}:${local.account_id}:function:${local.name_prefix}-acp-canary"
    }]
  })
}

# EventBridge Scheduler — weekly canary run
resource "aws_scheduler_schedule" "acp_canary_weekly" {
  name                         = "${local.name_prefix}-acp-canary-weekly"
  group_name                   = "default"
  schedule_expression          = "rate(7 days)"
  schedule_expression_timezone = "UTC"

  # DISABLED until Lambda is deployed and smoke-tested manually
  state = "DISABLED"

  flexible_time_window {
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 30
  }

  target {
    # Placeholder ARN — replace with real Lambda ARN after deploy
    arn      = "arn:aws:lambda:${local.region}:${local.account_id}:function:${local.name_prefix}-acp-canary"
    role_arn = aws_iam_role.canary_scheduler.arn

    input = jsonencode({
      source  = "eventbridge-scheduler"
      trigger = "weekly-canary"
      wave    = 0
    })

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }

  tags = {
    Project = "aa-cis"
    Ticket  = "AA-143"
    Wave    = "0"
  }
}
