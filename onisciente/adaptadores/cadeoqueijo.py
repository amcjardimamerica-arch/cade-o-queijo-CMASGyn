"""Adaptador do Cadê o Queijo: lê o que o motor antigo já produz e monta o panorama.

Fase 1 do roteiro: o núcleo do Onisciente roda com a Assistência Social como
primeiro domínio, a partir dos arquivos que o Cadê o Queijo grava toda semana
e todo mês (``relatorios/`` e ``dados/``). Nada aqui altera esses arquivos.
"""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime
from pathlib import Path

from .. import RAIZ
from .. import fiscal as fiscal_mod
from ..conferencias import compras as compras_mod
from ..legal.mapa import MapaLegal, carregar
from ..nucleo.ausencias import Ausencia
from ..nucleo.custodia import Original
from ..nucleo.indicios import Ficha, familia_do_legado
from ..nucleo.integridade import IndiceIntegridade
from ..nucleo.selos import Gravidade, Selo, Verificacao
from ..panorama import Panorama
from ..pisos import medir
from ..rio.afluentes import Afluente, Rio
from ..rio.fontes import Esfera, classificar

ORGAO_LAI = "Controladoria Geral do Município de Goiânia"

# Bloco do índice de transparência do Cadê o Queijo -> conferência que fica impedida.
IMPEDIMENTOS = {
    "Previsão orçamentária": "previsão e dotação por fonte (estações 3 e 4)",
    "Receita realizada": "origem do dinheiro e conciliação com os repasses (estação 1)",
    "Execução da despesa": "empenho, liquidação e pagamento (estações 5, 7 e 8)",
    "Pessoal e diárias": "folha, diárias e o dinheiro que deveria ter saído (família PES)",
    "Parcerias com entidades": "vínculo e prestação de contas das parcerias (estações 6 e 9)",
    "Atos do Conselho": "deliberações do controle social sobre o fundo",
}
ONDE = {
    "despesas_receitas": "Portal da Transparência de Goiânia, receitas e despesas",
    "responsabilidade_fiscal": "Portal da Transparência (responsabilidade fiscal) e SICONFI",
    "recursos_humanos": "Portal da Transparência de Goiânia, recursos humanos",
    "sitio_conselho": "sítio oficial do Conselho Municipal de Assistência Social",
}


