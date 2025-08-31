import json, os, datetime, boto3
from botocore.exceptions import ClientError

ddb = boto3.client('dynamodb')
TABLE_INVOICES = os.environ['TABLE_INVOICES']

def lambda_handler(event, context):
    try:
        path_params = event.get('pathParameters') or {}
        invoice_id = path_params.get('id')
        if not invoice_id:
            return {'statusCode': 400, 'body': 'Missing id'}

        now = datetime.datetime.utcnow().isoformat() + 'Z'
        try:
            ddb.update_item(
                TableName=TABLE_INVOICES,
                Key={'invoiceId': {'S': invoice_id}},
                UpdateExpression='SET #s = :cancelled, cancelledAt = :now',
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={':cancelled': {'S': 'CANCELLED'}, ':now': {'S': now}},
                ConditionExpression='attribute_exists(invoiceId)'
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                return {'statusCode': 404, 'body': 'Not found'}
            raise

        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps({'invoiceId': invoice_id, 'status': 'CANCELLED'})}
    except Exception as e:
        print('ERROR:', e)
        return {'statusCode': 500, 'body': json.dumps({'message': 'Internal error'})}
