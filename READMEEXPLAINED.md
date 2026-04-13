# Serverless RAG Explained End-to-End (Interview Master Guide)

This is the complete project narrative I would use in interviews to explain not just what I built, but why I built it this way, what tradeoffs I accepted, and how I would evolve it in production.

If someone asks anything from architecture to IAM to retrieval quality to cost controls, this guide prepares you to answer with confidence.

## 1. Problem and Goal

I wanted a system where engineers can ask infrastructure questions in plain English and get answers grounded in operational runbooks.

The system must:
- read runbooks from S3,
- retrieve relevant context using embeddings + vector search,
- generate a concise answer,
- cite source documents,
- and expose everything through a simple API.

Non-negotiable constraints in this implementation:
- No LangChain for embeddings/retrieval.
- OpenAI API key stored in SSM SecureString and fetched at runtime.
- Lambda IAM role scoped to one bucket and one SSM parameter.
- Emit custom metrics for latency and token count.
- Chunking defaults start at 500 with 50 overlap, tunable via environment variables.

## 2. Architecture in One Sentence

S3 stores runbooks, Lambda builds/reuses a FAISS index and answers queries using OpenAI, API Gateway exposes `POST /query`, Terraform provisions infra, and CloudWatch tracks latency/token usage.

## 3. Full Request Lifecycle

When a client calls `POST /query` with `{ "question": "..." }`, this is what happens:

1. API Gateway receives request and forwards it to Lambda using AWS proxy integration.
2. Lambda parses JSON body and validates `question` is non-empty.
3. Lambda lists objects in configured S3 bucket/prefix.
4. Lambda computes a manifest hash from object metadata (key, ETag, size).
5. Lambda checks cache:
   - if manifest unchanged, reuse cached FAISS index/chunks,
   - otherwise download runbooks, chunk text, embed chunks, and rebuild FAISS index.
6. Lambda embeds the user question.
7. Lambda retrieves top-k nearest chunks from FAISS.
8. Lambda prompts `gpt-3.5-turbo` with retrieved context and strict grounding instructions.
9. Lambda returns:
   - answer,
   - citations,
   - retrieved chunk metadata.
10. Lambda emits CloudWatch metrics in `finally` block:
    - `QueryLatencyMs`
    - `OpenAITokenCount`

## 3A. Companion Files You Should Know

These files make day-2 operations and demos easier:

- `app/events/query_request.json`: Known-good payload for API testing.
- `app/events/query_request_empty.json`: Negative test payload for 400 handling.
- `app/sample-runbooks/credential-rotation.md`: Seed runbook content for first retrieval checks.
- `scripts/package_lambda.ps1`: Builds `build/lambda.zip` locally.
- `scripts/deploy_infra.ps1`: Applies Terraform quickly.
- `scripts/smoke_test.ps1`: Sends a test query to the deployed API.
- `scripts/destroy_infra.ps1`: Destroys the stack to control costs.
- `docs/operational-checklist.md`: Checklist to avoid missing critical deploy/cleanup steps.
- `docs/interview-quick-revision.md`: Last-minute summary before interviews.

## 4. Why Each Technology Was Chosen

### S3 for runbooks
- Cheap, durable, and simple object storage.
- Works naturally with text files (`.md`, `.txt`).

### Lambda for query execution
- Zero server management.
- Pay-per-use works well for irregular query volume.

### API Gateway HTTP API
- Lightweight front door for Lambda.
- Easy route model (`POST /query`).

### OpenAI embeddings + chat
- Embeddings map text and queries to a semantic vector space.
- Chat model synthesizes user-friendly answer from retrieved context.

### FAISS
- Fast, local vector search.
- Good MVP choice for small/medium corpora.

### Terraform
- Reproducible infra, auditable IAM, consistent environments.

### GitHub Actions
- Automated build/deploy path from commit to cloud.

## 5. Security Model (What Interviewers Care About)

