# Serverless RAG for Infrastructure Runbooks on AWS

This project answers plain-English infrastructure questions by searching runbooks stored in S3 and returning grounded answers with citations.

It is intentionally built with minimal moving parts:
- API Gateway + Lambda for the query API.
- OpenAI embeddings and chat completions.
- FAISS for vector retrieval.
- SSM Parameter Store (SecureString) for the OpenAI API key.
- Terraform for infrastructure.
- GitHub Actions for automated deployment.

No LangChain is used for embedding or retrieval logic so the Lambda package remains lean and explicit.

## What You Get

- `POST /query` endpoint that accepts `{ "question": "..." }`.
- Response with:
  - `answer`
  - `citations` (source file keys)
  - `retrieved_chunks` (debug metadata)
- Two custom CloudWatch metrics per query:
  - `QueryLatencyMs`
  - `OpenAITokenCount`

## Architecture

1. Runbooks are stored in one S3 bucket (optionally under a prefix such as `runbooks/`).
2. Client calls API Gateway `POST /query`.
3. Lambda does:
   - Parse request and validate question.
   - Load runbooks from S3.
   - Chunk text by token count (`CHUNK_SIZE_TOKENS`, `CHUNK_OVERLAP_TOKENS`).
   - Generate embeddings using OpenAI.
   - Build or reuse a FAISS index.
   - Retrieve top-k chunks.
   - Ask `gpt-3.5-turbo` to answer using only retrieved context, with citations.
4. Lambda emits latency and token metrics to CloudWatch.
5. Lambda returns JSON answer payload to API Gateway.

## Repository Layout

- `app/src/lambda_function.py`: handler, chunking, embedding, retrieval, answer generation, metrics.
- `app/requirements.txt`: Lambda Python dependencies.
- `infra/`: Terraform files for AWS resources.
- `.github/workflows/deploy.yml`: CI/CD workflow.
- `build/`: generated artifact location (`lambda.zip`).
- `proof/`: local test/deploy evidence logs.

## Helper Assets Included

- `app/events/query_request.json`: Valid sample request body for local or live API testing.
- `app/events/query_request_empty.json`: Invalid request body to validate 400 handling.
- `app/sample-runbooks/credential-rotation.md`: Starter runbook for first retrieval test.
- `scripts/package_lambda.ps1`: Local packaging helper to produce `build/lambda.zip`.
- `scripts/deploy_infra.ps1`: One-command Terraform apply wrapper.
- `scripts/smoke_test.ps1`: Quick API smoke-test wrapper.
- `scripts/destroy_infra.ps1`: One-command Terraform destroy wrapper.
- `docs/operational-checklist.md`: Pre/post-deploy operator checklist.

## Prerequisites

- AWS account and configured CLI credentials.
- IAM permissions to create and manage S3, Lambda, API Gateway, CloudWatch Logs/Metrics, and IAM roles/policies.
- Terraform `>= 1.6`.
- Python `3.11` for packaging compatibility.
- OpenAI API key.

## Step-by-Step Setup

### 1) Store OpenAI key in SSM as SecureString

Choose a parameter name and keep it identical in Terraform.

```bash
aws ssm put-parameter \
  --name "/serverless-rag/openai-api-key" \
  --type "SecureString" \
  --value "YOUR_OPENAI_API_KEY" \
  --overwrite
```

### 2) Create `terraform.tfvars`

From `infra/`:

```bash
cp terraform.tfvars.example terraform.tfvars
```

Edit at least these fields:
- `aws_region`
- `project_name`
- `runbooks_bucket_name` (globally unique)
- `openai_api_key_parameter_name` (exact SSM parameter name)
- `runbook_prefix` (for example `runbooks/`)

Optional tuning knobs:
- `chunk_size_tokens` (default `500`)
- `chunk_overlap_tokens` (default `50`)
- `top_k` (default `4`)
- `metrics_namespace` (default `ServerlessRag`)

### 3) Build Lambda package

From repository root:

```bash
rm -rf build/package build/lambda.zip
mkdir -p build/package
pip install -r app/requirements.txt -t build/package
cp app/src/lambda_function.py build/package/
cd build/package && zip -r ../lambda.zip .
```

Why this exists: Terraform deploys `build/lambda.zip` directly (`infra/main.tf`), so packaging must happen before `terraform apply`.

### 4) Provision infrastructure

From `infra/`:

```bash
terraform init
terraform apply
```

Capture output value:
- `api_base_url`

### 5) Upload your runbooks

```bash
aws s3 cp ./my-runbooks s3://<your-runbooks-bucket>/<runbook-prefix> --recursive
```

Example:

```bash
aws s3 cp ./my-runbooks s3://my-rag-runbooks-123/runbooks/ --recursive
```

