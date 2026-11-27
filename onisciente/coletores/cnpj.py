"""Cadastro das empresas contratadas na Receita Federal: dados cadastrais e quadro societário (QSA).

Fonte primária: os **dados abertos do CNPJ** que a Receita Federal publica todo mês (dicionário de
dados "cnpj-metadados.pdf"). São arquivos zip com CSV sem cabeçalho, separados por ``;``, campos
entre aspas, em latin-1:

* ``Empresas0..9.zip``: um registro por CNPJ básico (8 primeiros dígitos): razão social, natureza
  jurídica, qualificação do responsável, capital social, porte, ente federativo;
* ``Estabelecimentos0..9.zip``: um registro por CNPJ completo (matriz e filiais): situação cadastral
  e a data e o motivo dela, início de atividade, CNAE principal e secundários, endereço, telefones,
  correio eletrônico;
* ``Socios0..9.zip``: o QSA por CNPJ básico, com o CPF do sócio mascarado como a Receita publica
  (``***123456**``: só os seis dígitos do meio), qualificação, data de entrada, representante legal
  e faixa etária;
* ``Simples.zip``: opção pelo Simples Nacional e pelo MEI, com as datas de opção e de exclusão;
* ``Cnaes``, ``Qualificacoes``, ``Motivos``, ``Naturezas`` e ``Municipios``: as tabelas de códigos.

Os arquivos têm dezenas de gigabytes descompactados. O coletor baixa um zip de cada vez para o disco,
lê o CSV em fluxo (linha a linha, sem carregar o arquivo) e guarda só os CNPJs básicos que estão no
banco; depois apaga o zip. A memória usada é a do conjunto de CNPJs procurados.

Via secundária, para o incremental (um CNPJ novo no meio do mês): uma API pública que espelha a mesma
base (BrasilAPI ``/api/cnpj/v1/{cnpj}``; minhareceita como reserva). Cada registro leva a via e a data
da base de onde veio (o selo de fonte); a via secundária não diz a data da base, e isso fica dito.

Nada aqui decide se há irregularidade: isso é de ``onisciente.conferencias.empresas``.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import re
import unicodedata
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Iterator

# --- Endereços ----------------------------------------------------------------------------------

# O compartilhamento público da Receita (Nextcloud) servido por WebDAV: o usuário é o token do
# compartilhamento e a senha é vazia. As pastas mensais (AAAA-MM) ficam debaixo de Dados/Cadastros/CNPJ.
WEBDAV = "https://arquivos.receitafederal.gov.br/public.php/webdav/Dados/Cadastros/CNPJ/"
TOKEN_PADRAO = "gn672Ad4CF8N6TK"
# O endereço antigo (índice Apache com as pastas AAAA-MM/), mantido como segunda porta.
INDICE_ANTIGO = "https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/"
METADADOS = "https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf"
BRASILAPI = "https://brasilapi.com.br/api/cnpj/v1/"
MINHARECEITA = "https://minhareceita.org/"

FONTE_BASE = "Receita Federal, dados abertos do CNPJ (arquivo mensal)"
FONTE_BRASILAPI = "BrasilAPI (espelho dos dados abertos do CNPJ da Receita Federal)"
FONTE_MINHARECEITA = "minhareceita (espelho dos dados abertos do CNPJ da Receita Federal)"

# --- Layout oficial (dicionário de dados do CNPJ) -----------------------------------------------

EMPRESAS = ("cnpj_basico", "razao", "natureza", "qualificacao_responsavel", "capital_social", "porte",
            "ente_federativo")
ESTABELECIMENTOS = ("cnpj_basico", "cnpj_ordem", "cnpj_dv", "matriz_filial", "nome_fantasia", "situacao",
                    "data_situacao", "motivo", "cidade_exterior", "pais", "data_abertura", "cnae_principal",
                    "cnaes_secundarios", "tipo_logradouro", "logradouro", "numero", "complemento", "bairro",
                    "cep", "uf", "municipio", "ddd1", "telefone1", "ddd2", "telefone2", "ddd_fax", "fax",
                    "email", "situacao_especial", "data_situacao_especial")
SOCIOS = ("cnpj_basico", "identificador", "nome", "cpf_cnpj", "qualificacao", "data_entrada", "pais",
          "representante_cpf", "representante", "qualificacao_representante", "faixa_etaria")
SIMPLES = ("cnpj_basico", "opcao_simples", "data_opcao_simples", "data_exclusao_simples", "opcao_mei",
           "data_opcao_mei", "data_exclusao_mei")
TABELAS_DE_CODIGOS = ("Cnaes", "Qualificacoes", "Motivos", "Naturezas", "Municipios")

SITUACOES = {"01": "NULA", "1": "NULA", "02": "ATIVA", "2": "ATIVA", "03": "SUSPENSA", "3": "SUSPENSA",
             "04": "INAPTA", "4": "INAPTA", "08": "BAIXADA", "8": "BAIXADA"}
PORTES = {"00": "NAO INFORMADO", "0": "NAO INFORMADO", "01": "MICRO EMPRESA", "1": "MICRO EMPRESA",
          "03": "EMPRESA DE PEQUENO PORTE", "3": "EMPRESA DE PEQUENO PORTE", "05": "DEMAIS", "5": "DEMAIS"}
IDENTIFICADOR_SOCIO = {"1": "PESSOA JURIDICA", "2": "PESSOA FISICA", "3": "ESTRANGEIRO"}
FAIXAS_ETARIAS = {"0": "não se aplica", "1": "0 a 12 anos", "2": "13 a 20 anos", "3": "21 a 30 anos",
                  "4": "31 a 40 anos", "5": "41 a 50 anos", "6": "51 a 60 anos", "7": "61 a 70 anos",
                  "8": "71 a 80 anos", "9": "mais de 80 anos"}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cnpj_empresas (cnpj TEXT PRIMARY KEY, cnpj_basico TEXT, razao TEXT, nome_fantasia TEXT,
    matriz INTEGER, situacao TEXT, data_situacao TEXT, motivo TEXT, data_abertura TEXT, natureza TEXT,
    porte TEXT, capital_social REAL, cnae_principal TEXT, cnaes_secundarios TEXT, municipio TEXT, uf TEXT,
    endereco TEXT, logradouro TEXT, numero TEXT, complemento TEXT, bairro TEXT, cep TEXT, telefone TEXT,
    email TEXT, simples TEXT, data_opcao_simples TEXT, data_exclusao_simples TEXT, mei TEXT,
    data_opcao_mei TEXT, data_exclusao_mei TEXT, fonte TEXT, data_base TEXT, consultado_em TEXT);
CREATE TABLE IF NOT EXISTS cnpj_socios (cnpj TEXT, nome TEXT, cpf_cnpj TEXT, identificador TEXT,
    qualificacao TEXT, data_entrada TEXT, representante TEXT, representante_cpf TEXT,
    qualificacao_representante TEXT, faixa_etaria TEXT, fonte TEXT, data_base TEXT);
CREATE TABLE IF NOT EXISTS cnpj_codigos (tabela TEXT, codigo TEXT, descricao TEXT, data_base TEXT,
    PRIMARY KEY (tabela, codigo));
CREATE TABLE IF NOT EXISTS cnpj_historico (cnpj TEXT, campo TEXT, valor TEXT, primeira_base TEXT,
    ultima_base TEXT, PRIMARY KEY (cnpj, campo, valor));
CREATE TABLE IF NOT EXISTS cnpj_ausentes (cnpj TEXT PRIMARY KEY, fonte TEXT, data_base TEXT, motivo TEXT);
"""


