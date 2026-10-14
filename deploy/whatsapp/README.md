# Gateway WhatsApp

Variáveis obrigatórias em produção: `MERCURIO_TOKEN_SALT`, `MERCURIO_PHONE_KEY`, `META_ACCESS_TOKEN`,
`META_PHONE_NUMBER_ID`, `META_VERIFY_TOKEN` e `META_APP_SECRET`. Injete-as pelo
gerenciador de segredos da hospedagem; não use `.env` versionado.
Gere `MERCURIO_PHONE_KEY` como uma chave Fernet; ela protege telefones em repouso.

O armazenamento SQLite incluído serve ao piloto de instância única. Antes de
escalar horizontalmente, substitua `ServerStore` por PostgreSQL e implemente
rate limiting compartilhado. O endpoint público deve usar HTTPS.
