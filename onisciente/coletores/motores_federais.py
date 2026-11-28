"""Motores da coleta histórica para as fontes do bloco 5: FNS, FNDE, Transferegov, CEIS e CNEP,
Economia GO, TCU e TCM-GO.

Cada motor recebe o ``Contexto`` de ``onisciente.historico`` (a leitura com paciência, o disjuntor,
o registro de cada chamada na tabela ``coletas``) e grava em tabelas próprias, criadas por
``preparar``. Nenhum motor interpreta nada: a interpretação fica em ``onisciente.conferencias.federais``.

A situação de cada fonte em cada alvo (um ano, um cadastro, um módulo) fica em ``fontes_federais``:
``lido`` (com registros), ``vazio`` (a fonte respondeu e não há registro), ``nao_publicado`` (nenhum
candidato trouxe o dado: ausência), ``falha`` (rede) ou ``formato`` (a resposta mudou). É dali que a
conferência tira a cobertura: falha e formato são falha do sistema; não publicado é alerta de
transparência de quem devia publicar.

Para ligar no ``historico``: somar ``ESQUEMA`` ao esquema, ``TABELAS_DO_MOTOR`` ao dicionário de
mesmo nome, ``MOTORES`` à tupla, ``TEMPO_DO_MOTOR`` ao tempo, e ``chamadas(ctx, alvo)`` às chamadas
de ``rodar``. Este módulo não importa o ``historico`` no topo, para não criar import circular.
"""

from __future__ import annotations

import calendar
import io
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import zlib
from datetime import UTC, date, datetime, timedelta

from . import base, economia_go, emendas, fnde, fns, sancoes, tcm, tcu, transferegov
from . import comum_federal as cf

ESQUEMA = """
CREATE TABLE IF NOT EXISTS fontes_federais (motor TEXT, alvo TEXT, situacao TEXT, via TEXT, registros INTEGER,
    erro TEXT, quando TEXT, PRIMARY KEY (motor, alvo));
CREATE TABLE IF NOT EXISTS repasses_fns (ano INTEGER, mes TEXT, data TEXT, competencia TEXT, bloco TEXT,
    programa TEXT, cnpj TEXT, favorecido TEXT, valor_bruto REAL, desconto REAL, valor_liquido REAL, banco TEXT,
    agencia TEXT, conta TEXT, ordem_bancaria TEXT, situacao TEXT, via TEXT);
CREATE TABLE IF NOT EXISTS fnde_entidades (ano INTEGER, cnpj TEXT, nome TEXT, total_declarado REAL,
    liberacoes INTEGER, situacao TEXT, PRIMARY KEY (ano, cnpj));
CREATE TABLE IF NOT EXISTS liberacoes_fnde (ano INTEGER, mes TEXT, data TEXT, cnpj TEXT, entidade TEXT,
    programa TEXT, ordem_bancaria TEXT, banco TEXT, agencia TEXT, conta TEXT, valor REAL);
CREATE TABLE IF NOT EXISTS emendas_municipio (planilha TEXT, emenda TEXT, ano INTEGER, mes TEXT, tipo TEXT,
    autor TEXT, cnpj TEXT, nome TEXT, situacao TEXT, objeto TEXT, referencia TEXT, valor_empenhado REAL,
    valor_liquidado REAL, valor_pago REAL, valor REAL, json TEXT);
CREATE TABLE IF NOT EXISTS transferegov_planos_especiais (id_plano TEXT PRIMARY KEY, codigo TEXT, ano INTEGER,
    situacao TEXT, cnpj TEXT, beneficiario TEXT, parlamentar TEXT, emenda TEXT, custeio REAL, investimento REAL,
    total REAL);
CREATE TABLE IF NOT EXISTS transferegov_registros (modulo TEXT, tabela TEXT, chave TEXT, ano INTEGER, cnpj TEXT,
    valor REAL, situacao TEXT, descricao TEXT, json TEXT, PRIMARY KEY (modulo, tabela, chave));
CREATE TABLE IF NOT EXISTS sancoes (cnpj_cpf TEXT, cadastro TEXT, inicio TEXT, fim TEXT, orgao TEXT, tipo TEXT,
    nome TEXT, tipo_pessoa TEXT, uf_orgao TEXT, esfera TEXT, abrangencia TEXT, processo TEXT, fundamentacao TEXT,
    publicacao TEXT, multa REAL, codigo TEXT, arquivo TEXT);
CREATE INDEX IF NOT EXISTS sancoes_cnpj_cpf ON sancoes (cnpj_cpf);
CREATE TABLE IF NOT EXISTS repasses_estado (mes TEXT, tributo TEXT, valor REAL, url TEXT,
    PRIMARY KEY (mes, tributo));
CREATE TABLE IF NOT EXISTS contas_irregulares_tcm (lista TEXT, municipio TEXT, entidade TEXT, responsavel TEXT,
    processo TEXT, exercicio TEXT, transito TEXT, url TEXT, json TEXT, cpf_parcial TEXT, assunto TEXT,
    decisao TEXT, data_julgamento TEXT, tipo_lista TEXT, url_processo TEXT);
CREATE TABLE IF NOT EXISTS repasse_dia_fns (data TEXT, nivel INTEGER, caminho TEXT, codigo TEXT, nome TEXT,
    valor_total REAL, valor_desconto REAL, valor_liquido REAL, competencia TEXT, tipo_competencia TEXT,
    tipo_transferencia TEXT, nivel_programa TEXT, processos INTEGER, folha INTEGER);
CREATE TABLE IF NOT EXISTS repasse_dia_fns_dias (data TEXT PRIMARY KEY, registros INTEGER, quando TEXT);
CREATE TABLE IF NOT EXISTS fns_entidades (ano INTEGER, cpf_cnpj TEXT, pessoa_fisica INTEGER, nome TEXT,
    esfera TEXT, municipio_ibge TEXT, sem_repasse INTEGER, PRIMARY KEY (ano, cpf_cnpj, nome));
CREATE TABLE IF NOT EXISTS decisoes_controle (tribunal TEXT, chave TEXT, numero TEXT, ano INTEGER,
    colegiado TEXT, data TEXT, relator TEXT, processo TEXT, tipo TEXT, titulo TEXT, sumario TEXT, url TEXT,
    sobre_goiania INTEGER, PRIMARY KEY (tribunal, chave));
"""

