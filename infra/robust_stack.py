# Importações de módulos necessários do AWS CDK e Python
from typing import Any
from constructs import Construct
from aws_cdk import (
    Stack,  # Classe base para stacks do CDK
    CfnOutput,  # Para exportar valores após o deploy
    RemovalPolicy,  # Política de remoção de recursos
    Duration,  # Utilitário para definir tempos
    aws_s3 as s3,  # S3 buckets
    aws_cloudfront as cloudfront,  # CDN CloudFront
    aws_cloudfront_origins as origins,  # Origens do CloudFront
    aws_cognito as cognito,  # Autenticação Cognito
    aws_apigateway as apigw,  # API Gateway
    aws_lambda as _lambda,  # Funções Lambda
    aws_dynamodb as dynamodb,  # Tabelas DynamoDB
    aws_sqs as sqs,  # Filas SQS
    aws_stepfunctions as sfn,  # Step Functions
    aws_stepfunctions_tasks as tasks,  # Tasks do Step Functions
    aws_wafv2 as wafv2,  # Web Application Firewall
    aws_logs as logs,  # Logs do CloudWatch
    aws_lambda_event_sources as lambda_events,  # Eventos para Lambda
    aws_rds as rds,  # Banco de dados RDS
    aws_ec2 as ec2,  # Recursos de rede EC2
)

import os  # Utilitário para manipulação de caminhos


