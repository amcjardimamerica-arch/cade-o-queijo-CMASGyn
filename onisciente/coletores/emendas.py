"""Emendas parlamentares: o arquivo único do Portal da Transparência, lido em fluxo e filtrado pelo Município.

O arquivo (``download-de-dados/emendas-parlamentares/UNICO``) é um zip de uns 47 MB com seis planilhas
(400 MB descompactadas). Nada dele fica guardado: o zip é lido do fluxo HTTP pelos cabeçalhos locais de
cada membro, descompactado aos pedaços e cada linha passa por um filtro barato (o código IBGE, o CNPJ ou
o nome do Município nos bytes) antes do CSV. Só as linhas do Município chegam ao banco.

Pessoas físicas favorecidas (a planilha ``PorFavorecido`` traz bolsistas e prestadores com CPF mascarado)
não são guardadas: o que interessa ao parecer é o ente, a entidade e a empresa.
"""
from __future__ import annotations

import csv
import io
import json
import struct
import unicodedata
import urllib.request
import zlib
from collections.abc import Callable, Iterable, Iterator

URL = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"

LOCAL = b"PK\x03\x04"
CENTRAL = (b"PK\x01\x02", b"PK\x05\x06", b"PK\x06\x06", b"PK\x06\x07")
DESCRITOR = b"PK\x07\x08"
BLOCO = 1 << 16

# As planilhas conhecidas (o nome do membro sem o prefixo "EmendasParlamentares").
EMENDAS, CONVENIOS, PARCERIAS, PLANO_PARCERIAS, PLANO_ESPECIAIS, FAVORECIDOS = (
    "emendas", "convenios", "parcerias", "plano_parcerias", "plano_especiais", "favorecidos")
PLANILHAS = {
    "EmendasParlamentares.csv": EMENDAS,
    "EmendasParlamentares_Convenios.csv": CONVENIOS,
    "EmendasParlamentares_Parcerias.csv": PARCERIAS,
    "EmendasParlamentares_PlanodeTrabalhoParcerias.csv": PLANO_PARCERIAS,
    "EmendasParlamentares_PlanodeTrabalhoTransferenciasEspeciais.csv": PLANO_ESPECIAIS,
    "EmendasParlamentares_PorFavorecido.csv": FAVORECIDOS,
}


class Formato(ValueError):
    """O fluxo não é o zip esperado (ou uma planilha mudou de cabeçalho)."""


def normalizar(texto: str) -> str:
    sem = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sem.upper().split())


