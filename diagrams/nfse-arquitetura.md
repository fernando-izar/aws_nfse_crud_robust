# Arquitetura NFS-e na AWS — ** (Fargate consome a fila; Lambda só DLQ)**

> Escopo do diagrama: **Admin Web (S3+CloudFront), API (API Gateway + Lambdas), Autenticação (Cognito), Orquestração (Step Functions), Mensageria (SQS), Persistência (DynamoDB + S3), Rede (VPC + Bastion), Observabilidade (CloudWatch)**.  
> Itens opcionais: **Mobile (stub)** e **Aurora PostgreSQL (provisionado, ainda sem schema/uso)**.

---

## Legenda (status)

- ✅ **Feito**
- 🟡 **Pendente / a implementar**
- ⚪ **Provisionado, não usado**

---

## 1) Clientes

### 1.1 Admin Web (Browser) — ✅
- **O que é:** SPA estática (HTML/JS) hospedada no S3 e servida via CloudFront.
- **Conexões:** `Browser → CloudFront → S3 (Admin Site)` e, para API, `Browser → CloudFront → API Gateway`.
- **Segurança:**
  - HTTPS (TLS) no CloudFront + **AWS WAF** (regras gerenciadas + rate limit).
  - Headers: **CSP**, **HSTS**, **X-Content-Type-Options**, **Referrer-Policy**.
  - **x-api-key** (identificação/quotas via Usage Plan) + **JWT Cognito** (AuthN/AuthZ baseada em *claims*).

### 1.2 Mobile App (iOS/Android, stub) — 🟡
- **O que é:** app RN/Expo simples que consome a mesma API.
- **Conexões:** `App → API Gateway` (não precisa passar pelo CloudFront).
- **Segurança:** JWT do Cognito em `Authorization: Bearer …` + `x-api-key`. HTTPS sempre.

---

## 2) Edge & Static Web

### 2.1 CloudFront (Admin) + WAF — ✅
- **Função:** CDN para o Admin Web e possível *proxy* para a API.
- **Segurança:** WAF (OWASP, bot control opcional, regra *rate-based*), ACM/TLS 1.2+, origin access para S3, **invalidação de cache** no deploy.

### 2.2 S3 (Admin Site) — ✅
- **Função:** armazenamento do site estático.
- **Segurança:** Block Public Access, criptografia (SSE-S3/KMS), política permitindo somente o CloudFront.

---

## 3) API & Autenticação

### 3.1 API Gateway (REST) + Usage Plan + API Key + WAF — ✅
- **Função:** fronteira da API; throttle e quotas por cliente (Usage Plan).
- **Conexões:** `Clients → API GW → Lambdas (Ping/Emit/Get/Cancel)`.
- **Segurança:** WAF regional, **CORS** nas rotas públicas, access logs/metrics no CloudWatch.

### 3.2 Cognito (User Pool + Hosted UI) + JWT Authorizer — ✅
- **Função:** autenticação via Hosted UI, emissão/validação de **JWT** (Authorizer no API GW).
- **Segurança:** MFA opcional, políticas de senha, RBAC/ABAC por *claims*.

---

## 4) Lambdas (Negócio)

- **PingFn** — ✅: *health check* público.  
- **EmitFn** — ✅: recebe emissão, grava estado, gera XML, inicia orquestração.  
- **GetFn** — ✅: consulta status/detalhes da nota.  
- **CancelFn** — ✅: registra cancelamento.

**Conexões:** `API GW → Ping/Emit/Get/Cancel`.  
`Emit → DynamoDB (Invoices/Requests) + S3 (XML) + Step Functions`.

**Segurança:** IAM mínimo por função; segredos no **Secrets Manager** (se houver); timeouts/memória adequados; **X-Ray** recomendado.

---

## 5) Orquestração & Mensageria (com **Fargate como consumidor**)

### 5.1 Step Functions (EmitWorkflow) — ✅
- **Função:** orquestrar o pós-emissão de forma assíncrona.
- **Conexões:** `EmitFn → Step Functions → SQS`.