MOTORES = ("fns", "fnde", "transferegov", "sancoes", "economia_go", "tcu", "tcm")

TABELAS_DO_MOTOR = {
    "fns": [("coletas", "motor = 'fns'"), ("repasses_fns", ""), ("repasse_dia_fns", ""),
            ("repasse_dia_fns_dias", ""), ("fns_entidades", ""), ("fontes_federais", "motor = 'fns'")],
    "fnde": [("coletas", "motor = 'fnde'"), ("liberacoes_fnde", ""), ("fnde_entidades", ""),
             ("fontes_federais", "motor = 'fnde'")],
    "transferegov": [("coletas", "motor = 'transferegov'"), ("transferegov_planos_especiais", ""),
                     ("emendas_municipio", ""),
                     ("transferegov_registros", ""), ("fontes_federais", "motor = 'transferegov'")],
    "sancoes": [("coletas", "motor = 'sancoes'"), ("sancoes", ""), ("fontes_federais", "motor = 'sancoes'")],
    "economia_go": [("coletas", "motor = 'economia_go'"), ("repasses_estado", ""),
                    ("fontes_federais", "motor = 'economia_go'")],
    "tcu": [("coletas", "motor = 'tcu'"), ("decisoes_controle", "tribunal = 'TCU'"),
            ("fontes_federais", "motor = 'tcu'")],
    "tcm": [("coletas", "motor = 'tcm'"), ("decisoes_controle", "tribunal = 'TCM-GO'"), ("contas_irregulares_tcm", ""),
            ("fontes_federais", "motor = 'tcm'")],
}

# Minutos por rodada (o FNDE lê uma página por entidade: conselhos escolares são centenas).
TEMPO_DO_MOTOR = {"fns": 20, "fnde": 45, "transferegov": 20, "sancoes": 15, "economia_go": 10,
                  "tcu": 15, "tcm": 10}
# De quanto em quanto tempo cada fonte é lida (dias), para o prazo de fonte parada.
CICLO_DIAS = {"fns": 7, "fnde": 7, "transferegov": 7, "sancoes": 1, "economia_go": 31, "tcu": 7, "tcm": 7}

PAGINAS_MAX = 50


# Colunas que entraram depois da tabela existir (um banco antigo ganha a coluna sem perder as linhas).
COLUNAS_NOVAS = {"contas_irregulares_tcm": ("cpf_parcial", "assunto", "decisao", "data_julgamento", "tipo_lista",
                                            "url_processo")}


def preparar(banco) -> None:
    """Cria as tabelas do bloco 5 num banco já aberto (idempotente)."""
    banco.con.executescript(ESQUEMA)
    for tabela, colunas in COLUNAS_NOVAS.items():
        existentes = {c[1] for c in banco.con.execute(f"PRAGMA table_info({tabela})")}
        for coluna in colunas:
            if coluna not in existentes:
                banco.con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} TEXT")


def _anos(ctx) -> list[int]:
    return sorted({int(m[:4]) for m in ctx.meses if date(int(m[:4]), 1, 1) <= ctx.hoje})


def _anotar(ctx, motor: str, alvo: str, mes: str, url: str, erro: str) -> None:
    """Falha que não é de rede (formato, conteúdo) junto das chamadas, como o ``historico`` faz."""
    ctx.banco.inserir("coletas", {
        "motor": motor, "alvo": alvo, "mes": mes, "url": url, "ok": 0, "http": None,
        "erro": erro[:500], "tentativas": 0, "segundos": 0.0, "bytes": 0, "sha256": None,
        "quando": datetime.now(UTC).isoformat(timespec="seconds")})


def _situacao(ctx, motor: str, alvo: str, situacao: str, *, via: str | None = None, registros: int = 0,
              erro: str | None = None) -> None:
    ctx.banco.inserir("fontes_federais", {
        "motor": motor, "alvo": alvo, "situacao": situacao, "via": via, "registros": registros,
        "erro": (erro or None) and erro[:500],
        "quando": datetime.now(UTC).isoformat(timespec="seconds")})


def _ausente(leitura) -> bool:
    """Resposta definitiva de que o endereço não tem o dado (não é falha de rede)."""
    return leitura.http in (400, 403, 404, 410) or (leitura.ok and cf.parece_pagina(leitura.conteudo))


# --- FNS ----------------------------------------------------------------------------------

def motor_fns(ctx, ibge: int) -> None:
    """Os repasses do FNS ao Município, ano a ano. O modelo de endereço que respondeu num ano é
    tentado primeiro no seguinte."""
    preparar(ctx.banco)
    preferido: str | None = None
    for ano in _anos(ctx):
        modelos = ([preferido] if preferido else []) + [m for m in fns.MODELOS_DE_REPASSE if m != preferido]
        ultimo_erro, situacao = "nenhum modelo de endereço respondeu", "nao_publicado"
        for modelo in modelos:
            linhas: list[dict] = []
            pagina, ok = 1, True
            while pagina <= PAGINAS_MAX:
                url = fns.url(modelo, ibge, ano, pagina)
                leitura = ctx.ler("fns", f"{ano} p{pagina}", url, mes=f"{ano}-01", tempo=120)
                if not leitura.ok:
                    ok = False
                    ultimo_erro = leitura.erro or f"HTTP {leitura.http}"
                    if not _ausente(leitura):
                        situacao = "falha"
                    break
                try:
                    novas, mais = fns.ler(leitura.conteudo)
                except ValueError as e:
                    _anotar(ctx, "fns", f"{ano} p{pagina}", f"{ano}-01", url, f"formato: {e}")
                    ok, ultimo_erro = False, f"formato: {e}"
                    if not cf.parece_pagina(leitura.conteudo):
                        situacao = "formato"
                    break
                linhas.extend(novas)
                if not mais or not novas:
                    break
                pagina += 1
            if not ok:
                continue
            ctx.banco.con.execute("DELETE FROM repasses_fns WHERE ano = ?", (ano,))
            for l in linhas:
                ctx.banco.inserir("repasses_fns", {"ano": ano, **l, "via": modelo})
            _situacao(ctx, "fns", str(ano), "lido" if linhas else "vazio", via=modelo, registros=len(linhas))
            preferido = modelo
            break
        else:
            _situacao(ctx, "fns", str(ano), situacao, erro=ultimo_erro)


