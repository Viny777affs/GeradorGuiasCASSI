#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GERADOR DE GUIAS CASSI
Painel web local (PyWebView + HTML) + processamento PDF, em um único arquivo Python.

Desenvolvimento: Python 3.11+
Execução: python gerar_guias.py
Compilação Windows: ver README_GERADOR_GUIAS_CASSI.md

A aplicação lê exclusivamente os PDFs de protocolo como fonte de dados.
O modelo oficial deve estar em modelo/guia_modelo.pdf.
"""

from __future__ import annotations

# ================================================================
# 1. IMPORTAÇÕES
# ================================================================
import base64
import csv
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
import urllib.request
from collections import deque
from datetime import datetime, date
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, RectangleObject
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

# ================================================================
# 2. CONFIGURAÇÕES E CONSTANTES
# ================================================================
VERSAO = "1.2.1"
NOME_APP = "GeradorGuiasCASSI"
TITULO_APP = "GERADOR DE GUIAS CASSI"
CONTRATADO = "Recriar Clínica Psicopedagogica"
PAGE_W = 842
PAGE_H = 596

UNIDADES = {
    "aguas_claras": "Águas Claras",
    "asa_norte": "Asa Norte",
}

MODOS = {
    "copias_identicas": "Guia completa — procedimentos juntos e cópias idênticas",
    "separadas": "Guias separadas — um PDF por procedimento",
}

# Preservado conforme o script anterior. O valor da Asa Norte tem 15 dígitos e
# será bloqueado pela validação até que o responsável o corrija nas configurações.
CONFIG_PADRAO = {
    "unidade": "asa_norte",
    "cnpjs": {
        "aguas_claras": "",
        "asa_norte": "202369330000351",
    },
    "modo_guias": "copias_identicas",
    "pasta_saida": "",
    # Caminho da cópia local do modelo oficial selecionado nas Configurações.
    "modelo_pdf": "",
}

# Código conhecido -> descrição padronizada exibida na guia.
# Não há inferência de especialidade por palavras-chave.
DESCRICOES = {
    "81020015": "Sessão de Musicoterapia",
    "81020023": "Sessão de Terapia Ocupacional",
    "81020040": "Sessão de Psicopedagogia",
    "81040024": "Sessão de Fonoaudiologia",
    "81020016": "Psicoterapia pelo o método ABA",
    "81030037": "Sessão de psicoterapia",
    "81050097": "Paralisia Cerebral Motora",
    "81030010": "Sessão de Psicomotricidade",
}

# Caminhos de recursos (somente leitura) e dados persistentes (graváveis).
if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).resolve().parent
else:
    BASE = Path(__file__).resolve().parent

RESOURCE_BASE = Path(getattr(sys, "_MEIPASS", BASE))
INTERFACE_RESOURCE = RESOURCE_BASE / "interface.html"
PASTA_MODELO = RESOURCE_BASE / "modelo"
MODELO = PASTA_MODELO / "guia_modelo.pdf"
# Em executável one-file, também aceita o modelo ao lado do EXE (pasta externa),
# caso ele não tenha sido embutido durante a compilação.
if getattr(sys, "frozen", False) and not MODELO.exists():
    PASTA_MODELO = BASE / "modelo"
    MODELO = PASTA_MODELO / "guia_modelo.pdf"

if os.name == "nt":
    _raiz_dados = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
else:
    _raiz_dados = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
APP_DATA_DIR = _raiz_dados / NOME_APP
PASTA_MODELO_DADOS = APP_DATA_DIR / "modelo"
MODELO_DADOS = PASTA_MODELO_DADOS / "guia_modelo.pdf"
ARQ_CONFIG = APP_DATA_DIR / "config.json"
ARQ_HISTORICO = APP_DATA_DIR / "historico.json"
PASTA_LOGS = APP_DATA_DIR / "logs"
ARQ_LOG = PASTA_LOGS / "gerador.log"
ENTRADA = APP_DATA_DIR / "entrada"

_DOCUMENTOS = Path.home() / "Documents"
if not _DOCUMENTOS.exists():
    _DOCUMENTOS = Path.home() / "Documentos"
PASTA_SAIDA_PADRAO = _DOCUMENTOS / "GERADOR_GUIAS_CASSI" / "saida"

# Variáveis globais de compatibilidade com as funções originais.
# O processamento recebe a pasta de saída explicitamente sempre que chamado pela GUI.
SAIDA = PASTA_SAIDA_PADRAO
ARQ_RELATORIO = SAIDA / "relatorio.csv"


# ================================================================
# 3. GERENCIAMENTO DO CONFIG.JSON E HISTÓRICO
# ================================================================
def configurar_logger() -> logging.Logger:
    """Configura log rotativo técnico, gravado na pasta de dados do usuário."""
    PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("GeradorGuiasCASSI")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(
            ARQ_LOG, maxBytes=2_000_000, backupCount=4, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(handler)
    return logger


LOGGER = configurar_logger()


def _config_copia_padrao() -> dict:
    return json.loads(json.dumps(CONFIG_PADRAO, ensure_ascii=False))


def carregar_config() -> dict:
    """Carrega JSON, migra config.json legado e cria defaults se necessário."""
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    origem = ARQ_CONFIG if ARQ_CONFIG.exists() else BASE / "config.json"
    if not origem.exists():
        resultado = _config_copia_padrao()
        resultado["pasta_saida"] = str(PASTA_SAIDA_PADRAO)
        salvar_config(resultado)
        return resultado

    try:
        with origem.open("r", encoding="utf-8") as arquivo:
            original = json.load(arquivo)
    except (OSError, json.JSONDecodeError) as erro:
        backup = ARQ_CONFIG.with_suffix(".json.bak")
        mensagem_backup = f" Há uma cópia de segurança em {backup}." if backup.exists() else ""
        raise RuntimeError(
            f"Não foi possível ler as configurações locais: {erro}.{mensagem_backup}"
        ) from erro

    resultado = _config_copia_padrao()
    if isinstance(original, dict):
        if original.get("unidade") in UNIDADES:
            resultado["unidade"] = original["unidade"]
        if isinstance(original.get("cnpjs"), dict):
            for chave in UNIDADES:
                if chave in original["cnpjs"]:
                    resultado["cnpjs"][chave] = str(original["cnpjs"][chave] or "")
        if original.get("modo_guias") in MODOS:
            resultado["modo_guias"] = original["modo_guias"]
        if original.get("pasta_saida"):
            resultado["pasta_saida"] = str(original["pasta_saida"])
        if original.get("modelo_pdf"):
            resultado["modelo_pdf"] = str(original["modelo_pdf"])

    if not resultado["pasta_saida"]:
        resultado["pasta_saida"] = str(PASTA_SAIDA_PADRAO)
    # Migra a configuração antiga para AppData e mantém o arquivo original intacto.
    if origem != ARQ_CONFIG:
        salvar_config(resultado)
    return resultado


def salvar_config(config: dict) -> None:
    """Grava JSON atomicamente e preserva cópia da configuração anterior."""
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporario = ARQ_CONFIG.with_suffix(".json.tmp")
    if ARQ_CONFIG.exists():
        try:
            shutil.copy2(ARQ_CONFIG, ARQ_CONFIG.with_suffix(".json.bak"))
        except OSError:
            LOGGER.exception("Não foi possível criar backup do config.json")
    with temporario.open("w", encoding="utf-8") as arquivo:
        json.dump(config, arquivo, ensure_ascii=False, indent=4)
        arquivo.flush()
        os.fsync(arquivo.fileno())
    temporario.replace(ARQ_CONFIG)


def carregar_historico() -> list[dict]:
    """Lê o histórico persistente; em caso de falha, mantém o aplicativo utilizável."""
    if not ARQ_HISTORICO.exists():
        return []
    try:
        with ARQ_HISTORICO.open("r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        return dados if isinstance(dados, list) else []
    except (OSError, json.JSONDecodeError):
        LOGGER.exception("Falha ao ler o histórico local")
        return []


def salvar_historico(historico: list[dict]) -> None:
    """Atualiza o histórico de forma atômica, mantendo no máximo 5.000 registros."""
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporario = ARQ_HISTORICO.with_suffix(".json.tmp")
    dados = historico[-5000:]
    with temporario.open("w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)
        arquivo.flush()
        os.fsync(arquivo.fileno())
    temporario.replace(ARQ_HISTORICO)


def somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def validar_cnpj(cnpj: str) -> tuple[bool, str]:
    """Valida CNPJ numérico de 14 dígitos e seus dois dígitos verificadores."""
    digitos = somente_digitos(cnpj)
    if not digitos:
        return False, "O CNPJ da unidade selecionada não foi informado."
    if len(digitos) != 14:
        return False, f"O CNPJ informado possui {len(digitos)} dígitos; são necessários 14."
    if digitos == digitos[0] * 14:
        return False, "O CNPJ informado é inválido (sequência repetida)."

    def calcular(base: str, pesos: list[int]) -> str:
        soma = sum(int(numero) * peso for numero, peso in zip(base, pesos))
        resto = soma % 11
        return str(0 if resto < 2 else 11 - resto)

    primeiro = calcular(digitos[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    segundo = calcular(digitos[:12] + primeiro, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    if digitos[-2:] != primeiro + segundo:
        return False, "Os dígitos verificadores do CNPJ não conferem. Confira o número com a administração."
    return True, ""


def caminho_modelo(config: dict | None = None) -> Path | None:
    """Resolve primeiro o modelo escolhido nas Configurações e depois o padrão distribuído."""
    config = config or {}
    configurado = str(config.get("modelo_pdf") or "").strip()
    if configurado:
        candidato = Path(configurado).expanduser()
        if candidato.is_file():
            return candidato.resolve()
    if MODELO_DADOS.is_file():
        return MODELO_DADOS.resolve()
    if MODELO.is_file():
        return MODELO.resolve()
    return None


def inspecionar_modelo(arquivo: Path, validar_dimensoes: bool = True) -> dict:
    """Confere integridade, dimensões A4 paisagem e rotação do formulário."""
    arquivo = Path(arquivo).expanduser().resolve()
    if not arquivo.is_file() or arquivo.suffix.lower() != ".pdf":
        raise ValueError("Selecione um arquivo PDF existente para usar como modelo.")
    if arquivo.stat().st_size <= 0:
        raise ValueError("O arquivo do modelo está vazio.")

    leitor = PdfReader(str(arquivo), strict=False)
    if leitor.is_encrypted:
        try:
            resultado = leitor.decrypt("")
        except Exception:
            resultado = 0
        if not resultado:
            raise ValueError("O PDF modelo está protegido por senha e não pode ser utilizado.")
    if not leitor.pages:
        raise ValueError("O PDF selecionado não possui páginas.")

    pagina = leitor.pages[0]
    largura = float(pagina.mediabox.width)
    altura = float(pagina.mediabox.height)
    rotacao = int(pagina.get("/Rotate", 0) or 0) % 360

    if validar_dimensoes and (abs(largura - PAGE_W) > 5 or abs(altura - PAGE_H) > 5):
        raise ValueError(
            "O tamanho da primeira página do modelo não corresponde ao formulário esperado. "
            f"Encontrado: {largura:.1f} × {altura:.1f} pt; esperado aproximadamente: "
            f"{PAGE_W} × {PAGE_H} pt (A4 paisagem). Selecione o modelo oficial usado pelo script original."
        )
    if validar_dimensoes and rotacao in (90, 270):
        raise ValueError(
            f"O PDF modelo possui rotação interna de {rotacao}°. "
            "Embora o tamanho informado seja A4 paisagem, essa rotação faz alguns leitores "
            "e impressoras interpretarem a página como retrato. Salve o formulário sem rotação "
            "(A4 paisagem, rotação 0°) e selecione-o novamente."
        )

    return {
        "path": str(arquivo),
        "name": arquivo.name,
        "pages": len(leitor.pages),
        "width": round(largura, 1),
        "height": round(altura, 1),
        "rotation": rotacao,
        "size_bytes": arquivo.stat().st_size,
    }


def caminho_saida(config: dict) -> Path:
    raiz = Path(config.get("pasta_saida") or PASTA_SAIDA_PADRAO).expanduser()
    return raiz / config.get("unidade", "asa_norte").upper()


# ================================================================
# 4. LEITURA DOS PDFs
# ================================================================
def texto_pdf(pdf: Path) -> str:
    """Extrai o texto de todas as páginas do PDF de protocolo/e-mail."""
    leitor = PdfReader(str(pdf))
    if leitor.is_encrypted:
        try:
            leitor.decrypt("")
        except Exception as erro:
            raise ValueError("O PDF está protegido por senha e não pôde ser lido.") from erro
    return "\n".join(pagina.extract_text() or "" for pagina in leitor.pages)


def qtd_global(txt: str) -> str:
    m = re.search(r"(\d+)\s*SESS", txt, re.I)
    return m.group(1) if m else ""


def secao_eventos(txt: str) -> str:
    m = re.search(
        r"EVENTOS\s+RELACIONADOS\s*:\s*(.*?)(?=\n\s*(?:EM CASO DE CONTINUIDADE|OBSERVA[CÇ][ÃA]O|ATENCIOSAMENTE)\b|$)",
        txt, re.I | re.S,
    )
    return m.group(1).strip() if m else ""


def limpar_nome_evento(nome: str) -> str:
    nome = re.sub(r"\s+", " ", nome or "").strip()
    return nome.strip(" -–—,;:\t")


def eventos_codigo_8_digitos(secao: str) -> list[dict]:
    """Lê códigos de evento CASSI como aparecem no texto, sem convertê-los em TUSS."""
    eventos: list[dict] = []
    if not secao:
        return eventos
    encontrados = list(re.finditer(r"(?<!\d)(\d{8})(?!\d)\s*[-–—]\s*", secao))
    qtd_fallback = qtd_global(secao)
    for indice, match in enumerate(encontrados):
        inicio = match.end()
        fim = encontrados[indice + 1].start() if indice + 1 < len(encontrados) else len(secao)
        trecho = secao[inicio:fim].strip()
        m_qtd = re.search(r"(\d+)\s*SESS", trecho, re.I)
        qtd = m_qtd.group(1) if m_qtd else qtd_fallback
        nome = trecho[:m_qtd.start()] if m_qtd else trecho
        nome = limpar_nome_evento(nome)
        if nome:
            eventos.append({"codigo": match.group(1), "nome": nome, "qtd": qtd})
    return eventos


# ================================================================
# 5. EXTRAÇÃO E VALIDAÇÃO DOS DADOS
# ================================================================
def ler_email(pdf: Path) -> dict:
    """Extrai campos e procedimentos do PDF; bloqueia campos/códigos inválidos."""
    txt = texto_pdf(pdf)

    def g(rx: str) -> str:
        m = re.search(rx, txt, re.I | re.M)
        return m.group(1).strip() if m else ""

    dados = {
        "protocolo": g(r"protocolo\s+de\s+n[ºo°]\s*(\d+)"),
        "carteira": g(r"BENEFICI[ÁA]RIO\s*:\s*(\d+)"),
        "nome": g(r"NOME\s*:\s*([^\r\n]+)"),
        "autorizacao": g(r"AUTORIZA[ÇC][ÃA]O\s*:\s*(\d+)"),
        "inicio": g(r"DATA\s+IN[ÍI]CIO\s*:\s*([\d/]+)"),
        "resposta": g(r"Bras[íi]lia\s*-\s*DF\s*,\s*([\d/]+)"),
        "fim": g(r"DATA\s+FIM\s*:\s*([\d/]+)"),
        "eventos": [],
        "obs_parsing": [],
    }

    secao = secao_eventos(txt)
    texto_eventos = secao or txt

    # Formato pontuado originalmente tratado pelo script (mantido).
    padrao_tuss = (
        r"(\d\.\d{3}\.\d{2}\.\d{4})\s+(.+?)\s*[-–—]\s*"
        r"(?:POR SESS[ÃA]O\s*[-–—]\s*)?(\d+)\s*SESS"
    )
    for m in re.finditer(padrao_tuss, texto_eventos, re.I | re.S):
        codigo = m.group(1).replace(".", "")[2:]
        nome = re.sub(r"\s+", " ", m.group(2)).strip()
        dados["eventos"].append({"codigo": codigo, "nome": nome, "qtd": m.group(3)})

    # Formato pontuado sem quantidade local: preserva fallback já existente.
    if not dados["eventos"]:
        codigos = list(re.finditer(r"(\d\.\d{3}\.\d{2}\.\d{4})\s+([^\r\n]+)", texto_eventos))
        if codigos:
            qtd_fallback = qtd_global(texto_eventos)
            for m in codigos:
                codigo = m.group(1).replace(".", "")[2:]
                nome = re.sub(r"\s+", " ", m.group(2)).strip(" -–—")
                dados["eventos"].append({"codigo": codigo, "nome": nome, "qtd": qtd_fallback})
            dados["obs_parsing"].append(
                "A quantidade de sessões não veio junto do evento; foi utilizada a primeira quantidade encontrada. Confira."
            )

    # Também examina todos os eventos de 8 dígitos, inclusive quando outro formato foi lido.
    eventos_cassi = eventos_codigo_8_digitos(texto_eventos)
    codigos_ja_lidos = {evento["codigo"] for evento in dados["eventos"]}
    for evento in eventos_cassi:
        if evento["codigo"] not in codigos_ja_lidos:
            dados["eventos"].append(evento)
            codigos_ja_lidos.add(evento["codigo"])

    if any(not evento["qtd"] for evento in dados["eventos"]):
        dados["obs_parsing"].append(
            "A quantidade de sessões não foi localizada para um ou mais eventos; confira antes de usar a guia."
        )

    invalidos = [evento for evento in dados["eventos"] if evento["codigo"] not in DESCRICOES]
    if invalidos:
        detalhes = "; ".join(
            f'{evento["codigo"]} ({evento["nome"] or "sem descrição"})' for evento in invalidos
        )
        raise ValueError(
            "ERRO: Código de procedimento não reconhecido: " + detalhes
            + ". Verificar protocolo junto à CASSI. Nenhuma guia foi gerada para este PDF."
        )

    faltando = [chave for chave in ("protocolo", "carteira", "nome", "autorizacao", "fim") if not dados[chave]]
    if faltando:
        raise ValueError("Erro de leitura: campos obrigatórios não encontrados: " + ", ".join(faltando))
    if not dados["eventos"]:
        raise ValueError("Erro de leitura: nenhum procedimento reconhecido em EVENTOS RELACIONADOS.")
    if len(dados["eventos"]) > 5:
        raise ValueError(
            f'Foram identificados {len(dados["eventos"])} procedimentos, mas o formulário comporta no máximo 5. '
            "Nenhuma guia foi gerada para evitar omissões."
        )
    return dados


# ================================================================
# 6. VALIDAÇÃO DOS PROCEDIMENTOS
# ================================================================
def validar_eventos(eventos: list[dict]) -> None:
    """Valida a lista inteira. Um único código desconhecido bloqueia o protocolo."""
    if not eventos:
        raise ValueError("Nenhum procedimento foi identificado no protocolo.")
    desconhecidos = [str(e.get("codigo", "")) for e in eventos if e.get("codigo") not in DESCRICOES]
    if desconhecidos:
        raise ValueError(
            "ERRO: Código de procedimento não reconhecido: " + ", ".join(desconhecidos)
            + ". Verificar protocolo junto à CASSI."
        )


# ================================================================
# 7. PREENCHIMENTO E GERAÇÃO DAS GUIAS
# ================================================================
def data_br(valor: str) -> str:
    try:
        dia, mes, ano = valor.split("/")
        return f"{int(dia):02d}/{int(mes):02d}/{ano}"
    except Exception:
        return valor


def desenhar_texto_ajustado(
    c: canvas.Canvas, x: float, y: float, texto: str,
    tamanho: float = 10, largura_max: float = 100, tamanho_min: float = 5.5,
    margem_seguranca: float = 3.0,
) -> None:
    """Dimensiona o texto para permanecer dentro da largura definida do campo.

    Reserva uma pequena margem de segurança antes do limite informado e, se mesmo
    assim o texto não couber na fonte mínima, corta com reticências — para nunca
    invadir visualmente o campo vizinho nem travar a geração da guia inteira.
    """
    texto = re.sub(r"\s+", " ", str(texto or "")).strip()
    if not texto:
        return
    fonte = "Helvetica"
    largura_disponivel = max(float(largura_max) - margem_seguranca, 1.0)
    tamanho_atual = float(tamanho)
    largura = stringWidth(texto, fonte, tamanho_atual)
    while largura > largura_disponivel and tamanho_atual > tamanho_min:
        tamanho_atual = max(tamanho_min, tamanho_atual - 0.25)
        largura = stringWidth(texto, fonte, tamanho_atual)
    if largura > largura_disponivel:
        tamanho_atual = tamanho_min
        reticencias = "…"
        cortado = texto
        while cortado and stringWidth(cortado + reticencias, fonte, tamanho_atual) > largura_disponivel:
            cortado = cortado[:-1]
        texto = (cortado + reticencias) if cortado else texto[0]
    c.setFont(fonte, tamanho_atual)
    c.drawString(x, PAGE_H - y, texto)


def camada(dados: dict, cnpj: str, eventos: list[dict] | None = None):
    """Cria a camada de preenchimento calibrada para o modelo CASSI enviado."""
    eventos = dados["eventos"] if eventos is None else eventos
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(PAGE_W, PAGE_H))

    # Linha superior: campos 4 (data), 5 (senha/autorização) e 6 (validade).
    desenhar_texto_ajustado(
        c, 373, 72, data_br(dados["resposta"] or dados["inicio"]),
        10, 66, tamanho_min=7.5,
    )
    desenhar_texto_ajustado(
        c, 448, 72, dados["autorizacao"], 10, 166, tamanho_min=7.5,
    )
    desenhar_texto_ajustado(
        c, 631, 72, dados["fim"], 10, 72, tamanho_min=7.5,
    )

    # Dados do beneficiário: campos 8 (carteira) e 11 (nome).
    desenhar_texto_ajustado(
        c, 32, 106, dados["carteira"], 11, 147, tamanho_min=7.5,
    )
    desenhar_texto_ajustado(
        c, 417, 106, dados["nome"], 11, 247, tamanho_min=7.0,
    )

    # Dados do contratante: campos 13 (CNPJ) e 14 (nome do contratado).
    desenhar_texto_ajustado(
        c, 34, 137, cnpj, 11, 196, tamanho_min=7.5,
    )
    desenhar_texto_ajustado(
        c, 242, 137, CONTRATADO, 10, 310, tamanho_min=7.0,
    )

    # Procedimentos solicitados: as coordenadas originais destas linhas foram mantidas.
    linhas_y = [223, 235, 246.5, 258, 270]
    for y, evento in zip(linhas_y, eventos[:5]):
        codigo = evento["codigo"]
        descricao = DESCRICOES[codigo]
        desenhar_texto_ajustado(c, 52, y, "22", 10, 35)
        desenhar_texto_ajustado(c, 100, y, codigo, 10, 92)
        desenhar_texto_ajustado(c, 205, y, descricao, 10, 480)
        desenhar_texto_ajustado(c, 694, y, evento["qtd"], 9, 28)
        desenhar_texto_ajustado(c, 733, y, evento["qtd"], 9, 36)

    c.save()
    buffer.seek(0)
    return PdfReader(buffer).pages[0]


def modelo_limpo(modelo_pdf: Path | str | None = None):
    """Abre o formulário e padroniza suas caixas físicas para A4 paisagem."""
    caminho = Path(modelo_pdf).expanduser() if modelo_pdf else caminho_modelo()
    if caminho is None or not caminho.exists():
        raise FileNotFoundError(
            "Modelo PDF não configurado. Acesse Configurações > Modelo oficial da guia "
            "e selecione o formulário da CASSI."
        )

    inspecionar_modelo(caminho, validar_dimensoes=True)
    leitor = PdfReader(str(caminho), strict=False)
    if not leitor.pages:
        raise ValueError("O PDF modelo não possui páginas.")

    pagina = leitor.pages[0]
    if "/Annots" in pagina:
        del pagina["/Annots"]

    # Rotação de 90°/270° já é bloqueada na inspeção. Para 180°, gravamos a
    # orientação no conteúdo e removemos a rotação interna do PDF.
    rotacao = int(pagina.get("/Rotate", 0) or 0) % 360
    if rotacao == 180:
        pagina.transfer_rotation_to_content()
    elif rotacao in (90, 270):
        raise ValueError(
            f"O modelo possui rotação de {rotacao}°. Selecione um PDF A4 paisagem sem rotação."
        )

    largura = float(pagina.mediabox.width)
    altura = float(pagina.mediabox.height)
    if abs(largura - PAGE_W) > 5 or abs(altura - PAGE_H) > 5 or largura <= altura:
        raise ValueError(
            "O modelo não pôde ser normalizado para A4 paisagem. "
            f"Dimensões encontradas: {largura:.1f} × {altura:.1f} pt; "
            f"esperado: {PAGE_W} × {PAGE_H} pt."
        )

    # Alinha MediaBox, CropBox, TrimBox, BleedBox e ArtBox ao mesmo A4 paisagem.
    caixa = RectangleObject((0, 0, PAGE_W, PAGE_H))
    pagina.mediabox = caixa
    pagina.cropbox = RectangleObject((0, 0, PAGE_W, PAGE_H))
    pagina.trimbox = RectangleObject((0, 0, PAGE_W, PAGE_H))
    pagina.bleedbox = RectangleObject((0, 0, PAGE_W, PAGE_H))
    pagina.artbox = RectangleObject((0, 0, PAGE_W, PAGE_H))
    pagina[NameObject("/Rotate")] = NumberObject(0)
    return pagina


def caminho_unico(caminho: Path) -> Path:
    """Cria nome alternativo incremental para nunca sobrescrever uma guia."""
    if not caminho.exists():
        return caminho
    contador = 2
    while True:
        candidato = caminho.with_name(f"{caminho.stem}_{contador}{caminho.suffix}")
        if not candidato.exists():
            return candidato
        contador += 1


def nome_seguro(texto: str) -> str:
    texto = re.sub(r"[^\w-]+", "_", str(texto or ""), flags=re.UNICODE).strip("_")
    return texto[:80] or "SEM_NOME"


def salvar_pdf(escritor: PdfWriter, destino: Path) -> Path:
    """Salva sem sobrescrever e valida a orientação real do PDF gravado."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino = caminho_unico(destino)
    temporario = destino.with_name(destino.stem + ".tmp" + destino.suffix)
    try:
        with temporario.open("wb") as arquivo:
            escritor.write(arquivo)
            arquivo.flush()
            os.fsync(arquivo.fileno())

        # Confere o arquivo já gravado, pois é essa versão que será impressa.
        leitor_teste = PdfReader(str(temporario), strict=False)
        if not leitor_teste.pages:
            raise ValueError("O PDF gerado não contém páginas.")

        caixas = ("mediabox", "cropbox", "trimbox", "bleedbox", "artbox")
        for numero, pagina in enumerate(leitor_teste.pages, start=1):
            largura = float(pagina.mediabox.width)
            altura = float(pagina.mediabox.height)
            rotacao = int(pagina.get("/Rotate", 0) or 0) % 360
            dimensoes_ok = abs(largura - PAGE_W) <= 1 and abs(altura - PAGE_H) <= 1
            caixas_ok = True
            for nome_caixa in caixas:
                caixa = getattr(pagina, nome_caixa)
                valores = tuple(float(valor) for valor in caixa)
                if len(valores) != 4 or any(abs(a - b) > 1 for a, b in zip(valores, (0, 0, PAGE_W, PAGE_H))):
                    caixas_ok = False
                    break

            if not dimensoes_ok or largura <= altura or rotacao != 0 or not caixas_ok:
                raise ValueError(
                    f"A página {numero} não foi gravada corretamente em A4 paisagem. "
                    f"MediaBox: {largura:.1f} × {altura:.1f} pt; rotação: {rotacao}°; "
                    f"caixas alinhadas: {'sim' if caixas_ok else 'não'}."
                )

        temporario.replace(destino)
    except Exception:
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return destino


