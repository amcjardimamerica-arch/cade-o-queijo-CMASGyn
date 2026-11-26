"""Adaptador do Cadê o Queijo: lê o que o motor antigo já produz e monta o panorama.

Fase 1 do roteiro: o núcleo do Onisciente roda com a Assistência Social como
primeiro domínio, a partir dos arquivos que o Cadê o Queijo grava toda semana
e todo mês (``relatorios/`` e ``dados/``). Nada aqui altera esses arquivos.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .. import RAIZ
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

def montar(competencia: str, *, raiz: Path = RAIZ, mapa: MapaLegal | None = None,
           alvo: str = "Prefeitura de Goiânia") -> Panorama:
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
    tempestividade = (pub.get("dias_com_edicao", 0) / dias_uteis) if dias_uteis else 0.0
    # Vínculo: entidades com lançamento no exercício que têm contrato, termo ou convênio.
    # A trilha soma os valores de cada entidade em vários anos, sem separar por exercício;
    # somar esses valores misturaria anos anteriores. Por isso a medida é por entidade.
    ativas = [e for e in (trilha.get("entidades") or []) if _ativa_no_ano(e, ano)]
    vinculo = (sum(1 for e in ativas if e.get("com_vinculo")) / len(ativas)) if ativas else 0.0
    parcerias = (transp.get("blocos") or {}).get("Parcerias com entidades", {})
    prestacao = 0.0 if "Prestações de contas" in (parcerias.get("falta") or []) else 1.0
    minimo = mapa.regra("INTEGRIDADE-LAI").valor or 50.0
    panorama.integridade = IndiceIntegridade(
        # O Cadê o Queijo não segue cada real pelas nove estações; até a execução ser
        # publicada, nenhum valor pago atravessa a trilha inteira com documento.
        cobertura=0.0,
        coerencia=0.0,  # nenhum valor do mês confirmado por duas vias
        tempestividade=tempestividade,
        vinculo=vinculo,
        prestacao=prestacao,
        minimo=minimo,
    )
    if pagamentos_mes == 0:
        panorama.notas.append("Nenhum pagamento publicado na competência: a cobertura da trilha é zero.")
    else:
        panorama.notas.append(f"{pagamentos_mes} ato(s) de pagamento no Diário da competência, mas "
                              "nenhum com as nove estações documentadas: a cobertura da trilha é zero.")
    panorama.notas.append(f"O vínculo é a parte das {len(ativas)} entidades com lançamento em {ano} "
                          "que têm contrato, termo ou convênio localizado; a trilha não separa "
                          "os valores por exercício, então a medida é por entidade, não por real.")
    panorama.notas.append(f"Montado a partir do Cadê o Queijo em {datetime.now():%d/%m/%Y}.")
    return panorama