### Secret management
- OpenAI API key is not in code.
- It is not passed as plain Terraform variable content.
- Lambda fetches SecureString at runtime via `ssm:GetParameter` with decryption.

### Least privilege IAM
Lambda role allows only:
- `s3:ListBucket` on exactly the runbooks bucket (with prefix condition).
- `s3:GetObject` on only the runbook objects path.
- `ssm:GetParameter` on one exact parameter ARN.
- log writes to the Lambda log group.
- `cloudwatch:PutMetricData` constrained by metrics namespace.

### Practical IAM nuance
CloudWatch metric writes use `Resource: "*"` because `PutMetricData` does not support resource-level ARNs. The scope is narrowed by namespace condition.

This is a good example to discuss in interviews: practical least privilege means using the narrowest control mechanism the API supports.

## 6. Data and Retrieval Pipeline

### 6.1 Input corpus
Runbooks are plain text/markdown files in S3.

### 6.2 Chunking
Token-based chunking is used because LLM cost/context constraints are token-based.

Defaults:
- chunk size = 500
- overlap = 50

Why overlap exists:
- procedures often span boundaries,
- overlap reduces semantic fragmentation,
- improves retrieval precision for multi-step instructions.

### 6.3 Embedding
- Embedding model default is `text-embedding-3-small`.
- Embeddings are requested in batches to reduce API overhead.
- Stored in `float32` for FAISS compatibility.

### 6.4 Vector search
- Uses FAISS `IndexFlatL2` exact nearest-neighbor search.
- Returns top-k chunks (default `4`).

### 6.5 Caching
There are two cache layers:
- in-memory process cache,
- `/tmp` cache files (`index.faiss`, `chunks.json`, `manifest.json`).

Manifest hash invalidates cache when runbooks change.

### 6.6 Retriever TODO and scale tradeoff
The code includes an intentional TODO to swap FAISS-in-Lambda for a managed vector DB at higher scale.

Tradeoff summary:
- FAISS-in-Lambda is cheaper and simple for MVP.
- Managed vector DB costs more but gives shared, durable, centrally managed indexes and better multi-instance behavior.

## 7. Prompting and Grounding Strategy

The prompt design intentionally restricts the model:
- answer only from provided runbook context,
- if context is insufficient, admit uncertainty,
- include source citations.

Grounding behavior is not just a model property; it is enforced by retrieval + prompt framing + citation output contract.

## 8. API Contract

### Request

```json
{
  "question": "How do I rotate credentials for the payment service?"
}
```

### Success response (200)

```json
{
  "answer": "... [source: runbooks/credentials.md]",
  "citations": ["runbooks/credentials.md"],
  "retrieved_chunks": [
    {
      "source": "runbooks/credentials.md",
      "chunk_id": 2,
      "distance": 0.143
    }
  ]
}
```

### Common error responses
- `400` invalid request or no readable runbooks.
- `502` AWS API error (for example S3 or SSM issue).
- `500` unexpected runtime failure.

## 9. Observability and Cost Awareness

Per query, Lambda emits:
- `QueryLatencyMs` for response-time tracking.
- `OpenAITokenCount` for usage/cost visibility.

How to explain this in interview:
- latency tells user experience health,
- token count correlates directly with model spend,
- together they let you detect both performance and cost regressions early.

## 10. Terraform Deep Dive

Resources provisioned:
- S3 bucket for runbooks.
- IAM role + inline least-privilege policy for Lambda.
- Lambda function using `build/lambda.zip`.
- CloudWatch log group.
- API Gateway HTTP API + integration + route + stage.
- Lambda permission for API invocation.

Important implementation details:
- Lambda `source_code_hash` tracks package changes for deterministic updates.
- timeout defaults to 30s because query path can include S3 reads + OpenAI calls.
- memory defaults to 1024 MB because FAISS/index operations benefit from extra CPU allocation tied to memory.

