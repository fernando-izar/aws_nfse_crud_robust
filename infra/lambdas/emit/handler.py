# Importa módulos necessários para manipulação de JSON, variáveis de ambiente, datas, UUID e AWS
import json, os, uuid, datetime, boto3

# Inicializa clientes AWS: DynamoDB, S3 e Step Functions
ddb = boto3.client("dynamodb")
s3 = boto3.client("s3")
sfn = boto3.client("stepfunctions")

# Obtém nomes de recursos a partir das variáveis de ambiente
TABLE_INVOICES = os.environ["TABLE_INVOICES"]
BUCKET_DOCS = os.environ["BUCKET_DOCS"]
SFN_ARN = os.environ.get("SFN_ARN")
# Define os cabeçalhos CORS para permitir requisições de outros domínios
CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,x-api-key",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def lambda_handler(event, context):
    # Função principal Lambda, chamada a cada requisição
    try:
        # Obtém o corpo da requisição (JSON)
        body = json.loads(event.get("body") or "{}")
        # Gera um invoice_id único (12 caracteres)
        invoice_id = uuid.uuid4().hex[:12]
        # Gera timestamp atual em formato ISO
        now = datetime.datetime.utcnow().isoformat() + "Z"

        # Monta o registro para salvar no DynamoDB
        record = {
            "invoiceId": {"S": invoice_id},
            "companyCnpj": {"S": str(body.get("companyCnpj", "00000000000000"))},
            "status": {"S": "EMITTED"},
            "createdAt": {"S": now},
            "total": {"N": str(body.get("total", 0))},
        }

        # Salva o registro na tabela DynamoDB, garantindo que não exista outro com o mesmo id
        ddb.put_item(
            TableName=TABLE_INVOICES,
            Item=record,
            ConditionExpression="attribute_not_exists(invoiceId)",
        )

        # Gera o XML da nota fiscal e salva no S3
        xml = f"<NFS-e><Id>{invoice_id}</Id><Status>EMITTED</Status><Date>{now}</Date></NFS-e>"
        s3.put_object(
            Bucket=BUCKET_DOCS,
            Key=f"xml/{invoice_id}.xml",
            Body=xml.encode("utf-8"),
            ContentType="application/xml",
        )

        # Dispara a State Machine para enfileirar no SQS (se configurado)
        if SFN_ARN:
            payload = {
                "invoiceId": invoice_id,
                "companyCnpj": body.get("companyCnpj", "00000000000000"),
                "total": body.get("total", 0),
                "status": "EMITTED",
                "xmlKey": f"xml/{invoice_id}.xml",
                "createdAt": now,
            }
            # Inicia execução da State Machine
            sfn.start_execution(stateMachineArn=SFN_ARN, input=json.dumps(payload))

        # Retorna resposta de sucesso com dados da nota emitida
        return {
            "statusCode": 201,
            "headers": CORS,
            "body": json.dumps(
                {
                    "invoiceId": invoice_id,
                    "status": "EMITTED",
                    "xmlKey": f"xml/{invoice_id}.xml",
                }
            ),
        }
    # Captura qualquer erro inesperado, loga e retorna erro 500
    except Exception as e:
        print("ERROR:", e)
        return {"statusCode": 500, "body": json.dumps({"message": "Internal error"})}