# --- Normalização ---------------------------------------------------------------------------------

def _norm(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.upper()).strip()


def so_cnpj(texto) -> str:
    """O CNPJ sem pontuação, em maiúsculas (o CNPJ alfanumérico, desde julho de 2026, tem letras
    nas 12 primeiras posições)."""
    return re.sub(r"[^0-9A-Za-z]", "", str(texto or "")).upper()


def cnpj_valido(texto) -> bool:
    """Dígitos verificadores do CNPJ, numérico ou alfanumérico (cada caractere vale ``ord - 48``)."""
    c = so_cnpj(texto)
    if len(c) != 14 or not c[12:].isdigit() or not re.fullmatch(r"[0-9A-Z]{12}", c[:12]):
        return False
    if c.isdigit() and c == c[0] * 14:
        return False
    valores = [ord(ch) - 48 for ch in c]
    for tam in (12, 13):
        pesos = list(range(2, 10)) * 2
        soma = sum(v * p for v, p in zip(reversed(valores[:tam]), pesos))
        dv = 11 - soma % 11
        if (0 if dv > 9 else dv) != valores[tam]:
            return False
    return True


def data_iso(texto) -> str | None:
    """``20240115`` ou ``2024-01-15`` viram ``2024-01-15``; zeros e vazios viram nada."""
    t = re.sub(r"\D", "", str(texto or ""))
    if len(t) != 8 or t == "0" * 8 or t.startswith("0000"):
        return None
    try:
        return date(int(t[:4]), int(t[4:6]), int(t[6:])).isoformat()
    except ValueError:
        return None