### 5.2 SQS (RequestsQueue + DLQ) — ✅
- **Função:** fila para processar integrações/tarefas em *background*; **DLQ** para falhas persistentes.
- **Segurança:** criptografia em repouso; políticas de acesso somente para produtores/consumidores autorizados.

### 5.3 **ECS Fargate Adapters (consumidor da fila)** — 🟡
- **Função:** *workers* por município/provedor (**pull** da **RequestsQueue** com *long polling*), chamadas SOAP/REST, **atualização de estado** e **persistência**.
- **Conexões:** `SQS → Fargate → Provedor Municipal`, `Fargate → DynamoDB/S3` e (opcional) `Fargate → Aurora (Data API)`.
- **Rede:** subnets privadas da **VPC**; saída internet por **NAT+EIP** (IP fixo para *whitelist*); **VPC Endpoints** para S3/Dynamo/Secrets/Logs.
- **Segurança:** SG com egress restrito; IAM mínimo (SQS read, DDB/S3 write, Secrets/Logs).

### 5.4 **ProcessorFn (Lambda) — somente DLQ/reprocessos** — ✅
- **Função:** não consome mais a fila principal. Usada para **reprocessar DLQ**, correções, migrações e **jobs manuais**.
- **Operação:** *event source mapping* para a **DLQ** (ou invocação manual); idempotência por `invoiceId`.

> **Vantagens do Fargate como consumidor principal**
> - **Um único “writer”** (evita *double-write* e corridas).  
> - **Throttling por município** e isolamento de falhas.  
> - **Libs pesadas** (SOAP/certificados/bins nativos) rodam melhor em container.  
> - **IP fixo** via NAT/EIP para *whitelist* de prefeituras.  
> - Custos mais previsíveis sob carga contínua.

---

## 6) Dados & Documentos

### 6.1 DynamoDB (InvoicesTable / RequestsTable) — ✅
- **Função:** estado/idempotência/consulta rápida (latência ms).
- **Modelagem:**  
  - `InvoicesTable`: PK `invoiceId`; `status`, `companyCnpj`, `total`, `createdAt`, `xmlKey`, `processedAt`, `providerProtocol`, `error`.  
  - `RequestsTable`: PK `requestId` (idempotência/trace).
- **Segurança:** criptografia, **PITR** (opcional), IAM por recurso.

### 6.2 S3 (DocsBucket — XML) — ✅
- **Função:** armazenamento dos XMLs (e futuramente DANFSe PDF).
- **Acesso:** presigned URL de curta duração para download. Lifecycle/Glacier (LGPD).

### 6.3 Aurora PostgreSQL Serverless v2 — ⚪
- **Função prevista:** modelo relacional para relatórios/consultas ricas.
- **Status:** provisionado, **sem schema/uso** no escopo atual (integração ficará no Fargate).

---

## 7) Rede

### 7.1 VPC (2 AZs, NAT, VPC Endpoints S3/Dynamo) — ✅
- **Função:** isolamento de rede e acesso **privado** a serviços AWS.
- **Conexões:** Fargate/Lambdas em subnets privadas; **Aurora** em subnets isoladas; **VPC Endpoints** para S3/Dynamo/Secrets/CloudWatch.

### 7.2 Bastion (SSM) — ✅
- **Função:** salto administrativo (Session Manager; sem portas públicas).
- **Uso:** *debug* interno e acesso ao **Aurora** (`psql`) via SG controlado.

---

## 8) Observabilidade

### 8.1 CloudWatch Logs/Metrics/Alarms — ✅
- Logs centralizados, métricas de API/Lambdas/SFN/SQS, alarmes básicos (erros, 5xx, **idade da SQS**).

### 8.2 AWS X-Ray — 🟡
- *Tracing* distribuído (ativar em API GW e Lambdas/Fargate).

---

## 9) Fluxos (fim-a-fim) — **com Fargate no caminho principal**