## 11. CI/CD Deep Dive

Pipeline responsibilities:
1. Build Lambda artifact.
2. Initialize Terraform backend/providers.
3. Plan infrastructure drift/changes.
4. Apply on main branch.

How to discuss maturity:
- this is a practical single-environment pipeline,
- production systems typically add environment promotion, approvals, policy-as-code, and rollback playbooks.

## 12. Failure Modes and Debugging Playbook

### IAM AccessDenied during apply
Symptom: Terraform fails creating IAM role/policy.

Interpretation:
- deployment principal lacks role-management permissions.

Fix:
- grant IAM create/update/delete role and attach inline policy rights.

### Query endpoint returns 400 no runbooks
Symptom: runbooks not found/readable.

Likely causes:
- wrong bucket,
- wrong prefix,
- empty files only.

### Query endpoint returns 502 SSM error
Symptom: SSM lookup fails.

Likely causes:
- parameter name mismatch,
- missing `ssm:GetParameter` permission on exact ARN.

### Slow first request
Symptom: first query slower than warm requests.

Reason:
- cache cold, index rebuild needed.

## 13. Performance and Cost Characteristics

Latency is a function of:
- S3 listing/download time,
- embedding generation time,
- FAISS retrieval time,
- chat completion time.

Cost is mostly model usage:
- embedding tokens during index refresh,
- chat tokens per query.

Operationally, this architecture is cheap for modest traffic but has predictable bottlenecks at larger scale.

## 14. What I Would Do Differently at Scale

1. Decouple indexing from query path.
   - Build index asynchronously on S3 object updates.
   - Keep query path fast and deterministic.

2. Move to managed vector infrastructure.
   - Avoid per-instance FAISS cache fragmentation.
   - Gain durability, sharing, and operational controls.

## 15. Interview Storyline (Use This Verbatim if Needed)

Start with this framing:
"I built a serverless RAG API for infrastructure runbooks. The API accepts plain-English questions, retrieves semantically relevant runbook chunks from S3 using OpenAI embeddings and FAISS, then generates a grounded answer with citations."

Then show engineering judgment:
- "I intentionally avoided LangChain to keep package size and abstraction overhead low."
- "I used SSM SecureString and runtime fetch for key security."
- "IAM was scoped to one bucket and one parameter for least privilege."
- "I emitted latency and token metrics per query for performance/cost tracking."

Then show maturity:
- "For scale, I would split ingestion and query and move vectors to a managed store."

## 16. Tough Interview Questions and Strong Answers

### Why did you choose FAISS over a managed vector DB?
For MVP speed, cost, and control. It avoids another service dependency. I also documented the exact migration path once concurrency/volume grows.

### How do you reduce hallucinations?
I constrain generation to retrieved context, require citations, and return retrieval metadata to audit grounding quality.

### How is security handled end to end?
No secrets in code, runtime secret fetch from SSM, least-privilege role scoped to specific resources, CloudWatch metrics namespace scoped.

### How do you reason about chunk size tuning?
I start with 500/50 as a balanced baseline for procedural docs, then tune based on retrieval hit quality, answer completeness, latency, and token cost.

### What would you instrument next?
I would add p95/p99 latency dimensions, cache-hit metrics, retrieval quality traces, and alerting thresholds tied to error rate and token spikes.

## 17. Practical Demo Plan (5 Minutes)

1. Show a runbook file in S3.
2. Call `POST /query` with curl.
3. Show answer and citation path.
4. Show CloudWatch metrics datapoints.
5. Explain one design tradeoff and one scale improvement.

If you do this cleanly, interviewers will see both implementation depth and system thinking.

## 18. Mock Interview Round (25 High-Probability Questions)

Use this section as a practice script. Answer out loud in your own words, but keep the technical structure.

### 1. What problem does this project solve?
It gives engineers a plain-English way to query operational runbooks. Instead of searching manually, the system retrieves semantically relevant runbook sections and returns a grounded answer with citations.