def capital(texto) -> float | None:
    t = str(texto or "").strip()
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def telefone(ddd, numero) -> str:
    d = re.sub(r"\D", "", f"{ddd or ''}{numero or ''}")
    return d if len(d) >= 8 else ""


def endereco(tipo, logradouro, numero, complemento, bairro, cep, municipio, uf) -> str:
    partes = [" ".join(p for p in (_norm(tipo), _norm(logradouro)) if p), _norm(numero), _norm(complemento),
              _norm(bairro), re.sub(r"\D", "", str(cep or "")), _norm(municipio), _norm(uf)]
    return ", ".join(p for p in partes if p)


# --- Leitura em fluxo dos arquivos da base mensal ------------------------------------------------

def linhas_do_zip(caminho: Path | io.BytesIO, colunas: tuple[str, ...],
                  basicos: set[str] | None = None) -> Iterator[dict]:
    """As linhas de todos os CSV do zip, uma a uma, como dicionário pelo layout oficial.
    Com ``basicos``, só as linhas cujo primeiro campo (o CNPJ básico) está no conjunto: o arquivo
    nunca é carregado inteiro (o zip é lido do disco e o CSV é descomprimido em fluxo)."""
    with zipfile.ZipFile(caminho) as z:
        for nome in z.namelist():
            if nome.endswith("/"):
                continue
            with z.open(nome) as bruto:
                texto = io.TextIOWrapper(bruto, encoding="latin-1", newline="")
                for linha in csv.reader(texto, delimiter=";", quotechar='"'):
                    if not linha:
                        continue
                    if basicos is not None and linha[0].strip().upper() not in basicos:
                        continue
                    if len(linha) < len(colunas):
                        linha = linha + [""] * (len(colunas) - len(linha))
                    yield dict(zip(colunas, (c.strip() for c in linha)))


def codigos_do_zip(caminho: Path | io.BytesIO) -> dict[str, str]:
    return {r["codigo"]: r["descricao"] for r in linhas_do_zip(caminho, ("codigo", "descricao"))}


# --- Descoberta das pastas mensais ---------------------------------------------------------------

def meses_da_listagem(texto: str) -> list[str]:
    """As pastas AAAA-MM de uma listagem: o índice HTML antigo ou a resposta PROPFIND do WebDAV."""
    achados = set(re.findall(r"(?<![\d-])(20\d\d-(?:0[1-9]|1[0-2]))/", texto))
    return sorted(achados)


def arquivos_da_listagem(texto: str) -> list[str]:
    """Os zips de uma pasta mensal (índice HTML ou PROPFIND)."""
    return sorted(set(re.findall(r"([A-Za-z]+\d?\.zip)", texto)))


def autorizacao(token: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{token}:".encode()).decode()}


PROPFIND = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/>'
            '<d:getcontentlength/></d:prop></d:propfind>')


def pedir(url: str, *, metodo: str = "GET", cabecalhos: dict | None = None, corpo: bytes | None = None,
          tempo: int = 60) -> tuple[int | None, bytes, str]:
    """Uma requisição simples (inclusive PROPFIND). Devolve (código, corpo, erro); nunca levanta."""
    from .base import AGENTE
    req = urllib.request.Request(url, data=corpo, method=metodo,
                                 headers={"User-Agent": AGENTE, **(cabecalhos or {})})
    try:
        with urllib.request.urlopen(req, timeout=tempo) as r:  # noqa: S310 (endereço fixo da Receita)
            return getattr(r, "status", 200), r.read(), ""
    except urllib.error.HTTPError as e:
        return e.code, b"", f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, b"", f"{type(e).__name__}: {getattr(e, 'reason', e)}"


