GERADOR DE GUIAS CASSI — VERSÃO PARA A CLÍNICA

COMO COMEÇAR
1. Extraia este ZIP para uma pasta do computador (por exemplo, Documentos\GeradorGuiasCASSI).
2. Dê dois cliques em GeradorGuiasCASSI.exe.
3. Na primeira abertura, vá a Configurações.
4. Selecione o modelo oficial PDF da guia CASSI.
5. Escolha a unidade, confira o CNPJ e defina a pasta de saída.
6. Salve as configurações e abra Gerar Guias para selecionar os PDFs dos protocolos.

NÃO É NECESSÁRIO INSTALAR PYTHON, PIP, VS CODE OU OUTRA FERRAMENTA DE DESENVOLVIMENTO.
O executável já inclui o interpretador Python e as bibliotecas Python usadas pelo programa.

PRIMEIRA EXECUÇÃO
O painel utiliza Microsoft Edge WebView2. Se o Runtime estiver ausente, o aplicativo tentará
instalá-lo silenciosamente por usuário, usando o instalador oficial da Microsoft incorporado.
Essa preparação requer conexão com a internet. Normalmente não exige privilégios administrativos.

ARQUIVOS E CONFIGURAÇÕES
As configurações, o modelo selecionado, o histórico e os logs ficam no perfil do usuário Windows:
%APPDATA%\GeradorGuiasCASSI

Os PDFs de saída ficam na pasta escolhida em Configurações, separados pela unidade.
O PDF do protocolo original não é alterado.

ATENÇÃO
- Confira e valide o CNPJ da unidade antes de emitir guias.
- Códigos de procedimento não reconhecidos bloqueiam a emissão do protocolo.
- Faça conferência visual das primeiras guias emitidas com o formulário oficial da clínica.
- Não coloque PDFs de pacientes, históricos ou configurações locais no GitHub.

SUPORTE
Informe a versão do aplicativo (Configurações > Sobre) e envie o log técnico quando solicitado.
O log fica em %APPDATA%\GeradorGuiasCASSI\logs.