def gerar_guia(
    dados: dict, cnpj: str, modo: str, pasta_saida: Path | None = None,
    modelo_pdf: Path | str | None = None,
) -> list[Path]:
    """Gera os PDFs. A lógica do modo completo permanece: cópia idêntica por evento."""
    valido, motivo = validar_cnpj(cnpj)
    if not valido:
        raise ValueError("Emissão bloqueada: " + motivo)
    validar_eventos(dados.get("eventos", []))
    saida_destino = Path(pasta_saida) if pasta_saida else SAIDA
    saida_destino.mkdir(parents=True, exist_ok=True)
    nome = nome_seguro(dados["nome"])
    autorizacao = nome_seguro(dados["autorizacao"])
    arquivos_gerados: list[Path] = []

    if modo == "copias_identicas":
        # Regra original preservada: todas as especialidades em cada página,
        # com uma cópia idêntica por procedimento reconhecido.
        escritor = PdfWriter()
        camada_completa = camada(dados, cnpj, dados["eventos"])
        for _ in dados["eventos"]:
            escritor.add_page(modelo_limpo(modelo_pdf))
            escritor.pages[-1].merge_page(camada_completa)
            escritor.pages[-1][NameObject("/Rotate")] = NumberObject(0)
        destino = saida_destino / f"GUIA_{nome}_{autorizacao}.pdf"
        arquivos_gerados.append(salvar_pdf(escritor, destino))

    elif modo == "separadas":
        # Modo independente: uma página/arquivo contendo somente um procedimento.
        for evento in dados["eventos"]:
            escritor = PdfWriter()
            escritor.add_page(modelo_limpo(modelo_pdf))
            escritor.pages[0].merge_page(camada(dados, cnpj, [evento]))
            escritor.pages[0][NameObject("/Rotate")] = NumberObject(0)
            descricao = nome_seguro(DESCRICOES[evento["codigo"]])
            codigo = nome_seguro(evento["codigo"])
            destino = saida_destino / f"GUIA_{nome}_{autorizacao}_{codigo}_{descricao}.pdf"
            arquivos_gerados.append(salvar_pdf(escritor, destino))
    else:
        raise ValueError(f"Modo de geração desconhecido: {modo}")
    return arquivos_gerados