def baixar(url: str, destino: Path, *, cabecalhos: dict | None = None, tempo: int = 300,
           bloco: int = 1 << 20) -> tuple[bool, int, str]:
    """Baixa para o disco em blocos de 1 MB (nunca o arquivo inteiro na memória).
    Devolve (ok, bytes, erro)."""
    from .base import AGENTE
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE, **(cabecalhos or {})})
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=tempo) as r, open(destino, "wb") as saida:  # noqa: S310
            while True:
                parte = r.read(bloco)
                if not parte:
                    break
                saida.write(parte)
                total += len(parte)
        return True, total, ""
    except urllib.error.HTTPError as e:
        return False, total, f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, total, f"{type(e).__name__}: {getattr(e, 'reason', e)}"


@dataclass
class Porta:
    """Uma via de acesso à base mensal: como listar as pastas e como montar a URL de um arquivo."""

    nome: str
    raiz: str
    cabecalhos: dict = field(default_factory=dict)
    propfind: bool = False

    def url(self, mes: str, arquivo: str = "") -> str:
        return f"{self.raiz}{mes}/{arquivo}"


def portas(token: str = TOKEN_PADRAO) -> list[Porta]:
    return [Porta("webdav", WEBDAV, autorizacao(token), propfind=True), Porta("indice", INDICE_ANTIGO)]


def listar(porta: Porta, caminho: str = "", *, pedir_url: Callable = pedir) -> tuple[str, str]:
    """A listagem de uma pasta da porta: (texto, erro)."""
    url = porta.raiz + caminho
    if porta.propfind:
        codigo, corpo, erro = pedir_url(url, metodo="PROPFIND",
                                        cabecalhos={**porta.cabecalhos, "Depth": "1",
                                                    "Content-Type": "application/xml"},
                                        corpo=PROPFIND.encode())
    else:
        codigo, corpo, erro = pedir_url(url, cabecalhos=porta.cabecalhos)
    if erro or not corpo:
        return "", erro or f"HTTP {codigo}: listagem vazia"
    return corpo.decode("utf-8", "replace"), ""


# --- Montagem do registro -------------------------------------------------------------------------

@dataclass
class Cadastro:
    """O que a coleta devolve: empresas (por CNPJ completo), sócios e tabelas de códigos."""

    empresas: dict[str, dict] = field(default_factory=dict)
    socios: list[dict] = field(default_factory=list)
    codigos: dict[str, dict[str, str]] = field(default_factory=dict)
    ausentes: dict[str, str] = field(default_factory=dict)       # cnpj -> motivo
    fonte: str = ""
    data_base: str | None = None
    erros: list[str] = field(default_factory=list)
    completa: bool = False          # a base inteira foi lida (o CNPJ que não apareceu não existe nela)


