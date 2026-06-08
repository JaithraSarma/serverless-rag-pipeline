
import os
import json
import sys
from unittest.mock import MagicMock, patch

# Set environment variables required by lambda_function.py
os.environ["S3_BUCKET"] = "serverless-rag-test-bucket"
os.environ["OPENAI_API_KEY_SSM_PARAM"] = "/serverless-rag/openai-api-key"
os.environ["RUNBOOK_PREFIX"] = "runbooks/"

# Load real sample content
runbook_path = "app/sample-runbooks/credential-rotation.md"
with open(runbook_path, "r", encoding="utf-8") as f:
    sample_content = f.read()

# Mocking boto3 and OpenAI
with patch("boto3.client") as mock_boto3_client, \
     patch("openai.OpenAI") as mock_openai:
    
    def side_effect(service_name, **kwargs):
        mock = MagicMock()
        if service_name == "s3":
            paginator = MagicMock()
            paginator.paginate.return_value = [{"Contents": [{"Key": "runbooks/credential-rotation.md", "ETag": "abc", "Size": 316}]}]
            mock.get_paginator.return_value = paginator
            mock.get_object.return_value = {"Body": MagicMock(read=lambda: sample_content.encode("utf-8"))}
            return mock
        elif service_name == "ssm":
            mock.get_parameter.return_value = {"Parameter": {"Value": "sk-mock-key"}}
            return mock
        elif service_name == "cloudwatch":
            return mock
        return mock

    mock_boto3_client.side_effect = side_effect
    
    mock_oa_client = MagicMock()
    mock_openai.return_value = mock_oa_client
    mock_oa_client.embeddings.create.return_value = MagicMock(data=[MagicMock(embedding=[0.1] * 1536)])
    mock_oa_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="To rotate credentials safely, disable sessions, create new secrets, update services, validate for 15 mins, and revoke old ones. [source: runbooks/credential-rotation.md]"))],
        usage=MagicMock(total_tokens=142)
    )

    sys.path.append(os.path.abspath("app/src"))
    import lambda_function

    event = {"body": json.dumps({"question": "How do I rotate credentials?"})}
    
    print(">>> INVOKING LAMBDA HANDLER")
    response = lambda_function.lambda_handler(event, None)
    
    print(f"\n>>> STATUS: {response['statusCode']}")
    print(">>> BODY:")
    print(json.dumps(json.loads(response["body"]), indent=2))
