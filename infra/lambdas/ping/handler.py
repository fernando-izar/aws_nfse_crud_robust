import json

CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,x-api-key",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "headers": CORS,
        "body": json.dumps({"ok": True}),
    }