def abrir_pasta(pasta: Path) -> None:
    """Abre uma pasta no gerenciador de arquivos padrão."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(str(pasta))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(pasta)])
        else:
            subprocess.Popen(["xdg-open", str(pasta)])
    except Exception:
        LOGGER.exception("Não foi possível abrir a pasta: %s", pasta)


# ================================================================
# 8. HISTÓRICO E RELATÓRIOS
# ================================================================
COLUNAS_HISTORICO = [
    "Data/hora", "Arquivo original", "Paciente", "Protocolo", "Autorização",
    "Unidade", "CNPJ", "Modelo", "Guias", "Resultado", "Detalhes",
]


def exportar_historico_csv(registros: list[dict], destino: Path) -> None:
    """Exporta apenas os campos administrativos apresentados na tela de histórico."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8-sig") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(COLUNAS_HISTORICO)
        for r in registros:
            escritor.writerow([
                r.get("data_hora", ""), r.get("arquivo_original", ""),
                r.get("paciente", ""), r.get("protocolo", ""),
                r.get("autorizacao", ""), r.get("unidade", ""),
                r.get("cnpj", ""), r.get("modelo", ""),
                r.get("quantidade_guias", 0), r.get("resultado", ""),
                r.get("detalhes", ""),
            ])



# ================================================================
# 9. API LOCAL DO PAINEL WEB (PYWEBVIEW)
# ================================================================
class DashboardAPI:
    """Ponte segura entre interface.html e as funções de processamento Python."""

    LIMITE_UPLOAD = 50 * 1024 * 1024  # 50 MB por PDF importado por arrastar/soltar.

    def __init__(self):
        self.lock = threading.RLock()
        self.events = deque(maxlen=500)
        self.event_id = 0
        self.state = "ready"
        self.progress = {"done": 0, "total": 0, "current": ""}
        self.session_stats = {"processed": 0, "completed": 0, "guides": 0, "errors": 0}
        self.queue: list[dict] = []
        self.history = carregar_historico()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.window = None
        self.uploads: dict[str, dict] = {}
        self._config = carregar_config()
        ENTRADA.mkdir(parents=True, exist_ok=True)
        caminho_saida(self._config).mkdir(parents=True, exist_ok=True)

    # ------------------------------ estado e eventos do painel
    def emit(self, level: str, title: str, description: str = "", **extra):
        with self.lock:
            self.event_id += 1
            event = {
                "id": self.event_id,
                "type": level,
                "title": str(title),
                "description": str(description),
                "time": datetime.now().astimezone().strftime("%H:%M:%S"),
            }
            for key in ("file", "patient", "protocol", "status", "guides"):
                if key in extra and extra[key] is not None:
                    event[key] = extra[key]
            self.events.append(event)
        if level == "error":
            LOGGER.error("%s — %s", title, description)
        elif level == "warning":
            LOGGER.warning("%s — %s", title, description)
        else:
            LOGGER.info("%s — %s", title, description)

    def _public_queue(self) -> list[dict]:
        with self.lock:
            return [
                {"id": item["id"], "name": item["name"], "status": item["status"]}
                for item in self.queue
            ]

    def get_initial_data(self):
        with self.lock:
            recent = list(reversed(self.history[-8:]))
            modelo_info = self._model_info()
            return {
                "config": json.loads(json.dumps(self._config, ensure_ascii=False)),
                "stats": dict(self.session_stats),
                "state": self.state,
                "progress": dict(self.progress),
                "queue": self._public_queue(),
                "history": recent,
                "output_path": str(caminho_saida(self._config)),
                "model": modelo_info,
                "model_exists": modelo_info["exists"],
                "version": VERSAO,
            }

    def get_updates(self, last_id=0):
        try:
            last_id = int(last_id or 0)
        except (TypeError, ValueError):
            last_id = 0
        with self.lock:
            oldest = self.events[0]["id"] if self.events else self.event_id + 1
            return {
                "events": [dict(item) for item in self.events if item["id"] > last_id],
                "reset": bool(last_id and last_id < oldest - 1),
                "last_id": self.event_id,
                "state": self.state,
                "progress": dict(self.progress),
                "stats": dict(self.session_stats),
                "queue": self._public_queue(),
            }

    # -------------------------------------------- configurações e modelo PDF
    def _model_info(self) -> dict:
        arquivo = caminho_modelo(self._config)
        if not arquivo:
            return {"exists": False, "path": "", "name": "Nenhum modelo selecionado", "pages": 0}
        try:
            dados = inspecionar_modelo(arquivo, validar_dimensoes=True)
            dados["exists"] = True
            dados["managed_copy"] = arquivo == MODELO_DADOS.resolve() if MODELO_DADOS.exists() else False
            return dados
        except Exception as exc:
            return {"exists": False, "path": str(arquivo), "name": arquivo.name, "error": str(exc)}

    def select_model_pdf(self):
        """Seleciona um PDF e copia-o para AppData; o original permanece intacto."""
        if self.worker and self.worker.is_alive():
            return {"ok": False, "error": "Não é possível trocar o modelo durante um processamento."}
        if self.window is None:
            return {"ok": False, "error": "Janela ainda não inicializada."}
        try:
            import webview
            selecionado = self.window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False,
                file_types=("Arquivo PDF (*.pdf)", "Todos os arquivos (*.*)"),
            )
            if not selecionado:
                return {"ok": False, "cancelled": True}
            origem = Path(selecionado[0] if isinstance(selecionado, (list, tuple)) else selecionado).resolve()
            # O arquivo deve respeitar o mesmo tamanho de página usado pelas coordenadas
            # do preenchimento original; isso evita deslocamento do conteúdo na emissão.
            dados_modelo = inspecionar_modelo(origem, validar_dimensoes=True)
            PASTA_MODELO_DADOS.mkdir(parents=True, exist_ok=True)
            temporario = MODELO_DADOS.with_name("guia_modelo.importando.pdf")
            try:
                shutil.copy2(origem, temporario)
                inspecionar_modelo(temporario, validar_dimensoes=True)
                if MODELO_DADOS.exists():
                    try:
                        shutil.copy2(MODELO_DADOS, MODELO_DADOS.with_suffix(".pdf.bak"))
                    except OSError:
                        LOGGER.exception("Não foi possível fazer backup do modelo PDF anterior")
                temporario.replace(MODELO_DADOS)
            finally:
                temporario.unlink(missing_ok=True)

            novo = json.loads(json.dumps(self._config, ensure_ascii=False))
            novo["modelo_pdf"] = str(MODELO_DADOS.resolve())
            salvar_config(novo)
            with self.lock:
                self._config = novo
            self.emit(
                "success", "Modelo PDF atualizado",
                f"Modelo {origem.name} copiado para a área local do aplicativo "
                f"({dados_modelo['pages']} página(s))."
            )
            return {"ok": True, "model": self._model_info(), "config": novo}
        except Exception as exc:
            LOGGER.exception("Falha ao selecionar o modelo PDF")
            return {"ok": False, "error": str(exc)}

    def open_model_folder(self):
        try:
            PASTA_MODELO_DADOS.mkdir(parents=True, exist_ok=True)
            abrir_pasta(PASTA_MODELO_DADOS)
            return {"ok": True, "path": str(PASTA_MODELO_DADOS)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def save_settings(self, payload):
        payload = payload or {}
        novo = json.loads(json.dumps(self._config, ensure_ascii=False))
        unidade = str(payload.get("unidade", novo.get("unidade", "asa_norte")))
        modo = str(payload.get("modo_guias", novo.get("modo_guias", "copias_identicas")))
        if unidade not in UNIDADES:
            return {"ok": False, "error": "Unidade selecionada inválida."}
        if modo not in MODOS:
            return {"ok": False, "error": "Modelo de geração inválido."}
        novo["unidade"] = unidade
        novo["modo_guias"] = modo

        cnpjs = payload.get("cnpjs", {})
        if isinstance(cnpjs, dict):
            for chave in UNIDADES:
                if chave in cnpjs:
                    novo.setdefault("cnpjs", {})[chave] = str(cnpjs[chave] or "").strip()
        pasta = payload.get("pasta_saida", novo.get("pasta_saida", ""))
        if pasta:
            novo["pasta_saida"] = str(Path(str(pasta)).expanduser())

        try:
            salvar_config(novo)
        except Exception as exc:
            LOGGER.exception("Falha ao persistir as configurações")
            return {"ok": False, "error": f"Não foi possível salvar as configurações: {exc}"}
        with self.lock:
            self._config = novo
        try:
            caminho_saida(novo).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            LOGGER.exception("Falha ao criar pasta de saída")
            return {"ok": False, "error": f"Configurações salvas, mas a pasta de saída não pôde ser criada: {exc}"}
        self.emit("success", "Configurações salvas", "As preferências locais foram atualizadas.")
        return {"ok": True, "config": novo, "output_path": str(caminho_saida(novo))}

    def select_output_folder(self):
        if self.window is None:
            return {"ok": False, "error": "Janela ainda não inicializada."}
        try:
            import webview
            escolhido = self.window.create_file_dialog(webview.FOLDER_DIALOG)
            if not escolhido:
                return {"ok": False, "cancelled": True}
            return {"ok": True, "path": str(escolhido[0] if isinstance(escolhido, (list, tuple)) else escolhido)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # -------------------------------------------- importação de PDFs
    def _add_paths(self, paths):
        adicionados, ignorados = [], []
        with self.lock:
            existentes = {str(Path(item["path"]).resolve()).casefold() for item in self.queue}
        for raw in paths or []:
            try:
                path = Path(str(raw)).expanduser().resolve()
                if path.is_dir():
                    candidatos = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
                else:
                    candidatos = [path]
                for candidato in candidatos:
                    if not candidato.is_file() or candidato.suffix.lower() != ".pdf":
                        continue
                    chave = str(candidato.resolve()).casefold()
                    if chave in existentes:
                        ignorados.append(candidato.name)
                        continue
                    item = {"id": uuid.uuid4().hex, "name": candidato.name, "path": str(candidato), "status": "Na fila"}
                    with self.lock:
                        self.queue.append(item)
                    existentes.add(chave)
                    adicionados.append(candidato.name)
            except Exception as exc:
                LOGGER.warning("Arquivo ignorado na importação: %s", exc)
        if adicionados:
            self.emit("success", "PDFs adicionados", f"{len(adicionados)} documento(s) adicionado(s) à fila.")
        if ignorados:
            self.emit("warning", "Arquivos repetidos ignorados", f"{len(ignorados)} arquivo(s) já estavam na fila.")
        return {"ok": True, "added": adicionados, "ignored": ignorados, "queue": self._public_queue()}

    def select_pdfs(self):
        if self.window is None:
            return {"ok": False, "error": "Janela ainda não inicializada."}
        try:
            import webview
            selecionados = self.window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=True, file_types=("Arquivos PDF (*.pdf)",)
            )
            if not selecionados:
                return {"ok": False, "cancelled": True, "queue": self._public_queue()}
            return self._add_paths(selecionados)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def select_input_folder(self):
        if self.window is None:
            return {"ok": False, "error": "Janela ainda não inicializada."}
        try:
            import webview
            pasta = self.window.create_file_dialog(webview.FOLDER_DIALOG)
            if not pasta:
                return {"ok": False, "cancelled": True, "queue": self._public_queue()}
            caminho = pasta[0] if isinstance(pasta, (list, tuple)) else pasta
            return self._add_paths([caminho])
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def begin_upload(self, filename, size):
        """Abre um upload temporário em blocos para suportar PDFs arrastados ao painel."""
        nome = re.split(r"[\\/]+", str(filename or "arquivo.pdf"))[-1]
        nome = nome[:180] or "arquivo.pdf"
        if Path(nome).suffix.lower() != ".pdf":
            return {"ok": False, "error": "Somente arquivos PDF são aceitos."}
        try:
            tamanho = int(size)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Tamanho do arquivo inválido."}
        if tamanho <= 0 or tamanho > self.LIMITE_UPLOAD:
            return {"ok": False, "error": "O PDF está vazio ou excede o limite de 50 MB."}
        uid = uuid.uuid4().hex
        caminho = ENTRADA / f"upload_{uid}.part"
        try:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_bytes(b"")
        except OSError as exc:
            return {"ok": False, "error": f"Não foi possível preparar o arquivo: {exc}"}
        with self.lock:
            self.uploads[uid] = {"name": nome, "size": tamanho, "written": 0, "path": caminho}
        return {"ok": True, "upload_id": uid, "chunk_size": 192 * 1024}

    def append_upload_chunk(self, upload_id, chunk_base64):
        with self.lock:
            item = self.uploads.get(str(upload_id))
        if not item:
            return {"ok": False, "error": "Upload não encontrado ou expirado."}
        try:
            bloco = base64.b64decode(str(chunk_base64), validate=True)
            if not bloco:
                return {"ok": True}
            if item["written"] + len(bloco) > item["size"] or item["written"] + len(bloco) > self.LIMITE_UPLOAD:
                return {"ok": False, "error": "O conteúdo recebido excedeu o tamanho informado."}
            with item["path"].open("ab") as arquivo:
                arquivo.write(bloco)
            item["written"] += len(bloco)
            return {"ok": True, "written": item["written"]}
        except Exception as exc:
            LOGGER.exception("Erro no upload do PDF")
            return {"ok": False, "error": str(exc)}

    def finish_upload(self, upload_id):
        with self.lock:
            item = self.uploads.pop(str(upload_id), None)
        if not item:
            return {"ok": False, "error": "Upload não encontrado ou expirado."}
        temporario: Path = item["path"]
        try:
            if item["written"] != item["size"]:
                raise ValueError("Upload incompleto. Tente adicionar o PDF novamente.")
            with temporario.open("rb") as arquivo:
                cabecalho = arquivo.read(1024)
            if b"%PDF-" not in cabecalho:
                raise ValueError("O arquivo selecionado não parece ser um PDF válido.")
            destino = caminho_unico(ENTRADA / nome_seguro(Path(item["name"]).stem))
            destino = destino.with_suffix(".pdf")
            destino = caminho_unico(destino)
            temporario.replace(destino)
            resposta = self._add_paths([destino])
            return resposta
        except Exception as exc:
            temporario.unlink(missing_ok=True)
            return {"ok": False, "error": str(exc)}

    def cancel_upload(self, upload_id):
        with self.lock:
            item = self.uploads.pop(str(upload_id), None)
        if item:
            try:
                item["path"].unlink(missing_ok=True)
            except OSError:
                pass
        return {"ok": True}

    def remove_pdf(self, item_id):
        if self.worker and self.worker.is_alive():
            return {"ok": False, "error": "Não é possível alterar a fila durante o processamento."}
        with self.lock:
            antes = len(self.queue)
            self.queue = [item for item in self.queue if item["id"] != str(item_id)]
            removido = len(self.queue) < antes
        return {"ok": removido, "queue": self._public_queue()}

    def clear_queue(self):
        if self.worker and self.worker.is_alive():
            return {"ok": False, "error": "A fila não pode ser limpa durante o processamento."}
        with self.lock:
            self.queue.clear()
        self.emit("info", "Fila limpa", "A lista de PDFs selecionados foi esvaziada.")
        return {"ok": True, "queue": []}

    # -------------------------------------------- processamento em segundo plano
    def start_processing(self, payload=None):
        if self.worker and self.worker.is_alive():
            return {"ok": False, "error": "Já existe um processamento em andamento."}
        payload = payload or {}
        if payload.get("settings"):
            result = self.save_settings(payload["settings"])
            if not result.get("ok"):
                return result
        with self.lock:
            queue_snapshot = [dict(item) for item in self.queue]
            config = json.loads(json.dumps(self._config, ensure_ascii=False))
        if not queue_snapshot:
            return {"ok": False, "error": "Adicione pelo menos um PDF antes de iniciar."}
        modelo_atual = caminho_modelo(config)
        if modelo_atual is None:
            return {"ok": False, "error": "Modelo da guia não selecionado. Acesse Configurações > Modelo oficial da guia e selecione o PDF da CASSI."}
        try:
            inspecionar_modelo(modelo_atual, validar_dimensoes=True)
        except Exception as exc:
            return {"ok": False, "error": f"Modelo da guia inválido: {exc}"}
        unidade = config.get("unidade", "asa_norte")
        cnpj = config.get("cnpjs", {}).get(unidade, "")
        valido, motivo = validar_cnpj(cnpj)
        if not valido:
            return {"ok": False, "error": "Emissão bloqueada: " + motivo}
        ausentes = [item["name"] for item in queue_snapshot if not Path(item["path"]).is_file()]
        if ausentes:
            return {"ok": False, "error": "Não foi possível localizar: " + ", ".join(ausentes[:5])}

        self.stop_event.clear()
        with self.lock:
            self.state = "running"
            self.progress = {"done": 0, "total": len(queue_snapshot), "current": "Preparando lote..."}
            self.session_stats = {"processed": 0, "completed": 0, "guides": 0, "errors": 0}
            for item in self.queue:
                item["status"] = "Na fila"
        self.emit("info", "Processamento iniciado", f"Lote com {len(queue_snapshot)} PDF(s) — {UNIDADES[unidade]}.")
        self.worker = threading.Thread(
            target=self._worker_main, args=(queue_snapshot, config),
            name="CASSIGuiasWorker", daemon=True,
        )
        self.worker.start()
        return {"ok": True}

    def _set_queue_status(self, item_id, status):
        with self.lock:
            for item in self.queue:
                if item["id"] == item_id:
                    item["status"] = status
                    break

    def _save_record(self, record):
        with self.lock:
            self.history.append(record)
            snapshot = list(self.history)
        try:
            salvar_historico(snapshot)
        except Exception:
            LOGGER.exception("Não foi possível persistir o histórico do processamento")
            self.emit("warning", "Histórico não salvo", "O processamento terminou, mas ocorreu uma falha ao persistir o histórico local.")

    def _worker_main(self, queue_snapshot, config):
        unidade = config["unidade"]
        unidade_nome = UNIDADES[unidade]
        cnpj = config.get("cnpjs", {}).get(unidade, "")
        modo = config["modo_guias"]
        total = len(queue_snapshot)
        pasta_saida = caminho_saida(config)
        pasta_saida.mkdir(parents=True, exist_ok=True)
        modelo_pdf = caminho_modelo(config)
        modelo_nome = modelo_pdf.name if modelo_pdf else "Não configurado"
        resumo = {"processados": 0, "concluidos": 0, "erros": 0, "guias": 0}

        for indice, item in enumerate(queue_snapshot, start=1):
            if self.stop_event.is_set():
                break
            pdf = Path(item["path"])
            self._set_queue_status(item["id"], "Processando")
            with self.lock:
                self.progress = {"done": indice - 1, "total": total, "current": pdf.name}
            self.emit("info", "Lendo protocolo", f"[{indice}/{total}] {pdf.name}", file=pdf.name)
            instante = datetime.now().astimezone().isoformat(timespec="seconds")
            registro = {
                "data_hora": instante,
                "arquivo_original": pdf.name,
                "caminho_original": str(pdf),
                "paciente": "",
                "protocolo": "",
                "autorizacao": "",
                "unidade": unidade_nome,
                "unidade_chave": unidade,
                "cnpj": cnpj,
                "modelo": MODOS[modo],
                "arquivo_modelo": modelo_nome,
                "modo_chave": modo,
                "quantidade_guias": 0,
                "arquivos_gerados": [],
                "resultado": "Erro",
                "detalhes": "",
            }
            try:
                dados = ler_email(pdf)
                registro["paciente"] = dados.get("nome", "")
                registro["protocolo"] = dados.get("protocolo", "")
                registro["autorizacao"] = dados.get("autorizacao", "")
                arquivos = gerar_guia(
                    dados, cnpj, modo, pasta_saida=pasta_saida, modelo_pdf=modelo_pdf
                )
                quantidade = len(arquivos) if modo == "separadas" else len(dados["eventos"])
                registro["quantidade_guias"] = quantidade
                registro["arquivos_gerados"] = [str(arq) for arq in arquivos]
                registro["resultado"] = "Atenção" if dados.get("obs_parsing") else "Concluído"
                registro["detalhes"] = "; ".join(dados.get("obs_parsing", []))
                resumo["concluidos"] += 1
                resumo["guias"] += quantidade
                self._set_queue_status(item["id"], registro["resultado"])
                self.emit(
                    "success" if registro["resultado"] == "Concluído" else "warning",
                    registro["resultado"],
                    f"{registro['paciente']} — {quantidade} guia(s) gerada(s).",
                    file=pdf.name, patient=registro["paciente"], protocol=registro["protocolo"],
                    status=registro["resultado"], guides=quantidade,
                )
            except Exception as exc:
                registro["resultado"] = "Erro"
                registro["detalhes"] = str(exc)
                resumo["erros"] += 1
                self._set_queue_status(item["id"], "Erro")
                LOGGER.exception("Falha ao processar %s", pdf.name)
                self.emit("error", "Falha no documento", f"{pdf.name}: {exc}", file=pdf.name, status="Erro")

            resumo["processados"] += 1
            self._save_record(registro)
            with self.lock:
                self.session_stats["processed"] += 1
                self.session_stats["completed"] += 1 if registro["resultado"] in ("Concluído", "Atenção") else 0
                self.session_stats["guides"] += int(registro["quantidade_guias"] or 0)
                self.session_stats["errors"] += 1 if registro["resultado"] == "Erro" else 0
                self.progress = {"done": indice, "total": total, "current": pdf.name}

        parou = self.stop_event.is_set()
        with self.lock:
            self.state = "stopped" if parou else "finished"
            self.progress["current"] = ""
        self.emit(
            "warning" if parou else "success",
            "Processamento interrompido" if parou else "Lote finalizado",
            f"PDFs processados: {resumo['processados']}/{total}; guias: {resumo['guias']}; erros: {resumo['erros']}."
        )

    def request_stop(self):
        if not (self.worker and self.worker.is_alive()):
            return {"ok": False, "error": "Não existe processamento em andamento."}
        self.stop_event.set()
        with self.lock:
            self.state = "stopping"
        self.emit("warning", "Parada solicitada", "O documento atual será concluído; os próximos não serão iniciados.")
        return {"ok": True}

    # -------------------------------------------- histórico e arquivos
    def get_history(self, filters=None):
        filters = filters or {}
        unidade = str(filters.get("unidade", "all"))
        resultado = str(filters.get("resultado", "all")).casefold()
        inicio = str(filters.get("inicio", ""))
        fim = str(filters.get("fim", ""))
        busca = str(filters.get("busca", "")).strip().casefold()
        with self.lock:
            registros = list(reversed(self.history))
        filtrados = []
        for item in registros:
            dt = str(item.get("data_hora", ""))[:10]
            if unidade != "all" and item.get("unidade_chave") != unidade:
                continue
            if resultado != "all" and str(item.get("resultado", "")).casefold() != resultado:
                continue
            if inicio and dt and dt < inicio:
                continue
            if fim and dt and dt > fim:
                continue
            hay = " ".join(str(item.get(k, "")) for k in ("arquivo_original", "paciente", "protocolo", "autorizacao")).casefold()
            if busca and busca not in hay:
                continue
            filtrados.append(item)
        return {"items": filtrados[:1000], "total": len(filtrados)}

    def export_history(self):
        if self.window is None:
            return {"ok": False, "error": "Janela ainda não inicializada."}
        try:
            import webview
            destino = self.window.create_file_dialog(
                webview.SAVE_DIALOG, save_filename="historico_gerador_guias_cassi.csv",
                file_types=("Arquivo CSV (*.csv)",),
            )
            if not destino:
                return {"ok": False, "cancelled": True}
            path = destino[0] if isinstance(destino, (list, tuple)) else destino
            exportar_historico_csv(self.history, Path(path))
            self.emit("success", "Relatório exportado", f"Histórico exportado para {path}.")
            return {"ok": True, "path": str(path)}
        except Exception as exc:
            LOGGER.exception("Falha ao exportar histórico")
            return {"ok": False, "error": str(exc)}

    def open_output_folder(self):
        try:
            pasta = caminho_saida(self._config)
            abrir_pasta(pasta)
            return {"ok": True, "path": str(pasta)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_pdf(self, path):
        try:
            candidate = Path(str(path)).resolve()
            allowed_roots = [Path(self._config.get("pasta_saida") or PASTA_SAIDA_PADRAO).expanduser().resolve()]
            if not candidate.is_file() or candidate.suffix.lower() != ".pdf":
                return {"ok": False, "error": "O PDF selecionado não foi encontrado."}
            if not any(candidate == root or root in candidate.parents for root in allowed_roots):
                return {"ok": False, "error": "O arquivo não pertence à pasta de saída configurada."}
            if os.name == "nt":
                os.startfile(str(candidate))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(candidate)])
            else:
                subprocess.Popen(["xdg-open", str(candidate)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_output_info(self):
        info_modelo = self._model_info()
        return {"path": str(caminho_saida(self._config)), "model_exists": info_modelo["exists"], "model": info_modelo}


# ================================================================
# 10. INICIALIZAÇÃO DO PAINEL WEB
# ================================================================
def iniciar_interface():
    """Abre o painel HTML local e conecta a API Python pelo PyWebView."""
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "PyWebView não está instalado. No ambiente de desenvolvimento execute: pip install -r requirements.txt"
        ) from exc

    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    ENTRADA.mkdir(parents=True, exist_ok=True)
    config = carregar_config()
    caminho_saida(config).mkdir(parents=True, exist_ok=True)

    html_path = BASE / "interface.html"
    if not html_path.exists():
        html_path = INTERFACE_RESOURCE
    if not html_path.exists():
        raise FileNotFoundError(
            "A interface web não foi encontrada. Mantenha interface.html ao lado de gerar_guias.py "
            "ou inclua o arquivo na compilação do executável."
        )

    api = DashboardAPI()
    LOGGER.info("Iniciando PyWebView %s com HTML local: %s", getattr(webview, "__version__", "desconhecida"), html_path.resolve())
    janela = webview.create_window(
        "Gerador de Guias CASSI",
        str(html_path.resolve()),
        js_api=api,
        width=1440,
        height=960,
        min_size=(1120, 740),
        background_color="#F4F7FB",
        text_select=True,
    )
    api.window = janela
    webview.start(debug=False, http_server=True)



# ================================================================
# 11. PRÉ-REQUISITO WINDOWS: MICROSOFT EDGE WEBVIEW2 RUNTIME
# ================================================================
WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_BOOTSTRAPPER_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
WEBVIEW2_BOOTSTRAPPER_NAME = "MicrosoftEdgeWebView2Setup.exe"


def webview2_runtime_instalado() -> bool:
    """Detecta o Evergreen WebView2 Runtime no registro do Windows (HKCU/HKLM)."""
    if os.name != "nt":
        return True
    try:
        import winreg
    except ImportError:
        return False

    subchaves = [
        (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}"),
    ]
    flags = [getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)]
    for raiz, subchave in subchaves:
        for flag in dict.fromkeys(flags):
            try:
                with winreg.OpenKey(raiz, subchave, 0, winreg.KEY_READ | flag) as chave:
                    versao, _ = winreg.QueryValueEx(chave, "pv")
                partes = [int(x) for x in re.findall(r"\d+", str(versao))[:4]]
                if partes and any(partes):
                    return True
            except (OSError, ValueError, TypeError):
                continue
    return False


