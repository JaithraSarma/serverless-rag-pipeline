provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

locals {
  lambda_function_name = "${var.project_name}-query"
  log_group_name       = "/aws/lambda/${local.lambda_function_name}"
  ssm_parameter_arn    = "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter${var.openai_api_key_parameter_name}"
}

resource "aws_s3_bucket" "runbooks" {
  bucket = var.runbooks_bucket_name
}

resource "aws_iam_role" "lambda_role" {
  name = "${var.project_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_least_privilege" {
  name = "${var.project_name}-lambda-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.lambda_logs.arn}:*"
      },
      {
        Sid    = "ListRunbookPrefix"
        Effect = "Allow"
        Action = [
          "s3:ListBucket"
        ]
        Resource = aws_s3_bucket.runbooks.arn
        Condition = {
          StringLike = {
            "s3:prefix" = var.runbook_prefix == "" ? ["*"] : ["${var.runbook_prefix}*"]
          }
        }
      },
      {
        Sid    = "ReadRunbooksOnly"
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = var.runbook_prefix == "" ? "${aws_s3_bucket.runbooks.arn}/*" : "${aws_s3_bucket.runbooks.arn}/${var.runbook_prefix}*"
      },
      {
        Sid    = "ReadSpecificOpenAIKey"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter"
        ]
        Resource = local.ssm_parameter_arn
      },
      {
        Sid    = "PutProjectMetrics"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = var.metrics_namespace
          }
        }
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = local.log_group_name
  retention_in_days = 14
}

resource "aws_lambda_function" "query" {
  function_name = local.lambda_function_name
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.11"
  filename      = "${path.module}/../build/lambda.zip"

  source_code_hash = filebase64sha256("${path.module}/../build/lambda.zip")

  # 30 seconds keeps user-facing latency bounded while still allowing S3 reads + OpenAI calls.
  timeout     = var.lambda_timeout_seconds
  memory_size = var.lambda_memory_mb

  environment {
    variables = {
      S3_BUCKET                = aws_s3_bucket.runbooks.bucket
      RUNBOOK_PREFIX           = var.runbook_prefix
      OPENAI_API_KEY_SSM_PARAM = var.openai_api_key_parameter_name
      CHUNK_SIZE_TOKENS        = tostring(var.chunk_size_tokens)
      CHUNK_OVERLAP_TOKENS     = tostring(var.chunk_overlap_tokens)
      EMBEDDING_MODEL          = var.embedding_model
      CHAT_MODEL               = var.chat_model
      TOP_K                    = tostring(var.top_k)
      METRICS_NAMESPACE        = var.metrics_namespace
    }
  }

  depends_on = [
    aws_iam_role_policy.lambda_least_privilege,
    aws_cloudwatch_log_group.lambda_logs
  ]
}

resource "aws_apigatewayv2_api" "http_api" {
  name          = "${var.project_name}-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda_integration" {
  api_id                 = aws_apigatewayv2_api.http_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.query.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "query_route" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "POST /query"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http_api.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "allow_api_gateway" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.query.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http_api.execution_arn}/*/*"
}
