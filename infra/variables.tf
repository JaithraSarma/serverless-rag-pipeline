variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix used in resource names."
  type        = string
  default     = "serverless-rag"
}

variable "runbooks_bucket_name" {
  description = "S3 bucket name that stores runbooks. Must be globally unique."
  type        = string
}

variable "openai_api_key_parameter_name" {
  description = "Exact SSM Parameter Store name that holds the OpenAI API key as SecureString."
  type        = string
}

variable "runbook_prefix" {
  description = "Optional S3 prefix where runbooks are stored."
  type        = string
  default     = ""
}

variable "chunk_size_tokens" {
  description = "Chunk size for token-aware splitting. Tunable for retrieval quality and cost."
  type        = number
  default     = 500
}

variable "chunk_overlap_tokens" {
  description = "Token overlap between chunks to preserve context near boundaries."
  type        = number
  default     = 50
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout in seconds. 30s gives room for embedding + completion calls without hanging too long."
  type        = number
  default     = 30
}

variable "lambda_memory_mb" {
  description = "Lambda memory size in MB. Higher memory improves CPU throughput for local FAISS indexing/search."
  type        = number
  default     = 1024
}

variable "embedding_model" {
  description = "OpenAI embedding model name."
  type        = string
  default     = "text-embedding-3-small"
}

variable "chat_model" {
  description = "OpenAI chat model used for answer synthesis."
  type        = string
  default     = "gpt-3.5-turbo"
}

variable "top_k" {
  description = "Number of chunks retrieved from FAISS for answer generation."
  type        = number
  default     = 4
}

variable "metrics_namespace" {
  description = "CloudWatch custom metrics namespace."
  type        = string
  default     = "ServerlessRag"
}