def localizar_ou_baixar_webview2_bootstrapper() -> Path:
    """Localiza o bootstrapper embutido no EXE; no modo dev, baixa-o da Microsoft."""
    candidatos = [
        RESOURCE_BASE / "runtime" / WEBVIEW2_BOOTSTRAPPER_NAME,
        BASE / "runtime" / WEBVIEW2_BOOTSTRAPPER_NAME,
    ]
    for candidato in candidatos:
        if candidato.is_file() and candidato.stat().st_size > 100_000:
            return candidato

    pasta_runtime = APP_DATA_DIR / "runtime"
    pasta_runtime.mkdir(parents=True, exist_ok=True)
    destino = pasta_runtime / WEBVIEW2_BOOTSTRAPPER_NAME
    temporario = destino.with_suffix(".download")
    try:
        requisicao = urllib.request.Request(
            WEBVIEW2_BOOTSTRAPPER_URL,
            headers={"User-Agent": f"{NOME_APP}/{VERSAO}"},
        )
        with urllib.request.urlopen(requisicao, timeout=60) as resposta, temporario.open("wb") as arquivo:
            while True:
                bloco = resposta.read(1024 * 1024)
                if not bloco:
                    break
                arquivo.write(bloco)
        if temporario.stat().st_size <= 100_000:
            raise RuntimeError("O instalador obtido da Microsoft parece incompleto.")
        with temporario.open("rb") as arquivo:
            if arquivo.read(2) != b"MZ":
                raise RuntimeError("O arquivo baixado não foi reconhecido como executável Windows.")
        temporario.replace(destino)
        return destino
    except Exception as exc:
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(
            "O Microsoft Edge WebView2 Runtime não está instalado e não foi possível preparar "
            "seu instalador. Conecte este computador à internet e tente novamente. "
            "Também é possível instalar o Evergreen WebView2 Runtime pelo site oficial: "
            "https://developer.microsoft.com/microsoft-edge/webview2/"
        ) from exc