def _moeda(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _sileg_do_mes(banco: Path, competencia: str) -> int | None:
    """Edições do mês no índice do SILEG, pela coleta histórica; None se não houver leitura."""
    if not banco.exists():
        return None
    import sqlite3
    con = sqlite3.connect(f"file:{banco}?mode=ro", uri=True)
    try:
        linha = con.execute("select edicoes from diario_oficial_mes where fonte='sileg' and mes=? and "
                            "erro is null and edicoes is not null", (competencia,)).fetchone()
    finally:
        con.close()
    return int(linha[0]) if linha else None


def _ler(caminho: Path) -> dict | None:
    if not caminho.exists():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


def _texto_publico(t: str | None) -> str:
    """Tira das falas antigas os marcadores internos de pendência."""
    t = (t or "").strip()
    return t.replace("URL_TRANSPARENCIA (pendência P2)", "portal da transparência do Município")


def ficha_do_legado(achado: dict, competencia: str | None) -> Ficha:
    norma = _texto_publico(achado.get("norma")) or "norma não indicada no achado de origem"
    docs = achado.get("documentos_complementares") or []
    if docs:
        providencia = "Requisitar: " + "; ".join(docs[:6]) + ("; e outros." if len(docs) > 6 else ".")
    elif achado.get("onde_obter"):
        providencia = "Obter em: " + _texto_publico(achado["onde_obter"]) + "."
    else:
        providencia = ""
    return Ficha(
        codigo=achado["codigo"],
        familia=familia_do_legado(achado["codigo"]),
        titulo=achado["titulo"],
        gravidade=Gravidade.de(achado.get("severidade", "media")),
        como_deveria=f"A regra aplicada está em {norma}.",
        norma=norma,
        como_esta=_texto_publico(achado.get("detalhe")),
        verificacao=Verificacao.de(achado.get("selo", "INCONCLUSIVO")),
        providencia=providencia,
        competencia=competencia,
        origem="cadeoqueijo",
    )


def _esfera_do_codigo(codigo: str) -> Esfera:
    if codigo == "tesouro" or codigo == "patrimonial":
        return Esfera.MUNICIPAL
    fonte = classificar(codigo)
    if fonte.destinacao:
        return fonte.destinacao.esfera
    return Esfera.MISTA


def _fonte_do_codigo(codigo: str) -> str | None:
    if codigo == "tesouro":
        return "1500"
    if codigo.isdigit():
        return codigo
    return None


def _ativa_no_ano(entidade: dict, ano: str) -> bool:
    """A entidade teve lançamento no exercício: sua janela [primeiro, último] toca o ano."""
    primeiro = (entidade.get("primeiro") or "")[:4]
    ultimo = (entidade.get("ultimo") or primeiro)[:4]
    return bool(primeiro) and primeiro <= ano <= ultimo

def _fim_da_competencia(competencia: str) -> date:
    a, m = int(competencia[:4]), int(competencia[5:7])
    return date(a, m, calendar.monthrange(a, m)[1])


# O que o índice de transparência chama de execução da despesa, item a item.
EXECUCAO_INDIVIDUALIZADA = ("Empenhos", "Liquidações", "Pagamentos")


_CACHE_COMPRAS: dict[tuple, "compras_mod.Conferencias"] = {}


def _compras_do_banco(banco: Path, mapa: MapaLegal) -> "compras_mod.Conferencias":
    """As conferências valem para o Município inteiro: rodam uma vez por banco, não uma por competência."""
    chave = (str(banco), banco.stat().st_mtime_ns, id(mapa))
    if chave not in _CACHE_COMPRAS:
        _CACHE_COMPRAS.clear()
        _CACHE_COMPRAS[chave] = compras_mod.conferir(banco, mapa=mapa)
    return _CACHE_COMPRAS[chave]


def montar(competencia: str, *, raiz: Path = RAIZ, mapa: MapaLegal | None = None,
           alvo: str = "Prefeitura de Goiânia", banco: Path | None = None) -> Panorama:
    """Monta o panorama da competência (``AAAA-MM``) a partir dos dados do Cadê o Queijo."""
    mapa = mapa or carregar()
    ano = competencia[:4]
    verif = _ler(raiz / "relatorios" / "mensal" / f"verificacao_{competencia}.json")
    if verif is None:
        raise FileNotFoundError(
            f"não há verificação do Cadê o Queijo para {competencia}; "
            "rode antes o ciclo mensal (cadeoqueijo/run_mensal.py)"
        )

    rio = Rio(competencia)
    panorama = Panorama(competencia=competencia, alvo=alvo, dominio="Assistência Social", rio=rio)

    # 1. Fichas do mês e do exercício, sem repetir código.
    vistos = set()
    for a in verif.get("achados", []):
        panorama.fichas.append(ficha_do_legado(a, competencia))
        vistos.add(a["codigo"])
    consolidados = _ler(raiz / "relatorios" / f"achados_consolidados_{ano}.json") or {}
    for a in consolidados.get("achados", []):
        if a["codigo"] not in vistos:
            ficha = ficha_do_legado(a, None)
            ficha.observacao = "achado do exercício"
            panorama.fichas.append(ficha)
            vistos.add(a["codigo"])

    # 2. O rio: o previsto da competência por fonte (o realizado não foi publicado).
    receita = _ler(raiz / "dados" / f"receita_mensal_{ano}.json") or {}
    nomes = {f["fonte"]: f["nome"] for f in receita.get("fontes", [])}
    comp = next((c for c in receita.get("competencias", []) if c["competencia"] == competencia), None)
    if comp:
        for codigo, valor in (comp.get("previsto_por_fonte") or {}).items():
            if not valor:
                continue
            rio.afluentes.append(Afluente(
                nome=nomes.get(codigo, codigo), esfera=_esfera_do_codigo(codigo), valor=float(valor),
                fonte=_fonte_do_codigo(codigo), selo=Selo.AZUL,
                origem="previsto na LOA (lei publicada)"))
        if comp.get("realizado") is None:
            panorama.notas.append("O rio mostra o previsto na LOA para o mês: a receita realizada "
                                  "da competência não foi publicada.")
            panorama.ausencias.append(Ausencia(
                o_que_falta="Receita realizada do Fundo por fonte", periodo=competencia,
                conferencia_impedida=IMPEDIMENTOS["Receita realizada"],
                onde_deveria_estar=ONDE["responsabilidade_fiscal"], orgao=ORGAO_LAI,
                bloco="Receita realizada"))

        # 3. Piso do IGD ao controle social (o demonstrativo é obrigatório).
        igd = comp.get("igd") or {}
        if igd:
            panorama.medidas.append(medir("IGD-CONTROLE-SOCIAL", igd.get("aplicado_publicado"),
                                          igd.get("base_mensal_estimada"), mapa=mapa))

    # 4. Ausências do índice de transparência do Cadê o Queijo.
    transp = _ler(raiz / "dados" / "nivel_transparencia.json") or {}
    for bloco, info in (transp.get("blocos") or {}).items():
        for item in info.get("falta", []):
            panorama.ausencias.append(Ausencia(
                o_que_falta=item, periodo=f"exercício {ano}",
                conferencia_impedida=IMPEDIMENTOS.get(bloco, bloco),
                onde_deveria_estar=ONDE.get(info.get("onde"), "Portal da Transparência de Goiânia"),
                orgao=ORGAO_LAI, bloco=bloco))
    for a in verif.get("achados", []):
        if Verificacao.de(a.get("selo", "")) is Verificacao.INCONCLUSIVO and a.get("impedimento"):
            panorama.ausencias.append(Ausencia(
                o_que_falta=a["titulo"], periodo=competencia,
                conferencia_impedida=_texto_publico(a["impedimento"]),
                onde_deveria_estar=_texto_publico(a.get("onde_obter")) or "Portal da Transparência",
                fundamento=_texto_publico(a.get("norma")) or Ausencia.__dataclass_fields__["fundamento"].default,
                orgao=ORGAO_LAI, bloco="competência"))
    unicas, chaves = [], set()
    for a in panorama.ausencias:
        chave = (a.o_que_falta.lower(), a.periodo)
        if chave not in chaves:
            chaves.add(chave)
            unicas.append(a)
    panorama.ausencias = unicas

    # 4b. O Município pelo RGF e pelo RREO do banco histórico (tetos, duas vias, liquidado).
    fim = _fim_da_competencia(competencia)
    banco = banco or (raiz / "dados" / "onisciente" / "historico.db")
    liquidado_funcao, rreo_funcao = None, None
    if banco.exists():
        panorama.fiscal = fiscal_mod.medir_municipio(fim, banco=banco, mapa=mapa)
        panorama.fichas += panorama.fiscal.fichas(competencia)
        liquidado_funcao, rreo_funcao = fiscal_mod.liquidado_na_funcao("Assistência Social", fim, banco=banco)
        # 4c. As compras e os contratos do Município conferidos no banco; fichas só da pasta.
        panorama.compras = _compras_do_banco(banco, mapa)
        panorama.fichas += panorama.compras.fichas(competencia)
        rreo = panorama.fiscal.rreo
        if rreo is not None and str(rreo.exercicio) == ano:
            # O RREO é do ente, não do Fundo: está publicado no SICONFI e não falta.
            antes = len(panorama.ausencias)
            panorama.ausencias = [a for a in panorama.ausencias
                                  if a.o_que_falta != "Relatório Resumido da Execução Orçamentária"]
            if len(panorama.ausencias) < antes:
                panorama.notas.append(f"O Relatório Resumido da Execução Orçamentária está publicado no "
                                      f"SICONFI ({rreo.rotulo}) e não entra como ausência.")
    else:
        panorama.leitura_falhou.append(
            "Banco histórico (dados/onisciente/historico.db) não encontrado: os tetos do Município, as "
            "duas vias e a cobertura ficam sem medida nesta competência.")

    # 5. Custódia: os originais do mês na trilha do dinheiro.
    trilha = _ler(raiz / "dados" / "trilha_dinheiro.json") or {}
    coletado = (trilha.get("gerado_em") or "")[:10]
    pagamentos_mes = 0
    for ev in trilha.get("detalhe", []):
        if not str(ev.get("data", "")).startswith(competencia):
            continue
        if "pagamento" in (ev.get("estacoes") or []):
            pagamentos_mes += 1
        if ev.get("url") and ev.get("sha256_edicao"):
            panorama.custodia.append(Original(
                url=ev["url"], coletado_em=coletado or ev["data"], sha256=ev["sha256_edicao"],
                pagina=ev.get("pagina"), edicao=ev.get("edicao"), fonte="Diário Oficial do Município"))
    unicos = {o.sha256 + str(o.pagina): o for o in panorama.custodia}
    panorama.custodia = list(unicos.values())

    # 6. Fontes que existem mas a leitura não alcançou (vermelho).
    siconfi = _ler(raiz / "dados" / "siconfi.json") or {}
    if siconfi and not siconfi.get("rgf") and siconfi.get("tentativas"):
        panorama.leitura_falhou.append(
            f"SICONFI (RREO e RGF): {len(siconfi['tentativas'])} tentativa(s) sem leitura na coleta "
            f"de {siconfi.get('coletado_em', 'data desconhecida')}; os pisos ficam sem segunda via.")

    # 7. Índice de integridade da trilha.
    pub = verif.get("publicacao_do_mes") or {}
    dias_uteis = pub.get("dias_uteis") or 0
    dias_lidos = pub.get("dias_com_edicao", 0)
    tempestividade: float | None = (dias_lidos / dias_uteis) if dias_uteis else None
    # Segunda via da tempestividade: o índice do próprio SILEG guardado no banco histórico.
    sileg = _sileg_do_mes(banco or (raiz / "dados" / "onisciente" / "historico.db"), competencia)
    motivo_tempo = None
    if dias_uteis and sileg is not None:
        estimados = min(sileg, dias_uteis)
        if abs(estimados - dias_lidos) > 1:
            tempestividade = None
            motivo_tempo = (f"as duas leituras do Diário divergem ({dias_lidos} dias lidos pelo motor semanal, "
                            f"{sileg} edições no índice do SILEG): a leitura falhou em uma delas e a medida "
                            "não pesa contra o Município")
            panorama.leitura_falhou.append(
                f"Diário Oficial de {competencia}: o motor semanal leu {dias_lidos} dia(s) com edição e o índice "
                f"do SILEG tem {sileg} edição(ões); a tempestividade fica sem medida até as leituras baterem.")
    # Vínculo: entidades com lançamento no exercício que têm contrato, termo ou convênio.
    # A trilha soma os valores de cada entidade em vários anos, sem separar por exercício;
    # somar esses valores misturaria anos anteriores. Por isso a medida é por entidade.
    ativas = [e for e in (trilha.get("entidades") or []) if _ativa_no_ano(e, ano)]
    vinculo = (sum(1 for e in ativas if e.get("com_vinculo")) / len(ativas)) if ativas else 0.0
    parcerias = (transp.get("blocos") or {}).get("Parcerias com entidades", {})
    prestacao = 0.0 if "Prestações de contas" in (parcerias.get("falta") or []) else 1.0
    minimo = mapa.regra("INTEGRIDADE-LAI").valor or 50.0
    motivos: dict[str, str] = {}

    # Cobertura: do liquidado na função (RREO), quanto atravessa as nove estações com documento.
    execucao = (transp.get("blocos") or {}).get("Execução da despesa", {})
    nao_publicada = [i for i in EXECUCAO_INDIVIDUALIZADA if i in (execucao.get("falta") or [])]
    cobertura: float | None
    if liquidado_funcao is None:
        cobertura = None
        motivos["cobertura"] = ("sem o liquidado da função no RREO do banco histórico, não há base para "
                                "medir quanto do gasto atravessa a trilha")
    elif liquidado_funcao <= 0:
        cobertura = None
        motivos["cobertura"] = f"nada liquidado na função até o {rreo_funcao.rotulo}"
    elif nao_publicada:
        cobertura = 0.0  # medido: o Município não publica o gasto item a item
        motivos["cobertura"] = (
            f"{_moeda(liquidado_funcao)} liquidados na Assistência Social até o {rreo_funcao.rotulo}; "
            f"nenhum real com {', '.join(i.lower() for i in nao_publicada)} publicados item a item "
            f"(conferência do portal em {transp.get('gerado_em', 'data não registrada')}), então nenhum "
            "atravessa as nove estações")
    else:
        cobertura = None
        motivos["cobertura"] = ("a execução da despesa consta como publicada, mas o Onisciente ainda não "
                                "a lê item a item: falha do sistema, não do Município")
        panorama.leitura_falhou.append("Execução da despesa item a item: publicada, mas ainda não lida; "
                                       "a cobertura da trilha fica sem medida.")

    # Coerência: dos valores com duas vias independentes, quantos dizem o mesmo.
    # Um valor com uma via só (a outra ainda no prazo) não é incoerência: fica fora da conta.
    certs = [c for c in (panorama.fiscal.certificacoes() if panorama.fiscal else []) if len(c.vias) >= 2]
    coerencia: float | None
    if certs:
        iguais = sum(1 for c in certs if c.selo is Selo.VERDE and not c.divergencia)
        coerencia = iguais / len(certs)
        motivos["coerencia"] = (f"{iguais} de {len(certs)} valores publicados em duas vias oficiais do mesmo "
                                "período (no RGF e no RREO; no SIOPS, no SIOPE e no RREO; no RREO e na matriz de saldos "
                                "contábeis; no SIAFI e na matriz) dizem o mesmo "
                                "dentro de 1%")
    else:
        coerencia = None
        motivos["coerencia"] = "nenhum valor da competência com duas vias independentes no banco"
    motivos["tempestividade"] = motivo_tempo or (
        f"{dias_lidos} de {dias_uteis} dias úteis com Diário Oficial publicado"
        + (f", confirmado pelo índice do SILEG ({sileg} edições)" if sileg is not None else "")
        if dias_uteis else "sem calendário de dias úteis da competência")
    motivos["prestacao"] = ("prestações de contas das parcerias não publicadas" if prestacao == 0.0
                            else "prestações de contas das parcerias publicadas")
    panorama.integridade = IndiceIntegridade(
        cobertura=cobertura,
        coerencia=coerencia,
        tempestividade=tempestividade,
        vinculo=vinculo if ativas else None,
        prestacao=prestacao,
        minimo=minimo,
        motivos=motivos,
    )
    motivos["vinculo"] = (f"{sum(1 for e in ativas if e.get('com_vinculo'))} de {len(ativas)} entidades "
                          f"com lançamento em {ano} têm contrato, termo ou convênio localizado"
                          if ativas else "nenhuma entidade com lançamento no exercício")
    panorama.notas.append(f"O vínculo é a parte das {len(ativas)} entidades com lançamento em {ano} "
                          "que têm contrato, termo ou convênio localizado; a trilha não separa "
                          "os valores por exercício, então a medida é por entidade, não por real.")
    panorama.notas.append(f"Montado a partir do Cadê o Queijo em {datetime.now():%d/%m/%Y}.")
    return panorama
