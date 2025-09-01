# Importa módulos necessários para manipulação de JSON, variáveis de ambiente, datas e AWS
import json, os, datetime, boto3

# Importa exceção específica do boto3 para tratamento de erros do DynamoDB
from botocore.exceptions import ClientError

# Inicializa o cliente DynamoDB
ddb = boto3.client("dynamodb")
# Obtém o nome da tabela de invoices a partir da variável de ambiente
TABLE_INVOICES = os.environ["TABLE_INVOICES"]

# Define os cabeçalhos CORS para permitir requisições de outros domínios
CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,x-api-key",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def lambda_handler(event, context):
    # Função principal Lambda, chamada a cada requisição
    # Bloco try para capturar erros gerais
    try:
        # Obtém os parâmetros de caminho da requisição (ex: /invoices/{id})
        path_params = event.get("pathParameters") or {}
        # Extrai o invoice_id dos parâmetros
        invoice_id = path_params.get("id")
        # Valida se o parâmetro 'id' foi informado
        if not invoice_id:
            # Retorna erro 400 se não houver id
            return {"statusCode": 400, "body": "Missing id"}

        # Gera timestamp atual em formato ISO para registrar o cancelamento
        now = datetime.datetime.utcnow().isoformat() + "Z"
        try:
            # Atualiza o status da invoice para CANCELLED e registra o horário do cancelamento
            ddb.update_item(
                TableName=TABLE_INVOICES,
                Key={"invoiceId": {"S": invoice_id}},
                UpdateExpression="SET #s = :cancelled, cancelledAt = :now",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":cancelled": {"S": "CANCELLED"},
                    ":now": {"S": now},
                },
                # Só atualiza se o invoice existir
                ConditionExpression="attribute_exists(invoiceId)",
            )
        except ClientError as e:
            # Se não existir a invoice, retorna 404
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return {"statusCode": 404, "body": "Not found"}
            # Outros erros são propagados
            raise

        # Retorna sucesso e dados do invoice cancelado
        return {
            "statusCode": 200,
            "headers": CORS,
            "body": json.dumps({"invoiceId": invoice_id, "status": "CANCELLED"}),
        }
    # Captura qualquer erro inesperado, loga e retorna erro 500
    except Exception as e:
        print("ERROR:", e)
        return {"statusCode": 500, "body": json.dumps({"message": "Internal error"})}
