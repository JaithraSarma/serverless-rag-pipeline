# Credential Rotation Runbook

1. Disable new login sessions for the service account.
2. Create a new credential and store it in your secret manager.
3. Update downstream services to use the new credential.
4. Validate traffic and error rate for 15 minutes.
5. Revoke the old credential and capture audit evidence.
