# Interview Quick Revision

## One-minute summary
This is a serverless RAG system on AWS where runbooks live in S3, retrieval runs inside Lambda with direct OpenAI embeddings plus FAISS, and API Gateway exposes a plain-English query endpoint with citations.

## Three key strengths
- Small package footprint by avoiding LangChain abstraction layers.
- Least-privilege IAM and runtime secret retrieval from SSM SecureString.
- Built-in custom metrics for latency and token usage per request.

## Two honest limitations
- Cold starts can increase p95 latency.
- FAISS index is rebuilt from S3 during fresh execution environments.
