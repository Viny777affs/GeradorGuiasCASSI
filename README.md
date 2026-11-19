# GERADOR DE GUIAS CASSI — Painel Web local

**Versão:** 1.2.0  
**Plataforma de distribuição:** Windows 10/11 x64  
**Interface:** HTML, CSS e JavaScript em PyWebView  
**Backend:** um único arquivo `gerar_guias.py`

O aplicativo processa PDFs de protocolos CASSI localmente. O painel HTML conversa com o backend Python pela API local do PyWebView. Não há servidor remoto nem envio de documentos clínicos para serviços externos.

## Download para a clínica

Depois que o GitHub Actions concluir uma compilação marcada por tag `v*`, abra a aba **Releases** do repositório e baixe:

`GeradorGuiasCASSI-Windows-x64-v1.2.0.zip`

O ZIP contém somente o executável pronto e o guia rápido `README_CLIENTE.txt`. O usuário final não instala Python nem dependências Python, não abre terminal e não precisa de VS Code.

A distribuição é portátil: extraia o ZIP em uma pasta acessível e abra `GeradorGuiasCASSI.exe`. Os arquivos de configuração, histórico e modelo selecionado ficam no `%APPDATA%` do usuário Windows. A pasta de saída é configurada dentro do aplicativo.

### Dependência WebView2

As bibliotecas Python, o Python e o painel HTML são empacotados no EXE. O Evergreen WebView2 Runtime é um componente do sistema que o aplicativo verifica ao iniciar. Se estiver ausente, ele usa o bootstrapper oficial da Microsoft incluído dentro do executável, instalando o Runtime silenciosamente por usuário. Essa instalação inicial requer internet. O WebView2 Runtime é incluído no Windows 11 e está presente na maioria dos Windows 10, mas a verificação continua necessária. Consulte a [documentação oficial Microsoft](https://learn.microsoft.com/pt-br/microsoft-edge/webview2/concepts/distribution).

## Configurações escolhidas dentro do aplicativo

Na página **Configurações**, o usuário poderá:

- Escolher a unidade (Águas Claras ou Asa Norte).
- Informar e validar o CNPJ da unidade.
- Escolher o modo de geração (guia completa ou PDFs separados por procedimento).
- Selecionar o modelo PDF oficial por meio de um seletor de arquivos.
- Escolher a pasta de saída usando o seletor de pastas do Windows.

Os caminhos são locais a cada computador e ficam persistidos em `%APPDATA%\GeradorGuiasCASSI\config.json`. O modelo selecionado é copiado para `%APPDATA%\GeradorGuiasCASSI\modelo\guia_modelo.pdf`. Portanto, ao instalar em outro computador, o usuário seleciona o PDF daquele computador apenas uma vez; não é preciso alterar caminhos no código ou recompilar.

O executável inclui `interface.html`; o usuário não precisa baixar ou configurar o HTML separadamente.

## Estrutura do código-fonte

```text
GERADOR_GUIAS_CASSI/
├── .github/
│   └── workflows/
│       └── build-windows.yml
├── modelo/
│   └── LEIA-ME.txt
├── gerar_guias.py
├── interface.html
├── requirements.txt
├── README.md
├── README_CLIENTE.txt
├── RELATORIO_TESTES.md
└── .gitignore
```

Não existem módulos Python auxiliares e não são utilizados arquivos `.bat`.

## Publicação e compilação no GitHub

O fluxo `.github/workflows/build-windows.yml` compila em um runner Windows x64 hospedado pelo GitHub. Assim, o desenvolvedor não precisa ter Windows disponível localmente para produzir o artefato, mas o executável é efetivamente compilado no ambiente Windows.

### Publicar uma nova versão

1. Envie os arquivos-fonte para a branch `main`.
2. Crie uma tag de versão, por exemplo `v1.2.0`.
3. Envie a tag ao GitHub.
4. A ação `Build Windows EXE e publicar Release` instala as dependências no runner, baixa e confere a assinatura do bootstrapper oficial WebView2, compila o EXE e publica o ZIP e o SHA-256 na aba Releases.

Comandos Git para um desenvolvedor, dentro do clone do repositório:

```powershell
git add .
git commit -m "Publica Gerador de Guias CASSI v1.2.0"
git push origin main
git tag v1.2.0
git push origin v1.2.0
```

O GitHub Actions requer permissão `contents: write`, declarada no workflow. Não é necessário guardar token de acesso pessoal nos arquivos do projeto.

### Compilação manual no Windows (opcional)

Em um ambiente de desenvolvimento Windows x64 com Python 3.11+:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
New-Item -ItemType Directory -Force runtime
Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile "runtime\MicrosoftEdgeWebView2Setup.exe"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name GeradorGuiasCASSI --add-data "interface.html;." --add-data "runtime\MicrosoftEdgeWebView2Setup.exe;runtime" --collect-all webview --collect-all pythonnet --collect-all clr_loader --hidden-import clr --hidden-import webview.platforms.edgechromium gerar_guias.py
```

O arquivo será criado em `dist\GeradorGuiasCASSI.exe`. O bootstrapper baixado deve ser o oficial da Microsoft; o workflow automatizado valida sua assinatura Authenticode antes de compilar.

## Dados locais e privacidade

- O projeto não deve conter PDFs de protocolo, documentos clínicos, histórico real, CNPJ de produção ou `config.json` de máquinas da clínica.
- O `.gitignore` exclui PDFs, configuração, histórico, logs, entrada, saída e runtime do WebView2.
- Cada computador cria sua própria configuração e histórico em `%APPDATA%\GeradorGuiasCASSI`.
- A visibilidade do repositório GitHub deve ser escolhida pelo responsável. Em repositório público, o código-fonte e o histórico de versões ficam públicos; Releases podem ser baixados sem login. Em repositório privado, os usuários precisam receber acesso ao repositório para baixar Releases.

## Testes e limitações

Consulte `RELATORIO_TESTES.md` para os testes de parsing, validação, geração dos dois modos, seleção e persistência do modelo e interface web. A compilação final e a abertura nativa do executável devem ser verificadas pelo GitHub Actions e, antes de colocar em produção, em um computador Windows da clínica.

O modelo PDF oficial precisa ser selecionado dentro do aplicativo e conferido visualmente pela clínica antes de liberar a emissão de produção.
