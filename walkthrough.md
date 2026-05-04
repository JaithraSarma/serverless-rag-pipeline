# Serverless RAG Pipeline: Deployment Walkthrough

This guide provides a step-by-step walkthrough of how to deploy and verify the Serverless RAG Pipeline using either GitHub Actions or AWS Native services.

## Phase 1: Local Verification (Recommended)

Before deploying to the cloud, ensure your core logic is sound:

1.  **Install Dependencies**:
    ```bash
    pip install -r app/requirements.txt
    ```
2.  **Run Mock Test**:
    ```bash
    python scripts/test_lambda_local.py
    ```
    Verify that you see a `200 OK` response with a grounded answer and citation.

---

## Phase 2: Choose Your Deployment Path

### Option A: GitHub Actions (Standard)

Use this if you want to keep your CI/CD visible in your GitHub repository.

1.  **Configure Secrets**: Add the following secrets to your GitHub repository settings:
    - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `OPENAI_API_KEY_PARAMETER_NAME`, etc. (See README for full list).
2.  **Push Code**: Push your changes to the `main` branch.
3.  **Monitor**: Go to the **Actions** tab in GitHub to watch the build and deploy process.

### Option B: AWS Native CI/CD (Enterprise-Style)

Use this to keep all operations within the AWS security boundary.

1.  **Initial Provisioning**: Run Terraform manually once to create the pipeline:
    ```bash
    cd infra
    terraform init
    terraform apply
    ```
2.  **Setup CodeCommit**:
    - Retrieve the CodeCommit clone URL from the Terraform outputs.
    - Add it as a remote: `git remote add aws <URL>`.
3.  **Deploy**: Push your code to AWS:
    ```bash
    git push aws main
    ```
    AWS CodePipeline will automatically trigger the build and deploy.

---

## Phase 3: Post-Deployment Verification

1.  **Upload Runbooks**:
    ```bash
    aws s3 cp ./app/sample-runbooks/ s3://<your-bucket-name>/runbooks/ --recursive
    ```
2.  **Smoke Test**:
    Use the provided PowerShell script to test the live API:
    ```powershell
    .\scripts\smoke_test.ps1 -ApiUrl <your-api-url>
    ```

---

## Troubleshooting Tips

- **Lambda Errors?** Check CloudWatch Logs for the `/aws/lambda/serverless-rag-query` log group.
- **SSM Issues?** Ensure the OpenAI key is stored as a `SecureString` in the correct region.
- **Pipeline Failing?** Check the CodeBuild logs in the AWS Console for specific Terraform or Python errors.
