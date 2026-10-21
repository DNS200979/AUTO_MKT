# Plataforma para Mercado Autonomo

Primeiro incremento executavel do plano de desenvolvimento. A API implementa o nucleo
deterministico de cadastro e autorizacao de acesso, sem armazenar dados de cartao ou
imagens biometricas.

## O que ja funciona

- cadastro e consulta persistente de clientes;
- verificacao de telefone por OTP com expiracao, limite de tentativas e uso unico;
- registro versionado de consentimentos;
- ativacao, bloqueio e desbloqueio de conta;
- referencia de enrollment biometrico (o template fica no provedor/cofre);
- autorizacao de acesso por regras explicaveis;
- criacao de sessao para cada acesso autorizado;
- compras e itens com valores calculados em centavos;
- cobranca tokenizada e retry de pagamentos recusados ou pendentes;
- webhooks de pagamento assinados e idempotentes;
- estados de pagamento protegidos contra regresso depois da aprovacao;
- notificacao unica de recusa registrada em outbox para WhatsApp;
- consulta e regularizacao de dividas com troca segura do token;
- bloqueio de acesso enquanto houver pendencia e liberacao apos quitar todas;
- trilha de auditoria correlacionada por cliente e recurso.

Por padrao a aplicacao usa SQLite para desenvolvimento local. PostgreSQL pode ser
ativado apenas configurando `MARKET_DATABASE_URL`.

## Continuidade do desenvolvimento

O repositório reúne o backend FastAPI (`src/market_api/`), a console React/Vite
(`operator-console/`), migrações (`migrations/`), testes (`tests/`) e scripts de
operação (`ops/`). O documento `plano_desenvolvimento_chatbot_mercado_autonomo.docx`
contém o planejamento; as funcionalidades entregues devem ser conferidas no código
e nos testes, pois o planejamento também inclui trabalho futuro.

Para começar em outra máquina:

```bash
git clone https://github.com/DNS200979/AUTO_MKT.git
cd AUTO_MKT
```

Use Python 3.12 ou superior e siga a seção **Executar** abaixo. Para a console,
use uma versão LTS do Node.js compatível com o Vite registrado no lockfile:

```bash
cd operator-console
npm ci
cp .env.example .env.local
npm run dev
```

O exemplo do backend habilita autenticação de desenvolvimento. Para conectar a
console local, use o token de exemplo `operator-local-secret`. Deixe as variáveis
Supabase vazias até configurar um projeto real. Esses valores de exemplo servem
somente ao desenvolvimento local.

Os arquivos `.env` e `.env.local`, credenciais de infraestrutura, bancos locais,
dependências instaladas e builds não são versionados. Configure cada ambiente
a partir dos `.env.example`; acessos reais devem ser compartilhados por um canal
seguro, fora do Git. O envio do código não configura nem valida um deploy.

Antes de alterar o projeto, execute `pytest -q` e `ruff check src tests migrations`
no ambiente Python; na console, execute `npm run build`. A CI do GitHub também
verifica migrações, dependências e a imagem Docker.

As próximas integrações a validar incluem OTP por provedor real, biometria,
controlador de porta, gateway de pagamento e WhatsApp no ambiente contratado.
O fluxo atual de onboarding é determinístico, e o rate limiting ainda é local
ao processo. Consulte as seções específicas abaixo para os contratos existentes
e os requisitos de produção.

## Estado atual do projeto — 21/10/2026

- A console do operador consulta a API para o resumo operacional, acessos,
  pagamentos e dívidas abertas. Os endpoints de pagamentos e dívidas aceitam
  filtros e paginação; o endpoint de dívidas também retorna o valor agregado.
- `ops/seed_local_demo.py` gera registros sintéticos apenas em SQLite e em
  desenvolvimento. Ele se recusa a misturar exemplos com uma base que já tenha
  registros. Identificadores `DEMO-*` não são transações reais.
- Neste workspace, a API está configurada para um PostgreSQL 17 local, na base
  `market`. O esquema está na revisão Alembic `c4f1b2a3d4e5`; `/ready` confirmou
  banco e esquema disponíveis. O arquivo `.env` e os dados locais não são
  versionados.
- A base PostgreSQL local está vazia e nenhuma fonte real de POS/ERP ou gateway
  está conectada. A console mostrará zero registros até importar dados da
  operação ou implementar a integração correspondente. Não usar dados de demo
  para representar atividade real.
- Última verificação registrada: `pytest` — 60 testes passaram, com um aviso de
  depreciação do Starlette. Ruff, build da console e a prontidão da API também
  foram verificados. A suíte de testes foi executada antes de configurar este
  PostgreSQL local.