### 9.1 Emissão
1. Cliente chama `POST /invoices` com **JWT** + **x-api-key**.  
2. **API Gateway** valida JWT/WAF/Usage Plan.  
3. **EmitFn** gera `invoiceId`, grava **DynamoDB** (`status="EMITTED"`), salva **XML** no **S3** (`xmlKey`) e inicia **Step Functions**.  
4. **Step Functions** envia **mensagem na RequestsQueue (SQS)**.  
5. **ECS Fargate (Adapters)** consome a mensagem (long polling), chama o **provedor municipal** (SOAP/REST, *retries/backoff*), define resultado:  
   - sucesso → `ISSUED` + `providerProtocol`;  
   - falha → `FAILED` + `error`.  
6. **Fargate** atualiza **DynamoDB** (status final, `processedAt`, `providerProtocol/error`) e, **se optar usar** o relacional, faz **UPSERT no Aurora (Data API)**.  
7. **Fargate** remove a mensagem da fila. Mensagens com falhas repetidas vão para a **DLQ**.

### 9.2 DLQ / Reprocesso
- **ProcessorFn** (Lambda) lê da **DLQ** sob demanda, corrige/repete a chamada ao provedor e reaplica a persistência (DDB/Aurora).

### 9.3 Consulta
- `GET /invoices/{invoiceId}` → **GetFn** lê no **DynamoDB** e retorna `status`, `xmlKey`, `providerProtocol`, `createdAt/processedAt`.  
- (Opcional) presigned URL do **S3** para baixar o XML.

### 9.4 Cancelamento
- `POST /invoices/{invoiceId}/cancel` → fluxo similar ao de emissão (DDB + SFN + SQS + **Fargate**).

---

## 10) Camadas de segurança (resumo)

1. **Borda:** CloudFront + **WAF** (TLS, HSTS, OWASP, rate-limit, geo/ASN).  
2. **API:** API Gateway + WAF + Usage Plan (throttle/quota), JWT (Cognito), CORS, logs/metrics.  
3. **Identidade:** Cognito (MFA opcional, Hosted UI, *claims* para RBAC/ABAC).  
4. **Rede:** VPC privada, SGs estritos, **VPC Endpoints** (S3/Dynamo/Secrets/Logs), **NAT+EIP** para saída controlada.  
5. **Dados:** S3/Dynamo criptografados; S3 privado com URLs assinadas curtas; Dynamo **PITR**; S3 Lifecycle/Glacier (LGPD).  
6. **Execução:** IAM mínimo por Lambda/SFN/SQS/Fargate; segredos no **Secrets Manager**; logs sem PII.  
7. **Observabilidade:** CloudWatch (logs/alarms), **X-Ray** opcional.

---

## 11) Status geral

- ✅ **Implementado:** Admin (S3+CF+WAF), Cognito (Hosted UI), API (REST) com Usage Plan/API Key/WAF, Lambdas (Ping/Emit/Get/Cancel), DynamoDB, S3 (XML), Step Functions, SQS+DLQ, **ProcessorFn (DLQ/utilidades)**, VPC+Endpoints, Bastion (SSM), CloudWatch.  
- 🟡 **A implementar (Opção Fargate):** **ECS Fargate Adapters** como **consumidor principal da RequestsQueue** (com NAT/EIP e *autoscaling*), **X-Ray**.  
- ⚪ **Provisionado, não usado:** Aurora PostgreSQL (sem schema).

---

## 12) Passos de transição para a Opção Fargate

1. **Criar** serviço **ECS Fargate** por município/provedor (ou um único com *sharding* por `municipalityCode`).  
2. **Dar permissão** ao serviço (IAM) para: `sqs:ReceiveMessage/DeleteMessage/ChangeMessageVisibility`, `dynamodb:UpdateItem`, `s3:PutObject`, `secretsmanager:GetSecretValue`, `rds-data:*` (se usar Aurora).  
3. **Rede:** tasks em **subnets privadas**; **NAT+EIP**; **SG** e **VPC Endpoints** (S3/DDB/Secrets/Logs).  
4. **Desabilitar** o *event source mapping* da `ProcessorFn` para a **fila principal** (manter apenas DLQ).  
5. **Autoscaling** do serviço por **profundidade/idade** da SQS.  
6. (Opc.) **Schema** do **Aurora** e UPSERT no Fargate.

---
