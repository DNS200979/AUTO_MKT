# Console do operador

Frontend React/Vite da vertical slice da POC. A tela funciona em modo demonstração
quando a API não está disponível e tenta consumir `GET /operator/overview` quando
`VITE_API_BASE_URL` está configurada.

```bash
npm install
cp .env.example .env.local
npm run dev
```

Com `VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY`, a console usa Supabase Auth com
sessão restrita ao navegador e envia o JWT para a API. Sem essas variáveis, a POC mantém
o fallback de token local. O backend deve usar `MARKET_AUTH_MODE=supabase` e o usuário
precisa ter `app_metadata.market_role=OPERATOR`.