def _registro_estabelecimento(e: dict, emp: dict | None, simples: dict | None, codigos: dict,
                              fonte: str, data_base: str | None, hoje: str) -> dict:
    municipios = codigos.get("Municipios", {})
    municipio = municipios.get(e["municipio"], e["municipio"])
    sec = [c for c in re.split(r"[,\s]+", e.get("cnaes_secundarios") or "") if c.strip()]
    tel = [t for t in (telefone(e.get("ddd1"), e.get("telefone1")), telefone(e.get("ddd2"), e.get("telefone2")))
           if t]
    s = simples or {}
    emp = emp or {}
    return {
        "cnpj": so_cnpj(e["cnpj_basico"] + e["cnpj_ordem"] + e["cnpj_dv"]),
        "cnpj_basico": e["cnpj_basico"].upper(),
        "razao": emp.get("razao"),
        "nome_fantasia": e.get("nome_fantasia") or None,
        "matriz": 1 if e.get("matriz_filial") == "1" else 0,
        "situacao": SITUACOES.get(e.get("situacao", ""), e.get("situacao") or None),
        "data_situacao": data_iso(e.get("data_situacao")),
        "motivo": codigos.get("Motivos", {}).get(e.get("motivo", ""), e.get("motivo") or None),
        "data_abertura": data_iso(e.get("data_abertura")),
        "natureza": codigos.get("Naturezas", {}).get(emp.get("natureza", ""), emp.get("natureza") or None),
        "porte": PORTES.get(emp.get("porte", ""), emp.get("porte") or None),
        "capital_social": capital(emp.get("capital_social")),
        "cnae_principal": e.get("cnae_principal") or None,
        "cnaes_secundarios": ",".join(sec),
        "municipio": municipio,
        "uf": e.get("uf"),
        "endereco": endereco(e.get("tipo_logradouro"), e.get("logradouro"), e.get("numero"), e.get("complemento"),
                             e.get("bairro"), e.get("cep"), municipio, e.get("uf")),
        "logradouro": _norm(f"{e.get('tipo_logradouro', '')} {e.get('logradouro', '')}"),
        "numero": _norm(e.get("numero")),
        "complemento": _norm(e.get("complemento")),
        "bairro": _norm(e.get("bairro")),
        "cep": re.sub(r"\D", "", e.get("cep") or ""),
        "telefone": ",".join(tel),
        "email": (e.get("email") or "").strip().lower() or None,
        "simples": s.get("opcao_simples") or None,
        "data_opcao_simples": data_iso(s.get("data_opcao_simples")),
        "data_exclusao_simples": data_iso(s.get("data_exclusao_simples")),
        "mei": s.get("opcao_mei") or None,
        "data_opcao_mei": data_iso(s.get("data_opcao_mei")),
        "data_exclusao_mei": data_iso(s.get("data_exclusao_mei")),
        "fonte": fonte, "data_base": data_base, "consultado_em": hoje,
    }


def _registro_socio(cnpj: str, s: dict, codigos: dict, fonte: str, data_base: str | None) -> dict:
    qual = codigos.get("Qualificacoes", {})
    return {
        "cnpj": cnpj, "nome": _norm(s.get("nome")) or None, "cpf_cnpj": (s.get("cpf_cnpj") or "").strip() or None,
        "identificador": IDENTIFICADOR_SOCIO.get(s.get("identificador", ""), s.get("identificador") or None),
        "qualificacao": qual.get(s.get("qualificacao", ""), s.get("qualificacao") or None),
        "data_entrada": data_iso(s.get("data_entrada")),
        "representante": _norm(s.get("representante")) or None,
        "representante_cpf": (s.get("representante_cpf") or "").strip() or None,
        "qualificacao_representante": qual.get(s.get("qualificacao_representante", ""),
                                               s.get("qualificacao_representante") or None),
        "faixa_etaria": (s.get("faixa_etaria") or "").strip() or None,
        "fonte": fonte, "data_base": data_base,
    }


def montar(cnpjs: Iterable[str], *, empresas: Iterable[dict], estabelecimentos: Iterable[dict],
           socios: Iterable[dict], simples: Iterable[dict], codigos: dict[str, dict[str, str]],
           fonte: str = FONTE_BASE, data_base: str | None = None, hoje: str | None = None,
           completa: bool = True) -> Cadastro:
    """Junta as linhas já filtradas dos quatro arquivos no registro de cada CNPJ procurado.
    Com ``completa`` (a base inteira foi lida), o CNPJ procurado que não apareceu vira ausente."""
    hoje = hoje or date.today().isoformat()
    alvo = {so_cnpj(c) for c in cnpjs}
    emp = {e["cnpj_basico"].upper(): e for e in empresas}
    simp = {s["cnpj_basico"].upper(): s for s in simples}
    out = Cadastro(codigos=codigos, fonte=fonte, data_base=data_base, completa=completa)
    for e in estabelecimentos:
        cnpj = so_cnpj(e["cnpj_basico"] + e["cnpj_ordem"] + e["cnpj_dv"])
        if cnpj in alvo:
            out.empresas[cnpj] = _registro_estabelecimento(e, emp.get(e["cnpj_basico"].upper()),
                                                           simp.get(e["cnpj_basico"].upper()), codigos,
                                                           fonte, data_base, hoje)
    por_basico: dict[str, list[str]] = {}
    for c in out.empresas:
        por_basico.setdefault(c[:8], []).append(c)
    for s in socios:
        for cnpj in por_basico.get(s["cnpj_basico"].upper(), []):
            out.socios.append(_registro_socio(cnpj, s, codigos, fonte, data_base))
    if completa:
        for c in sorted(alvo - set(out.empresas)):
            out.ausentes[c] = "não consta na base mensal da Receita"
    return out


