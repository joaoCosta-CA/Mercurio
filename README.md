# Mercúrio

Mercúrio é uma aplicação independente criada para resolver um problema muito
comum no ambiente universitário: **o esquecimento de prazos e datas de entrega
de atividades acadêmicas**.

O projeto nasceu da dificuldade de acompanhar prazos longos, inúmeras
atividades e responsabilidades pessoais. Ele consulta as atividades do
**Google Classroom** e gera lembretes sem duplicidade. O canal padrão é o
terminal; o WhatsApp é opcional e usa um serviço intermediário para que o token
da Meta nunca seja distribuído ao notebook.

O objetivo do Mercúrio não é substituir a organização pessoal de cada
estudante, mas facilitar esse processo e diminuir as chances de uma entrega
importante ser esquecida.

## Desenvolvimento

Requer Python 3.12 ou mais recente.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,google,whatsapp-client]'
mercurio --help
python -m unittest discover -s tests -v
```

Execute apenas `mercurio` em um terminal interativo para abrir o painel TUI.
Ele mostra atividades ativas, filtros por disciplina e histórico de avisos;
use `r` para sincronizar e `?` para ver os atalhos. Os subcomandos continuam
disponíveis para automação, como `mercurio sync` e `mercurio start`.
Se ainda não houver uma conta autorizada, `r` abre o navegador para o mesmo
fluxo OAuth de `mercurio auth login`. A TUI procura um único
`docs/client_secret*.json`; em instalações externas, informe o caminho com
`MERCURIO_CLIENT_SECRETS=/caminho/client_secret.json mercurio`.

Para começar sem credenciais externas:

```bash
PYTHONPATH=src python -m mercurio setup --non-interactive
PYTHONPATH=src python -m mercurio sync --fixture tests/fixtures/classroom.json
PYTHONPATH=src python -m mercurio atividades
PYTHONPATH=src python -m mercurio atividades --disciplina "Equações Diferenciais"
PYTHONPATH=src python -m mercurio avisos --at 2026-10-14T12:00:00+00:00
```

Os dados seguem o padrão XDG: configuração em `~/.config/mercurio`, banco em
`~/.local/share/mercurio` e logs em `~/.local/state/mercurio`. Use variáveis
`XDG_CONFIG_HOME`, `XDG_DATA_HOME` e `XDG_STATE_HOME` nos testes.

## Google Classroom

Crie um cliente OAuth do tipo Desktop, habilite a Classroom API e salve o JSON
fora do repositório. Depois execute:

```bash
pip install -e '.[google]'
mercurio auth login --client-secrets /caminho/client_secret.json
mercurio sync
```

O Mercúrio pede somente leitura de cursos, trabalhos e submissões próprias.
No modo OAuth External/Testing, a renovação pode expirar e exigir novo login.

## Segurança e privacidade

O Mercúrio não solicita a senha Google. Tokens não são escritos em logs. O
comando `mercurio dados apagar --confirmar APAGAR` remove configuração, banco,
logs e credencial local. O consentimento do Google é independente do canal
WhatsApp. Veja `docs/PRIVACIDADE.md`.

## Serviço automático

Os arquivos em `packaging/systemd/` executam `mercurio sync --notify --channel desktop`
como serviço do usuário. Instale-os em `~/.config/systemd/user/` ou use
`mercurio start`; não execute o Mercúrio como root.

## Notificações desktop no Linux

O canal padrão de lembretes é `desktop` e usa o comando `notify-send`, fornecido
normalmente pelo pacote `libnotify`. Ele requer uma sessão gráfica do usuário
com um servidor de notificações ativo. Teste-o manualmente com:

```bash
mercurio avisos --channel desktop
```

Caso a sessão gráfica ou o D-Bus não estejam disponíveis, o aviso fica marcado
como falho e será tentado novamente pelo próximo ciclo do timer. Consulte
`mercurio avisos --historico` e `journalctl --user -u mercurio.service` para
diagnóstico. Os canais `console`, `desktop`, `whatsapp` e `all` podem ser
selecionados com `--channel`.

## Situação

O núcleo local é funcional e testável com fixtures. Integrações reais exigem
credenciais do Google/Meta e validação das políticas atuais antes de produção.