def _valor(texto: str) -> float | None:
    t = (texto or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


# --- o zip em fluxo ---------------------------------------------------------------------------

class _Fluxo:
    """Um leitor com devolução: o que a descompressão leu além do membro volta para o próximo."""

    def __init__(self, fonte):
        self.fonte = fonte
        self.sobra = b""
        self.lidos = 0

    def ler(self, n: int) -> bytes:
        if self.sobra:
            parte, self.sobra = self.sobra[:n], self.sobra[n:]
            return parte
        parte = self.fonte.read(n) or b""
        self.lidos += len(parte)
        return parte

    def exato(self, n: int) -> bytes:
        partes, falta = [], n
        while falta:
            p = self.ler(falta)
            if not p:
                break
            partes.append(p)
            falta -= len(p)
        return b"".join(partes)

    def devolver(self, dados: bytes) -> None:
        self.sobra = dados + self.sobra


def membros(fonte) -> Iterator[tuple[str, Iterator[bytes]]]:
    """Cada membro do zip lido em sequência de um fluxo: (nome, pedaços descompactados).

    Funciona sem o diretório central (que fica no fim): usa o cabeçalho local de cada membro, e o fim
    do fluxo deflate marca o fim dos dados (também quando o tamanho só vem no descritor depois deles).
    Cada iterador de pedaços deve ser consumido (ou abandonado) antes de pedir o próximo membro.
    """
    f = _Fluxo(fonte)
    while True:
        assinatura = f.exato(4)
        if not assinatura or assinatura in CENTRAL:
            return
        if assinatura != LOCAL:
            raise Formato(f"assinatura inesperada no zip: {assinatura!r}")
        cab = f.exato(26)
        if len(cab) < 26:
            raise Formato("zip cortado no cabeçalho de um membro")
        (_versao, bandeiras, metodo, _hora, _dia, _crc, comprimido, _tamanho,
         n_nome, n_extra) = struct.unpack("<HHHHHIIIHH", cab)
        nome = f.exato(n_nome).decode("cp437" if not bandeiras & 0x800 else "utf-8", "replace")
        extra = f.exato(n_extra)
        if comprimido == 0xFFFFFFFF:
            comprimido = _zip64(extra) or comprimido
        consumido = {"fim": False}

        def pedacos(metodo=metodo, comprimido=comprimido, bandeiras=bandeiras, consumido=consumido):
            if metodo == 8:
                d = zlib.decompressobj(-15)
                while not d.eof:
                    bruto = f.ler(BLOCO)
                    if not bruto:
                        raise Formato("zip cortado no meio de um membro")
                    saida = d.decompress(bruto)
                    if saida:
                        yield saida
                if d.unused_data:
                    f.devolver(d.unused_data)
            elif metodo == 0:
                if bandeiras & 0x08:
                    raise Formato("membro sem compressão e sem tamanho no cabeçalho")
                falta = comprimido
                while falta:
                    bruto = f.ler(min(BLOCO, falta))
                    if not bruto:
                        raise Formato("zip cortado no meio de um membro")
                    falta -= len(bruto)
                    yield bruto
            else:
                raise Formato(f"método de compressão {metodo} não suportado")
            if bandeiras & 0x08:
                _pular_descritor(f)
            consumido["fim"] = True

        it = pedacos()
        yield nome, it
        if not consumido["fim"]:
            for _ in it:                          # o membro não lido é descartado, sem guardar
                pass


def _zip64(extra: bytes) -> int | None:
    i = 0
    while i + 4 <= len(extra):
        tipo, tam = struct.unpack("<HH", extra[i:i + 4])
        if tipo == 0x0001 and tam >= 16:
            return struct.unpack("<Q", extra[i + 12:i + 20])[0]
        i += 4 + tam
    return None


def _pular_descritor(f: _Fluxo) -> None:
    inicio = f.exato(4)
    if inicio == DESCRITOR:
        f.exato(12)
    else:
        f.devolver(inicio)
        f.exato(12)
    # zip64 teria 8 bytes a mais; o próximo cabeçalho diz se sobrou algo
    proximo = f.exato(4)
    if proximo and proximo != LOCAL and proximo not in CENTRAL:
        f.exato(4)
    else:
        f.devolver(proximo)


def registros(pedacos: Iterable[bytes], aceita_bruto: Callable[[bytes], bool] | None = None,
              codificacao: str = "latin-1") -> Iterator[dict]:
    """As linhas de um CSV do Portal (``;``, aspas) a partir dos pedaços descompactados.

    ``aceita_bruto`` decide pelos bytes de cada registro, antes de montar o dicionário: é o filtro
    barato que deixa a leitura dos 400 MB em segundos.
    """
    cabeca: list[str] | None = None
    resto = b""
    pendente = b""                       # registro com quebra de linha dentro das aspas
    for parte in pedacos:
        bloco = resto + parte
        linhas = bloco.split(b"\n")
        resto = linhas.pop()
        for linha in linhas:
            linha = pendente + linha + b"\n"
            if linha.count(b'"') % 2:
                pendente = linha
                continue
            pendente = b""
            if cabeca is None:
                cabeca = next(csv.reader([linha.decode(codificacao).strip("\r\n")], delimiter=";"))
                continue
            if aceita_bruto is not None and not aceita_bruto(linha):
                continue
            campos = next(csv.reader(io.StringIO(linha.decode(codificacao)), delimiter=";"), [])
            if campos:
                yield dict(zip(cabeca, campos))
    final = pendente + resto
    if final.strip() and cabeca is not None and (aceita_bruto is None or aceita_bruto(final)):
        campos = next(csv.reader(io.StringIO(final.decode(codificacao)), delimiter=";"), [])
        if campos:
            yield dict(zip(cabeca, campos))


# --- o filtro do Município ------------------------------------------------------------------------

class Filtro:
    """O que é do Município em cada planilha. Cada uma diz o lugar de um jeito: código IBGE, a
    "Localidade" em texto, a UF e o nome, ou o CNPJ do beneficiário."""

    def __init__(self, municipio: str, uf: str, ibge7: str | int, cnpjs: Iterable[str] = ()):
        self.nome = normalizar(municipio)
        self.uf = normalizar(uf)
        self.ibge7 = str(ibge7)
        self.cnpjs = {c for c in cnpjs if c}
        variantes = {municipio.upper(), self.nome}
        self.agulhas = [v.encode("latin-1", "ignore") for v in variantes if v] + [self.ibge7.encode()]
        self.agulhas += [c.encode() for c in self.cnpjs]

    def bruto(self, linha: bytes) -> bool:
        return any(a in linha for a in self.agulhas)

    def aceita(self, planilha: str, r: dict) -> bool:
        if planilha == EMENDAS:
            return r.get("Código Município IBGE", "").strip() == self.ibge7
        if planilha == CONVENIOS:
            return normalizar(r.get("Localidade do gasto", "")) == f"{self.nome} - {self.uf}"
        if planilha in (PARCERIAS, PLANO_PARCERIAS):
            return (normalizar(r.get("UF", "")) == self.uf
                    and normalizar(r.get("Município", "")) == self.nome)
        if planilha == PLANO_ESPECIAIS:
            if r.get("CNPJ do Beneficiário", "").strip() in self.cnpjs:
                return True
            return (normalizar(r.get("UF do Beneficiário", "")) == self.uf
                    and normalizar(r.get("Beneficiário", "")) in (f"MUNICIPIO DE {self.nome}",
                                                                   f"PREFEITURA MUNICIPAL DE {self.nome}"))
        if planilha == FAVORECIDOS:
            return (normalizar(r.get("UF Favorecido", "")) == self.uf
                    and normalizar(r.get("Município Favorecido", "")) == self.nome
                    and normalizar(r.get("Tipo Favorecido", "")) != "PESSOA FISICA")
        return False


def linha(planilha: str, r: dict) -> dict:
    """Um registro de qualquer planilha na forma da tabela ``emendas_municipio``."""
    g = r.get
    if planilha == EMENDAS:
        return {"emenda": g("Código da Emenda"), "ano": g("Ano da Emenda"), "tipo": g("Tipo de Emenda"),
                "autor": g("Nome do Autor da Emenda"), "cnpj": None, "nome": g("Localidade de aplicação do recurso"),
                "situacao": None, "objeto": f"{g('Nome Função', '')} / {g('Nome Ação', '')}".strip(" /"),
                "referencia": g("Código Ação"), "valor_empenhado": _valor(g("Valor Empenhado", "")),
                "valor_liquidado": _valor(g("Valor Liquidado", "")), "valor_pago": _valor(g("Valor Pago", "")),
                "valor": _valor(g("Valor Restos A Pagar Pagos", ""))}
    if planilha == CONVENIOS:
        return {"emenda": g("Código da Emenda"), "ano": (g("Data Publicação Convênio") or "")[-4:] or None,
                "tipo": g("Tipo de Emenda"), "autor": None, "cnpj": None, "nome": g("Convenente"),
                "situacao": None, "objeto": g("Objeto Convênio"), "referencia": g("Número Convênio"),
                "valor": _valor(g("Valor Convênio", ""))}
    if planilha == PARCERIAS:
        return {"emenda": g("Emenda Parlamentar"), "ano": (g("Emenda Parlamentar") or "")[:4] or None,
                "tipo": None, "autor": g("Autor da Emenda"), "cnpj": g("CNPJ Beneficiário (Ente Recebedor)"),
                "nome": g("Beneficiário (Ente Recebedor)"), "situacao": g("Situação da Parceria"),
                "objeto": g("Objeto"), "referencia": g("Código da Parceria"), "valor": _valor(g("Valor (R$)", ""))}
    if planilha == PLANO_PARCERIAS:
        return {"emenda": None, "ano": (g("Código da Parceria") or "")[:4] or None, "tipo": None, "autor": None,
                "cnpj": g("CNPJ Beneficiário (Ente Recebedor)"), "nome": g("Beneficiário (Ente Recebedor)"),
                "situacao": g("Situação da Parceria"), "objeto": f"{g('Etapa', '')} / {g('Item', '')}".strip(" /"),
                "referencia": g("Código da Parceria"), "valor": _valor(g("Valor do Item (R$)", ""))}
    if planilha == PLANO_ESPECIAIS:
        return {"emenda": g("Emenda Parlamentar"), "ano": (g("Emenda Parlamentar") or "")[:4] or None,
                "tipo": "Transferência especial", "autor": g("Autor da Emenda"), "cnpj": g("CNPJ do Beneficiário"),
                "nome": g("Beneficiário"),
                "situacao": f"{g('Situação do Plano de Trabalho', '')} / {g('Situação do Plano de Ação', '')}".strip(" /"),
                "objeto": g("Detalhamento do Objeto"), "referencia": g("Plano de Ação"), "valor": _valor(g("Valor", ""))}
    if planilha == FAVORECIDOS:
        return {"emenda": g("Código da Emenda"), "ano": (g("Ano/Mês") or "")[:4] or None, "mes": g("Ano/Mês"),
                "tipo": g("Tipo de Emenda"), "autor": g("Nome do Autor da Emenda"), "cnpj": g("Código do Favorecido"),
                "nome": g("Favorecido"), "situacao": g("Natureza Jurídica"), "objeto": None, "referencia": None,
                "valor": _valor(g("Valor Recebido", ""))}
    raise Formato(f"planilha desconhecida: {planilha}")


def filtrar(fonte, filtro: Filtro) -> Iterator[tuple[str, dict]]:
    """(planilha, linha da tabela) do Município, lendo o zip do fluxo ``fonte`` uma vez só."""
    vistas = set()
    for nome, pedacos in membros(fonte):
        planilha = PLANILHAS.get(nome.rsplit("/", 1)[-1])
        if planilha is None:
            continue                               # membro novo: descartado (o motor avisa)
        vistas.add(planilha)
        for r in registros(pedacos, filtro.bruto):
            if filtro.aceita(planilha, r):
                saida = {"planilha": planilha, "mes": None, "valor_empenhado": None, "valor_liquidado": None,
                         "valor_pago": None, **linha(planilha, r)}
                saida["ano"] = int(saida["ano"]) if str(saida.get("ano") or "").isdigit() else None
                saida["json"] = json.dumps(r, ensure_ascii=False)
                yield planilha, saida
    if not vistas:
        raise Formato("nenhuma planilha de emendas conhecida no arquivo")


def abrir(url: str, tempo: int = 300):
    """O fluxo HTTP do arquivo (fechado por quem o usa). Levanta ``urllib.error`` em falha."""
    from .base import AGENTE
    pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    return urllib.request.urlopen(pedido, timeout=tempo)


class Contador:
    """Envolve o fluxo e conta os bytes que passaram (para o registro da coleta)."""

    def __init__(self, fonte):
        self.fonte = fonte
        self.bytes = 0
        self.status = getattr(fonte, "status", None)

    def read(self, n: int = -1) -> bytes:
        parte = self.fonte.read(n)
        self.bytes += len(parte or b"")
        return parte


__all__ = [
    "PLANILHAS",
    "URL",
    "Contador",
    "Filtro",
    "Formato",
    "abrir",
    "filtrar",
    "linha",
    "membros",
    "registros",
]