### 2. Why did you build this as RAG instead of fine-tuning?
Runbooks change often. RAG lets me update source documents without retraining a model. It is faster to iterate, easier to operate, and cheaper for this use case.

### 3. Why serverless for this workload?
Query traffic is usually bursty and unpredictable. Lambda + API Gateway gives pay-per-use economics and minimal ops overhead while still giving enough flexibility for a retrieval pipeline.

### 4. Why no LangChain?
I intentionally avoided LangChain to keep package size and dependency complexity low. I only needed direct embedding calls, chunking, FAISS indexing, and prompt construction, so custom code was leaner and easier to reason about.

### 5. Walk me through a single request.
API Gateway receives POST /query, invokes Lambda, Lambda validates input, loads or rebuilds vector index from S3 runbooks, embeds the question, retrieves top-k chunks via FAISS, asks the chat model to answer from that context, returns answer plus citations, then emits latency and token metrics.

### 6. How do you ensure answer grounding?
Grounding comes from three controls: retrieval-first architecture, strict prompt instructions to answer only from context, and citation output contract. If context is insufficient, the model is instructed to say so.

### 7. How do citations work?
Each retrieved chunk carries source metadata, usually the S3 object key. The response includes cited source keys so users can verify claims against original runbooks.

### 8. Why token-based chunking with overlap?
Model constraints and costs are token-based, so chunking is token-based too. Overlap reduces boundary loss where procedures span chunk edges, improving retrieval quality.

### 9. Why 500 chunk size and 50 overlap?
It is a practical baseline for operational docs: large enough for procedural continuity, small enough to stay retrieval-efficient. I made both values environment variables so tuning is deployment-time, not code-time.

### 10. Why FAISS IndexFlatL2?
It gives exact nearest-neighbor search and predictable behavior, which is useful for correctness in an MVP. It is simple and fast for modest corpus sizes.

### 11. What are FAISS limitations here?
Index lives with the Lambda runtime cache, so instances do not share one durable global index. Under high concurrency or frequent cold starts, cache behavior becomes less predictable, which is why migration to a managed vector store is the next scale step.

### 12. How is secret management done safely?
OpenAI API key is stored as SecureString in SSM Parameter Store. Lambda retrieves and decrypts it at runtime using scoped IAM permission. No hardcoded secret and no Terraform variable plaintext for the key.

### 13. Explain your least-privilege IAM design.
Lambda can list/read only one specific runbooks bucket/prefix, read only one specific SSM parameter, write logs to its log group, and publish metrics under a constrained namespace. No broad wildcard access to data resources.

### 14. Why custom CloudWatch metrics?
I emit QueryLatencyMs and OpenAITokenCount because they map directly to user experience and cost. This gives immediate visibility for performance regressions and spend spikes.

### 15. What does a healthy response look like?
A 200 JSON containing answer text, citations array, and retrieved chunk metadata. This makes the response both useful to users and auditable for trust.

### 16. What are expected error classes?
400 for invalid question input or no usable corpus, 502 for upstream AWS API failures like S3 or SSM integration errors, and 500 for unexpected runtime failures.

### 17. How do you handle runbook updates?
I compute a manifest hash from S3 object metadata. If it changes, the in-memory and /tmp cached index is invalidated and rebuilt. If unchanged, cached index is reused for faster responses.

### 18. What is the cold start impact?
Cold starts plus index rebuild can increase first-query latency, especially when corpus size grows. Warm invocations are faster due to cache reuse.

### 19. Why 30-second Lambda timeout and 1024 MB memory?
Timeout accounts for S3 IO + embedding calls + chat completion in one request path. Higher memory gives more CPU share, which helps vector operations and reduces tail latency.

### 20. How do you reason about cost?
Primary cost drivers are model tokens and request volume. Embedding cost spikes on re-index, chat cost scales per query. Token metric plus latency trend gives a practical FinOps feedback loop.