def motor_fns_entidades(ctx, ibge, paginas_max: int = 20) -> None:
    """Quem recebeu do FNS no Município, ano a ano (``consulta-detalhada/entidades``, 100 por página).
    O ano só é trocado na tabela quando todas as páginas vieram; entidade de outro Município é formato."""
    preparar(ctx.banco)
    ibge6 = str(ibge)[:6]
    for ano in _anos(ctx):
        alvo, linhas, total, situacao, erro = f"entidades {ano}", [], 0, None, None
        pagina, paginas = 1, 1
        while pagina <= min(paginas, paginas_max):
            url = fns.url(fns.ENTIDADES, ibge, ano, pagina)
            leitura = ctx.ler("fns", f"{alvo} p{pagina}", url, mes=f"{ano}-01", tempo=120)
            if not leitura.ok:
                situacao = "nao_publicado" if _ausente(leitura) else "falha"
                erro = leitura.erro or f"HTTP {leitura.http}"
                break
            try:
                novas, total, paginas = fns.entidades(leitura.conteudo, ibge6)
            except ValueError as e:
                _anotar(ctx, "fns", f"{alvo} p{pagina}", f"{ano}-01", url, f"formato: {e}")
                situacao, erro = "formato", f"formato: {e}"
                break
            linhas.extend(novas)
            if not novas:
                break
            pagina += 1
        if situacao is None:
            ctx.banco.con.execute("DELETE FROM fns_entidades WHERE ano = ?", (ano,))
            for l in linhas:
                ctx.banco.con.execute("INSERT OR REPLACE INTO fns_entidades VALUES (?, ?, ?, ?, ?, ?, ?)",
                                      (ano, l["cpf_cnpj"], l["pessoa_fisica"], l["nome"], l["esfera"],
                                       l["municipio_ibge"], l["sem_repasse"]))
            situacao = "lido" if linhas else "vazio"
            if total and len(linhas) < total:
                erro = f"{len(linhas)} de {total} entidades (limite de {paginas_max} páginas)"
        _situacao(ctx, "fns", alvo, situacao, via=fns.ENTIDADES, registros=len(linhas), erro=erro)


def motor_fns_repasse_dia(ctx, dias_max: int = 40) -> None:
    """O repasse do dia do FNS (``repasse-dia/consultar``): o total nacional pago em cada dia, por bloco,
    grupo e programa. Lê a data do último pagamento e desce dia a dia, do mais novo, dentro do período
    da rodada; dia já lido não é lido de novo. Não traz o Município: é o calendário e o total dos
    pagamentos; quem recebeu no Município vem de ``motor_fns_entidades``."""
    preparar(ctx.banco)
    alvo = "repasse_dia"
    url = fns.url_repasse_dia("recuperar-data-ultimo-pagamento")
    leitura = ctx.ler("fns", "repasse dia ultimo", url, tempo=60)
    if not leitura.ok:
        _situacao(ctx, "fns", alvo, "nao_publicado" if _ausente(leitura) else "falha", via=url,
                  erro=leitura.erro or f"HTTP {leitura.http}")
        return
    try:
        ultimo = date.fromisoformat(fns.data_ultimo_pagamento(leitura.conteudo))
    except ValueError as e:
        _anotar(ctx, "fns", "repasse dia ultimo", "", url, f"formato: {e}")
        _situacao(ctx, "fns", alvo, "formato", via=url, erro=f"formato: {e}")
        return
    if not ctx.meses:
        _situacao(ctx, "fns", alvo, "vazio", via=url, erro="período da rodada vazio")
        return
    inicio = date.fromisoformat(min(ctx.meses) + "-01")
    fim = min(ultimo, fim_do_mes(max(ctx.meses)), ctx.hoje)
    lidos = {d for (d,) in ctx.banco.consultar("SELECT data FROM repasse_dia_fns_dias")}
    dias, dia = [], fim
    while dia >= inicio and len(dias) < dias_max:
        if dia.isoformat() not in lidos and dia.weekday() < 5:
            dias.append(dia)
        dia -= timedelta(days=1)
    novos, linhas, falhas, formatos = 0, 0, [], []
    for dia in dias:
        url_dia = fns.url_repasse_dia("consultar", ano=dia.year, mes=dia.month, dia=dia.day)
        leitura = ctx.ler("fns", f"repasse dia {dia.isoformat()}", url_dia, mes=dia.isoformat()[:7], tempo=60)
        if not leitura.ok:
            falhas.append(f"{dia.isoformat()} ({leitura.erro or leitura.http})")
            if len(falhas) >= 3 and not novos:
                break                            # o serviço caiu: a próxima rodada retoma
            continue
        try:
            nos = fns.arvore_repasse_dia(leitura.conteudo, dia.isoformat())
        except ValueError as e:
            _anotar(ctx, "fns", f"repasse dia {dia.isoformat()}", dia.isoformat()[:7], url_dia, f"formato: {e}")
            formatos.append(f"{dia.isoformat()} ({e})")
            continue
        ctx.banco.con.execute("DELETE FROM repasse_dia_fns WHERE data = ?", (dia.isoformat(),))
        for n in nos:
            ctx.banco.inserir("repasse_dia_fns", n)
        ctx.banco.con.execute("INSERT OR REPLACE INTO repasse_dia_fns_dias VALUES (?, ?, ?)",
                              (dia.isoformat(), len(nos), datetime.now(UTC).isoformat(timespec="seconds")))
        novos, linhas = novos + 1, linhas + len(nos)
    erro = "; ".join(x for x in (f"falha: {', '.join(falhas)}" if falhas else "",
                                 f"formato: {', '.join(formatos)}" if formatos else "") if x) or None
    total = ctx.banco.consultar("SELECT COUNT(*) FROM repasse_dia_fns")[0][0]
    if novos or (lidos and not falhas and not formatos):
        situacao = "lido" if total else "vazio"
    elif formatos:
        situacao = "formato"
    elif falhas:
        situacao = "falha"
    else:
        situacao = "lido" if total else "vazio"
    _situacao(ctx, "fns", alvo, situacao, via=f"último pagamento {ultimo.isoformat()}", registros=linhas,
              erro=erro)


