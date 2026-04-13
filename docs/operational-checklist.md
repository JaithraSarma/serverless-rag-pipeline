# Operational Checklist

## Before Deploy
- Confirm AWS CLI identity with aws sts get-caller-identity.
- Confirm SSM parameter /serverless-rag/openai-api-key exists in the target region.
- Confirm terraform.tfvars has a globally unique bucket name.

## After Deploy
- Upload runbooks to the configured prefix.
- Send one test query and confirm citations are returned.
- Verify CloudWatch metrics QueryLatencyMs and OpenAITokenCount.

## Before Shutdown
- Export any logs you need for demo evidence.
- Run terraform destroy.
- Verify API and bucket are removed.
