# PRD da plataforma para mercado autônomo

## Objetivo

Definir o escopo do MVP que conecta cadastro e atendimento do cliente à autorização de acesso, compra, pagamento e operação. O chatbot conduz a conversa; regras de identidade, acesso e transação permanecem determinísticas no backend e geram registros auditáveis.

Este PRD consolida o escopo do plano de desenvolvimento com o estado observado no repositório. Uma capacidade marcada como implementada descreve a base de código disponível; integrações externas ainda dependem de fornecedor, credenciais e validação em ambiente contratado.

## Usuários e sistemas envolvidos

| Ator | Necessidade |
| --- | --- |
| Cliente | Cadastrar-se, validar o telefone, consentir com os termos aplicáveis, acessar a loja e consultar ou regularizar pagamentos. |
| Operador | Acompanhar a operação e tratar falhas, notificações e pendências. |
| Dispositivo de acesso | Solicitar uma decisão de entrada e executar a decisão autorizada pelo backend. |
| Integrador de POS/ERP ou pagamento | Registrar compras e enviar resultados de cobrança com segurança e idempotência. |
| Sistema | Processar notificações, retenção, auditoria e tarefas operacionais. |

## Jornada principal do MVP

1. O cliente inicia o cadastro por API ou pelo fluxo de onboarding conversacional.
2. O cliente confirma o telefone por OTP e registra os consentimentos exigidos pela operação.
3. Um provedor biométrico registra uma referência de enrollment; a aplicação não deve armazenar imagens faciais brutas.
4. Um dispositivo envia uma solicitação de acesso. O backend aplica as regras de conta, biometria, prova de vida e política de pagamento.
5. Uma entrada autorizada cria uma sessão que pode ser associada à compra.
6. Uma integração de POS/ERP ou o fluxo de homologação registra a compra em centavos.
7. O orquestrador envia a cobrança por um método tokenizado e processa o resultado por resposta ou webhook assinado.
8. Se houver recusa ou pendência, a dívida fica consultável, novas tentativas seguem a política configurada e a notificação entra na fila de entrega.
9. O operador acompanha indicadores e eventos correlacionados e pode tratar exceções autorizadas.

## Requisitos funcionais

| ID | Requisito e critério de aceite | Estado no repositório |
| --- | --- | --- |
| PRD-01 | Criar e consultar clientes com telefone validado por formato, e-mail opcional e estado de conta explícito. | API disponível. |
| PRD-02 | Solicitar e verificar OTP com expiração, limite de tentativas e uso único. Um novo desafio invalida o anterior; o código de desenvolvimento não deve ser exposto em produção. | Fluxo de desenvolvimento disponível; provedor real de SMS/WhatsApp pendente. |
| PRD-03 | Registrar versões de Termos, Aviso de Privacidade e consentimento biométrico com trilha consultável. | API disponível. A política jurídica e os textos aprovados dependem da operação. |
| PRD-04 | Retomar uma sessão de onboarding e avançar por nome, telefone, OTP e consentimentos até encaminhar a captura biométrica a uma interface/provedor seguro. | Chat determinístico persistido disponível; captura real pendente. |
| PRD-05 | Receber uma solicitação de acesso e devolver decisão explicável, horário e identificador de correlação. Uma falha não pode autorizar entrada por estado indefinido. | Regras e API disponíveis; reconhecimento e controlador de porta usam simulação/contratos substituíveis. |
| PRD-06 | Registrar compras e itens com quantidade, preços, descontos e totais calculados em centavos. | API disponível; integração real com POS/ERP pendente. |
| PRD-07 | Cobrar uma compra sem armazenar dados completos do cartão. Exigir `Idempotency-Key` na criação de compra e pagamento e impedir regressão de estado após aprovação. | Fluxo e proteção de webhook disponíveis; gateway contratado pendente. |
| PRD-08 | Aceitar eventos de pagamento assinados e idempotentes; registrar tentativa, referência do provedor e motivo de recusa sem regredir estado aprovado. | Webhook disponível; validação ponta a ponta com gateway pendente. |
| PRD-09 | Consultar dívidas, regularizar com novo token de pagamento e impedir novo acesso quando a política de inadimplência assim determinar. | Fluxo disponível com provedores simulados. |
| PRD-10 | Enfileirar notificações sem duplicação, aplicar retries duráveis com backoff, isolar falhas persistentes e permitir reprocessamento autorizado. | Outbox, worker e dead-letter queue disponíveis; credenciais e templates reais pendentes. |
| PRD-11 | Exibir resumo operacional com clientes, pagamentos, dívidas, falhas de notificação e eventos recentes, sem incluir dados pessoais desnecessários. | Endpoints `/operator/overview`, `/operator/payments` e `/operator/debts` disponíveis; a console conecta resumo, acessos, pagamentos e dívidas. Notificações ainda precisam de consulta operacional própria. |
| PRD-12 | Anonimizar dados pessoais quando permitido, executar retenção configurada e rotacionar ciphertexts sem perder a capacidade de leitura durante a transição. | Endpoints operacionais disponíveis; prazos e base legal exigem aprovação da operação. |