Próximo passo: identificar a fonte dos dados da operação (POS/ERP, gateway ou
exportação CSV/Excel), definir o mapeamento e então validar a tela com registros
reais em um ambiente apropriado. `docs/PRD.md` resume o escopo funcional,
integrações pendentes e critérios de aceite do piloto.

## Executar

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
docker compose up -d postgres
alembic upgrade head
uvicorn market_api.main:app --reload
```

A documentacao interativa fica em `http://127.0.0.1:8000/docs`.

## Banco, migracoes e prontidao

O esquema e versionado com Alembic. Antes de iniciar uma nova versao da API, execute:

```bash
alembic upgrade head
```

Para conferir se uma alteracao do modelo ainda precisa de migracao:

```bash
alembic check
```

`MARKET_AUTO_CREATE_SCHEMA=true` existe apenas para facilitar testes e desenvolvimento
local. Em ambientes gerenciados use `false`, aplique as migracoes como uma etapa unica
do deployment e habilite `MARKET_ENFORCE_MIGRATION_HEAD=true`.

`GET /health` e um liveness check sem dependencia externa. `GET /ready` testa a conexao
com o banco e a presenca do esquema; com enforcement ativo, tambem exige que a revisao
do banco seja exatamente o `head` do Alembic. Falhas retornam `503`.

Em `production`, a aplicacao se recusa a iniciar com SQLite, criacao automatica de
tabelas, migracao sem enforcement, segredos padrao, simuladores ativos ou autenticacao
local/desabilitada. O PostgreSQL do `compose.yaml` usa credenciais locais e nao deve ser
reutilizado em producao.

## Observabilidade

Cada requisicao recebe `X-Correlation-ID`. Um valor valido enviado pelo chamador e
preservado; caso contrario, a API gera um UUID. O mesmo identificador aparece na
resposta, nos erros e nos logs JSON. Erros seguem um envelope estavel:

```json
{
  "error": {"code": "NOT_FOUND", "message": "customer not found"},
  "correlation_id": "pilot-request-123"
}
```

`GET /metrics` expoe contadores e histogramas no formato Prometheus para requisicoes
HTTP, decisoes de acesso, pagamentos e entregas do worker. Quando a autenticacao esta
ativa, somente `SYSTEM` e `OPERATOR` podem consultar essa rota. Evite publicar o endpoint
diretamente na internet; restrinja-o a rede de observabilidade.

```dotenv
MARKET_LOG_LEVEL=INFO
MARKET_METRICS_ENABLED=true
```

## Vertical slice da POC

O endpoint `GET /operator/overview` entrega o primeiro contrato do painel operacional,
restrito a `OPERATOR` e `SYSTEM`: contagens de clientes e pagamentos por estado, total
e valor de dividas abertas, notificacoes em falha e os eventos de auditoria mais recentes.
Ele nao retorna telefone, email, biometria, tokens ou payloads de notificacao, permitindo
que um frontend de operador seja conectado sem ampliar a superficie de dados sensiveis.
O parametro `limit` aceita de 1 a 50 eventos.

O frontend correspondente está em `operator-console/`. Ele apresenta a visão inicial
da operação, funciona com dados de demonstração quando a API não está disponível e
consome o endpoint acima quando `VITE_API_BASE_URL` é configurada. Execute `npm install`
e `npm run dev` dentro desse diretório para abrir a console local.

Os labels usam apenas valores limitados como rota, status e resultado; IDs de cliente,
pagamento e notificacao ficam nos logs, nao nos labels. O worker usa o ID da notificacao
como correlation ID e nao registra telefone nem o conteudo da mensagem.

## Resiliencia das integracoes

Chamadas externas usam timeout configuravel e falhas normalizadas como transitorias ou
definitivas. No WhatsApp, timeout/erro de transporte, `408`, `429` e `5xx` sao
transitorios; rejeicoes `4xx` sao definitivas. Respostas de sucesso malformadas tambem
sao definitivas, pois repetir nao corrige o contrato.

O worker faz retry duravel com backoff exponencial e jitter. Nao ha retry imediato da
mesma requisicao HTTP, pois uma resposta perdida pode esconder uma entrega concluida e
duplicar a mensagem. O circuit breaker abre depois de falhas transitorias consecutivas,
recusa chamadas durante a janela de recuperacao e permite uma unica sonda em half-open.

