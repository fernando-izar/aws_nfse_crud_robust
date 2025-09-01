# Importa módulos necessários para manipulação de ambiente, JSON, datas e AWS
import os, json, datetime, boto3

# Inicializa o cliente DynamoDB
ddb = boto3.client("dynamodb")
# Obtém o nome da tabela de invoices a partir da variável de ambiente
TABLE_INVOICES = os.environ["TABLE_INVOICES"]


# Função principal Lambda, chamada a cada evento recebido da fila SQS
def lambda_handler(event, context):
    for rec in event.get("Records", []):
        # Obtém o corpo da mensagem da fila
        body = json.loads(rec.get("body") or "{}")
        # A State Machine envia {"type":"InvoiceIssued","detail":{...}}
        detail = body.get("detail", body)
        # Extrai o invoice_id do detalhe
        invoice_id = detail.get("invoiceId")
        if not invoice_id:
            # Se não houver id, nada a fazer; ignora
            continue

        # Gera timestamp atual em formato ISO
        now = datetime.datetime.utcnow().isoformat() + "Z"

        try:
            # 1) Marca como PROCESSING (idempotente: só se estava EMITTED)
            ddb.update_item(
                TableName=TABLE_INVOICES,
                Key={"invoiceId": {"S": invoice_id}},
                UpdateExpression="SET #s=:processing, processingAt=:t",
                ConditionExpression="attribute_exists(invoiceId) AND #s=:emitted",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":processing": {"S": "PROCESSING"},
                    ":emitted": {"S": "EMITTED"},
                    ":t": {"S": now},
                },
            )

            # ... aqui entraria a chamada ao provedor municipal ...

            # 2) Finaliza como PROCESSED
            ddb.update_item(
                TableName=TABLE_INVOICES,
                Key={"invoiceId": {"S": invoice_id}},
                UpdateExpression="SET #s=:processed, processedAt=:t2",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":processed": {"S": "PROCESSED"},
                    ":t2": {"S": now},
                },
            )

        except Exception as e:
            # Deixa a Lambda falhar para o SQS reentregar e, após N tentativas, ir pra DLQ
            print("ERROR processing", invoice_id, ":", e)
            raise

    # Retorna resposta simples indicando sucesso
    return {"ok": True}