### 21. What security risks remain?
Prompt injection risk from malicious document content, over-broad IAM drift if policies are changed casually, and accidental data exposure if runbooks contain sensitive content without classification controls.

### 22. How would you harden this for production?
Decouple ingestion from query, move vectors to managed storage, add authN/authZ at API layer, implement rate limiting and WAF, add structured tracing, and enforce CI policy checks for IAM/security regressions.

### 23. How would you improve retrieval quality?
Add hybrid retrieval (keyword + vector), reranking stage, better chunk boundary heuristics, and offline evaluation sets that measure citation correctness and answer faithfulness.

### 24. How would you test this system?
Unit tests for chunking/parsing/retrieval logic, integration tests for Lambda handler with mocked AWS/OpenAI, contract tests for API responses, and load tests for latency/cost behavior under concurrency.

### 25. If an interviewer asks your biggest engineering tradeoff, what do you say?
I optimized for simplicity, learning velocity, and low operational overhead first. That meant accepting FAISS-in-Lambda limitations. I documented the exact migration path to managed vector infrastructure once scale justifies it.

## 19. Complete Configuration Matrix (Everything You Can Tune)

Use this section as the single source of truth for all deploy-time settings.

### Terraform variables

1. `project_name`
- What it affects: naming of Lambda/API/IAM resources.
- Why it exists: keeps environments isolated and avoids name collisions.

2. `aws_region`
- What it affects: where all resources are created.
- Why it exists: latency, service availability, and free-tier usage all depend on region.

3. `runbooks_bucket_name`
- What it affects: S3 storage location for documents.
- Why it exists: S3 bucket names are globally unique and must be explicit.

4. `runbooks_prefix`
- What it affects: which folder path Lambda scans inside the bucket.
- Why it exists: lets one bucket hold multiple datasets safely.

5. `openai_api_key_parameter_name`
- What it affects: which SSM SecureString Lambda reads.
- Why it exists: secret is rotated/managed outside code.

6. `lambda_timeout_seconds`
- What it affects: max runtime per request.
- Why it exists: retrieval + model calls are network-bound and need headroom.

7. `lambda_memory_mb`
- What it affects: memory and proportional CPU for vector operations.
- Why it exists: faster FAISS operations generally need more CPU share.

8. `chunk_size_tokens`
- What it affects: retrieval granularity.
- Why it exists: larger chunks preserve context but can reduce precision.

9. `chunk_overlap_tokens`
- What it affects: continuity across chunk boundaries.
- Why it exists: avoids losing steps split between adjacent chunks.

10. `embedding_model`
- What it affects: vector quality, latency, and embedding cost.
- Why it exists: model upgrades should be config-driven, not code-driven.

11. `chat_model`
- What it affects: answer quality, token usage, and response time.
- Why it exists: lets you balance quality and cost.

### Lambda environment variables (applied via Terraform)

1. `RUNBOOKS_BUCKET`
2. `RUNBOOKS_PREFIX`
3. `OPENAI_API_KEY_PARAMETER_NAME`
4. `CHUNK_SIZE_TOKENS`
5. `CHUNK_OVERLAP_TOKENS`
6. `EMBEDDING_MODEL`
7. `CHAT_MODEL`
8. `METRICS_NAMESPACE`

Why this matters in interviews: this separation shows operational maturity. Code stays stable while behavior is tuned by configuration.

## 20. Click-by-Click AWS Console Walkthrough

This section explains exactly what to click and what to expect on each screen.

### A. Create the OpenAI SecureString in SSM

1. Open AWS Console.
2. Search for `Systems Manager`.
3. In left nav: `Application Management` -> `Parameter Store`.
4. Click `Create parameter`.
5. Set `Name` to `/serverless-rag/openai-api-key`.
6. Set `Tier` to `Standard`.
7. Set `Type` to `SecureString`.
8. Keep default KMS key unless your org requires a custom key.
9. Paste OpenAI key in `Value`.
10. Click `Create parameter`.

