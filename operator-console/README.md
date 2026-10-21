# Console do operador

Frontend React/Vite da vertical slice da POC. A visão operacional e a tela de acessos
consomem `GET /operator/overview`. A tela de acessos filtra os eventos de autorização,
recusa e controlador da porta sem exibir dados pessoais.
A tela de pagamentos consulta `GET /operator/payments`, com filtro por estado e paginação.
A resposta omite o cliente e o token de pagamento.
A tela de dívidas consulta `GET /operator/debts`, com filtro por estado, valor total e paginação.
Sua resposta também omite dados pessoais e o token de pagamento.

Durante o desenvolvimento, o Vite encaminha `/api/*` para a API local em `127.0.0.1:8000`.
Configure `VITE_API_BASE_URL` para apontar diretamente ao backend em outro ambiente.
A console mostra dados de demonstração se a API não estiver disponível.

```bash
npm install
cp .env.example .env.local
npm run dev
```

Com `VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY`, a console usa Supabase Auth com
sessão restrita ao navegador e envia o JWT para a API. Sem essas variáveis, a POC mantém
o fallback de token local. O backend deve usar `MARKET_AUTH_MODE=supabase` e o usuário
precisa ter `app_metadata.market_role=OPERATOR`.
