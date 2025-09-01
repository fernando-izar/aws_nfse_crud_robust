# Fluxo de criação de NFS-e — com **provedor municipal** e **PostgreSQL (Aurora)**

> Versão estendida do fluxo incluindo a chamada ao **provedor da prefeitura** e a **gravação no Postgres via Data API**.

---

## Campos e nomes (exatos)

**DynamoDB — `InvoicesTable` (chaves/atributos que usamos)**
- `invoiceId` *(PK)*  
- `companyCnpj`  
- `municipalityCode` *(opcional, quando houver)*  
- `total` *(Number como string na API do Dynamo: `"100.00"`)*  
- `status` *(valores: `EMITTED`, `ISSUED`, `FAILED`)*  
- `createdAt` *(ISO UTC, ex.: `2025-08-31T12:00:00Z`)*  
- `processedAt` *(ISO UTC — preenchido pelo processamento assíncrono)*  
- `xmlKey` *(ex.: `xml/{invoiceId}.xml` — pode ser gravado já no `EmitFn` ou no `ProcessorFn`)*  
- `providerProtocol` *(protocolo retornado pela prefeitura)*  
- `error` *(string com a causa, se falhar)*

   - DynamoDB usado para:
      - Estados da nota (EMITTED, ISSUED, FAILED, timestamps).
      - Lookup por invoiceId.
      - Idempotência de requisições.
      - Dados “quentes” que a UI precisa ver rápido.

   - Vantagens da utilizazão do DynamoDB:
      - Hot path ultra-rápido (latência de milissegundos) para a API:
         - POST /invoices grava rápido (status=EMITTED) e responde sem travar no provedor.
         - GET /invoices/{id} pega por chave (invoiceId) em O(1).
      - Escala e picos: aguenta rajadas (on-demand), ótimo com SQS/Lambda.
      - Idempotência/locks simples: ConditionExpression, attribute_not_exists() etc.
      - Custo previsível no pico e zero administração (serverless).
      - PITR/TTL (opcional) p/ retenção e recuperação rápida de estados efêmeros.
      - Resiliência do fluxo: se o Postgres oscilar, o core continua (DDB + S3 + fila).

**Aurora PostgreSQL — `nfse.invoices` (via Data API)**
- `invoice_id` *(PK)*  
- `company_cnpj`  
- `municipality_code` *(nullable)*  
- `total` *(numeric(12,2))*  
- `status` *(text: `EMITTED`/`ISSUED`/`FAILED`)*  
- `xml_key`  
- `provider_protocol`  
- `created_at` *(timestamptz)*  
- `processed_at` *(timestamptz)*  
- `error` *(text)*

   - PostgreSQL usado para:
      - Relatórios (ex.: faturamento por município/mês).
      - Listagens com múltiplos filtros/ordenações.
      - Análises históricas, reconciliação e auditoria.

   - Vantagens da utilização do PostgreSQL:
      - Consultas complexas e relatórios:
         - filtros por período/município/CNPJ, joins com empresas/itens, agregações.
      - Modelo relacional com consistência/constraints:
         - chaves estrangeiras, UNIQUE, CHECK, transações.
      - SQL padrão (ad-hoc e BI), índices específicos, window functions.
      - Integração BI (QuickSight, Metabase etc.) e auditoria fiscal.

> **Mapeamento**: `invoiceId ↔ invoice_id`, `companyCnpj ↔ company_cnpj`, `municipalityCode ↔ municipality_code`, `xmlKey ↔ xml_key`, `providerProtocol ↔ provider_protocol`.


Como DynamoDB e PostgreSQL se complementam:
- Entrada rápida
   EmitFn → DynamoDB (status=EMITTED) + S3 (XML) → Step Functions → SQS.
- Processamento assíncrono
   ProcessorFn (consumer SQS) → chama provedor municipal → define ISSUED/FAILED.
- Persistência final
   ProcessorFn:
      - Atualiza DynamoDB (status final).
      - Faz UPSERT no Postgres (via Data API).
      - (Opcional) publica evento InvoiceIssued.
Assim o hot path não depende do Postgres. Se Aurora estiver indisponível, a fila segura e você reprocessa depois.
---

## Fluxo (fim-a-fim)

