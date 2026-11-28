"""Motores das empresas contratadas: o cadastro na Receita (``cnpj``) e os impedimentos (``impedimentos``).

Os dois seguem o contrato dos motores de ``onisciente.historico``: recebem o ``Contexto`` da rodada,
leem a rede pelo ``ctx.ler`` (que registra cada chamada em ``coletas``) e gravam no banco. O download
grande da base mensal do CNPJ não passa pelo ``ctx.ler``, que guarda a resposta inteira na memória:
vai direto para o disco, em blocos, e cada arquivo é anotado em ``coletas`` do mesmo jeito.

Para registrar no ``historico.py`` (dono: coordenador)::

    MOTORES = (..., "cnpj", "impedimentos")
    TEMPO_DO_MOTOR["cnpj"] = 150; TEMPO_DO_MOTOR["impedimentos"] = 15
    TABELAS_DO_MOTOR["cnpj"] = [("coletas", "motor = 'cnpj'")]
    TABELAS_DO_MOTOR["impedimentos"] = [("coletas", "motor = 'impedimentos'")]
    chamadas["cnpj"] = lambda: motor_cnpj.motor_cnpj(ctx)
    chamadas["impedimentos"] = lambda: motor_cnpj.motor_impedimentos(ctx)
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import cnpj as rf
from . import impedimentos as imp

DIAS_PARA_RECONSULTAR = 31        # registro da via secundária mais velho que isso é consultado de novo
PAGINAS_TCU = 200


def _anotar(ctx, alvo: str, url: str, ok: bool, bytes_: int, erro: str, mes: str = "",
            sha256: str | None = None, metodo: str = "GET") -> None:
    """Anota em ``coletas`` uma leitura que não passou pelo ``ctx.ler`` (a listagem e os arquivos da base
    mensal), com o SHA-256 dos bytes recebidos (``sha256``) quando houve resposta."""
    ctx.banco.inserir("coletas", {
        "motor": "cnpj", "alvo": alvo[:80], "mes": mes, "url": url, "ok": int(ok), "http": None,
        "erro": erro or None, "tentativas": 1, "segundos": 0, "bytes": bytes_, "sha256": sha256,
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"), "metodo": metodo})


def impressao_do_texto(texto: str) -> str | None:
    """SHA-256 da listagem recebida (o texto volta a bytes em UTF-8, a codificação da resposta)."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest() if texto else None


def impressao_do_arquivo(caminho: Path) -> str | None:
    """SHA-256 do arquivo baixado (lido em blocos: os zips da Receita passam de 1 GB)."""
    if not caminho.exists():
        return None
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def mes_mais_novo(portas: list[rf.Porta], listar_url: Callable = rf.listar,
                  anotar: Callable = lambda *a: None) -> tuple[rf.Porta | None, str | None]:
    """A primeira porta que lista as pastas mensais e a pasta mais nova dela."""
    for porta in portas:
        texto, erro = listar_url(porta, "")
        meses = rf.meses_da_listagem(texto) if texto else []
        anotar(f"listagem {porta.nome}", porta.raiz, bool(meses), len(texto), erro or ("" if meses else
                                                                                       "nenhuma pasta AAAA-MM"),
               impressao_do_texto(texto), "PROPFIND" if porta.propfind else "GET")
        if meses:
            return porta, meses[-1]
    return None, None


def motor_cnpj(ctx, *, portas: list[rf.Porta] | None = None, listar_url: Callable = rf.listar,
               baixar_url: Callable = rf.baixar, pasta: Path | None = None) -> dict:
    """O cadastro e o QSA de cada CNPJ fornecedor no banco.

    1. Descobre a pasta mensal mais nova da base da Receita; se ela é mais nova que o que o banco tem,
       lê a base inteira (em fluxo, filtrando os CNPJs do banco) e grava, com a data da base.
    2. O que a base não trouxe (porta fora do ar, CNPJ que entrou depois) vai pela via secundária,
       um CNPJ por vez: BrasilAPI, e minhareceita se a BrasilAPI falhar.
    """
    con = ctx.banco.con
    rf.preparar(con)
    hoje = ctx.hoje.isoformat()
    cnpjs = rf.cnpjs_do_banco(con)
    resumo: dict = {"cnpjs": len(cnpjs), "base": None, "porta": None, "da_base": 0, "da_api": 0,
                    "ausentes": 0, "erros": []}
    if not cnpjs:
        ctx.banco.inserir("meta", {"chave": "cnpj_base", "valor": json.dumps(resumo, ensure_ascii=False)})
        return resumo
    token = os.environ.get("RFB_SHARE_TOKEN") or rf.TOKEN_PADRAO
    porta, mes = mes_mais_novo(portas if portas is not None else rf.portas(token), listar_url,
                               lambda alvo, url, ok, n, erro, sha=None, metodo="GET": _anotar(
                                   ctx, alvo, url, ok, n, erro, sha256=sha, metodo=metodo))
    linha = con.execute("SELECT valor FROM meta WHERE chave = 'cnpj_base_lida'").fetchone()
    lida = linha[0] if linha else ""
    if porta and mes:
        resumo.update(base=mes, porta=porta.nome)
        if mes > lida:
            # Pasta mensal nova: a base inteira de novo, para todos os CNPJs (o histórico de razão
            # social e de CNAE depende de cada fotografia mensal).
            with tempfile.TemporaryDirectory(dir=pasta) as tmp:
                cad = rf.coletar_base(cnpjs, mes=mes, porta=porta, pasta=Path(tmp), baixar_url=baixar_url,
                                      listar_url=listar_url, hoje=hoje,
                                      registrar=lambda url, ok, n, erro: _anotar(
                                          ctx, url.rsplit("/", 1)[-1], url, ok, n, erro, mes,
                                          sha256=impressao_do_arquivo(Path(tmp) / url.rsplit("/", 1)[-1])))
            rf.gravar(con, cad)
            resumo["erros"] = cad.erros
            if cad.completa:      # base lida inteira: não se relê no mesmo mês
                ctx.banco.inserir("meta", {"chave": "cnpj_base_lida", "valor": mes})
    no_banco = dict(con.execute("SELECT cnpj, fonte || '|' || COALESCE(consultado_em, '') FROM cnpj_empresas"))
    resumo["da_base"] = sum(1 for v in no_banco.values() if v.startswith(rf.FONTE_BASE))
    ausentes = {c for (c,) in con.execute("SELECT cnpj FROM cnpj_ausentes WHERE fonte = ?", (rf.FONTE_BASE,))}
    limite = (ctx.hoje - timedelta(days=DIAS_PARA_RECONSULTAR)).isoformat()
    faltam = []
    for c in cnpjs:
        if c in ausentes:
            continue
        reg = no_banco.get(c)
        if reg is None:
            faltam.append(c)
        elif not reg.startswith(rf.FONTE_BASE) and reg.split("|", 1)[1] < limite:
            faltam.append(c)
    for c in faltam:
        if _por_api(ctx, c, hoje):
            resumo["da_api"] += 1
    resumo["ausentes"] = con.execute("SELECT count(*) FROM cnpj_ausentes").fetchone()[0]
    ctx.banco.inserir("meta", {"chave": "cnpj_base", "valor": json.dumps(resumo, ensure_ascii=False)})
    ctx.banco.con.commit()
    return resumo