```dotenv
MARKET_WHATSAPP_TIMEOUT_SECONDS=15
MARKET_NOTIFICATION_RETRY_BASE_SECONDS=30
MARKET_NOTIFICATION_RETRY_MAX_SECONDS=3600
MARKET_NOTIFICATION_RETRY_JITTER_RATIO=0.20
MARKET_INTEGRATION_CIRCUIT_FAILURE_THRESHOLD=5
MARKET_INTEGRATION_CIRCUIT_RECOVERY_SECONDS=30
```

Falhas definitivas ou tentativas esgotadas entram na dead-letter queue, representada por
notificacoes `FAILED`. Operadores e processos `SYSTEM` podem inspecionar e reprocessar:

- `GET /operations/dead-letters`;
- `POST /operations/dead-letters/{notification_id}/requeue`.

O reprocessamento zera as tentativas, remove o ultimo erro, registra auditoria e devolve
a notificacao para `QUEUED`.

## Criptografia e dados sensiveis

Tokens de pagamento e referencias biometricas usam Fernet, com confidencialidade e
autenticacao do ciphertext. O formato `enc:v1:{key_id}:{token}` permite identificar a
chave sem tentar todas as chaves. O primeiro item do mapa JSON e a chave ativa para
novas escritas; as demais permanecem disponiveis somente para leitura durante a rotacao.

Gere chaves fora do repositorio e entregue-as por secret manager:

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

```dotenv
MARKET_DATA_ENCRYPTION_KEYS={"key-2026-08":"BASE64_FERNET_KEY_ATIVA","key-antiga":"BASE64_FERNET_KEY_ANTIGA"}
MARKET_OPERATIONAL_RETENTION_DAYS=90
```

Para rotacionar, adicione a nova chave na primeira posicao, mantenha as anteriores e
execute primeiro `POST /operations/encryption/rotate?dry_run=true` e depois a mesma rota
sem `dry_run`. Os mapas `before` e `after` contabilizam ciphertexts por `key_id`. Remova
uma chave antiga somente quando ela estiver ausente de `after` e depois de validar o backup.
Registros legados em texto puro sao aceitos durante a transicao e criptografados por
essa mesma operacao.

Em producao, prefira montar um arquivo JSON de modo somente leitura por Docker Secrets,
Kubernetes Secrets CSI ou um agente do cofre corporativo e informe seu caminho em
`MARKET_SECRETS_FILE`. O arquivo e autoritativo para os campos presentes e aceita apenas:
`data_encryption_keys`, `onboarding_token_secret`, `webhook_secret`,
`whatsapp_access_token`, `whatsapp_app_secret`, `whatsapp_verify_token` e
`development_auth_tokens`. Exemplo:

```json
{
  "data_encryption_keys": {"key-2026-09": "BASE64_FERNET_KEY"},
  "webhook_secret": "SEGREDO_DO_WEBHOOK",
  "onboarding_token_secret": "SEGREDO_COM_PELO_MENOS_32_CARACTERES"
}
```

A atualizacao deve ser atomica (novo arquivo e troca de mount/symlink) e requer reinicio
controlado dos processos; a aplicacao nunca registra o conteudo do arquivo. O backend
concreto do cofre e sua identidade de workload continuam sendo configuracoes externas.

Operacoes de privacidade, restritas a `OPERATOR` e `SYSTEM`:

- `POST /operations/customers/{customer_id}/anonymize`: bloqueia quando existe divida
  aberta e remove nome, contato, biometria, tokens reutilizaveis e payloads de mensagem;
- `POST /operations/retention/run`: remove OTPs expirados e registros antigos de
  idempotencia de webhook conforme a janela configurada;
- `POST /operations/encryption/rotate`: recriptografa dados com a chave ativa.

Compras, pagamentos, consentimentos, auditoria e IDs pseudonimos sao preservados para
integridade financeira e evidencia operacional. A janela e as bases de retencao devem
ser aprovadas juridicamente antes do piloto. Em producao, a aplicacao nao inicia sem
chaves de criptografia configuradas.

## Empacotamento, CI e entrega

O `Dockerfile` usa build em dois estagios e executa API, worker e Alembic como UID/GID
`10001`, sem shell de login e sem codigo-fonte de testes na imagem final. A mesma imagem
e usada pelos tres processos.

Para homologacao local:

```bash
docker compose up --build
docker compose ps
curl -fsS http://127.0.0.1:8000/ready
```

O servico `migrate` aguarda o PostgreSQL, aplica `alembic upgrade head` e precisa
terminar com sucesso antes de `api` e `worker` iniciarem. O Compose usa credenciais de
desenvolvimento por padrao; defina `POSTGRES_PASSWORD` e os demais segredos fora do
arquivo em qualquer ambiente compartilhado.

