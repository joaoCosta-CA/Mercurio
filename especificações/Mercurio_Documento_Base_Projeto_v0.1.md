> **Propósito** — Reduzir atrasos e esquecimentos de atividades acadêmicas por meio de lembretes automáticos baseados nos prazos registrados no Google Classroom.

*Este documento é um guia de implementação e decisões. Não afirma que as integrações externas ou o envio em produção já estão concluídos.*

# MERCÚRIO — Documento-base do projeto

**Versão:** 0.1 · **Data:** 14 de outubro de 2026 · **Situação:** planejamento e OAuth criado.

**Objetivo:** reduzir perdas de prazo por meio de lembretes automáticos integrados ao Google Classroom.


## 1. Visão geral


### 1.1. Problema e proposta

Estudantes frequentemente perdem prazos por não acompanhar o Google Classroom continuamente, por dispersão das atividades em várias disciplinas ou por simplesmente esquecer uma entrega. O Mercúrio pretende consultar as atividades autorizadas pelo usuário e transformá-las em avisos emitidos com antecedência configurável.

A aplicação inicial será executada no notebook do estudante, em segundo plano, sem necessidade de infraestrutura própria de hospedagem para a leitura e processamento dos prazos. O canal desejado para a notificação é o WhatsApp, com um número associado ao projeto; esse canal será integrado em uma fase posterior, após validar suas regras e segurança.


### 1.2. Objetivos do produto

- Identificar disciplinas e atividades publicadas às quais o usuário tem acesso.
- Ler datas e horários de entrega, links e estado de submissão quando disponível.
- Gerar lembretes nos marcos configurados (ex.: 7 dias, 3 dias, 24 horas, 2 horas).
- Evitar repetição de avisos e interrompê-los quando a entrega estiver concluída.
- Funcionar como ferramenta de linha de comando (CLI) e serviço local no Linux.
- Preparar o código para distribuição como pacote Python e, mais adiante, pela AUR.


### 1.3. Critério principal de sucesso

> **Marco do primeiro protótipo** — O usuário autoriza o Google, visualiza suas atividades reais no terminal e recebe lembretes simulados no horário correto, sem duplicidade e sem guardar a senha da conta Google.


## 2. Delimitação do escopo

| Parte | MVP local | Evolução posterior |
|---|---|---|
| Autenticação | OAuth 2.0 em conta própria | Publicação OAuth e suporte a várias instituições |
| Atividades | Listar cursos, tarefas e prazos | Filtros por curso, prioridades e histórico |
| Alertas | Mensagem simulada no terminal e histórico local | WhatsApp em produção e outros canais |
| Configuração | CLI e arquivo de configuração | Experiência guiada e talvez interface gráfica |
| Execução | Verificação periódica em notebook | Aprimoramento de inicialização e distribuição |
| Distribuição | Instalação em venv / pacote Python | PKGBUILD, AUR e outros sistemas |

Fora do MVP: uso de inteligência artificial; hospedagem própria permanente; aplicativo Android/iOS; escrita ou entrega de atividades no Classroom; painel web; envio massivo sem consentimento; integração de notas e calendário externo.


## 3. Requisitos funcionais

| ID | Requisito | Prioridade |
|---|---|---|
| RF-01 | Autenticar a conta Google usando OAuth de aplicativo desktop. | Essencial |
| RF-02 | Recuperar cursos ativos e percorrer a paginação da API. | Essencial |
| RF-03 | Recuperar atividades, títulos, prazos e URLs. | Essencial |
| RF-04 | Consultar o estado de entrega do próprio estudante. | Essencial |
| RF-05 | Calcular tempo restante no fuso local configurado. | Essencial |
| RF-06 | Gerar lembretes em marcos configuráveis. | Essencial |
| RF-07 | Persistir histórico para impedir envios repetidos. | Essencial |
| RF-08 | Oferecer comandos de consulta e configuração pela CLI. | Essencial |
| RF-09 | Executar verificações automáticas com logs. | Essencial |
| RF-10 | Enviar mensagens reais após opt-in pelo canal autorizado. | Fase 2 |
| RF-11 | Pausar lembretes, revogar autorização e apagar dados locais. | Essencial |
| RF-12 | Permitir empacotamento e instalação via gerenciador. | Fase 3 |


## 4. Requisitos não funcionais