def _por_api(ctx, cnpj: str, hoje: str) -> bool:
    con = ctx.banco.con
    for url, fonte in ((rf.url_brasilapi(cnpj), rf.FONTE_BRASILAPI), (rf.url_minhareceita(cnpj),
                                                                        rf.FONTE_MINHARECEITA)):
        leitura = ctx.ler("cnpj", cnpj, url, tempo=30)
        if leitura.ok:
            try:
                reg, socios = rf.de_api(leitura.conteudo, fonte=fonte, hoje=hoje)
            except ValueError as e:
                _anotar(ctx, cnpj, url, False, len(leitura.conteudo), f"formato: {e}",
                        sha256=_historico().impressao_da_resposta(leitura))
                continue
            cad = rf.Cadastro(empresas={reg["cnpj"]: reg}, socios=socios, fonte=fonte, data_base=reg["data_base"])
            rf.gravar(con, cad)
            return True
        if leitura.http == 404:
            # O espelho responde 404 para CNPJ que não existe na base que ele carrega.
            rf.gravar(con, rf.Cadastro(ausentes={cnpj: "não encontrado no espelho da base da Receita"},
                                       fonte=fonte, data_base=hoje))
            return False
    return False


def motor_impedimentos(ctx) -> dict:
    """O CEPIM do último arquivo diário publicado e a lista de inidôneos do TCU."""
    con = ctx.banco.con
    imp.preparar(con)
    resumo: dict = {"cepim": None, "tcu": None}
    for dia in imp.dias_para_tentar(ctx.hoje):
        url = imp.url_cepim(dia)
        leitura = ctx.ler("impedimentos", "cepim", url, mes=dia.isoformat()[:7], tempo=120)
        if not leitura.ok:
            continue
        try:
            linhas = imp.linhas_cepim(leitura.conteudo, dia)
        except ValueError as e:
            _anotar_imp(ctx, "cepim", url, f"formato: {e}")
            continue
        imp.gravar(con, linhas, "CEPIM")
        resumo["cepim"] = {"dia": dia.isoformat(), "linhas": len(linhas)}
        break
    todas: list[dict] = []
    vistas: set = set()
    for pagina in range(PAGINAS_TCU):
        url = imp.url_tcu(pagina)
        leitura = ctx.ler("impedimentos", f"tcu {pagina}", url, tempo=60)
        if not leitura.ok:
            break
        try:
            linhas, mais = imp.pagina_tcu(leitura.conteudo)
        except ValueError as e:
            _anotar_imp(ctx, f"tcu {pagina}", url, f"formato: {e}")
            break
        novas = [l for l in linhas if (l["cnpj_cpf"], l["nome"], l["processo"]) not in vistas]
        if not novas:
            break               # a API ignorou a paginação: a mesma página de novo
        for l in novas:
            vistas.add((l["cnpj_cpf"], l["nome"], l["processo"]))
            l["data_base"] = ctx.hoje.isoformat()
        todas.extend(novas)
        if not mais:
            break
    if todas:
        imp.gravar(con, todas, "TCU-INIDONEOS")
        resumo["tcu"] = {"linhas": len(todas)}
    ctx.banco.inserir("meta", {"chave": "impedimentos", "valor": json.dumps(resumo, ensure_ascii=False)})
    con.commit()
    return resumo


def _historico():
    from .. import historico   # tarde: o historico importa este módulo
    return historico


def _anotar_imp(ctx, alvo: str, url: str, erro: str) -> None:
    ctx.banco.inserir("coletas", {
        "motor": "impedimentos", "alvo": alvo, "mes": "", "url": url, "ok": 0, "http": None, "erro": erro[:300],
        "tentativas": 0, "segundos": 0, "bytes": 0, "sha256": None,
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds")})

