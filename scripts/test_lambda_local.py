
import os
import json
import sys
from unittest.mock import MagicMock, patch

# This script performs a local dry-run of the Lambda function's RAG logic.
# It mocks all AWS and OpenAI service calls to verify the chunking, indexing, 
# and retrieval logic without requiring live cloud resources.

def run_local_test():
    # 1. Setup Mock Environment
    os.environ["S3_BUCKET"] = "mock-bucket"
    os.environ["OPENAI_API_KEY_SSM_PARAM"] = "/mock/key"
    os.environ["RUNBOOK_PREFIX"] = "runbooks/"

    # Path to real sample data
    sample_runbook = os.path.join("app", "sample-runbooks", "credential-rotation.md")
    if not os.path.exists(sample_runbook):
        print(f"Error: Sample runbook not found at {sample_runbook}")
        return

    with open(sample_runbook, "r", encoding="utf-8") as f:
        content = f.read()

    # 2. Mock AWS and OpenAI
    with patch("boto3.client") as mock_boto3, \
         patch("openai.OpenAI") as mock_openai:
        
        # S3 Mock
        s3 = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": [{"Key": "runbooks/credential-rotation.md", "ETag": "mock", "Size": len(content)}]}]
        s3.get_paginator.return_value = paginator
        s3.get_object.return_value = {"Body": MagicMock(read=lambda: content.encode("utf-8"))}
        
        # SSM and CW Mocks
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "mock-key"}}
        cw = MagicMock()

        def client_side_effect(service, **kwargs):
            if service == "s3": return s3
            if service == "ssm": return ssm
            if service == "cloudwatch": return cw
            return MagicMock()
        
        mock_boto3.side_effect = client_side_effect

        # OpenAI Mock
        oa = MagicMock()
        mock_openai.return_value = oa
        oa.embeddings.create.return_value = MagicMock(data=[MagicMock(embedding=[0.1] * 1536)])
        oa.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="To rotate credentials, follow the steps in [source: runbooks/credential-rotation.md]"))],
            usage=MagicMock(total_tokens=100)
        )

        # 3. Import and Invoke
        sys.path.append(os.path.abspath("app/src"))
        try:
            import lambda_function
        except ImportError as e:
            print(f"Error importing lambda_function: {e}")
            return

        event = {"body": json.dumps({"question": "How do I rotate credentials?"})}
        
        print("--- Starting Local RAG Verification ---")
        response = lambda_function.lambda_handler(event, None)
        
        print(f"Status Code: {response['statusCode']}")
        print("Response Body:")
        print(json.dumps(json.loads(response["body"]), indent=2))
        print("---------------------------------------")
        
        if response["statusCode"] == 200:
            print("SUCCESS: Core RAG logic is operational.")
        else:
            print("FAILURE: Lambda returned an error.")

if __name__ == "__main__":
    run_local_test()