## Regras de segurança e autorização

- As decisões críticas de acesso e cobrança são determinísticas e independentes de LLM.
- As rotas aplicam os papéis `CUSTOMER`, `OPERATOR`, `DEVICE`, `INTEGRATOR` e `SYSTEM` segundo menor privilégio. Clientes só consultam os próprios recursos; dispositivos solicitam decisões de acesso; integradores registram compras/pagamentos; operadores tratam operações.
- Em produção, usar identidade configurada (atualmente há suporte a Supabase Auth), PostgreSQL, migrações explícitas, gestão externa de segredos, chaves de criptografia e simuladores desativados.
- Assinar webhooks e validar idempotência antes de alterar pagamentos. Correlacionar requisições, eventos e erros sem registrar OTP, token de pagamento, credenciais, conteúdo de mensagens ou dados biométricos.
- Manter referências biométricas segregadas e criptografadas. Captura, prova de vida, limiar de similaridade, retenção e exclusão devem ser responsabilidade de fornecedor/provedor aprovado.
- Não tratar a configuração de desenvolvimento do Compose, tokens locais ou segredo de exemplo como configuração de produção.

## Escopo fora do MVP

- Identificação automática de produtos por computer vision, RFID ou antifraude baseado em IA.
- Decisão de acesso ou cobrança por um modelo de linguagem.
- Implementação de fornecedor biométrico, hardware de porta, PSP, WhatsApp Business ou ERP sem seleção e credenciais aprovadas.
- Operação SaaS multi-tenant completa: o modelo atual aceita identificadores de loja em alguns fluxos, mas isolamento, administração e políticas por tenant ainda precisam ser definidos.
- Metas quantitativas de disponibilidade, latência e recuperação ainda não aprovadas.

## Critérios de aceite do piloto

O piloto só começa quando uma jornada sintética ponta a ponta puder ser executada em ambiente isolado: onboarding, OTP real, consentimentos aprovados, enrollment e acesso com provedor/dispositivo, compra associada à sessão, cobrança, webhook, notificação e auditoria. Também deve haver teste de falha para recusa, timeout, duplicidade de webhook, integração indisponível, dívida aberta, reprocessamento de notificação e rollback operacional.

Antes de usar dados ou uma porta real, a operação deve aprovar os fornecedores, as políticas de acesso e inadimplência, textos/versões de consentimento, retenção, atendimento de direitos do titular, estratégia de backup/restauração e critérios de contingência da porta.

## Métricas a instrumentar

- Onboarding: taxa de conclusão, tempo de conclusão, OTP expirado/recusado e falha de enrollment.
- Acesso: decisões autorizadas/negadas, latência, falha de dispositivo e uso de fallback.
- Comércio: compras por sessão, erros de integração e divergência de totais.
- Pagamentos: aprovação, recusa, pendência, recuperação e tempo até regularização.
- Notificações: entrega, falha, retries, backlog e itens em dead-letter.
- Operação: disponibilidade, latência, readiness, eventos de auditoria e falhas de integração.

Os limites e metas de sucesso serão definidos antes do piloto, usando a loja e o volume de operação escolhidos.

## Decisões pendentes

1. Qual fornecedor entregará OTP e qual canal será usado no piloto?
2. Qual provedor biométrico fornece enrollment, liveness, reconhecimento, fallback e exclusão?
3. Qual modelo de controlador de porta e protocolo de integração serão usados? Qual comportamento seguro deve ocorrer se o backend estiver indisponível?
4. Qual POS/ERP será integrado e qual evento fecha uma sessão de compra?
5. Qual PSP, métodos de pagamento, regras de retry, contestação e regularização serão usados?
6. Qual conta Meta, template e política de comunicação transacional serão aprovados para WhatsApp?
7. A primeira implantação é de uma única loja ou exige isolamento multi-tenant desde o piloto?
8. Quais documentos, prazos de retenção e fluxos de direitos do titular serão aprovados pelo jurídico/DPO?
9. Quais metas de disponibilidade, latência, RPO e RTO o piloto precisa cumprir?

## Próxima entrega de engenharia

Fechar as decisões pendentes do piloto e converter este PRD em backlog com histórias e critérios de aceite. Em seguida, implementar e homologar a primeira integração real de OTP no contrato existente, sem acoplar o fluxo conversacional a um fornecedor específico. A seleção do fornecedor e das credenciais é uma dependência antes da homologação externa.

## Referências do repositório

- `README.md`: capacidades atuais, execução local, segurança e limitações de produção.
- `plano_desenvolvimento_chatbot_mercado_autonomo.docx`: visão, fases, MVP, riscos e artefatos recomendados.
- `src/market_api/main.py`, `src/market_api/domain.py`, `src/market_api/onboarding.py` e `src/market_api/auth.py`: contratos, regras e autorização atuais.