Expected result:
- Parameter appears in list with Type `SecureString`.

### B. Upload runbooks to S3

1. Open `S3` in console.
2. Click your project bucket.
3. Click `Create folder` and create `runbooks/` (if not already present).
4. Open `runbooks/`.
5. Click `Upload`.
6. Add `.md`/`.txt` runbook files.
7. Click `Upload`.

Expected result:
- Objects are visible under `runbooks/` with non-zero file size.

### C. Verify Lambda deployment

1. Open `Lambda`.
2. Click function named like `serverless-rag-...-query`.
3. Open `Configuration` -> `Environment variables`.
4. Confirm bucket, prefix, chunk settings, and SSM parameter name are correct.
5. Open `Monitoring` tab.

Expected result:
- Function exists and environment config matches Terraform values.

### D. Verify API Gateway route

1. Open `API Gateway`.
2. Select HTTP API named like `serverless-rag-...-api`.
3. Open `Routes`.
4. Confirm `POST /query` exists.
5. Open `Stages` and copy invoke URL.

Expected result:
- Route `POST /query` is attached to Lambda integration.

### E. Verify CloudWatch logs and metrics

1. Open `CloudWatch`.
2. For logs: `Logs` -> `Log groups` -> `/aws/lambda/<function-name>`.
3. Open latest stream and check invocation details.
4. For metrics: `Metrics` -> `All metrics` -> `Custom namespaces`.
5. Open namespace `ServerlessRag` (or configured namespace).
6. Confirm metrics `QueryLatencyMs` and `OpenAITokenCount`.

Expected result:
- At least one datapoint for both metrics after query test.

## 21. End-to-End Input/Output Matrix

### System inputs

1. Document input
- Location: S3 bucket + prefix.
- Format: UTF-8 `.md` or `.txt`.
- Behavior: files are chunked and indexed.

2. User query input
- API: `POST /query`.
- Body: `{ "question": "<plain English question>" }`.
- Behavior: query is embedded and searched against indexed chunks.

3. Secret input
- Source: SSM SecureString.
- Behavior: fetched at runtime for OpenAI calls.

### System outputs

1. API success output (HTTP 200)
- `answer`: grounded response text.
- `citations`: source keys used for grounding.
- `retrieved_chunks`: chunk metadata and distance for auditability.

2. API error outputs
- `400`: invalid payload or no usable runbooks.
- `502`: upstream AWS/API dependency issue.
- `500`: unexpected runtime exception.

3. Telemetry outputs
- `QueryLatencyMs` metric per request.
- `OpenAITokenCount` metric per request.
- CloudWatch logs per invocation.

## 22. Operator Playbook: What To Do If X Happens

### Scenario 1: Deploy fails with IAM AccessDenied

1. Check Terraform output for denied IAM action.
2. Confirm deploy identity has `iam:CreateRole`, `iam:PassRole`, role policy attach/update permissions.
3. Re-run `terraform apply` after permissions are fixed.

### Scenario 2: API returns 400 no runbooks

1. Check bucket and prefix values in Lambda env.
2. Confirm files exist in S3 path and are readable text.
3. Re-test with a known valid runbook file.

### Scenario 3: API returns 502 with SSM issue

1. Verify parameter path exactly matches env value.
2. Confirm parameter type is `SecureString`.
3. Confirm Lambda role has `ssm:GetParameter` on that ARN.

### Scenario 4: No custom metrics visible

1. Trigger at least one successful query.
2. Wait 1-2 minutes for metric ingestion.
3. Confirm namespace value in Lambda env matches what you search in CloudWatch.

### Scenario 5: Cost concerns during testing

1. Run one query only.
2. Validate logs/metrics.
3. Run `terraform destroy` immediately.
4. Verify API and bucket no longer exist.
