# Importa módulos necessários para manipulação de JSON, variáveis de ambiente e AWS
import json, os, boto3

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
    try:
        # Bloco try para capturar erros gerais
        path_params = event.get("pathParameters") or {}
        # Obtém os parâmetros de caminho da requisição (ex: /invoices/{id})
        invoice_id = path_params.get("id")
        # Extrai o invoice_id dos parâmetros
        if not invoice_id:
            # Valida se o parâmetro 'id' foi informado
            return {"statusCode": 400, "body": "Missing id"}

        # Busca o item no DynamoDB pela chave invoiceId
        res = ddb.get_item(
            TableName=TABLE_INVOICES, Key={"invoiceId": {"S": invoice_id}}
        )
        # Obtém o item retornado
        item = res.get("Item")
        if not item:
            # Se não encontrar, retorna 404
            return {"statusCode": 404, "body": "Not found"}

        # Converte o formato do DynamoDB para dicionário simples
        data = {k: list(v.values())[0] for k, v in item.items()}
        if "total" in data:
            try:
                # Se houver campo 'total', tenta converter para float
                data["total"] = float(data["total"])
            except:
                pass
        # Retorna os dados encontrados
        return {
            "statusCode": 200,
            "headers": CORS,
            "body": json.dumps(data),
        }
    # Captura qualquer erro inesperado, loga e retorna erro 500
    except Exception as e:
        print("ERROR:", e)
        return {"statusCode": 500, "body": json.dumps({"message": "Internal error"})}
