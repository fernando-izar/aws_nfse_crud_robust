# Importa módulo para manipulação de JSON
import json

# Define os cabeçalhos CORS para permitir requisições de outros domínios
CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,x-api-key",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


# Função principal Lambda, chamada a cada requisição
def lambda_handler(event, context):
    # Retorna resposta de sucesso para indicar que o serviço está online
    return {
        "statusCode": 200,
        "headers": CORS,
        "body": json.dumps({"ok": True}),
    }
