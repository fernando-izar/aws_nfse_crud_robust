import os, json, datetime, boto3

ddb = boto3.client("dynamodb")
TABLE_INVOICES = os.environ["TABLE_INVOICES"]


def lambda_handler(event, context):
    for rec in event.get("Records", []):
        body = json.loads(rec.get("body") or "{}")
        # A SM envia {"type":"InvoiceIssued","detail":{...}}
        detail = body.get("detail", body)
        invoice_id = detail.get("invoiceId")
        if not invoice_id:
            # nada a fazer; deixa passar
            continue

        now = datetime.datetime.utcnow().isoformat() + "Z"

        try:
            # 1) marca como PROCESSING (idempotente: só se estava EMITTED)
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

            # 2) finaliza como PROCESSED
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

    return {"ok": True}
