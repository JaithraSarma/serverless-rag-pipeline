Param(
  [Parameter(Mandatory = $true)]
  [string]$ApiUrl,
  [string]$Question = "How do I rotate service account credentials safely?"
)

$body = @{ question = $Question } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$ApiUrl/query" -ContentType "application/json" -Body $body