# --- FNDE ---------------------------------------------------------------------------------

def motor_fnde(ctx, uf: str, ibge6: str) -> None:
    """As liberações do FNDE a cada entidade do Município, ano a ano (SIMAD)."""
    preparar(ctx.banco)
    for ano in _anos(ctx):
        lista = ctx.ler("fnde", f"entidades {ano}", fnde.ENTIDADES, mes=f"{ano}-01",
                        formulario=fnde.formulario(ano, uf, ibge6), tempo=120)
        if not lista.ok:
            _situacao(ctx, "fnde", str(ano), "nao_publicado" if _ausente(lista) else "falha",
                      erro=lista.erro or f"HTTP {lista.http}")
            continue
        try:
            ents = fnde.entidades(cf.decodificar(lista.conteudo))
        except ValueError as e:
            _anotar(ctx, "fnde", f"entidades {ano}", f"{ano}-01", lista.url, f"formato: {e}")
            _situacao(ctx, "fnde", str(ano), "formato", erro=str(e))
            continue
        enderecos = {e["cnpj"]: e.get("url") or fnde.url_liberacoes(ano, e["cnpj"], uf, ibge6) for e in ents}
        ctx.antecipar("fnde", list(enderecos.values()), tempo=120)
        ctx.banco.con.execute("DELETE FROM liberacoes_fnde WHERE ano = ?", (ano,))
        ctx.banco.con.execute("DELETE FROM fnde_entidades WHERE ano = ?", (ano,))
        total_linhas, problemas = 0, 0
        for e in ents:
            url = enderecos[e["cnpj"]]
            leitura = ctx.ler("fnde", f"{ano} {e['cnpj']}", url, mes=f"{ano}-01", tempo=120)
            linha_ent = {"ano": ano, "cnpj": e["cnpj"], "nome": e["nome"], "total_declarado": None,
                         "liberacoes": 0, "situacao": None}
            if not leitura.ok:
                linha_ent["situacao"] = "falha"
                problemas += 1
                ctx.banco.inserir("fnde_entidades", linha_ent)
                continue
            try:
                libs, total = fnde.liberacoes(cf.decodificar(leitura.conteudo))
            except ValueError as erro:
                _anotar(ctx, "fnde", f"{ano} {e['cnpj']}", f"{ano}-01", url, f"formato: {erro}")
                linha_ent["situacao"] = "formato"
                problemas += 1
                ctx.banco.inserir("fnde_entidades", linha_ent)
                continue
            for l in libs:
                ctx.banco.inserir("liberacoes_fnde", {"ano": ano, "mes": (l["data"] or "")[:7] or None,
                                                      "cnpj": e["cnpj"], "entidade": e["nome"], **l})
            linha_ent.update(total_declarado=total, liberacoes=len(libs), situacao="lido")
            ctx.banco.inserir("fnde_entidades", linha_ent)
            total_linhas += len(libs)
        situacao = "lido" if total_linhas else "vazio"
        if problemas:
            situacao = "falha" if problemas == len(ents) else situacao
        _situacao(ctx, "fnde", str(ano), situacao, via=fnde.ENTIDADES, registros=total_linhas,
                  erro=f"{problemas} de {len(ents)} entidades sem leitura" if problemas else None)


# --- Transferegov -------------------------------------------------------------------------

def cnpjs_do_municipio(banco, extras=()) -> list[str]:
    """Os CNPJs dos entes do Município: os favorecidos públicos municipais das transferências da
    União (Município, fundos municipais) e os órgãos conhecidos do PNCP."""
    achados: set[str] = {cf.digitos(c) for c in extras if cf.digitos(c)}
    try:
        for (c,) in banco.consultar(
                "SELECT DISTINCT favorecido FROM transferencias_federais WHERE tipo_favorecido LIKE "
                "'Administração Pública%' AND tipo_favorecido NOT LIKE '%Estadual%'"):
            if len(cf.digitos(c)) == 14:
                achados.add(cf.digitos(c))
    except sqlite3.OperationalError:
        pass
    return sorted(achados)


def _ibge7(ibge) -> str:
    """O código IBGE de sete dígitos (o sétimo é o verificador, calculável a partir dos seis)."""
    texto = "".join(ch for ch in str(ibge) if ch.isdigit())
    if len(texto) != 6:
        return texto
    soma = sum(sum(divmod(int(d) * (1 if i % 2 == 0 else 2), 10)) for i, d in enumerate(texto))
    return texto + str((10 - soma % 10) % 10)


def motor_emendas(ctx, municipio: str, uf: str, ibge, cnpjs=()) -> None:
    """O arquivo único de emendas do Portal da Transparência, lido em fluxo (sem guardar o zip) e
    filtrado pelo Município; a tabela ``emendas_municipio`` é trocada inteira só quando a leitura
    chega ao fim. Com um leitor de teste no contexto, o arquivo vem por ele."""
    preparar(ctx.banco)
    filtro = emendas.Filtro(municipio, uf, ibge, cnpjs)
    inicio = time.monotonic()
    linhas, contagem = [], {}
    url, http, lidos, erro, situacao = emendas.URL, None, 0, None, "falha"
    try:
        if ctx.ler_url is not base.ler:
            leitura = ctx.ler("transferegov", "emendas arquivo unico", url, tempo=300)
            if not leitura.ok:
                raise OSError(leitura.erro or f"HTTP {leitura.http}")
            fonte = emendas.Contador(io.BytesIO(leitura.conteudo))
            registrar = False
        else:
            fonte = emendas.Contador(emendas.abrir(url, tempo=300))
            registrar = True
        http = fonte.status
        try:
            for planilha, linha in emendas.filtrar(fonte, filtro):
                linhas.append(linha)
                contagem[planilha] = contagem.get(planilha, 0) + 1
        finally:
            lidos = fonte.bytes
            fechar = getattr(fonte.fonte, "close", None)
            if fechar:
                fechar()
        situacao = "lido" if linhas else "vazio"
    except emendas.Formato as e:
        situacao, erro, registrar = "formato", f"formato: {e}", locals().get("registrar", True)
    except (urllib.error.URLError, TimeoutError, OSError, zlib.error) as e:
        erro, registrar = f"{type(e).__name__}: {getattr(e, 'reason', e)}", locals().get("registrar", True)
        http = getattr(e, "code", http)
    if registrar:
        ctx.gastos["transferegov"] = ctx.gastos.get("transferegov", 0) + 1
        ctx.banco.inserir("coletas", {
            "motor": "transferegov", "alvo": "emendas arquivo unico (fluxo)", "mes": "", "url": url,
            "ok": int(situacao in ("lido", "vazio")), "http": http, "erro": erro, "tentativas": 1,
            "segundos": round(time.monotonic() - inicio, 2), "bytes": lidos, "sha256": None,
            "quando": datetime.now(UTC).isoformat(timespec="seconds")})
    if situacao in ("lido", "vazio"):
        with ctx.banco.con:
            ctx.banco.con.execute("DELETE FROM emendas_municipio")
            for linha in linhas:
                ctx.banco.inserir("emendas_municipio", linha)
        erro = ", ".join(f"{k}: {v}" for k, v in sorted(contagem.items())) or None
    _situacao(ctx, "transferegov", "emendas", situacao, via=url, registros=len(linhas), erro=erro)


