# Proposta de trabalho

Monte um desenho de arquitetura a nível de componente obrigatoriamente usando a AWS, especificando os serviços utilizados e tecnologias aplicáveis em cada camada. Explique ou especifique no desenho as camadas de segurança, o fluxo de comunicação e responsabilidades.
O sistema a ser desenvolvido deve possuir uma área administrativa (web), um aplicativo (iOS e Android) e uma API que deve receber um grande volume de requisições com a finalidade de fazer emissão, consulta e cancelamento de nota fiscal de serviço.


# Solução proposta

A solução proposta é baseada em uma arquitetura serverless utilizando serviços da AWS, como Lambda, API Gateway, DynamoDB, S3, Cognito, Step Functions e outros.
Abaixo a lista de arquivos que explicam a arquitetura proposta bem como o status dos itens já implantados e os que ainda serão.

- fluxo para apresencao do projeto : diagrams/fluxo_apresentacao_projeto.md
- diagrama de sequência : diagrams/diagrama_sequencia.md
- infraestrutura AWS implantada: diagrams/infrastructure-composer-NfseStack
- fluxograma da arquitetura + status da implementação  : diagrams/nfse-arquitetura-fluxograma-status.png/.html
- detalhes da arquitetura : diagrams/nfse-arquitetura.md
- ferramentas da AWS: diagrams/ferramentas-aws.md
- tela da área administrativa (web): web/admin-app_img.png
