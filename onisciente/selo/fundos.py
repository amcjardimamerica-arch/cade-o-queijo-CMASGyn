"""Transparência do Fundo Municipal de Assistência Social (FMAS) e do Conselho (CMAS) de Goiânia.

O PNTP cobre pouco dos dois: o Conselho entra só no critério 19.4 (composição e funcionamento do
Conselho de Assistência Social), que é recomendado e vale dentro de uma dimensão de peso 1; o Fundo não
tem critério próprio e só aparece se o portal do Município incluir a unidade gestora nas consultas de
receita, despesa, convênios e contratos. Por isso o Onisciente confere os dois pela lei:

* Lei 12.527/2011, art. 8º, § 1º, II e III (repasses e despesas) e art. 8º, caput;
* LC 101/2000, art. 48-A, I e II (todos os atos da despesa e toda a receita de cada unidade gestora);
* Lei 14.133/2021, art. 174, § 2º, V e VI (contratos, aditivos e notas fiscais no PNCP);
* Lei 13.019/2014, arts. 10 e 11 (parcerias e planos de trabalho no sítio oficial);
* Lei 8.742/1993 (LOAS), art. 30, I e II (conselho paritário e fundo sob controle do conselho);
* Lei municipal 7.531/1995, art. 3º (FMAS gerido pela SEMAS sob orientação e controle do CMAS);
* Lei municipal 9.009/2010, arts. 3º e 10 (composição, sessões públicas, resoluções no Diário Oficial).

Premissa do dono: o que não está provado como publicado é alerta de descumprimento de transparência.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .. import RAIZ
from ..conferencias.compras import Achado
from .provas import CNPJ_FMAS, Prova, _sem_acento, ausencias_da_pasta, reais
from .verificadores import Pagina, tem_dado

FMAS = "FUNDO MUNICIPAL DE ASSISTENCIA SOCIAL-FMAS"
CMAS = "CONSELHO MUNICIPAL DE ASSISTENCIA SOCIAL DE GOIANIA - CMASGyn"


@dataclass(frozen=True)
class Obrigacao:
    id: str
    orgao: str                        # FMAS ou CMAS
    texto: str
    base: str
    ausencias: tuple[str, ...]        # nomes de ausência do parecer que provam a falta
    termos: tuple[str, ...] = ()      # termos para achar a publicação nas páginas sondadas
    usa_repasses: bool = False
    pntp: str = ""                    # critério do PNTP que cobre, se cobre


OBRIGACOES = (
    Obrigacao("F1", "FMAS", "Receita do Fundo publicada: repasses recebidos do Fundo Nacional e do Estado e receita "
              "realizada por fonte, mês a mês", "LC 101/2000, art. 48-A, II; Lei 12.527/2011, art. 8º, § 1º, II",
              ("receita realizada", "repasses do fundo nacional", "extratos da conta"),
              ("fundo municipal de assistencia", "receita"), usa_repasses=True, pntp="3.1 (só se o portal incluir o Fundo)"),
    Obrigacao("F2", "FMAS", "Execução da despesa do Fundo publicada: empenhos, liquidações, pagamentos e restos a pagar, "
              "com credor e licitação de origem", "LC 101/2000, art. 48-A, I; Lei 12.527/2011, art. 8º, § 1º, III",
              ("empenhos", "liquidac", "pagamentos", "ordens bancarias", "restos a pagar"),
              ("fundo municipal de assistencia", "empenho"), usa_repasses=True, pntp="4.1 e 4.3 (só se o portal incluir o Fundo)"),
    Obrigacao("F3", "FMAS", "Contratos, aditivos e notas fiscais do Fundo no PNCP",
              "Lei 14.133/2021, art. 174, § 2º, V e VI", (), pntp="9.1 (sem as notas fiscais)"),
    Obrigacao("F4", "FMAS", "Parcerias com organizações da sociedade civil: chamamentos, planos de trabalho e "
              "prestações de contas no sítio oficial", "Lei 13.019/2014, arts. 10 e 11",
              ("planos de trabalho", "prestacoes de contas", "editais de chamamento"),
              ("parceria", "plano de trabalho"), pntp="5.2"),
    Obrigacao("F5", "FMAS", "Fundo sob orientação e controle do Conselho: apreciação das contas e prestação quadrimestral "
              "publicadas", "Lei 8.742/1993, art. 30, II; Lei municipal 7.531/1995, art. 3º",
              ("apreciacao mensal das contas", "prestacao quadrimestral"),
              ("apreciacao", "prestacao de contas"), usa_repasses=True),
    Obrigacao("C1", "CMAS", "Resoluções do Conselho publicadas no Diário Oficial do Município",
              "Lei municipal 9.009/2010, art. 10, § 2º", ("resolucoes",), ("resolucao",), pntp="19.4"),
    Obrigacao("C2", "CMAS", "Sessões públicas com cronograma divulgado e atas das plenárias publicadas",
              "Lei municipal 9.009/2010, art. 10, caput e § 1º; Lei 12.527/2011, art. 8º, caput",
              ("atas de plenaria",), ("ata", "plenaria"), pntp="19.4"),
    Obrigacao("C3", "CMAS", "Composição paritária com os conselheiros e o decreto de nomeação publicados",
              "Lei 8.742/1993, art. 30, I; Lei municipal 9.009/2010, art. 3º",
              ("decreto de nomeacao",), ("conselheiro",), pntp="19.4"),
    Obrigacao("C4", "CMAS", "Regimento interno publicado", "Lei municipal 9.009/2010 (competência do Conselho de aprovar o "
              "seu regimento); Lei 12.527/2011, art. 8º, caput", ("regimento interno",), ("regimento",), pntp="19.4"),
)


@dataclass
class Situacao:
    obrigacao: Obrigacao
    estado: str                       # publicado, em falta ou sem dado
    provas: list[str] = field(default_factory=list)
    valor_em_jogo: float = 0.0

    @property
    def alerta(self) -> bool:
        return self.estado != "publicado"

    def como_dict(self) -> dict:
        o = self.obrigacao
        return {"id": o.id, "orgao": o.orgao, "texto": o.texto, "base": o.base, "pntp": o.pntp,
                "estado": self.estado, "alerta": self.alerta, "provas": self.provas, "valor_em_jogo": self.valor_em_jogo}


def _calendario_do_conselho(raiz: Path) -> list[str]:
    reg = raiz / "estado" / "cmasgyn_registro.json"
    if not reg.exists():
        return []
    try:
        d = json.loads(reg.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return [k for k in d if "calendario" in k.lower()]


def avaliar(provas: list[Prova], repasses: dict, paginas: list[Pagina], raiz: Path = RAIZ) -> list[Situacao]:
    competencia, ausencias = ausencias_da_pasta(raiz)
    nomes = [(_sem_acento(a.get("o_que_falta", "")), a) for a in ausencias]
    nf_fmas = [p for p in provas if p.criterio == "O.1" and "Assistência Social" in p.descricao]
    cmas_paginas = [p for p in paginas if p.ok and p.fonte in ("e_cmas", "e_portal")]
    out: list[Situacao] = []
    for o in OBRIGACOES:
        faltas = [f"{a['o_que_falta']} ({a.get('periodo') or competencia}): não publicado, segundo o parecer {competencia}"
                  for n, a in nomes for chave in o.ausencias if chave in n]
        if o.id == "F3" and nf_fmas:
            faltas.append(nf_fmas[0].descricao)
        publicadas = [p.url for p in cmas_paginas if o.termos and all(t in p.norm for t in o.termos) and tem_dado(p)]
        if o.id == "C2":
            publicadas += [f"calendário das plenárias guardado no acervo: {k}" for k in _calendario_do_conselho(raiz)]
        valor = repasses.get("total", 0.0) if o.usa_repasses else 0.0
        if faltas:
            out.append(Situacao(o, "em falta", faltas + [f"publicação vista: {u}" for u in publicadas[:2]], valor))
        elif publicadas and o.id != "C2":
            out.append(Situacao(o, "publicado", [f"publicação vista: {u}" for u in publicadas[:3]]))
        elif o.id == "C2" and publicadas and not faltas:
            out.append(Situacao(o, "publicado", publicadas[:3]))
        else:
            out.append(Situacao(o, "sem dado", ["nenhuma publicação comprovada nas fontes lidas; ausência de dado é "
                                                "alerta de descumprimento de transparência"], valor))
    return out


def achados(situacoes: list[Situacao], repasses: dict, mes: str) -> list[Achado]:
    """Um achado por obrigação sem publicação comprovada, no formato das conferências."""
    lista = []
    for s in situacoes:
        if not s.alerta:
            continue
        o = s.obrigacao
        fmas = o.orgao == "FMAS"
        desc = (f"{o.texto[:1].lower() + o.texto[1:]}: {s.estado}. " + " ".join(s.provas[:3]))
        if o.usa_repasses and repasses.get("total"):
            desc += (f" O Fundo Nacional repassou {reais(repasses['total'])} ao FMAS entre "
                     f"{min(repasses['por_ano'])} e {repasses.get('ultima')}.")
        lista.append(Achado("fundo_sem_transparencia" if fmas else "conselho_sem_transparencia",
                            CNPJ_FMAS if fmas else "", FMAS if fmas else CMAS, f"{o.id}", mes, desc.strip(),
                            s.valor_em_jogo, 0.0, {"obrigacao": o.id, "base": o.base, "estado": s.estado,
                                                   "pntp": o.pntp}))
    return lista