**Cliente (Web/Mobile)**  
- Envia `POST /invoices` com **JWT Cognito** (`Authorization: Bearer …`) e **API Key** (`x-api-key`).  
- (Opcional) cabeçalho `Idempotency-Key` para evitar duplicidade.

**Edge (CloudFront + WAF)**  
- Termina **TLS**, aplica **WAF** (OWASP / *rate limit*) e repassa para a API (HTTPS).

*** Obs: Futuramente utilizar Route 53 (DNS gerenciada da AWX) entre app Mobile/admin web e Api Gateway

**API Gateway (REST + Usage Plan)**  
- Valida **API Key** (rate/quota) e o **JWT** via Cognito Authorizer.  
- Com tudo OK, **invoca a Lambda `EmitFn`**.

**Lambda `EmitFn` (negócio síncrono)**  
1. Gera `invoiceId`.  
2. **DynamoDB**: `putItem` com `invoiceId`, `companyCnpj`, `municipalityCode` (se houver), `total`, `status="EMITTED"`, `createdAt`.  
3. **S3**: `putObject` do **XML** em `xml/{invoiceId}.xml` *(guarde a `xmlKey`)*.  
4. **Step Functions**: inicia `EmitWorkflow` com payload `{ invoiceId, companyCnpj, municipalityCode, total, xmlKey, createdAt }`.  
5. **Resposta**: `201` com `{ invoiceId, status: "EMITTED", xmlKey }`.

**Step Functions + SQS (assíncrono)**  
- O workflow **publica** na `RequestsQueue` (SQS) a mensagem com os campos acima.  

**ECS Fargate (adapters — consumidor da fila principal)**  
> **Agora o caminho principal.** O Fargate **não recebe “trigger”**; ele **faz *pull* (long polling) na SQS**.
1. **Consome** mensagens da `RequestsQueue` (long polling).  
2. **Chama o provedor municipal** (SOAP/REST):  
   - Credenciais/certificados no **Secrets Manager** (se necessário).  
   - **Timeouts** e **retry com backoff** (ex.: 3 tentativas).  
3. **Determina** o resultado:  
   - Sucesso → `status = "ISSUED"`, `providerProtocol = "<protocolo>"`.  
   - Falha/timeout → `status = "FAILED"`, `error = "<motivo>"`.  
4. **Atualiza DynamoDB**: `status`, `processedAt`, `providerProtocol` (ou `error`) — garante `xmlKey`.  
5. **UPSERT no Aurora (Data API)**:  
   - `INSERT ... ON CONFLICT (invoice_id) DO UPDATE` em `nfse.invoices` com  
     `invoice_id, company_cnpj, municipality_code, total, status, xml_key, provider_protocol, created_at, processed_at, error`.  
6. **Delete** da mensagem na SQS (confirmação).  
7. **DLQ**: mensagens com falhas repetidas vão para a DLQ.

**Lambda `ProcessorFn` (DLQ / utilitários)**  
- **Não** consome a fila principal.  
- Usos: **reprocessar DLQ**, correções, migrações e **jobs manuais**.  
- Pode ler da **DLQ** sob demanda e refazer a etapa de chamada ao provedor ou apenas persistência.

---

### Observação — por que o **Fargate** como consumidor da fila é melhor que o **Lambda ProcessoFn** neste caso?

- **Um único “writer”** do Postgres/Dynamo por operação → evita *double-write* e condições de corrida.  
- **Padrão de “workers” estáveis**: controla **concorrência** e **throttling por provedor/município** (evita ban/limites).  
- **Libs pesadas** (ex.: SOAP/Java, certificados, binários nativos) rodam melhor em **containers**.  
- **IP fixo** via **NAT + EIP** (para *whitelist* da prefeitura).  
- **Custos** mais previsíveis sob carga contínua/alta (vs. Lambda invocações dispersas).  
- **Observabilidade** dedicada (métricas de fila, taxa `ISSUED/FAILED`, latência do provedor).

---

**Consulta (`GET /invoices/{invoiceId}`)**  
- A **Lambda `GetFn`** lê no **DynamoDB** e retorna o **status atual**, `xmlKey`, `providerProtocol`, `createdAt/processedAt`, etc.  
- (Opcional) Emite **presigned URL** para baixar o XML no **S3**.

---

## Estados (transições)