- Segurança: não armazenar a senha Google; solicitar apenas escopos necessários; restringir permissões de arquivos com tokens.
- Privacidade: minimizar coleta e retenção; explicar quais dados são acessados e como removê-los.
- Resiliência: lidar com internet indisponível, tokens inválidos, cotas e falhas de API sem encerrar silenciosamente.
- Idempotência: não disparar o mesmo lembrete duas vezes quando o processo reiniciar.
- Observabilidade: apresentar logs com horário, curso e resultado de cada verificação, sem expor segredos.
- Portabilidade: isolar regras de negócio das integrações; não acoplar todo o código ao systemd ou ao WhatsApp.
- Desempenho: usar consultas periódicas moderadas e paginação, evitando requisições desnecessárias.


## 5. Arquitetura proposta


### 5.1. Arquitetura do MVP — execução no notebook

```text
Usuário -> mercurio setup / mercurio atividades
                      |
                      v
                 CLI Python
                      |
             Google OAuth 2.0
                      |
                      v
              Google Classroom API
                      |
                Normalização
                      |
          Motor de prazos e regras
                      |
            SQLite + histórico
                      |
         Notificador de terminal
                      ^
                      |
           Agendador periódico
             (systemd / APScheduler)
```

O aplicativo consulta dados em nome do estudante, transforma atividades em objetos internos, compara o prazo com a data atual e decide se existe aviso a registrar. O notificador do MVP não acessa a Meta: apenas apresenta o aviso no terminal e produz histórico de testes.


### 5.2. Arquitetura para vários usuários — decisão futura

```text
Notebook A ----> Classroom autorizado A
Notebook B ----> Classroom autorizado B
      |                    |
      +------ eventos autenticados --------+
                       |
                Serviço central
         valida consentimento e limites
                       |
         Token Meta guardado no servidor
                       |
               WhatsApp Cloud API
                       |
                  Estudantes
```

> **Decisão de segurança** — Um token único do WhatsApp não deve ser embutido no pacote distribuído aos usuários. Para usar um número compartilhado em produção, o envio deve passar por um componente confiável que guarde esse segredo e aplique autenticação, autorização e limites.

Esse serviço intermediário não precisa ser uma VM própria: poderá ser pequeno e sob demanda, desde que custos, autenticação e mecanismos contra abuso sejam analisados. A versão inicial pode continuar inteiramente local enquanto essa decisão é estudada.


## 6. Organização dos módulos

| Módulo | Responsabilidade | Entrada e saída |
|---|---|---|
| cli | Interpretar comandos, informar erros e orquestrar os casos de uso. | Entrada: argumentos; saída: mensagens |
| auth | OAuth, renovação de token, logout e armazenamento seguro. | Credencial do usuário -> sessão |
| classroom | Consultas aos cursos, atividades e submissões. | Sessão -> registros de API |
| domain / atividades | Normalizar modelos e classificar tarefas. | API -> curso / atividade / status |
| reminders / rules | Calcular janelas de aviso e verificar elegibilidade. | Atividade + configuração -> evento |
| notifications | Definir interface de envio e adaptadores: console e WhatsApp. | Evento -> resultado de entrega |
| scheduler | Executar a sincronização no intervalo estabelecido. | Configuração -> execuções |
| storage | Persistir configurações não secretas, tarefas e histórico. | Modelos -> SQLite |
| logging | Registrar erros e auditoria mínima de envios. | Eventos -> logs locais |
| packaging | Definir metadados do pacote, comandos e integração systemd. | Código -> pacote instalável |


### 6.1. Estrutura de diretórios sugerida

```text
mercurio/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/mercurio/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── domain/
│   │   ├── models.py
│   │   └── reminders.py
│   ├── integrations/
│   │   ├── google_auth.py
│   │   ├── classroom.py
│   │   └── whatsapp.py
│   ├── notifications/
│   │   ├── base.py
│   │   └── console.py
│   ├── storage/
│   │   └── sqlite.py
│   └── scheduler.py
├── packaging/arch/
│   ├── PKGBUILD
│   └── mercurio.service
└── tests/
```

Os nomes servem como proposta inicial; podem ser ajustados. O ponto central é manter a lógica de prazos independente da origem dos dados, da interface de terminal e do canal de envio.


## 7. Integração com Google Classroom


### 7.1. Autorização e operações

O estudante entra com OAuth no navegador e autoriza leitura; não deve informar sua senha ao Mercúrio. Recomenda-se começar pelos escopos classroom.courses.readonly e classroom.coursework.me.readonly e confirmar, em testes reais, o conjunto mínimo para as consultas escolhidas. As operações previstas são courses.list, courses.courseWork.list e courses.courseWork.studentSubmissions.list. [R1–R4]