O workflow `CI` executa lint, testes, compilacao, ida e volta das migracoes, auditoria de
dependencias, build da imagem e verificacao do usuario nao-root. Tags `v*` disparam o
workflow de release, que publica no GHCR duas referencias imutaveis: a tag da versao e o
SHA do commit. As actions oficiais de checkout e Python usam a geracao 7, compativel com
o runtime Node atual do GitHub Actions.

### Procedimento de deploy

1. Criar backup e validar restauracao do PostgreSQL.
2. Selecionar a imagem pelo SHA, nunca por `latest`.
3. Executar uma unica instancia de `alembic upgrade head`.
4. Iniciar API e worker com os mesmos segredos e versao de imagem.
5. Aguardar `/ready` e executar a jornada sintetica antes de liberar trafego.
6. Monitorar erros, latencia, circuit breakers e dead letters.

O procedimento executável está em [ops/README.md](ops/README.md). Ele gera dumps
customizados com manifesto SHA-256 e exige um banco-alvo isolado para o teste de
restauração. O armazenamento externo deve fornecer criptografia, retenção imutável e
permissões separadas das chaves de dados da aplicação.

### Procedimento de rollback

1. Retirar a versao com falha do balanceador.
2. Reimplantar a imagem anterior pelo SHA.
3. Manter o banco na migracao mais nova quando ela for retrocompativel.
4. Executar `alembic downgrade <revision>` somente se a migracao declarar rollback
   seguro, depois de backup e janela aprovada.
5. Confirmar `/ready`, worker e jornada sintetica antes de restaurar trafego.

Publicacao da imagem nao equivale a deploy em uma nuvem especifica. Credenciais do
cluster, registro definitivo, estrategia blue/green e aprovacao do ambiente continuam
dependendo da infraestrutura escolhida.

Em `development`, a resposta de solicitacao do OTP inclui `development_code` para
facilitar testes. Configure `MARKET_ENVIRONMENT=production` para nunca retornar o
codigo pela API; nessa configuracao, um adaptador de SMS/WhatsApp deve ser conectado.

Chamadas `POST /purchases` e `POST /payments` exigem o header `Idempotency-Key`.
Webhooks usam `X-Webhook-Signature`, calculado como HMAC-SHA256 de
`event_id:payment_id:status` com `MARKET_WEBHOOK_SECRET`.

As notificacoes ficam inicialmente em estado `QUEUED`. Um worker/provedor de WhatsApp
podera consumi-las sem acoplar mensageria ao processamento financeiro do webhook.

## Homologacao local sem fornecedores

Ative `MARKET_SIMULATION_ENABLED=true` somente em desenvolvimento ou homologacao. As
rotas sob `/simulations` ficam desabilitadas por padrao e permitem validar a jornada
antes da contratacao dos fornecedores:

- `POST /simulations/customers/{customer_id}/biometrics`: enrollment com prova de vida;
- `POST /simulations/access`: reconhecimento, decisao de acesso e abertura da porta;
- `POST /simulations/payments/{payment_id}/settle`: resultado do gateway de pagamento.

Os simuladores implementam contratos substituiveis (`BiometricProvider`,
`DoorController` e `PaymentProvider`). Assim, uma integracao real entra como novo
adaptador sem alterar as regras do dominio.

Para cenarios de falha, use `liveness-fail*` ou `no-match*` como referencia biometrica,
`offline*` como porta/dispositivo e os tokens `sim_declined*`, `sim_pending*` ou
`sim_error*`. Qualquer outro token simulado resulta em pagamento aprovado.

## Autenticacao e papeis na homologacao

O modo padrao e `MARKET_AUTH_MODE=disabled` para manter o desenvolvimento inicial
compativel. Para exercitar autorizacao local, use `MARKET_AUTH_MODE=development` e um
mapa JSON de tokens opacos para `SUBJECT:ROLE` em `MARKET_DEVELOPMENT_AUTH_TOKENS`.
Esse modo guarda somente hashes dos tokens em memoria e se recusa a iniciar quando
`MARKET_ENVIRONMENT=production`.

Os papeis suportados sao `CUSTOMER`, `OPERATOR`, `DEVICE`, `INTEGRATOR` e `SYSTEM`.
Quando a autenticacao esta ativa, as rotas operacionais aplicam menor privilegio:
dispositivos autorizam acesso, integradores registram compra/pagamento, operadores
administram a operacao e clientes consultam somente os proprios recursos. Cadastro,
solicitacao e verificacao de OTP permanecem publicos; consentimentos e enrollment
exigem uma credencial temporaria quando a autenticacao esta ativa.