def coletar_base(cnpjs: Iterable[str], *, mes: str, porta: Porta, pasta: Path,
                 baixar_url: Callable = baixar, listar_url: Callable = listar,
                 registrar: Callable[[str, bool, int, str], None] = lambda *a: None,
                 hoje: str | None = None) -> Cadastro:
    """Lê a pasta mensal inteira da porta, um zip por vez, e devolve o cadastro filtrado.
    ``registrar(url, ok, bytes, erro)`` anota cada arquivo (o motor grava em ``coletas``)."""
    alvo = {so_cnpj(c) for c in cnpjs if cnpj_valido(c)}
    basicos = {c[:8] for c in alvo}
    pasta.mkdir(parents=True, exist_ok=True)
    listagem, erro = listar_url(porta, f"{mes}/")
    arquivos = arquivos_da_listagem(listagem) if listagem else []
    if not arquivos:      # sem listagem: os nomes do layout oficial
        arquivos = ([f"{n}{i}.zip" for n in ("Empresas", "Estabelecimentos", "Socios") for i in range(10)]
                    + ["Simples.zip"] + [f"{t}.zip" for t in TABELAS_DE_CODIGOS])
    codigos: dict[str, dict[str, str]] = {}
    empresas: list[dict] = []
    estabelecimentos: list[dict] = []
    socios: list[dict] = []
    simples: list[dict] = []
    erros: list[str] = [f"listagem de {mes}: {erro}"] if erro else []
    faltou_essencial = False

    def ordem(nome: str) -> int:       # as tabelas de códigos primeiro, depois os grandes
        for i, prefixo in enumerate((*TABELAS_DE_CODIGOS, "Simples", "Empresas", "Socios", "Estabelecimentos")):
            if nome.startswith(prefixo):
                return i
        return 99

    for nome in sorted(arquivos, key=lambda n: (ordem(n), n)):
        url = porta.url(mes, nome)
        destino = pasta / nome
        ok, tamanho, erro = baixar_url(url, destino, cabecalhos=porta.cabecalhos)
        registrar(url, ok, tamanho, erro)
        if not ok:
            erros.append(f"{nome}: {erro}")
            if nome.startswith(("Empresas", "Estabelecimentos", "Socios", "Simples")):
                faltou_essencial = True
            continue
        try:
            tabela = next((t for t in TABELAS_DE_CODIGOS if nome.startswith(t)), None)
            if tabela:
                codigos[tabela] = codigos_do_zip(destino)
            elif nome.startswith("Empresas"):
                empresas.extend(linhas_do_zip(destino, EMPRESAS, basicos))
            elif nome.startswith("Estabelecimentos"):
                estabelecimentos.extend(linhas_do_zip(destino, ESTABELECIMENTOS, basicos))
            elif nome.startswith("Socios"):
                socios.extend(linhas_do_zip(destino, SOCIOS, basicos))
            elif nome.startswith("Simples"):
                simples.extend(linhas_do_zip(destino, SIMPLES, basicos))
        except (zipfile.BadZipFile, UnicodeDecodeError, csv.Error) as e:
            erros.append(f"{nome}: formato: {e}")
            faltou_essencial = faltou_essencial or not tabela
        finally:
            destino.unlink(missing_ok=True)
    cad = montar(alvo, empresas=empresas, estabelecimentos=estabelecimentos, socios=socios, simples=simples,
                 codigos=codigos, fonte=FONTE_BASE, data_base=mes, hoje=hoje, completa=not faltou_essencial)
    cad.erros = erros
    return cad


# --- Via secundária: um CNPJ por vez ---------------------------------------------------------------

def url_brasilapi(cnpj: str) -> str:
    return BRASILAPI + so_cnpj(cnpj)


def url_minhareceita(cnpj: str) -> str:
    return MINHARECEITA + so_cnpj(cnpj)


