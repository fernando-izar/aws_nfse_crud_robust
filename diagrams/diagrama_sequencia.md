## Sequência (Mermaid)

```mermaid
sequenceDiagram
  autonumber
  participant U as Cliente (Web/Mobile)
  participant CF as CloudFront + WAF
  participant API as API Gateway
  participant COG as Cognito Authorizer
  participant EMIT as Lambda EmitFn
  participant GET as Lambda GetFn
  participant DDB as DynamoDB (InvoicesTable)
  participant S3 as S3 (Docs: XML)
  participant SFN as Step Functions
  participant SQS as SQS (RequestsQueue)
  participant FGT as ECS Fargate (Adapters)
  participant PRV as Provedor Municipal
  participant RDS as Aurora (Data API)
  participant DLQ as SQS (DLQ)
  participant PROC as Lambda ProcessorFn (reprocesso)

  %% Emissão (síncrono)
  U->>CF: POST /invoices (JWT + x-api-key)
  CF->>API: encaminha (HTTPS)
  API->>COG: valida JWT
  COG-->>API: OK
  API->>EMIT: invoke (cnpj, municipio, total)
  EMIT->>DDB: putItem {invoiceId, status=EMITTED, createdAt, total, cnpj}
  EMIT->>S3: putObject xml/{invoiceId}.xml (xmlKey)
  EMIT->>SFN: startExecution(invoiceId, xmlKey, ...)
  EMIT-->>U: 201 {invoiceId, EMITTED, xmlKey}

  %% Orquestração -> Fila
  SFN->>SQS: SendMessage (payload)

  %% Consumo principal pela ECS (long polling)
  FGT->>SQS: ReceiveMessage (long poll)
  SQS-->>FGT: Mensagem (invoiceId, xmlKey, ...)

  %% Chamada ao provedor
  FGT->>PRV: emitir NFS-e (HTTP/SOAP + retry/backoff)
  alt sucesso
    PRV-->>FGT: protocolo
    FGT->>DDB: update {status=ISSUED, processedAt, providerProtocol}
    FGT->>RDS: UPSERT nfse.invoices(...)
    FGT->>SQS: DeleteMessage
  else erro temporário
    PRV-->>FGT: erro/timeout
    FGT->>SQS: ChangeMessageVisibility (reentrega futura)
  else falhas repetidas
    SQS-->>DLQ: MoveToDLQ (após N tentativas)
  end

  %% Reprocesso manual/automação da DLQ (fora do caminho principal)
  opt Reprocesso DLQ
    PROC->>DLQ: ReceiveMessage
    DLQ-->>PROC: Mensagem (invoiceId, ...)
    PROC->>PRV: tentar novamente
    alt sucesso
      PRV-->>PROC: protocolo
      PROC->>DDB: update {status=ISSUED, processedAt, providerProtocol}
      PROC->>RDS: UPSERT nfse.invoices(...)
      PROC->>DLQ: DeleteMessage
    else falha
      PRV-->>PROC: erro
      PROC->>DDB: update {status=FAILED, error, processedAt}
      PROC-->>DLQ: (manter p/ nova análise)
    end
  end

  %% Consulta
  U->>CF: GET /invoices/{invoiceId}
  CF->>API: encaminha
  API->>GET: invoke
  GET->>DDB: getItem(invoiceId)
  DDB-->>GET: {status, xmlKey, providerProtocol, ...}
  GET-->>U: 200 {status, xmlKey, providerProtocol, ...}

  ```