# Classe principal da stack de infraestrutura
class RobustNfseStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Criação da VPC principal do projeto, com três tipos de sub-redes:
        # - public: para recursos públicos (ex: Bastion Host)
        # - private-egress: para recursos privados com acesso à internet via NAT (ex: Lambdas)
        # - isolated: para recursos totalmente privados (ex: banco Aurora)
        self.vpc = ec2.Vpc(
            self,
            "AppVpc",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            max_azs=2,  # Número de zonas de disponibilidade
            nat_gateways=1,  # Apenas 1 NAT para reduzir custos em dev
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="private-egress",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )

        # Adiciona endpoints de gateway para S3 e DynamoDB, evitando saída pela internet/NAT
        self.vpc.add_gateway_endpoint(
            "S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3
        )
        self.vpc.add_gateway_endpoint(
            "DynamoEndpoint", service=ec2.GatewayVpcEndpointAwsService.DYNAMODB
        )

        # Criação dos grupos de segurança:
        # - db_sg: para o banco Aurora
        # - lambda_sg: para as Lambdas que acessam o banco
        db_sg = ec2.SecurityGroup(self, "DbSg", vpc=self.vpc, description="Aurora SG")
        lambda_sg = ec2.SecurityGroup(
            self, "LambdaDbSg", vpc=self.vpc, description="Lambdas to DB"
        )
        # Permite que as Lambdas acessem o banco na porta 5432 (Postgres)
        db_sg.add_ingress_rule(
            lambda_sg, ec2.Port.tcp(5432), "Lambda to Aurora (Postgres)"
        )

        # Criação do cluster Aurora PostgreSQL Serverless v2
        # - Usa sub-redes isoladas
        # - Credenciais geradas automaticamente no Secrets Manager
        # - Writer e reader serverless
        # - Capacidade ajustável (min/max)
        # - Remoção automática em dev
        cluster = rds.DatabaseCluster(
            self,
            "Aurora",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_15_3
            ),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            credentials=rds.Credentials.from_generated_secret("appadmin"),
            writer=rds.ClusterInstance.serverless_v2("writer"),
            readers=[rds.ClusterInstance.serverless_v2("reader1")],
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=4,
            security_groups=[db_sg],
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Criação do Bastion Host para acesso administrativo ao banco
        bastion_sg = ec2.SecurityGroup(
            self,
            "BastionSg",
            vpc=self.vpc,
            description="Acesso de admin (psql) ao Aurora",
            allow_all_outbound=True,
        )
        bastion = ec2.BastionHostLinux(
            self,
            "DevBastion",
            vpc=self.vpc,
            subnet_selection=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType("t3.small"),
            security_group=bastion_sg,
        )

        # Permite que o Bastion acesse o banco Aurora na porta padrão do Postgres
        cluster.connections.allow_default_port_from(bastion, "Bastion to Aurora (psql)")

        # Criação do bucket S3 para o site admin, protegido e criptografado
        admin_bucket = s3.Bucket(
            self,
            "AdminSiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        # Permite acesso do CloudFront ao bucket via OAI
        oai = cloudfront.OriginAccessIdentity(self, "OAI")
        admin_bucket.grant_read(oai)

        # Criação do WAF para proteger o CloudFront
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
        # Distribuição CloudFront para servir o site admin
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

        # Criação do bucket S3 para documentos
        docs_bucket = s3.Bucket(
            self,
            "DocsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Criação do User Pool Cognito para autenticação de usuários
        user_pool = cognito.UserPool(
            self,
            "Users",
            self_sign_up_enabled=True,  # Permite auto-registro
            sign_in_aliases=cognito.SignInAliases(email=True),  # Login por e-mail
            password_policy=cognito.PasswordPolicy(
                min_length=8, require_lowercase=True, require_digits=True
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )
        # Client do User Pool
        user_pool_client = cognito.UserPoolClient(
            self,
            "UsersClient",
            user_pool=user_pool,
            generate_secret=False,
        )

        # Criação das tabelas DynamoDB para invoices e requests
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

        # Criação das funções Lambda principais do sistema
        # - emit_fn: emissão de invoice
        # - get_fn: consulta de invoice
        # - cancel_fn: cancelamento de invoice
        # - ping_fn: endpoint público de saúde
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

        # Permissões para as Lambdas acessarem os recursos necessários
        docs_bucket.grant_read_write(emit_fn)
        invoices.grant_read_write_data(emit_fn)
        invoices.grant_read_data(get_fn)
        invoices.grant_read_write_data(cancel_fn)
        requests.grant_read_write_data(emit_fn)

        # Criação das filas SQS e Step Functions para processamento assíncrono
        dlq = sqs.Queue(self, "RequestsDLQ")  # Dead Letter Queue
        queue = sqs.Queue(
            self,
            "RequestsQueue",
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=3),
        )

        # Task do Step Functions que envia mensagem para a fila
        to_queue = tasks.SqsSendMessage(
            self,
            "EnqueueRequest",
            queue=queue,
            message_body=sfn.TaskInput.from_object(
                {
                    "type": "InvoiceIssued",
                    "detail.$": "$",  # O input da execução vira "detail" na mensagem
                }
            ),
        )

        # Máquina de estados do Step Functions
        state_machine = sfn.StateMachine(self, "EmitWorkflow", definition=to_queue)

        # Permite que a Lambda de emissão inicie a máquina de estados e exporta o ARN
        state_machine.grant_start_execution(emit_fn)
        emit_fn.add_environment("SFN_ARN", state_machine.state_machine_arn)

        # Criação da Lambda que processa mensagens da fila SQS
        processor_fn = _lambda.Function(
            self,
            "ProcessorFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "lambdas/processor")
            ),
            environment={
                "TABLE_INVOICES": invoices.table_name,
                "DB_HOST": cluster.cluster_endpoint.hostname,
                "DB_NAME": "nfse",
                "DB_SECRET_ARN": cluster.secret.secret_arn,
            },
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[lambda_sg],
            timeout=Duration.seconds(30),
        )

        # Permissões para a Lambda acessar a tabela e o segredo do banco
        invoices.grant_read_write_data(processor_fn)
        cluster.secret.grant_read(processor_fn)

        # Configura a Lambda para ser disparada por eventos da fila SQS
        processor_fn.add_event_source(
            lambda_events.SqsEventSource(queue, batch_size=5, enabled=True)
        )

        # Criação do API Gateway REST para expor os endpoints da aplicação
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
                    "x-api-key",
                    "X-Amz-Date",
                    "X-Requested-With",
                ],
            ),
        )
        # Authorizer Cognito para proteger os endpoints
        authorizer = apigw.CognitoUserPoolsAuthorizer(
            self, "CognitoAuthorizer", cognito_user_pools=[user_pool]
        )

        # Endpoint público de ping (saúde)
        ping_res = api.root.add_resource("public").add_resource("ping")
        ping_res.add_method("GET", apigw.LambdaIntegration(ping_fn))

        # Endpoints protegidos para invoices
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

        # Criação da chave de API e plano de uso
        api_key = apigw.ApiKey(self, "NfseApiKey")
        plan = apigw.UsagePlan(
            self,
            "NfseUsagePlan",
            # rate_limit: número máximo de requisições por segundo permitidas
            # burst_limit: número máximo de requisições que podem ser feitas em um curto período (pico)
            throttle=apigw.ThrottleSettings(rate_limit=100, burst_limit=200),
        )
        plan.add_api_stage(stage=api.deployment_stage)
        plan.add_api_key(api_key)

        # Exporta valores importantes após o deploy para fácil consulta
        # O valores exportados via CfnOutput podem ser consultados no console do CloudFormation na aba "Outputs" da stack ou
        # via AWS CLI - exemplo para extrair o valor da API URL:
        # API_URL=$(aws cloudformation describe-stacks --stack-name <nome-da-sua-stack> --region <sua-regiao> --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)

        CfnOutput(self, "ApiUrl", value=api.url)  # URL da API
        CfnOutput(
            self, "UserPoolId", value=user_pool.user_pool_id
        )  # ID do User Pool Cognito
        CfnOutput(
            self, "UserPoolClientId", value=user_pool_client.user_pool_client_id
        )  # ID do client Cognito
        CfnOutput(
            self, "AdminBucketName", value=admin_bucket.bucket_name
        )  # Nome do bucket admin
        CfnOutput(
            self, "AdminDistributionDomain", value=distribution.distribution_domain_name
        )  # Domínio do CloudFront admin
        CfnOutput(
            self, "DocsBucketName", value=docs_bucket.bucket_name
        )  # Nome do bucket de documentos
        CfnOutput(self, "ApiKeyId", value=api_key.key_id)  # ID da chave de API
        CfnOutput(self, "VpcId", value=self.vpc.vpc_id)  # ID da VPC
        CfnOutput(
            self, "AuroraEndpoint", value=cluster.cluster_endpoint.hostname
        )  # Endpoint do Aurora
        CfnOutput(
            self, "AuroraSecretArn", value=cluster.secret.secret_arn
        )  # ARN do segredo do Aurora
        CfnOutput(
            self, "BastionInstanceId", value=bastion.instance_id
        )  # ID da instância Bastion