def _txt(d: dict, *chaves) -> str:
    for k in chaves:
        v = d.get(k)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def de_api(conteudo: bytes | str | dict, *, fonte: str = FONTE_BRASILAPI,
           hoje: str | None = None) -> tuple[dict, list[dict]]:
    """A resposta da BrasilAPI ou da minhareceita (mesmo esquema) no registro do banco.
    Levanta ``ValueError`` se a resposta não é o cadastro de um CNPJ."""
    d = conteudo if isinstance(conteudo, dict) else json.loads(conteudo)
    cnpj = so_cnpj(d.get("cnpj"))
    if not cnpj_valido(cnpj):
        raise ValueError("a resposta não traz um CNPJ válido")
    hoje = hoje or date.today().isoformat()
    data_base = _txt(d, "data_base", "atualizado_em", "data_atualizacao") or None
    sec = d.get("cnaes_secundarios") or []
    codigos_sec = [str(c.get("codigo")) for c in sec if isinstance(c, dict) and c.get("codigo")]
    situacao = _txt(d, "descricao_situacao_cadastral").upper() or \
        SITUACOES.get(_txt(d, "situacao_cadastral"), _txt(d, "situacao_cadastral") or "")
    tel = [re.sub(r"\D", "", _txt(d, k)) for k in ("ddd_telefone_1", "ddd_telefone_2")]
    natureza = _txt(d, "natureza_juridica")
    if not natureza and d.get("codigo_natureza_juridica"):
        natureza = str(d["codigo_natureza_juridica"])
    municipio = _txt(d, "municipio")
    registro = {
        "cnpj": cnpj, "cnpj_basico": cnpj[:8], "razao": _norm(_txt(d, "razao_social")) or None,
        "nome_fantasia": _norm(_txt(d, "nome_fantasia")) or None,
        "matriz": 1 if _txt(d, "identificador_matriz_filial", "descricao_identificador_matriz_filial")
        in ("1", "MATRIZ") else 0,
        "situacao": _norm(situacao) or None,
        "data_situacao": data_iso(_txt(d, "data_situacao_cadastral")),
        "motivo": _txt(d, "descricao_motivo_situacao_cadastral", "motivo_situacao_cadastral") or None,
        "data_abertura": data_iso(_txt(d, "data_inicio_atividade")),
        "natureza": natureza or None,
        "porte": _norm(_txt(d, "porte", "descricao_porte")) or PORTES.get(_txt(d, "codigo_porte")) or None,
        "capital_social": capital(d.get("capital_social")) if not isinstance(d.get("capital_social"), (int, float))
        else float(d["capital_social"]),
        "cnae_principal": _txt(d, "cnae_fiscal") or None,
        "cnaes_secundarios": ",".join(codigos_sec),
        "municipio": _norm(municipio) or None, "uf": _txt(d, "uf") or None,
        "endereco": endereco(_txt(d, "descricao_tipo_de_logradouro"), _txt(d, "logradouro"), _txt(d, "numero"),
                             _txt(d, "complemento"), _txt(d, "bairro"), _txt(d, "cep"), municipio, _txt(d, "uf")),
        "logradouro": _norm(f"{_txt(d, 'descricao_tipo_de_logradouro')} {_txt(d, 'logradouro')}"),
        "numero": _norm(_txt(d, "numero")), "complemento": _norm(_txt(d, "complemento")),
        "bairro": _norm(_txt(d, "bairro")), "cep": re.sub(r"\D", "", _txt(d, "cep")),
        "telefone": ",".join(t for t in tel if len(t) >= 8),
        "email": _txt(d, "email").lower() or None,
        "simples": _sn(d.get("opcao_pelo_simples")),
        "data_opcao_simples": data_iso(_txt(d, "data_opcao_pelo_simples")),
        "data_exclusao_simples": data_iso(_txt(d, "data_exclusao_do_simples")),
        "mei": _sn(d.get("opcao_pelo_mei")),
        "data_opcao_mei": data_iso(_txt(d, "data_opcao_pelo_mei")),
        "data_exclusao_mei": data_iso(_txt(d, "data_exclusao_do_mei")),
        "fonte": fonte, "data_base": data_base, "consultado_em": hoje,
    }
    socios = []
    for s in d.get("qsa") or []:
        if not isinstance(s, dict):
            continue
        ident = _txt(s, "identificador_de_socio")
        socios.append({
            "cnpj": cnpj, "nome": _norm(_txt(s, "nome_socio")) or None,
            "cpf_cnpj": _txt(s, "cnpj_cpf_do_socio") or None,
            "identificador": IDENTIFICADOR_SOCIO.get(ident, ident.upper() or None),
            "qualificacao": _txt(s, "qualificacao_socio") or _txt(s, "codigo_qualificacao_socio") or None,
            "data_entrada": data_iso(_txt(s, "data_entrada_sociedade")),
            "representante": _norm(_txt(s, "nome_representante_legal")) or None,
            "representante_cpf": _txt(s, "cpf_representante_legal") or None,
            "qualificacao_representante": _txt(s, "qualificacao_representante_legal") or None,
            "faixa_etaria": _txt(s, "codigo_faixa_etaria") or None,
            "fonte": fonte, "data_base": data_base,
        })
    return registro, socios