def motor_transferegov(ctx, cnpjs, municipio: str | None = None, uf: str | None = None, ibge=None) -> None:
    """Cada módulo do Transferegov: as tabelas com CNPJ (pela descrição da raiz), lidas pelo CNPJ de
    cada ente do Município, página a página. Com o Município, também o arquivo de emendas do Portal."""
    preparar(ctx.banco)
    cnpjs = [c for c in cnpjs if c]
    if municipio and uf and ibge:
        motor_emendas(ctx, municipio, uf, _ibge7(ibge), cnpjs)
    if not cnpjs:
        for modulo in transferegov.MODULOS:
            _situacao(ctx, "transferegov", modulo, "formato", erro="nenhum CNPJ do Município para consultar")
        return
    adiados = [m for m in transferegov.MODULOS if _modulo_transferegov(ctx, m, cnpjs, ultima=False)]
    for modulo in adiados:                       # nova tentativa depois dos outros módulos
        _modulo_transferegov(ctx, modulo, cnpjs, ultima=True)


def _fora_do_ar(leitura) -> bool:
    """Falha de rede ou 5xx (o ``ctx.ler`` já tentou de novo com espera): a API caiu, não falta o dado."""
    return not leitura.ok and not _ausente(leitura) and (leitura.http is None or leitura.http >= 500)


def _modulo_transferegov(ctx, modulo: str, cnpjs: list[str], *, ultima: bool) -> bool:
    """Um módulo do Transferegov. Com a raiz e a primeira consulta fora do ar (a sondagem de 28/11/2026
    viu 503 na API e 404 no repositório de dados abertos), não insiste em cada tabela e CNPJ: devolve
    True para uma nova tentativa no fim do motor; na última, grava falha e a próxima rodada tenta de novo."""
    raiz = ctx.ler("transferegov", f"{modulo} raiz", transferegov.url_raiz(modulo), tempo=90)
    tabelas = dict(transferegov.PADRAO.get(modulo, {}))
    if raiz.ok:
        try:
            descritas = transferegov.tabelas_com_cnpj(raiz.conteudo)
            tabelas = descritas or tabelas
        except ValueError as e:
            _anotar(ctx, "transferegov", f"{modulo} raiz", "", raiz.url, f"formato: {e}")
    raiz_caiu = _fora_do_ar(raiz)
    lidos, falhas, ultimo, consultas = 0, 0, None, 0
    for tabela, coluna in sorted(tabelas.items()):
        for cnpj in cnpjs:
            offset = 0
            while offset < transferegov.PAGINA * PAGINAS_MAX:
                url = transferegov.url_tabela(modulo, tabela, {coluna: f"eq.{cnpj}"}, offset=offset)
                leitura = ctx.ler("transferegov", f"{modulo}/{tabela} {cnpj} +{offset}", url, tempo=90)
                consultas += 1
                if not leitura.ok:
                    falhas += 1
                    ultimo = leitura.erro or f"HTTP {leitura.http}"
                    if raiz_caiu and consultas == 1 and _fora_do_ar(leitura):
                        erro = (f"API fora do ar: a raiz e a primeira consulta falharam ({raiz.erro or raiz.http}; "
                                f"{ultimo})")
                        if not ultima:
                            return True
                        _situacao(ctx, "transferegov", modulo, "falha", via=transferegov.url_raiz(modulo),
                                  erro=erro + "; tentado de novo no fim do motor, a próxima rodada tenta outra vez")
                        return False
                    break
                try:
                    regs = transferegov.pagina(leitura.conteudo)
                except ValueError as e:
                    _anotar(ctx, "transferegov", f"{modulo}/{tabela} {cnpj}", "", url, f"formato: {e}")
                    falhas += 1
                    ultimo = f"formato: {e}"
                    break
                for r in regs:
                    if modulo == transferegov.ESPECIAIS and tabela == transferegov.PLANOS:
                        p = transferegov.plano(r)
                        if p:
                            ctx.banco.inserir("transferegov_planos_especiais", p)
                            lidos += 1
                    else:
                        ctx.banco.inserir("transferegov_registros", transferegov.generico(modulo, tabela, r))
                        lidos += 1
                if len(regs) < transferegov.PAGINA:
                    break
                offset += transferegov.PAGINA
    tentadas = len(tabelas) * len(cnpjs)
    if falhas and falhas >= tentadas:
        situacao = "falha"
    else:
        situacao = "lido" if lidos else "vazio"
    _situacao(ctx, "transferegov", modulo, situacao, via=transferegov.url_raiz(modulo), registros=lidos,
              erro=(f"{falhas} de {tentadas} consultas falharam; última: {ultimo}" if falhas else None))
    return False


# --- CEIS e CNEP --------------------------------------------------------------------------

