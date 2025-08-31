from typing import Any
from constructs import Construct
from aws_cdk import (
    Stack,
    CfnOutput,
    RemovalPolicy,
    Duration,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_cognito as cognito,
    aws_apigateway as apigw,
    aws_lambda as _lambda,
    aws_dynamodb as dynamodb,
    aws_sqs as sqs,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    aws_wafv2 as wafv2,
    aws_logs as logs,
)

import os


class RobustNfseStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # S3 + CloudFront (Admin) + WAF
        admin_bucket = s3.Bucket(
            self,
            "AdminSiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        oai = cloudfront.OriginAccessIdentity(self, "OAI")
        admin_bucket.grant_read(oai)

        cf_waf = wafv2.CfnWebACL(
            self,
            "CfWebAcl",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            scope="CLOUDFRONT",
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True,
                metric_name="cfWebAcl",
                sampled_requests_enabled=True,
            ),
            name="nfse-cf-waf",
        )
        distribution = cloudfront.Distribution(
            self,
            "AdminSiteDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(admin_bucket, origin_access_identity=oai),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
            web_acl_id=cf_waf.attr_arn,
        )

        # Docs bucket
        docs_bucket = s3.Bucket(
            self,
            "DocsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Cognito
        user_pool = cognito.UserPool(
            self,
            "Users",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8, require_lowercase=True, require_digits=True
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )
        user_pool_client = cognito.UserPoolClient(
            self,
            "UsersClient",
            user_pool=user_pool,
            generate_secret=False,
        )

        # DynamoDB
        invoices = dynamodb.Table(
            self,
            "InvoicesTable",
            partition_key=dynamodb.Attribute(
                name="invoiceId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )
        requests = dynamodb.Table(
            self,
            "RequestsTable",
            partition_key=dynamodb.Attribute(
                name="requestId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Lambdas
        common_env = {
            "TABLE_INVOICES": invoices.table_name,
            "TABLE_REQUESTS": requests.table_name,
            "BUCKET_DOCS": docs_bucket.bucket_name,
        }
        emit_fn = _lambda.Function(
            self,
            "EmitFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "lambdas/emit")
            ),
            environment=common_env,
            timeout=Duration.seconds(15),
        )
        get_fn = _lambda.Function(
            self,
            "GetFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "lambdas/consult")
            ),
            environment=common_env,
            timeout=Duration.seconds(10),
        )
        cancel_fn = _lambda.Function(
            self,
            "CancelFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "lambdas/cancel")
            ),
            environment=common_env,
            timeout=Duration.seconds(10),
        )
        ping_fn = _lambda.Function(
            self,
            "PingFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "lambdas/ping")
            ),
            timeout=Duration.seconds(5),
        )

        docs_bucket.grant_read_write(emit_fn)
        invoices.grant_read_write_data(emit_fn)
        invoices.grant_read_data(get_fn)
        invoices.grant_read_write_data(cancel_fn)
        requests.grant_read_write_data(emit_fn)

        # SQS + Step Functions (demo)
        dlq = sqs.Queue(self, "RequestsDLQ")
        queue = sqs.Queue(
            self,
            "RequestsQueue",
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=3),
        )
        # emit_task = tasks.LambdaInvoke(
        #     self, "EmitLambda", lambda_function=emit_fn, payload_response_only=True
        # )
        # to_queue = tasks.SqsSendMessage(
        #     self,
        #     "EnqueueRequest",
        #     queue=queue,
        #     message_body=sfn.TaskInput.from_object({"detail.$": "$"}),
        # )
        # sfn.StateMachine(self, "EmitWorkflow", definition=emit_task.next(to_queue))

        to_queue = tasks.SqsSendMessage(
            self,
            "EnqueueRequest",
            queue=queue,
            message_body=sfn.TaskInput.from_object(
                {
                    "type": "InvoiceIssued",
                    "detail.$": "$",  # o input da execução vira "detail" na mensagem
                }
            ),
        )

        state_machine = sfn.StateMachine(self, "EmitWorkflow", definition=to_queue)

        # permitir que a EmitFn inicie a State Machine e expor o ARN na env
        state_machine.grant_start_execution(emit_fn)
        emit_fn.add_environment("SFN_ARN", state_machine.state_machine_arn)

        # API Gateway + WAF + Usage Plan
        log_group = logs.LogGroup(
            self, "ApiLogs", retention=logs.RetentionDays.ONE_WEEK
        )
        api = apigw.RestApi(
            self,
            "NfseApi",
            rest_api_name="nfse-api",
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                throttling_burst_limit=500,
                throttling_rate_limit=1000,
                metrics_enabled=True,
                logging_level=apigw.MethodLoggingLevel.INFO,
                data_trace_enabled=False,
                tracing_enabled=True,
                access_log_destination=apigw.LogGroupLogDestination(log_group),
                access_log_format=apigw.AccessLogFormat.clf(),
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=[
                    "Content-Type",
                    "Authorization",
                    "X-Requested-With",
                    "X-Idempotency-Key",
                ],
            ),
        )
        authorizer = apigw.CognitoUserPoolsAuthorizer(
            self, "CognitoAuthorizer", cognito_user_pools=[user_pool]
        )

        ping_res = api.root.add_resource("public").add_resource("ping")
        ping_res.add_method("GET", apigw.LambdaIntegration(ping_fn))

        invoices_res = api.root.add_resource("invoices")
        invoices_res.add_method(
            "POST",
            apigw.LambdaIntegration(emit_fn),
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
            api_key_required=True,
        )
        invoice_id_res = invoices_res.add_resource("{id}")
        invoice_id_res.add_method(
            "GET",
            apigw.LambdaIntegration(get_fn),
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
            api_key_required=True,
        )
        cancel_res = invoice_id_res.add_resource("cancel")
        cancel_res.add_method(
            "POST",
            apigw.LambdaIntegration(cancel_fn),
            authorizer=authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
            api_key_required=True,
        )

        api_key = apigw.ApiKey(self, "NfseApiKey")
        plan = apigw.UsagePlan(
            self,
            "NfseUsagePlan",
            throttle=apigw.ThrottleSettings(rate_limit=100, burst_limit=200),
        )
        plan.add_api_stage(stage=api.deployment_stage)
        plan.add_api_key(api_key)

        # Outputs
        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=user_pool_client.user_pool_client_id)
        CfnOutput(self, "AdminBucketName", value=admin_bucket.bucket_name)
        CfnOutput(
            self, "AdminDistributionDomain", value=distribution.distribution_domain_name
        )
        CfnOutput(self, "DocsBucketName", value=docs_bucket.bucket_name)
        CfnOutput(self, "ApiKeyId", value=api_key.key_id)