def _sn(v) -> str | None:
    if v is True:
        return "S"
    if v is False:
        return "N"
    t = _norm(v)
    return {"S": "S", "SIM": "S", "N": "N", "NAO": "N"}.get(t) if t else None


# --- Gravação ------------------------------------------------------------------------------------

def preparar(con) -> None:
    con.executescript(ESQUEMA)


def gravar(con, cad: Cadastro) -> None:
    """Grava o cadastro: a empresa e o QSA de cada CNPJ são substituídos pelo mais novo, e o
    histórico guarda em que base cada razão social e cada CNAE apareceram pela primeira vez."""
    preparar(con)
    for cnpj, reg in cad.empresas.items():
        con.execute("DELETE FROM cnpj_socios WHERE cnpj = ?", (cnpj,))
        con.execute("DELETE FROM cnpj_ausentes WHERE cnpj = ?", (cnpj,))
        colunas = ", ".join(reg)
        con.execute(f"INSERT OR REPLACE INTO cnpj_empresas ({colunas}) VALUES ({', '.join('?' * len(reg))})",
                    list(reg.values()))
        base = reg.get("data_base") or reg.get("consultado_em")
        valores = [("razao", reg.get("razao")), ("situacao", reg.get("situacao"))]
        valores += [("cnae", c) for c in [reg.get("cnae_principal"), *(reg.get("cnaes_secundarios") or "").split(",")]
                    if c]
        for campo, valor in valores:
            if not valor:
                continue
            con.execute("INSERT OR IGNORE INTO cnpj_historico VALUES (?, ?, ?, ?, ?)",
                        (cnpj, campo, valor, base, base))
            con.execute("UPDATE cnpj_historico SET ultima_base = max(ultima_base, ?), "
                        "primeira_base = min(primeira_base, ?) WHERE cnpj = ? AND campo = ? AND valor = ?",
                        (base, base, cnpj, campo, valor))
    for s in cad.socios:
        con.execute(f"INSERT INTO cnpj_socios ({', '.join(s)}) VALUES ({', '.join('?' * len(s))})",
                    list(s.values()))
    for tabela, codigos in cad.codigos.items():
        for codigo, descricao in codigos.items():
            con.execute("INSERT OR REPLACE INTO cnpj_codigos VALUES (?, ?, ?, ?)",
                        (tabela, codigo, descricao, cad.data_base))
    for cnpj, motivo in cad.ausentes.items():
        con.execute("INSERT OR REPLACE INTO cnpj_ausentes VALUES (?, ?, ?, ?)",
                    (cnpj, cad.fonte, cad.data_base, motivo))
    con.commit()


def cnpjs_do_banco(con) -> list[str]:
    """Os CNPJs (14 posições, dígito conferido) dos fornecedores dos contratos e dos itens do PNCP."""
    achados: set[str] = set()
    for tabela, coluna in (("contratos_pncp", "fornecedor_ni"), ("pncp_itens", "fornecedor_ni")):
        try:
            for (ni,) in con.execute(f"SELECT DISTINCT {coluna} FROM {tabela}"):
                c = so_cnpj(ni)
                if len(c) == 14 and cnpj_valido(c):
                    achados.add(c)
        except Exception:  # noqa: BLE001 (tabela ausente num banco antigo)
            continue
    return sorted(achados)