### 6) Test endpoint with curl

```bash
curl -X POST "<api_base_url>/query" \
  -H "Content-Type: application/json" \
  -d '{"question":"How do I rotate credentials for the payment service?"}'
```

Expected successful response shape:

```json
{
  "answer": "Rotate credentials by ... [source: runbooks/credentials.md]",
  "citations": [
    "runbooks/credentials.md"
  ],
  "retrieved_chunks": [
    {
      "source": "runbooks/credentials.md",
      "chunk_id": 2,
      "distance": 0.143
    }
  ]
}
```

Expected validation error if question is missing:

```json
{
  "error": "Request body must include a non-empty 'question'"
}
```

## Security Decisions (Replicators Should Keep)

- OpenAI API key is fetched at runtime from SSM SecureString, not passed as Terraform variable value.
- Lambda IAM policy is scoped to:
  - one runbooks bucket/prefix
  - one SSM parameter ARN
- `cloudwatch:PutMetricData` is constrained by metrics namespace condition.

## Metrics and Verification

CloudWatch custom metrics written per request:
- `QueryLatencyMs` (`Milliseconds`)
- `OpenAITokenCount` (`Count`)

Check recent datapoints quickly:

```bash
aws cloudwatch get-metric-statistics \
  --namespace ServerlessRag \
  --metric-name QueryLatencyMs \
  --start-time 2026-01-01T00:00:00Z \
  --end-time 2026-12-31T23:59:59Z \
  --period 300 \
  --statistics Average
```

## CI/CD with GitHub Actions

Workflow file: `.github/workflows/deploy.yml`

Required repository secrets:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `PROJECT_NAME`
- `RUNBOOKS_BUCKET_NAME`
- `OPENAI_API_KEY_PARAMETER_NAME`
- `RUNBOOK_PREFIX`
- `CHUNK_SIZE_TOKENS`
- `CHUNK_OVERLAP_TOKENS`
- `METRICS_NAMESPACE`

Pipeline behavior:
1. Build Lambda artifact.
2. Run `terraform plan`.
3. Run `terraform apply` on `main`.

## Troubleshooting

### Terraform apply fails with `iam:CreateRole` AccessDenied

Your AWS identity cannot create IAM roles. Ask for permissions to:
- create/update/delete IAM role
- attach/update inline role policy

This is the most common blocker in restricted student/lab subscriptions.

### Lambda import errors in editor (`faiss`, `tiktoken`, `openai`)

Usually your editor is not using the project virtual environment. Select the interpreter where `app/requirements.txt` was installed.

### API returns `502` with SSM error

Confirm the parameter name in Terraform exactly matches the SSM key name and the Lambda role can read that parameter ARN.

### API returns `400` saying no runbooks found

Verify S3 bucket, prefix, and uploaded files. Prefix mismatch is common.

## Cleanup (Avoid Charges)

From `infra/`:

```bash
terraform destroy
```

Recommended post-check:
- confirm API no longer exists
- confirm bucket is deleted or empty
- confirm Lambda and log group are gone

## Free Trial Safe End-to-End (One Query Then Destroy)

If you are on AWS free trial or a constrained student account, run this exact flow to prove the project and minimize cost exposure:

1. Verify blockers before deploy:
  - your IAM identity can create roles (`iam:CreateRole`, `iam:PassRole`, attach/inline role policy actions)
  - SSM SecureString exists at `openai_api_key_parameter_name`
2. Build package once and run `terraform apply`.
3. Upload a tiny runbook set (1-3 small files) to your configured prefix.
4. Send exactly one `POST /query` request.
5. Verify one datapoint appears for:
  - `QueryLatencyMs`
  - `OpenAITokenCount`
6. Immediately run `terraform destroy`.
7. Run post-checks to confirm no billable resources remain.

Post-check examples:

```bash
aws apigatewayv2 get-apis --query "Items[?contains(Name, 'serverless-rag')]"
aws s3api head-bucket --bucket <your-runbooks-bucket>
```

If `head-bucket` still succeeds, empty and delete bucket:

```bash
aws s3 rm s3://<your-runbooks-bucket> --recursive
aws s3api delete-bucket --bucket <your-runbooks-bucket> --region <aws_region>
```

## What I'd do differently at scale

1. Move vector retrieval from FAISS-in-Lambda to a managed vector store.
   - Current approach is simple and fast for MVP.
   - At scale, managed vector DB gives durable shared indexes across concurrent workers.

2. Split ingestion from query serving.
   - Current Lambda can pay a heavy cold/index refresh penalty.
   - Better design: async indexing pipeline on S3 changes, thin query path for lower p95 latency.
