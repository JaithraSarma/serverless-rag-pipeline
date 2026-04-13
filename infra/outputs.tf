output "api_base_url" {
  value       = aws_apigatewayv2_stage.default.invoke_url
  description = "Invoke URL for the HTTP API stage. Append /query for requests."
}

output "runbooks_bucket_name" {
  value       = aws_s3_bucket.runbooks.bucket
  description = "S3 bucket that stores runbooks."
}

output "lambda_function_name" {
  value       = aws_lambda_function.query.function_name
  description = "Lambda function that serves RAG queries."
}