1. Validar se a Classroom API está ativada no projeto Google Cloud.
1. Validar cliente OAuth Desktop e usuário adicionado em Audience > Test users.
1. Realizar login e armazenar o token com acesso restrito.
1. Consultar cursos e atividades publicados, tratando paginação.
1. Consultar submissões do usuário quando a fase de controle de pendências estiver implementada.
1. Tratar erro de autorização e orientar a reconexão sem expor segredos.


### 7.2. Regras de interpretação dos dados

- Uma atividade sem dueDate não gera lembrete de prazo; deve ser exibida como “sem prazo definido”.
- Quando houver dueDate e dueTime, interpretar os campos como valores UTC e converter para o fuso configurado.
- Quando houver data sem horário, não inventar 23h59; classificar o horário como indefinido até definir regra de produto.
- Tarefas podem ser alteradas ou excluídas pelo professor; a sincronização deve atualizar e cancelar avisos antigos.
- O estado TURNED_IN indica trabalho entregue. RETURNED exige avaliação cuidadosa da regra, pois uma atividade devolvida pode ou não demandar ação adicional.
- Usar IDs de curso e atividade, e não apenas os títulos, para identificar registros.

> **Observação sobre OAuth** — No modo External + Testing, tokens de atualização associados a escopos do Classroom geralmente expiram após 7 dias. Para distribuição duradoura, avaliar publicação, requisitos de verificação e possíveis bloqueios de administradores de instituições. [R5]


## 8. Motor de lembretes


### 8.1. Regras iniciais sugeridas

| Condição | Ação esperada |
|---|---|
| Prazo em 7 dias, dentro da janela | Criar um aviso do marco “7 dias”. |
| Prazo em 3 dias, dentro da janela | Criar um aviso do marco “3 dias”. |
| Prazo em 24 horas, dentro da janela | Criar um aviso do marco “24 horas”. |
| Prazo em 2 horas, dentro da janela | Criar um aviso do marco “2 horas”. |
| Atividade já entregue | Não emitir novo lembrete de pendência. |
| Atividade sem prazo | Não programar avisos automáticos de prazo. |
| Prazo alterado | Cancelar programação antiga e recalcular lembretes. |
| Notebook desligado na hora do aviso | Na retomada, enviar no máximo o aviso útil mais recente, se ainda houver prazo. |

As janelas (por exemplo, ±15 minutos em torno do marco) devem refletir a frequência real de sincronização. A lógica precisa ser previsível e fácil de testar com um relógio simulado. Caso vários marcos tenham sido perdidos, não enviar uma enxurrada de notificações antigas.


### 8.2. Antiduplicação e reprocessamento

Uma chave de idempotência pode reunir: ID do usuário local, ID do curso, ID da atividade, tipo do marco e prazo normalizado. O banco deve impor unicidade; antes de registrar um novo envio, consultar se o mesmo evento já foi processado. Se o prazo for alterado, invalidar os eventos referentes ao prazo anterior.


### 8.3. Exemplo de template

```text
Mercúrio · Lembrete acadêmico
Disciplina: Equações Diferenciais
Atividade: Lista de Laplace
Prazo: 18/10/2026 às 23h59
Tempo restante: 2 dias
Acesse a atividade: [link]
```

*Exemplo fictício. Na integração oficial do WhatsApp o texto precisará respeitar os modelos aprovados e as variáveis permitidas.*


## 9. Banco de dados e estado local

| Tabela / entidade | Campos mínimos propostos |
|---|---|
| account | id_local, google_subject/id, fuso_horario, criado_em |
| course | google_course_id, nome, ativo, atualizado_em |
| assignment | course_id, google_work_id, titulo, url, due_utc, status, atualizado_em |
| reminder_rule | id, antecedencia_minutos, habilitada |
| notification_event | id, assignment_id, marco, prazo_utc, estado, criado_em, enviado_em |
| notification_consent | canal, telefone, aceito_em, revogado_em (quando aplicável) |

Para o MVP individual, SQLite é suficiente. O esquema representa uma proposta conceitual; ainda será necessário definir chaves estrangeiras, índices, migrações e políticas de retenção. O histórico de notificações deve distinguir “planejado”, “tentado”, “confirmado” e “falhou”, evitando confundir uma solicitação HTTP aceita com uma mensagem efetivamente entregue.


### 9.1. Localização dos arquivos no Linux

```text
~/.config/mercurio/config.toml       # Preferências
~/.local/share/mercurio/mercurio.db # Banco SQLite
~/.local/state/mercurio/           # Logs
Armazenamento protegido do usuário  # Credenciais OAuth
```

Adotar diretórios XDG quando possível. Preferir cofre de credenciais do sistema para tokens; caso arquivos sejam necessários, restringir permissões e nunca incluir tokens em commits, logs ou backups públicos.


