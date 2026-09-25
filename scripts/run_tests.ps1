param([ValidateSet('unit','postgres','scenarios','security','contracts','all')][string]$Mode='all')
$ErrorActionPreference = 'Stop'
$env:ENVIRONMENT = 'test'
if (-not $env:TRACEQ_TEST_DATABASE_URL) { $env:TRACEQ_TEST_DATABASE_URL = 'postgresql+psycopg://traceq_test:traceq_test@127.0.0.1:55433/traceq_test' }
& bash "$PSScriptRoot/run_tests.sh" $Mode
exit $LASTEXITCODE
