# Aviso de privacidade — versão inicial

O Mercúrio armazena localmente a identidade técnica da conta autorizada, IDs e
nomes de cursos, títulos e links de atividades, prazos, estados de entrega,
preferências e histórico mínimo de notificações. A senha Google nunca é
coletada.

No modo local, esses dados permanecem no computador. Ao habilitar WhatsApp,
somente o identificador remoto do destinatário, o template e as variáveis
necessárias ao lembrete são enviados ao serviço Mercúrio e à Meta. Tokens do
Google e descrições completas de atividades não são enviados.

As autorizações Google e WhatsApp são independentes e podem ser revogadas. O
comando `mercurio dados apagar --confirmar APAGAR` remove os dados locais. Logs
são sanitizados e devem ser conservados por no máximo 30 dias; eventos de
notificação, por no máximo 180 dias.

