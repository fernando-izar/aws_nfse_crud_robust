# NFS-e (Robusta r2) – Python CDK
Infra com S3+CloudFront(+WAF), API Gateway(+UsagePlan), Lambdas, Cognito, DynamoDB, SQS+StepFunctions.
Cuidado: use região correta e destrua quando não for usar.

## Deploy
cd infra
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm i -g aws-cdk
cdk bootstrap
cdk deploy