def motor_sancoes(ctx) -> None:
    """O arquivo mais recente de cada cadastro, inteiro, na tabela ``sancoes``. As datas vêm da
    página de download do cadastro; sem ela, recua até uma semana. Cada data é tentada no portal
    e no repositório da CGU."""
    preparar(ctx.banco)
    for cadastro in sancoes.CADASTROS:
        situacao, erro = "nao_publicado", "nenhum arquivo na última semana"
        indice = ctx.ler("sancoes", f"{cadastro} indice", sancoes.url_indice(cadastro), tempo=60)
        publicadas = sancoes.datas_publicadas(cf.decodificar(indice.conteudo), cadastro) if indice.ok else []
        # A data anunciada primeiro (só o arquivo mais recente existe: o do dia anterior dá 403); depois,
        # hoje e um dia a dia para trás, caso a página não diga a data.
        dias = list(dict.fromkeys(publicadas[:3] + sancoes.dias_para_tentar(ctx.hoje)))
        codigos: set[str] = set()
        lido = False
        for dia in dias:
            for url in sancoes.urls(cadastro, dia):
                leitura = ctx.ler("sancoes", f"{cadastro} {dia:%Y%m%d}", url, mes=f"{dia:%Y-%m}", tempo=180)
                if not leitura.ok or cf.parece_pagina(leitura.conteudo):
                    if leitura.ok or _ausente(leitura):
                        codigos.add(str(leitura.http or "página"))
                        continue                 # arquivo do dia ainda não saiu, ou esta via o recusa
                    situacao, erro = "falha", leitura.erro
                    break
                try:
                    linhas = sancoes.ler(leitura.conteudo, cadastro)
                except ValueError as e:
                    _anotar(ctx, "sancoes", f"{cadastro} {dia:%Y%m%d}", f"{dia:%Y-%m}", url, f"formato: {e}")
                    situacao, erro = "formato", str(e)
                    break
                ctx.banco.con.execute("DELETE FROM sancoes WHERE cadastro = ?", (cadastro,))
                for l in linhas:
                    ctx.banco.inserir("sancoes", {**l, "arquivo": f"{dia:%Y%m%d}"})
                _situacao(ctx, "sancoes", cadastro, "lido" if linhas else "vazio", via=url, registros=len(linhas))
                lido = True
                break
            if lido or situacao in ("falha", "formato"):
                break
        if lido:
            continue
        if situacao == "nao_publicado":
            origem = "nas datas da página de download" if publicadas else "na última semana"
            erro = (f"nenhum arquivo {origem}, no portal nem no repositório da CGU"
                    + (f" (respostas: {', '.join(sorted(codigos))})" if codigos else ""))
        _situacao(ctx, "sancoes", cadastro, situacao, erro=erro)


# --- Economia GO --------------------------------------------------------------------------

def _recursos_ckan(conteudo: bytes) -> list[str]:
    obj = cf.json_ou_none(conteudo)
    res = obj.get("result") if isinstance(obj, dict) else None
    pacotes = res.get("results", []) if isinstance(res, dict) else []
    urls = []
    for p in pacotes[:10]:
        for r in (p.get("resources") or [])[:10]:
            u = str(r.get("url") or "")
            if u.lower().endswith((".csv", ".json")):
                urls.append(u)
    return urls


