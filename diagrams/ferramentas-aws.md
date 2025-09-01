# Arquitetura NFS-e — Itens (baseline) e **novos** (robusta)
---

## 1) Itens (baseline)

### S3 (Admin Web estático)
- **O que é:** Bucket S3 servindo os arquivos estáticos da **área administrativa** (HTML/CSS/JS).
- **Como é usado:** Você faz `aws s3 sync` do diretório `web/admin` para o bucket (output `AdminBucketName`).
- **Segurança:** *Block Public Access* ativado; acesso público é via **CloudFront** com Origin Access Identity (OAI).
- **Por que usar:** barato, escalável e sem servidor para hospedar SPA.

### CloudFront (CDN do Admin Web)
- **O que é:** CDN que entrega o admin web com baixa latência.
- **Como é usado:** Distribuição aponta para o S3; domínio padrão é algo como `dxxxx.cloudfront.net` (output `AdminDistributionDomain`).
- **Segurança:** HTTPS obrigatório; headers de segurança no app; *(na robusta ganhou **WAF** dedicado)*.
- **Por que usar:** performance e cache global.

### Admin App (Vite/React) – Dev local
- **O que é:** App React (Vite) para testes locais, inclusive capturando `id_token` pelo **Hosted UI** do Cognito.
- **Como é usado:** `yarn dev` abre `http://localhost:5173`; você informa **API URL**, **API Key** e **JWT**.

### S3 (DocsBucket) — XML/PDF
- **O que é:** Bucket para armazenar artefatos fiscais (ex.: `xml/<invoiceId>.xml`).
- **Como é usado:** a `EmitFn` faz `put_object` com o **XML** gerado.
- **Segurança:** criptografia S3 gerenciada; *Block Public Access*; para download seguro, use **pre-signed URL**.

### API Gateway (REST/HTTP)
- **O que é:** Porta de entrada da API (`/public/ping`, `/invoices`, `/invoices/{id}`, `/invoices/{id}/cancel`).
- **Como é usado:** integrações **Lambda**; CORS liberado para o admin.
- **Segurança:** **Cognito Authorizer** exigindo `Authorization: Bearer <JWT>` nas rotas protegidas.
- **Por que usar:** roteamento, throttling básico e integração nativa com Lambda.

### AWS Lambda (negócio)
- **EmitFn** (`POST /invoices`): gera `invoiceId`, grava **DynamoDB**, salva **XML no S3** e retorna `201`.
- **GetFn** (`GET /invoices/{id}`): lê da **DynamoDB** e retorna a nota.
- **CancelFn** (`POST /invoices/{id}/cancel`): atualiza `status=CANCELLED` na **DynamoDB**.
- **PingFn** (`GET /public/ping`): diagnóstico público (health).

### DynamoDB (InvoicesTable e, opcional, RequestsTable)
- **InvoicesTable**
  - **PK:** `invoiceId` (String).
  - **Uso:** estado da NFS-e (`status`, `createdAt`, `total`, etc.).
- **RequestsTable** (opcional no baseline)
  - **Uso planejado:** idempotência e trilha de processamento.
- **Segurança/Performance:** on-demand (auto-scale), criptografia em repouso, latência milissegundos.

### Amazon Cognito (User Pool + App Client)
- **O que é:** identidade dos usuários do **seu sistema** (não IAM da AWS).
- **Como é usado:** **Hosted UI** para login; gera **JWT (id_token)** que o API Gateway valida.
- **Fluxos comuns:** `login → redirect_uri/#id_token=...`; “Forgot password” e troca de senha na própria Hosted UI.

### CloudWatch Logs (e Métricas)
- **O que é:** logs das Lambdas e da API.
- **Como é usado:** `aws logs tail /aws/lambda/<fn>` para depurar; métricas de invocações/erros no console.

### IAM (permissões mínimas)
- **O que é:** permissões específicas concedidas pelo CDK:
  - `EmitFn` pode `PutItem` na **InvoicesTable** e `PutObject` no **DocsBucket**.
  - `GetFn/CancelFn` com leituras/atualizações na tabela.
  - API Gateway invoca as Lambdas.

---

## 2) Itens **novos** (robusta)

### VPC (2 AZs, NAT, endpoints S3/Dynamo)
- **O que é:** rede privada com subnets públicas/privadas em **duas AZs**; **NAT** para saída; **gateway endpoints** S3/Dynamo.
- **Por que:** isolamento de rede, alta disponibilidade e **tráfego interno** para S3/Dynamo sem custo do NAT.

### WAF (CloudFront + API)
- **O que é:** firewall L7 com **regras gerenciadas** (OWASP) e **rate limit** por IP.
- **Por que:** protege de **SQLi/XSS/bots** e abuso de requisições antes de atingir app/API.

### API Gateway REST + Usage Plan + API Key
- **O que é:** além do JWT, a API passa a exigir/aceitar **API Key** atrelada ao **Usage Plan** (throttle/quota por cliente).
- **Por que:** controle fino de consumo e visibilidade/monetização.

### Step Functions (orquestração)
- **O que é:** motor de **workflows** (retries/backoff/compensações).
- **Como usamos:** depois da `EmitFn` → **envia para SQS** (preparando o terreno para processamento assíncrono).

### SQS + DLQ
- **O que é:** fila que desacopla API dos **adapters**; **DLQ** guarda mensagens que falharam repetidas vezes.
- **Por que:** absorve picos, garante reprocessos e não perde eventos problemáticos.

### EventBridge (eventos de domínio)
- **O que é:** barramento de eventos; **EmitFn** publica `InvoiceIssued`.
- **Por que:** **fan-out** para múltiplos consumidores (auditoria, notificações) sem acoplamento.

### ECS Fargate (ALB interno, *adapters* futuros)
- **O que é:** containers **serverless** em subnets privadas atrás de **ALB interno**.
- **Por que:** hospedar **adapters municipais** (SOAP/REST), com **autoscaling** e sem gerenciar EC2.
- **Status:** container **nginx** de exemplo (gancho pronto para plugar adapters).

### Aurora PostgreSQL Serverless v2 (Postgres 15)
- **O que é:** banco relacional **elástico** e multi-AZ.
- **Por que:** modelo de domínio/relatórios (empresas, itens, competências, impostos) além do estado no Dynamo.
- **Status:** endpoint exposto; schema e conectores serão adicionados posteriormente.

### X-Ray + Logs “enriquecidos”
- **O que é:** *tracing* distribuído (latência ponta-a-ponta) + logs estruturados.
- **Por que:** facilita achar *bottlenecks* e entender a jornada de cada requisição.

---

