# Relatório de testes — Gerador de Guias CASSI 1.2.0

Data de preparação do pacote: 19/11/2026

## Testes funcionais da aplicação documentados na versão anterior

| Verificação | Resultado registrado |
|---|---|
| Compilação sintática do `gerar_guias.py` | Aprovado |
| Sintaxe JavaScript do `interface.html` | Aprovado |
| Seleção do modelo pelo método da API PyWebView em teste controlado | Aprovado |
| Cópia do modelo para a pasta persistente e recuperação no JSON | Aprovado |
| Preservação do PDF original escolhido | Aprovado |
| Bloqueio de modelo com dimensões incompatíveis | Aprovado |
| Guia completa com quatro procedimentos: quatro páginas completas | Aprovado |
| Guias separadas: quatro PDFs individuais, cada um com um procedimento | Aprovado |
| Lote controlado: protocolo PDF → modelo → guia PDF → histórico | Aprovado |

## Verificações realizadas na preparação da distribuição 1.2.0

| Verificação | Resultado |
|---|---|
| `python -m py_compile gerar_guias.py` após incluir verificação/instalação do WebView2 | Aprovado |
| Versão interna atualizada para 1.2.0 | Aprovado |
| Painel HTML continua usando `window.pywebview.api` | Aprovado |
| Workflow Windows x64 criado para compilar no GitHub Actions | Criado; execução pendente |
| Workflow baixa o bootstrapper WebView2 da Microsoft e verifica assinatura Authenticode | Definido no workflow; execução pendente |
| PyInstaller configurado para embutir HTML, Python e dependências no EXE | Definido no workflow; execução pendente |
| ZIP de distribuição com EXE e instruções para a clínica | Definido no workflow; execução pendente |
| SHA-256 do pacote | Definido no workflow; execução pendente |
| Publicação automática do ZIP na aba Releases quando uma tag `v*` for enviada | Definido no workflow; execução pendente |
| Arquivo `.bat` | Não utilizado |

## O que ainda exige execução real no Windows/GitHub

1. Executar o workflow em um repositório GitHub real.
2. Verificar se o PyInstaller conclui a compilação Windows x64 sem erros.
3. Baixar o ZIP de Release em um computador Windows sem Python.
4. Executar o EXE e confirmar a abertura do WebView2.
5. Testar a instalação silenciosa do WebView2 em um computador no qual o Runtime esteja ausente.
6. Conferir seleção de modelo, pasta de saída, entrada de vários PDFs e persistência em outro perfil Windows.
7. Conferir visualmente as guias com o formulário oficial da CASSI antes de liberar uso de produção.

## Dependência WebView2

O Python e os pacotes Python serão empacotados pelo PyInstaller. O WebView2 Evergreen Runtime é um componente do Windows instalado separadamente do EXE. O aplicativo detecta a ausência e executa o bootstrapper oficial incorporado. A instalação inicial precisa de internet; a Microsoft documenta instalação por usuário sem elevação e o uso do bootstrapper Evergreen.

Documentação Microsoft: https://learn.microsoft.com/pt-br/microsoft-edge/webview2/concepts/distribution

## Segurança dos dados

O `.gitignore` exclui PDFs, `config.json`, histórico, logs, entrada, saída, pastas de build e runtime baixado. Não publicar PDFs de pacientes, histórico real ou configurações locais no GitHub.