def motor_economia_go(ctx, municipio: str, ibge: int, leituras_max: int = 25) -> None:
    """A cota de ICMS e de IPVA do Município pela via do Estado, ano a ano. Nenhum candidato com o
    dado: ``nao_publicado`` (ausência, que a conferência transforma em alerta com ofício). Arquivo do
    Estado que o coletor ainda não lê (PDF, planilha antiga) ou planilha lida sem a linha do Município:
    ``formato``, porque a falta é do sistema, e não do Estado. Tudo bloqueado ou fora do ar: ``falha``.

    Quando a página de repasses lista uma planilha por mês (``economia_go.arquivos_mensais``), o ano
    é lido dessas planilhas, todas, e os outros links da página não são seguidos."""
    preparar(ctx.banco)
    for ano in _anos(ctx):
        achadas: list[dict] = []
        via = None
        falhas_de_rede, bloqueios = 0, 0
        nao_lidos: list[str] = []
        sem_dado: list[str] = []
        mensais: dict[str, list[str]] = {}
        fila = list(economia_go.urls(ano, ibge))
        vistos: set[str] = set()
        while fila and not achadas and not mensais and len(vistos) < leituras_max:
            url = fila.pop(0)
            if url in vistos:
                continue
            vistos.add(url)
            if not economia_go.legivel(url):
                nao_lidos.append(url)            # existe, mas o coletor não lê PDF nem planilha antiga
                continue
            leitura = ctx.ler("economia_go", f"{ano}", url, mes=f"{ano}-01", tempo=90)
            if not leitura.ok:
                falhas_de_rede += 0 if _ausente(leitura) else 1
                continue
            if economia_go.bloqueado(leitura.conteudo):
                bloqueios += 1
                _anotar(ctx, "economia_go", f"{ano}", f"{ano}-01", url, "bloqueado pelo firewall do Estado (Acesso Negado)")
                continue
            if "/api/3/action/" in url:
                fila.extend(_recursos_ckan(leitura.conteudo))
                continue
            try:
                linhas = [l for l in economia_go.ler(leitura.conteudo, municipio, ano) if l["mes"].startswith(str(ano))]
            except ValueError as e:
                _anotar(ctx, "economia_go", f"{ano}", f"{ano}-01", url, f"formato: {e}")
                sem_dado.append(url)
                continue
            if linhas:
                achadas, via = linhas, url
            elif cf.parece_pagina(leitura.conteudo) or "<a" in cf.decodificar(leitura.conteudo[:200000]).lower():
                texto = cf.decodificar(leitura.conteudo)
                for a in economia_go.arquivos_mensais(texto, url):
                    if a["mes"].startswith(str(ano)):
                        mensais.setdefault(a["url"], []).append(a["mes"])
                if not mensais:
                    fila.extend(economia_go.links_de_repasse(texto, url))
            elif urllib.parse.urlparse(url).path.lower().endswith(economia_go.ARQUIVOS):
                sem_dado.append(url)
        por_chave = {(l["mes"], l["tributo"]): l for l in achadas}
        # A planilha do mês mais recente primeiro: a conciliação traz o ano inteiro, e as outras só
        # são baixadas para os meses que ela não cobriu (cada uma tem 15 MB).
        for arquivo, meses in sorted(mensais.items(), key=lambda kv: max(kv[1]), reverse=True):
            if all(any(k[0] == m for k in por_chave) for m in meses):
                continue
            vistos.add(arquivo)
            if not economia_go.legivel(arquivo):
                nao_lidos.append(arquivo)
                continue
            leitura = ctx.ler("economia_go", f"{ano} planilha {meses[0]}", arquivo, mes=meses[0], tempo=120)
            if not leitura.ok:
                falhas_de_rede += 0 if _ausente(leitura) else 1
                continue
            try:
                # Uma planilha que serve a um mês só leva o mês do link; a acumulada diz os meses.
                linhas = economia_go.ler(leitura.conteudo, municipio, ano, meses[0] if len(meses) == 1 else None)
            except ValueError as e:
                _anotar(ctx, "economia_go", f"{ano} planilha {meses[0]}", meses[0], arquivo, f"formato: {e}")
                sem_dado.append(arquivo)
                continue
            linhas = [l for l in linhas if l["mes"].startswith(str(ano))]
            if not linhas:
                sem_dado.append(arquivo)
            for l in linhas:                     # a planilha mais recente da página vale
                por_chave[(l["mes"], l["tributo"])] = l
            via = via or (arquivo if linhas else None)
        achadas = [por_chave[k] for k in sorted(por_chave)]
        if achadas:
            for l in achadas:
                ctx.banco.inserir("repasses_estado", {**l, "url": via})
            erro = None
            if sem_dado or nao_lidos:
                erro = f"{len(sem_dado) + len(nao_lidos)} arquivo(s) do ano sem leitura: {', '.join((sem_dado + nao_lidos)[:3])}"
            _situacao(ctx, "economia_go", str(ano), "lido", via=via, registros=len(achadas), erro=erro)
        elif sem_dado:
            _situacao(ctx, "economia_go", str(ano), "formato", via=sem_dado[0],
                      erro=f"planilha do Estado lida sem a linha de {municipio} ou sem as colunas de ICMS e IPVA "
                           f"(formato a confirmar): {', '.join(sem_dado[:5])}")
        elif nao_lidos:
            _situacao(ctx, "economia_go", str(ano), "formato", via=nao_lidos[0],
                      erro=f"o Estado publica em arquivo que o coletor ainda não lê: {', '.join(nao_lidos[:5])}")
        elif (falhas_de_rede + bloqueios) and falhas_de_rede + bloqueios == len(vistos):
            _situacao(ctx, "economia_go", str(ano), "falha",
                      erro=f"{bloqueios} endereço(s) bloqueado(s) pelo firewall do Estado e {falhas_de_rede} "
                           f"fora do ar ou com erro de rede")
        elif mensais and falhas_de_rede:
            _situacao(ctx, "economia_go", str(ano), "falha", via=next(iter(mensais)),
                      erro=f"{falhas_de_rede} planilha(s) mensal(is) do Estado com erro de rede")
        else:
            extra = f"; {bloqueios} bloqueado(s) pelo firewall do Estado" if bloqueios else ""
            _situacao(ctx, "economia_go", str(ano), "nao_publicado",
                      erro=f"{len(vistos)} endereços tentados, nenhum com a cota de ICMS e IPVA de {municipio}{extra}")


# --- TCU e TCM-GO -------------------------------------------------------------------------

def _guardar_decisoes(ctx, decisoes: list[dict], so_goiania: bool) -> int:
    n = 0
    for d in decisoes:
        if so_goiania and not d.get("sobre_goiania"):
            continue
        ctx.banco.inserir("decisoes_controle", d)
        n += 1
    return n