## 10. Notificações: console primeiro, WhatsApp depois


### 10.1. Interface de notificações

Definir um contrato único de envio — por exemplo, send(evento) -> resultado — e criar dois adaptadores. ConsoleNotifier registra/mostra lembretes durante o desenvolvimento. WhatsAppNotifier será implementado mais tarde, sem alterar o motor que decide quando notificar.


### 10.2. Requisitos para WhatsApp em produção

- Configurar recursos adequados na plataforma WhatsApp Business e no Meta for Developers.
- Obter consentimento explícito do destinatário para mensagens do Mercúrio e registrar a autorização.
- Usar modelos aprovados para iniciar avisos fora da janela de atendimento.
- Dispor de uma opção efetiva para cancelar mensagens; cumprir pedidos de parada.
- Proteger o token de envio; nunca distribuí-lo num pacote público.
- Analisar cobrança vigente, limites de envio e eventual exigência de estrutura empresarial.
- Se usar serviço intermediário, autenticar clientes, limitar requisições e minimizar os dados enviados.

Como fallback de custo zero e sem dependência da Meta, manter notificação de terminal/desktop disponível. A futura integração não deve bloquear a conclusão do núcleo acadêmico. [R6–R7]


## 11. CLI, background e empacotamento


### 11.1. Contrato inicial de comandos

| Comando planejado | Comportamento |
|---|---|
| mercurio setup | Configurar conta, preferências e autorizações. |
| mercurio auth login | Abrir OAuth no navegador. |
| mercurio auth logout | Revogar/remover acesso local conforme possível. |
| mercurio atividades | Mostrar atividades, disciplina e prazo. |
| mercurio sync | Sincronizar Classroom uma vez. |
| mercurio avisos | Mostrar os próximos alertas. |
| mercurio status | Informar sincronização recente e serviço. |
| mercurio start / stop | Ativar/desativar monitoramento do usuário. |

Esses comandos representam uma API de CLI proposta; não são comandos já implementados. A entrada de telefone ocorrerá durante o setup, não será usada como forma de obter acesso à conta Google.


### 11.2. Execução no Linux

Para o protótipo, um agendador no processo ou execução periódica via systemd --user atende ao objetivo. Mais adiante, recomendar uma unidade de serviço e/ou timer mantida por usuário, sem rodar o programa permanentemente como root. O sistema só executará verificações enquanto o computador/sessão estiver disponível; suspensão e falta de rede devem ser previstas.


### 11.3. Distribuição

1. Organizar o projeto com pyproject.toml e um entry point chamado mercurio.
1. Testar instalação local em ambiente virtual isolado.
1. Construir PKGBUILD e validar makepkg como usuário comum.
1. Publicar na AUR, quando o produto estiver estável e compatível com as regras de empacotamento.
1. Documentar dependências, atualização, remoção e tratamento de credenciais.

Instalação pela AUR (como yay -S mercurio) não é a mesma coisa que estar nos repositórios oficiais (pacman -S mercurio). O último comando exige um repositório pacman configurado que disponibilize esse pacote. [R8–R9]


## 12. Segurança, privacidade e conformidade

- Dados mínimos: conta autorizada, IDs e títulos necessários, prazo, status e preferências. Evitar armazenar descrições completas sem necessidade.
- Consentimento: separar autorização Google da autorização para receber WhatsApp; permitir retirada independente.
- Segredos: usar OAuth local seguro; enviar pelo número compartilhado apenas através de componente protegido.
- Retenção e exclusão: criar comando de exclusão de dados locais e política simples de conservação do histórico.
- Transparência: explicar quais dados saem do notebook em cada arquitetura, inclusive informações enviadas à Meta.
- Logs: nunca registrar tokens, dados completos desnecessários ou números de telefone sem mascaramento.
- Uso responsável: limites de frequência, cancelamento de avisos e prevenção contra spam/abuso.
- LGPD: antes de disponibilizar a terceiros, preparar aviso de privacidade e justificar o tratamento de dados pessoais.


## 13. Testes e critérios de aceite

| Categoria | Cenário mínimo |
|---|---|
| OAuth | Primeiro login; token renovado; token revogado/expirado; permissão institucional negada. |
| Classroom | Curso vazio; muitos cursos; paginação; atividade sem dueDate; alteração de prazo. |
| Estados | TURNED_IN; RETURNED; tarefa excluída; atividade sem submissão. |
| Datas | Mudança de fuso; UTC; virada do dia; ausência de dueTime. |
| Lembretes | Marcos exatos; reboot; aviso duplicado; vários marcos perdidos. |
| Rede | Timeout, conexão offline, erro 429/cota e indisponibilidade temporária. |
| Dados | Reiniciar o processo preservando o histórico; deletar os dados locais. |
| Empacotamento | Instalar, executar mercurio --help, habilitar e desinstalar serviço. |
| WhatsApp (fase 2) | Consentimento, template aprovado, erro no envio, opt-out e controle de custos. |

