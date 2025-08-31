import json, os, boto3

ddb = boto3.client('dynamodb')
TABLE_INVOICES = os.environ['TABLE_INVOICES']

def lambda_handler(event, context):
    try:
        path_params = event.get('pathParameters') or {}
        invoice_id = path_params.get('id')
        if not invoice_id:
            return {'statusCode': 400, 'body': 'Missing id'}

        res = ddb.get_item(TableName=TABLE_INVOICES, Key={'invoiceId': {'S': invoice_id}})
        item = res.get('Item')
        if not item:
            return {'statusCode': 404, 'body': 'Not found'}

        data = {k: list(v.values())[0] for k, v in item.items()}
        if 'total' in data:
            try: data['total'] = float(data['total'])
            except: pass
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps(data)}
    except Exception as e:
        print('ERROR:', e)
        return {'statusCode': 500, 'body': json.dumps({'message': 'Internal error'})}