O contrato `AuthProvider` separa as regras de autorizacao do mecanismo de identidade.
O modo `MARKET_AUTH_MODE=supabase` valida JWTs do Supabase Auth via JWKS. Defina
`MARKET_SUPABASE_URL` e atribua `app_metadata.market_role=OPERATOR` ao usuario do
console. O frontend usa `VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY`; a chave
`service_role` nunca deve ir para o navegador.

### Protecao do onboarding

Cadastro e solicitacao de OTP possuem limites deslizantes por IP; OTP tambem e limitado
por cliente. Excesso retorna `429` com `Retry-After`. Um novo desafio invalida o anterior
e cada codigo continua limitado por expiracao, tentativas e uso unico.

Depois de validar o OTP, a resposta inclui `X-Onboarding-Token` e
`X-Onboarding-Token-Expires-At`. Essa credencial HMAC tem vida curta, papel
`ONBOARDING` e somente pode alterar consentimentos e biometria do proprio cliente.
Configure um segredo aleatorio de pelo menos 32 caracteres:

```dotenv
MARKET_ONBOARDING_TOKEN_TTL_SECONDS=900
MARKET_ONBOARDING_TOKEN_SECRET=replace-with-at-least-32-random-characters
MARKET_REGISTRATION_RATE_LIMIT_PER_MINUTE=5
MARKET_OTP_RATE_LIMIT_PER_MINUTE=3
```

O `DevelopmentOtpProvider` entrega o codigo na resposta apenas em desenvolvimento e
nunca registra o valor. Em producao, a solicitacao retorna `503` enquanto nenhum
adaptador SMS/WhatsApp real estiver configurado. O limitador atual e local ao processo;
uma implantacao com varias replicas devera substitui-lo por estado compartilhado, como
Redis, mantendo a mesma politica.

## Worker de notificacoes

Em outro processo, execute continuamente:

```bash
python -m market_api.worker
```

Para processar somente um lote, util em tarefas agendadas e testes:

```bash
python -m market_api.worker --once
```

O worker processa lotes com lock no PostgreSQL, recupera itens abandonados apos cinco
minutos, aplica backoff exponencial e encerra em `FAILED` depois do limite configurado.
O adaptador atual escreve a entrega no log (`ConsoleProvider`); provedores reais devem
implementar `NotificationProvider` e devolver a referencia externa da mensagem.

### WhatsApp Business Platform

Depois de criar e aprovar o template com duas variaveis no corpo (compra e valor) e um
botao URL dinamico (payment ID), configure:

```dotenv
MARKET_NOTIFICATION_PROVIDER=whatsapp
MARKET_WHATSAPP_GRAPH_VERSION=v25.0
MARKET_WHATSAPP_PHONE_NUMBER_ID=...
MARKET_WHATSAPP_ACCESS_TOKEN=...
MARKET_WHATSAPP_APP_SECRET=...
MARKET_WHATSAPP_VERIFY_TOKEN=...
```

### Chatbot de onboarding

O primeiro fluxo conversacional está disponível em `POST /chat/onboarding`. A sessão é
persistida no banco e conduz nome, telefone, e-mail opcional, OTP, Termos de Uso, Aviso
de Privacidade e autorização de biometria. O endpoint devolve `session_id`, `step`,
mensagens e `next_action`; envie o mesmo `session_id` nas mensagens seguintes. Em
desenvolvimento, `development_code` aparece somente na resposta que dispara o OTP para
permitir testes locais.

```bash
curl -X POST http://127.0.0.1:8000/chat/onboarding \
  -H 'Content-Type: application/json' \
  -d '{"message":"oi"}'
```

O fluxo termina em `next_action=BIOMETRIC_ENROLLMENT`: a captura facial deve ser feita
por uma tela ou provedor seguro, nunca pelo interpretador de linguagem. A camada atual é
determinística e preparada para receber futuramente um LLM apenas para interpretar
linguagem natural e chamar ações com schemas validados.

Cadastre `GET/POST /webhooks/whatsapp` como callback na Meta. O POST valida
`X-Hub-Signature-256` sobre o corpo bruto e atualiza `SENT`, `DELIVERED`, `READ` ou
`FAILED`. A versao da Graph API e configuravel para permitir atualizacoes sem release.

## Testar

```bash
pytest
```

## Limites de seguranca desta versao

Nao use esta versao em uma porta real sem configurar o modo Supabase, banco gerenciado
com backups, rate limiting compartilhado, gestao externa de segredos e integracao
autenticada com dispositivos. Os webhooks de pagamento e
WhatsApp ja validam assinatura; eventos de pagamento tambem sao idempotentes.
