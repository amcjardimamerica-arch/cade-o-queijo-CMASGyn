"""Máscara de CPF de pessoa física nos arquivos que o Onisciente grava (a sondagem, num repositório público).

O CPF completo de pessoa física não fica gravado: vira ``***.NNN.NNN-**``, com os seis dígitos do meio,
como o Portal da Transparência mostra. CNPJ fica como está. Acham-se:

- o CPF formatado (``NNN.NNN.NNN-NN``) em qualquer lugar do texto;
- 11 dígitos no valor de um campo de documento: chave JSON com ``cpf`` ou ``documento`` no nome (``cpf``,
  ``nuCpf``, ``cpfCnpj``, ``nuDocumento``), parâmetro de endereço com ``cpf`` no nome e elemento XML com
  ``cpf`` no nome;
- 11 dígitos nas colunas de documento de um CSV (cabeçalho com ``CPF``, ``CNPJ``, ``DOCUMENTO`` ou
  ``CÓDIGO DO FAVORECIDO``, como ``CPF OU CNPJ DO SANCIONADO``), e o CPF com ``000`` na frente que a
  coluna ``CNPJ`` da despesa de Goiânia traz para pessoa física (14 dígitos que não são CNPJ válido e
  cujos 11 últimos são CPF válido).

Onze dígitos soltos fora desses campos (telefone, processo, NIS) não são tocados. A máscara não se aplica
de novo ao que já está mascarado. ``mascarar_zip`` faz o mesmo dentro de cada arquivo de texto de um ZIP
(também um ``.xlsx``), e ``cpfs_completos`` acha o que a máscara trocaria (é o que a trava procura).
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile

# Antes do CPF não pode vir dígito nem asterisco (já mascarado), nem "dígito e ponto" (o meio de um número
# maior). Um ponto depois de letra, como em "CPF SOB O N.598.819.251-34", não protege o CPF (28/11/2026).
_FORMATADO = re.compile(r"(?<![\d*])(?<!\d\.)\d{3}\.(\d{3})\.(\d{3})-\d{2}(?!\d)")
# O valor de 11 dígitos de um campo de documento: chave JSON, parâmetro de endereço ou elemento XML. A busca
# começa pelo nome do campo (rápida em arquivos grandes) e o resto do nome vem depois dele.
_CAMPO = re.compile(
    r"(?i)(?:cpf|documento|codigofavorecido)"
    r'(?:(\w*"\s*:\s*)"?(\d{11})"?(?=\s*[,}\]\n])'      # "nuCpf": "12345678901"
    r"|(\w*=)(\d{11})(?!\d)"                              # cpf=12345678901
    r"|([\w:.-]*>\s*)(\d{11})(?=\s*</))")                 # <cpf>12345678901</cpf>
_DELIMITADORES = (";", ",", "\t", "|")
# Colunas de documento num CSV (sem acento, em maiúsculas).
_COLUNAS = ("CPF", "CNPJ", "DOCUMENTO", "CODIGO DO FAVORECIDO")


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().upper()


def mascara(cpf: str) -> str:
    """``***.NNN.NNN-**`` de um CPF (formatado ou só dígitos)."""
    d = re.sub(r"\D", "", cpf)
    return f"***.{d[3:6]}.{d[6:9]}-**"


def _campos(linha: str, delim: str) -> list[tuple[int, int]]:
    """Onde começa e termina cada campo de uma linha de CSV (aspas respeitadas)."""
    if '"' not in linha or (linha.startswith('"') and linha.rstrip("\r").endswith('"')
                            and linha.count('"') == 2 * (linha.count(f'"{delim}"') + 1)):
        sep = 1 if '"' not in linha else 3              # o separador entre aspas é "{delim}"
        partes = linha.split(delim if sep == 1 else f'"{delim}"')
        spans, inicio = [], 0
        for parte in partes:
            spans.append((inicio, inicio + len(parte)))
            inicio += len(parte) + sep
        if sep == 3:                                    # as aspas das pontas ficam no primeiro e no último
            spans = [(a - (1 if i else 0), b + (1 if i < len(spans) - 1 else 0)) for i, (a, b) in enumerate(spans)]
        return spans
    spans, inicio, aspas = [], 0, False
    for i, c in enumerate(linha):
        if c == '"':
            aspas = not aspas
        elif c == delim and not aspas:
            spans.append((inicio, i))
            inicio = i + 1
    spans.append((inicio, len(linha)))
    return spans


def _cpf_valido(d: str) -> bool:
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for k in (9, 10):
        if (sum(int(d[i]) * (k + 1 - i) for i in range(k)) * 10) % 11 % 10 != int(d[k]):
            return False
    return True


def _cnpj_valido(d: str) -> bool:
    if len(d) != 14 or len(set(d)) == 1:
        return False
    for k in (12, 13):
        pesos = list(range(k - 7, 1, -1)) + list(range(9, 1, -1))
        resto = sum(int(x) * p for x, p in zip(d[:k], pesos, strict=True)) % 11
        if (0 if resto < 2 else 11 - resto) != int(d[k]):
            return False
    return True


def _cpf_da_coluna(valor: str) -> str | None:
    """O CPF de um valor de coluna de documento: 11 dígitos, ou o CPF com ``000`` na frente que a coluna
    CNPJ da despesa de Goiânia traz para pessoa física (14 dígitos que não são CNPJ válido e cujos 11
    últimos são um CPF válido). CNPJ fica de fora."""
    if not valor.isdigit():
        return None
    if len(valor) == 11:
        return valor
    if len(valor) == 14 and valor.startswith("000") and not _cnpj_valido(valor) and _cpf_valido(valor[3:]):
        return valor[3:]
    return None


def _cabecalho(linha: str) -> tuple[str, list[int]] | None:
    if len(linha) > 4000 or not any(c in _sem_acento(linha) for c in _COLUNAS):
        return None
    for delim in _DELIMITADORES:
        partes = [_sem_acento(linha[a:b].strip().strip('"')) for a, b in _campos(linha, delim)]
        if len(partes) >= 2:
            colunas = [i for i, p in enumerate(partes) if any(c in p for c in _COLUNAS)]
            if colunas and all(len(p) < 80 for p in partes):
                return delim, colunas
    return None


def _csv(texto: str) -> tuple[str, int]:
    maiusculo = texto.upper()
    if not any(c in maiusculo for c in ("CPF", "CNPJ", "DOCUMENTO", "FAVORECIDO")):
        return texto, 0                                 # nenhuma coluna de documento possível
    linhas = texto.split("\n")
    trocas, atual = 0, None
    for n, linha in enumerate(linhas):
        spans = _campos(linha, atual[0]) if atual else []
        if not atual or len(spans) != atual[2]:      # linha da tabela atual não é cabeçalho novo
            cab = _cabecalho(linha)
            if cab:
                atual = (cab[0], cab[1], len(_campos(linha, cab[0])))
            continue
        colunas = atual[1]
        nova, deslocamento = linha, 0
        for c in colunas:
            a, b = spans[c]
            valor = linha[a:b].strip().strip('"').strip()
            cpf = _cpf_da_coluna(valor)
            if cpf:
                trecho = linha[a:b].replace(valor, mascara(cpf), 1)
                nova = nova[:a + deslocamento] + trecho + nova[b + deslocamento:]
                deslocamento += len(trecho) - (b - a)
                trocas += 1
        linhas[n] = nova
    return "\n".join(linhas), trocas


def _trocar_campo(m: re.Match) -> str:
    inteiro, inicio = m.group(0), m.start()
    if m.group(2):
        return inteiro[:m.start(1) - inicio] + m.group(1) + f'"{mascara(m.group(2))}"'
    for g in (4, 6):
        if m.group(g):
            return inteiro[:m.start(g) - inicio] + mascara(m.group(g))
    return inteiro


def mascarar_texto(texto: str) -> tuple[str, int]:
    """O texto com todo CPF completo de pessoa física mascarado, e quantos foram trocados."""
    total = 0
    texto, n = _FORMATADO.subn(lambda m: f"***.{m.group(1)}.{m.group(2)}-**", texto)
    total += n
    texto, n = _CAMPO.subn(_trocar_campo, texto)
    total += n
    texto, n = _csv(texto)
    return texto, total + n


def cpfs_completos(texto: str) -> int:
    """Quantos CPFs completos de pessoa física a máscara trocaria neste texto (zero: está limpo)."""
    return mascarar_texto(texto)[1]


def _decodificar(dados: bytes) -> tuple[str, str] | None:
    if b"\x00" in dados[:4096]:
        return None                          # binário (imagem, planilha antiga)
    for cod in ("utf-8", "latin-1"):
        try:
            return dados.decode(cod), cod
        except UnicodeDecodeError:
            continue
    return None


def mascarar_bytes(dados: bytes) -> tuple[bytes, int]:
    """Os bytes de um arquivo de texto mascarados (binário volta como veio)."""
    texto = _decodificar(dados)
    if texto is None:
        return dados, 0
    novo, n = mascarar_texto(texto[0])
    return (novo.encode(texto[1]) if n else dados), n


def mascarar_zip(dados: bytes) -> tuple[bytes, int]:
    """Um ZIP (ou ``.xlsx``) com cada arquivo de texto mascarado; o ZIP volta igual se nada mudou."""
    entrada = zipfile.ZipFile(io.BytesIO(dados))
    membros, total = [], 0
    for info in entrada.infolist():
        conteudo = entrada.read(info)
        if info.filename.lower().endswith((".zip", ".xlsx")) and conteudo.startswith(b"PK"):
            novo, n = mascarar_zip(conteudo)
        else:
            novo, n = mascarar_bytes(conteudo)
        membros.append((info, novo if n else None))
        total += n
    if not total:
        return dados, 0
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as novo_zip:
        for info, novo in membros:
            novo_zip.writestr(info, novo if novo is not None else entrada.read(info))
    return saida.getvalue(), total


def zip_tem_cpf(dados: bytes) -> int:
    """Quantos CPFs completos há nos arquivos de texto de um ZIP."""
    return mascarar_zip(dados)[1]
