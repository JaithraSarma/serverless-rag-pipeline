
import os
import json
import sys
from unittest.mock import MagicMock, patch

# Set environment variables required by lambda_function.py
os.environ["S3_BUCKET"] = "test-bucket"
os.environ["OPENAI_API_KEY_SSM_PARAM"] = "/test/openai-key"
os.environ["RUNBOOK_PREFIX"] = "runbooks/"

# Mocking boto3 and OpenAI before importing the lambda function
with patch("boto3.client") as mock_boto3_client, \
     patch("openai.OpenAI") as mock_openai:
    
    # Setup S3 mock
    mock_s3 = MagicMock()
    mock_boto3_client.return_value = mock_s3 # This is a bit broad, but we can refine
    
    # We need to handle different clients if we want to be precise
    def side_effect(service_name, **kwargs):
        mock = MagicMock()
        if service_name == "s3":
            # Mock list_objects_v2 paginator
            paginator = MagicMock()
            paginator.paginate.return_value = [
                {
                    "Contents": [
                        {"Key": "runbooks/test1.md", "ETag": "tag1", "Size": 100},
                        {"Key": "runbooks/test2.md", "ETag": "tag2", "Size": 200}
                    ]
                }
            ]
            mock.get_paginator.return_value = paginator
            
            # Mock get_object
            def get_obj_side_effect(Bucket, Key):
                content = f"Content of {Key}. This is a test runbook for credential rotation."
                return {"Body": MagicMock(read=lambda: content.encode("utf-8"))}
            mock.get_object.side_effect = get_obj_side_effect
            return mock
        elif service_name == "ssm":
            mock.get_parameter.return_value = {
                "Parameter": {"Value": "mock-api-key"}
            }
            return mock
        elif service_name == "cloudwatch":
            return mock
        return mock

    mock_boto3_client.side_effect = side_effect
    
    # Setup OpenAI mock
    mock_oa_client = MagicMock()
    mock_openai.return_value = mock_oa_client
    
    # Mock embeddings
    mock_oa_client.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1] * 1536)]
    )
    
    # Mock chat completions
    mock_oa_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="To rotate credentials, use the aws cli [source: runbooks/test1.md]"))],
        usage=MagicMock(total_tokens=100)
    )

    # Now import the lambda function
    # We need to add the src directory to sys.path
    sys.path.append(os.path.abspath("app/src"))
    import lambda_function

    # Create a mock event
    event = {
        "body": json.dumps({"question": "How do I rotate credentials?"})
    }
    
    print("Starting test run of lambda_handler...")
    response = lambda_function.lambda_handler(event, None)
    
    print("\nResponse Status Code:", response["statusCode"])
    print("Response Body:")
    print(json.dumps(json.loads(response["body"]), indent=2))

    # Verify if it worked as expected
    body = json.loads(response["body"])
    if response["statusCode"] == 200 and "answer" in body:
        print("\nTest Run SUCCESSFUL!")
    else:
        print("\nTest Run FAILED!")
        sys.exit(1)
