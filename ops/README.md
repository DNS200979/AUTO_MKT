# Backup e recuperação

Os scripts deste diretório são auxiliares de operação e não fazem parte do processo da
API. O backup deve ser armazenado fora do host, com criptografia, retenção imutável e
controle de acesso separado das chaves Fernet da aplicação.

Eles exigem `pg_dump`, `pg_restore`, `psql`, `sha256sum` e Bash no host operador. Em
ambientes containerizados, use a imagem oficial `postgres:<major>-alpine` como cliente
descartável, mantendo a mesma versão major do servidor.

## Backup

```bash
MARKET_DATABASE_URL='postgresql://...' \
BACKUP_DIR=/var/backups/market BACKUP_LABEL=market-$(date -u +%Y%m%dT%H%M%SZ) \
./ops/backup_postgres.sh
```

O comando gera `*.dump` em formato customizado e `*.sha256`. O diretório local é apenas
um estágio: copie os dois arquivos para armazenamento externo antes de considerar o
backup concluído.

## Upload criptografado para R2

Depois de instalar `age` e a AWS CLI, o upload usa a API S3 compatível do R2. A chave
privada `age` deve ser guardada fora do R2 e dos segredos da aplicação; somente a chave
pública fica no job:

```bash
R2_ENDPOINT=https://ACCOUNT_ID.r2.cloudflarestorage.com \
R2_BUCKET=market-backups AGE_RECIPIENT=age1... \
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
./ops/upload_backup_r2.sh /var/backups/market/market-20260825T030000Z.dump
```

O script criptografa antes do upload, calcula o hash do arquivo criptografado e envia o
`.age` e o `.sha256` para um prefixo particionado por data. Crie um token R2 limitado ao
bucket de backup, sem permissões de leitura ou escrita em outros buckets.

## Teste de restauração

Use um PostgreSQL descartável ou uma instância isolada com a mesma versão major:

```bash
./ops/verify_restore_postgres.sh \
  /var/backups/market/market-20260825T030000Z.dump \
  'postgresql://restore_user:...@restore-db:5432/market_restore'
```

Por padrão o destino não é apagado. `ALLOW_DESTRUCTIVE_RESTORE=YES` habilita
`--clean --if-exists` e só deve ser usado quando o alvo foi confirmado explicitamente.
Depois da restauração, execute `alembic current`, `GET /ready` e uma jornada sintética.

## Metas operacionais

- RPO inicial: 24 horas, reduzível com agendamento de dumps e WAL archiving do provedor.
- RTO inicial: 4 horas, incluindo provisionamento, restauração, migração e smoke test.
- Realizar um teste de restauração pelo menos mensalmente e registrar duração, revisão
  Alembic, hash do backup e resultado do smoke test.
- Manter a cópia de backup e as chaves de criptografia em domínios de falha e controles
  de acesso diferentes; backup sem as chaves não recupera os dados sensíveis.
