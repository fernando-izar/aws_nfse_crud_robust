import json, os, uuid, datetime, boto3

ddb = boto3.client("dynamodb")
s3 = boto3.client("s3")
sfn = boto3.client("stepfunctions")

TABLE_INVOICES = os.environ["TABLE_INVOICES"]
BUCKET_DOCS = os.environ["BUCKET_DOCS"]
SFN_ARN = os.environ.get("SFN_ARN")
CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,x-api-key",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
        invoice_id = uuid.uuid4().hex[:12]
        now = datetime.datetime.utcnow().isoformat() + "Z"

        record = {
            "invoiceId": {"S": invoice_id},
            "companyCnpj": {"S": str(body.get("companyCnpj", "00000000000000"))},
            "status": {"S": "EMITTED"},
            "createdAt": {"S": now},
            "total": {"N": str(body.get("total", 0))},
        }

        ddb.put_item(
            TableName=TABLE_INVOICES,
            Item=record,
            ConditionExpression="attribute_not_exists(invoiceId)",
        )

        xml = f"<NFS-e><Id>{invoice_id}</Id><Status>EMITTED</Status><Date>{now}</Date></NFS-e>"
        s3.put_object(
            Bucket=BUCKET_DOCS,
            Key=f"xml/{invoice_id}.xml",
            Body=xml.encode("utf-8"),
            ContentType="application/xml",
        )

        # --- NOVO: dispara a State Machine para enfileirar no SQS ---
        if SFN_ARN:
            payload = {
                "invoiceId": invoice_id,
                "companyCnpj": body.get("companyCnpj", "00000000000000"),
                "total": body.get("total", 0),
                "status": "EMITTED",
                "xmlKey": f"xml/{invoice_id}.xml",
                "createdAt": now,
            }
            sfn.start_execution(stateMachineArn=SFN_ARN, input=json.dumps(payload))

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
    except Exception as e:
        print("ERROR:", e)
        return {"statusCode": 500, "body": json.dumps({"message": "Internal error"})}