def motor_tcu(ctx, termo: str = "Goiânia", paginas: int = 10) -> None:
    """Os acórdãos do TCU que citam Goiânia: pela pesquisa (termo) e pelos dados abertos (os
    recentes, filtrados pelo texto), até a data mais antiga do intervalo."""
    preparar(ctx.banco)
    desde = f"{min(ctx.meses)}-01" if ctx.meses else None
    for alvo, montar, so_goiania, por_pagina in (
            ("pesquisa", lambda i: tcu.url_pesquisa(termo, i), False, tcu.QUANTIDADE_PESQUISA),
            ("dados_abertos", lambda i: tcu.url_dados_abertos(i), True, tcu.QUANTIDADE)):
        guardadas, situacao, erro = 0, "vazio", None
        for p in range(max(1, paginas * tcu.QUANTIDADE // por_pagina)):     # o mesmo alcance com 50 por vez
            url = montar(p * por_pagina)
            leitura = ctx.ler("tcu", f"{alvo} {p}", url, tempo=90)
            if not leitura.ok:
                situacao, erro = ("nao_publicado" if _ausente(leitura) else "falha"), leitura.erro
                break
            try:
                decisoes = tcu.ler(leitura.conteudo, pesquisa=alvo == "pesquisa")
            except ValueError as e:
                _anotar(ctx, "tcu", f"{alvo} {p}", "", url, f"formato: {e}")
                situacao, erro = "formato", str(e)
                break
            guardadas += _guardar_decisoes(ctx, decisoes, so_goiania)
            situacao = "lido" if guardadas else "vazio"
            datas = [d["data"] for d in decisoes if d.get("data")]
            if len(decisoes) < por_pagina or (desde and datas and max(datas) < desde):
                break
        if guardadas and situacao in ("falha", "formato", "nao_publicado"):
            situacao = "lido"                            # as páginas anteriores valem; o erro fica anotado
        _situacao(ctx, "tcu", alvo, situacao, via=alvo, registros=guardadas, erro=erro)


def motor_listas_tcm(ctx, municipio: str = "Goiânia") -> None:
    """As listas de contas com parecer prévio pela rejeição ou julgadas irregulares (e as de governo
    julgadas pelas câmaras): os endereços vêm das páginas das listas, com ``tcm.LISTAS`` de reserva.
    Uma lista lida troca as linhas dela na tabela; a situação de todas fica no alvo ``listas``."""
    preparar(ctx.banco)
    enderecos = dict(tcm.LISTAS)
    for pagina in tcm.PAGINAS_DAS_LISTAS:
        leitura = ctx.ler("tcm", "listas pagina", pagina, tempo=90)
        if leitura.ok:
            for url in tcm.links_das_listas(cf.decodificar(leitura.conteudo)):
                if url not in enderecos.values():
                    enderecos[f"link {len(enderecos)}"] = url
    lidas, falhas, formatos, ausentes, linhas = [], [], [], [], 0
    for nome, url in enderecos.items():
        leitura = ctx.ler("tcm", f"lista {nome}", url, tempo=90)
        if not leitura.ok:
            (ausentes if _ausente(leitura) else falhas).append(f"{nome} ({leitura.erro or leitura.http})")
            continue
        try:
            achadas = tcm.contas(leitura.conteudo, municipio)
        except ValueError as e:
            _anotar(ctx, "tcm", f"lista {nome}", "", url, f"formato: {e}")
            formatos.append(f"{nome} ({e})")
            continue
        lidas.append(nome)
        ctx.banco.con.execute("DELETE FROM contas_irregulares_tcm WHERE lista = ?", (nome,))
        for a in achadas:
            ctx.banco.inserir("contas_irregulares_tcm", {
                **{k: (None if a.get(k) is None else str(a[k])) for k in
                   ("municipio", "entidade", "responsavel", "processo", "exercicio", "transito", "cpf_parcial",
                    "assunto", "decisao", "data_julgamento", "tipo_lista", "url_processo")},
                "lista": nome, "url": url, "json": json.dumps(a["registro"], ensure_ascii=False)})
            linhas += 1
    erros = "; ".join(x for x in (
        f"falha: {', '.join(falhas)}" if falhas else "", f"formato: {', '.join(formatos)}" if formatos else "",
        f"ausente: {', '.join(ausentes)}" if ausentes else "") if x) or None
    if lidas:
        situacao = "lido" if linhas else "vazio"
    elif formatos:
        situacao = "formato"
    elif falhas:
        situacao = "falha"
    else:
        situacao = "nao_publicado"
    _situacao(ctx, "tcm", "listas", situacao, via=tcm.PAGINAS_DAS_LISTAS[0], registros=linhas, erro=erros)


def motor_tcm(ctx, termo: str = "Goiânia", paginas: int = 5) -> None:
    """As decisões do TCM-GO sobre Goiânia, pelo primeiro candidato que responder. As listas de contas
    rejeitadas ou irregulares são de ``motor_listas_tcm``, que ``chamadas`` roda junto."""
    preparar(ctx.banco)
    ultimo_erro, situacao = "nenhum candidato respondeu", "nao_publicado"
    sem_decisoes: list[str] = []                 # responderam, mas nenhuma decisão na página
    for indice in range(len(tcm.CANDIDATOS)):
        guardadas, ok, chaves = 0, False, set()
        for p in range(1, paginas + 1):
            url = tcm.urls(termo, p)[indice]
            leitura = ctx.ler("tcm", f"candidato {indice} p{p}", url, tempo=90)
            if not leitura.ok:
                ultimo_erro = leitura.erro or f"HTTP {leitura.http}"
                if not _ausente(leitura):
                    situacao = "falha"
                break
            try:
                decisoes = tcm.ler(leitura.conteudo, tcm.PORTAL)
            except ValueError as e:
                _anotar(ctx, "tcm", f"candidato {indice} p{p}", "", url, f"formato: {e}")
                ultimo_erro, situacao = f"formato: {e}", "formato"
                break
            ok = True
            novas = [d for d in decisoes if d["chave"] not in chaves]
            chaves.update(d["chave"] for d in novas)
            guardadas += _guardar_decisoes(ctx, novas, True)
            if not novas:
                break
        if ok and chaves:
            _situacao(ctx, "tcm", "decisoes", "lido" if guardadas else "vazio", via=tcm.CANDIDATOS[indice],
                      registros=guardadas)
            return
        if ok:
            sem_decisoes.append(tcm.CANDIDATOS[indice].split("?")[0])
    if sem_decisoes:
        ultimo_erro = (f"{len(sem_decisoes)} endereço(s) responderam sem nenhuma decisão (páginas de serviço ou "
                       f"notícia, não resultado de pesquisa): " + ", ".join(sem_decisoes))
        situacao = "nao_publicado"
    _situacao(ctx, "tcm", "decisoes", situacao, erro=ultimo_erro)


# --- Ligação com o historico --------------------------------------------------------------

def chamadas(ctx, alvo, cnpjs=None) -> dict:
    """As chamadas dos motores do bloco 5 para o ``rodar`` do historico."""
    return {
        "fns": lambda: (motor_fns(ctx, alvo.ibge), motor_fns_entidades(ctx, alvo.ibge), motor_fns_repasse_dia(ctx)),
        "fnde": lambda: motor_fnde(ctx, alvo.uf, str(alvo.ibge)[:6]),
        "transferegov": lambda: motor_transferegov(
            ctx, cnpjs if cnpjs is not None else cnpjs_do_municipio(ctx.banco, ()),
            municipio=alvo.municipio, uf=alvo.uf, ibge=alvo.ibge),
        "sancoes": lambda: motor_sancoes(ctx),
        "economia_go": lambda: motor_economia_go(ctx, alvo.municipio, alvo.ibge),
        "tcu": lambda: motor_tcu(ctx, alvo.municipio),
        "tcm": lambda: (motor_tcm(ctx, alvo.municipio), motor_listas_tcm(ctx, alvo.municipio)),
    }


def fim_do_mes(mes: str) -> date:
    a, m = map(int, mes.split("-"))
    return date(a, m, calendar.monthrange(a, m)[1])


def resumo(banco) -> dict:
    """A situação de cada fonte do bloco 5, para o diagnóstico da rodada."""
    try:
        linhas = banco.consultar("SELECT motor, alvo, situacao, registros, erro FROM fontes_federais "
                                 "ORDER BY motor, alvo")
    except sqlite3.OperationalError:
        return {}
    out: dict = {}
    for motor, alvo, situacao, registros, erro in linhas:
        out.setdefault(motor, []).append({"alvo": alvo, "situacao": situacao, "registros": registros,
                                          "erro": erro})
    return json.loads(json.dumps(out))