def garantir_webview2_runtime() -> None:
    """Instala o WebView2 silenciosamente, por usuário, apenas quando estiver ausente."""
    if os.name != "nt" or webview2_runtime_instalado():
        return

    instalador = localizar_ou_baixar_webview2_bootstrapper()
    LOGGER.info("WebView2 Runtime ausente; iniciando instalador Microsoft: %s", instalador)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    try:
        resultado = subprocess.run(
            [str(instalador), "/silent", "/install"],
            check=False,
            timeout=600,
            creationflags=creationflags,
            startupinfo=startupinfo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("A instalação do WebView2 ultrapassou o tempo esperado. Reinicie o computador e tente novamente.") from exc
    except OSError as exc:
        raise RuntimeError(f"Não foi possível iniciar a instalação do WebView2: {exc}") from exc

    if not webview2_runtime_instalado():
        raise RuntimeError(
            "O instalador do WebView2 foi executado, mas o Runtime ainda não foi detectado. "
            f"Código retornado: {resultado.returncode}. Verifique a política de instalação do Windows "
            "ou solicite suporte ao administrador da clínica."
        )
    LOGGER.info("Microsoft Edge WebView2 Runtime detectado após instalação.")


def main() -> int:
    """Ponto único de entrada; pronto para PyInstaller --windowed/--noconsole."""
    try:
        garantir_webview2_runtime()
        iniciar_interface()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        LOGGER.exception("Não foi possível iniciar o Gerador de Guias CASSI")
        mensagem = f"Não foi possível iniciar o Gerador de Guias CASSI:\n{type(exc).__name__}: {exc}"
        detalhe = str(exc).casefold()
        if os.name == "nt" and any(chave in detalhe for chave in ("webview", "edgechromium", "edge chromium")):
            mensagem += (
                "\n\nEste aplicativo utiliza o Microsoft Edge WebView2 Runtime para exibir o painel. "
                "Verifique se o WebView2 Runtime está instalado no Windows."
            )
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, mensagem, TITULO_APP, 0x10)
            except Exception:
                print(mensagem, file=sys.stderr)
        else:
            print(mensagem, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())