> **Princípio de qualidade** — Um aviso deve ter data correta, não ser duplicado e não ser enviado para uma tarefa já concluída. Esses três comportamentos precisam ter testes automatizados antes de ativar mensagens reais.


## 14. Roteiro de implementação

| Etapa | O que construir | Critério de conclusão |
|---|---|---|
| 0 · Ambiente | Repositório, venv, pyproject, documentação, testes. | CLI inicial executa sem erro. |
| 1 · Google | OAuth, listagem dos cursos e tarefas, paginação. | Prazos reais aparecem no terminal. |
| 2 · Núcleo | Modelos, SQLite, datas, regras, estados e idempotência. | Simulações geram o aviso certo uma única vez. |
| 3 · Automação | Scheduler, CLI status, logs e serviço Linux. | Processo inicia automaticamente na sessão. |
| 4 · Mensagens | Adaptador WhatsApp de testes e consentimento. | Telefone de teste recebe aviso autorizado. |
| 5 · Distribuição | Segurança do envio compartilhado, AUR e documentação. | Instalação validada por outro estudante. |


### 14.1. Primeiras tarefas concretas

1. Confirmar Classroom API habilitada e escopos mínimos no projeto Google Cloud.
1. Criar o repositório mercurio com pyproject.toml, src/ e tests/.
1. Escrever uma função de autenticação e verificar a listagem de cursos.
1. Implementar listagem completa de atividades e exibir prazos corretamente.
1. Salvar atividade e prazo em SQLite para comparar alterações.
1. Criar testes do cálculo de tempo restante e dos marcos de lembrete.


## 15. Riscos, decisões e dúvidas em aberto

| Tema | Decisão inicial / risco | Próxima ação |
|---|---|---|
| Canal de envio | WhatsApp pode exigir estrutura e custos. | Usar console no MVP; pesquisar critérios de produção. |
| Token da Meta | Não pode acompanhar pacote público. | Definir serviço intermediário antes de disponibilizar. |
| OAuth externo | Teste expira e pode haver restrição institucional. | Validar com conta real e planejar publicação. |
| Prazo sem horário | Não assumir horário arbitrário. | Definir comportamento visível ao usuário. |
| Atividade devolvida | RETURNED não equivale sempre a “pendente” ou “concluída”. | Testar cenários com tarefas reais. |
| Notebook desligado | Alertas em tempo real não são garantidos. | Definir regra de retomada e estado “atrasado”. |
| Nome do pacote | Nome mercurio pode já estar usado nos índices. | Verificar disponibilidade ao publicar. |


### 15.1. Definição de pronto do MVP

- Autorização Google completada sem coletar senha.
- Disciplinas e atividades reais listadas com links e prazos consistentes.
- Prazos sem horário e mudanças de prazo tratados corretamente.
- Atividades já entregues não geram lembretes de pendência.
- Banco impede avisos duplicados, inclusive após reinicialização.
- CLI dispõe de ajuda, sincronização manual, status e configuração.
- Uma verificação periódica pode rodar sem privilégios de root.
- Testes automatizados passam e README permite reproduzir instalação local.


## 16. Fontes e documentação de apoio

- [R1] Google Classroom — Quickstart Python: https://developers.google.com/workspace/classroom/quickstart/python
- [R2] Classroom — Escopos de autorização: https://developers.google.com/workspace/classroom/guides/auth
- [R3] Classroom — CourseWork e prazos: https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork
- [R4] Classroom — Listar submissões: https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork.studentSubmissions/list
- [R5] Google OAuth 2.0 — validade de refresh token em Testing: https://developers.google.com/identity/protocols/oauth2
- [R6] WhatsApp Business — Política de mensagens e opt-in: https://business.whatsapp.com/policy/preview?lang=pt_BR
- [R7] Meta — WhatsApp Cloud API (coleção oficial Postman): https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api
- [R8] ArchWiki — Criando pacotes: https://wiki.archlinux.org/title/creating_packages
- [R9] ArchWiki — AUR: https://wiki.archlinux.org/title/Arch_User_Repository
- [R10] Classroom — Cotas da API: https://developers.google.com/workspace/classroom/reference/limits
*Fontes oficiais consultadas em 14/10/2026. Tarifas, políticas de plataforma, limites e critérios de verificação podem mudar; revisar os links antes da publicação.*
