# MERCÚRIO — Plano de implementação

**Versão:** 0.1 · **Data:** 14 de outubro de 2026

## Objetivo

Entregar uma CLI Python que autorize o Google Classroom, sincronize atividades,
calcule lembretes idempotentes, rode periodicamente no Linux e possa enviar
mensagens autorizadas pelo WhatsApp através de um serviço seguro.

## Fases e critérios de conclusão

1. **Fundação:** pacote instalável, CLI, configuração XDG, lint, tipos e testes.
2. **Domínio e SQLite:** modelos, migrações, fuso horário e chave idempotente;
   testes de datas, atualização de prazo, persistência e concorrência.
3. **Google:** OAuth Desktop, paginação de cursos/trabalhos/submissões e erros;
   teste manual lista atividades reais sem registrar credenciais em logs.
4. **Lembretes:** marcos de 7 dias, 3 dias, 24 h e 2 h, console, retomada e
   cancelamento; nenhum duplicado após reinício ou mudança de prazo.
5. **Automação e privacidade:** timer `systemd --user`, lock, retry, retenção,
   consentimentos independentes, logout e exclusão local verificável.
6. **WhatsApp:** API intermediária autenticada, convites, consentimento,
   idempotência, rate limit, templates e webhooks assinados; teste ponta a
   ponta em telefone autorizado sem expor o token Meta ao cliente.
7. **Release candidato:** fluxo completo, documentação reproduzível, cobertura
   global mínima de 85% e zero segredo detectado.

## Interfaces fixadas

CLI: `setup`, `auth login|status|logout`, `atividades`, `sync`, `avisos`,
`status`, `start`, `stop`, `canal whatsapp conectar|desconectar` e
`dados apagar`.

API do serviço: `POST /v1/enrollments`, `POST /v1/enrollments/{id}/verify`,
`POST /v1/notifications`, `DELETE /v1/enrollments/{id}`,
`GET|POST /v1/webhooks/meta` e endpoints de saúde.

## Fora desta versão

Interface gráfica, aplicativo móvel, IA, entrega de trabalhos, painel web,
publicação OAuth ampla, AUR e abertura pública sem convites.

