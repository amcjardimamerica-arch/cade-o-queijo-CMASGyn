"""Custo fixo que muda sem aditivo (regra CUSTO-FIXO-SEM-ADITIVO).

Sobre os contratos e os termos do PNCP guardados no banco, três conferências:

1. **O termo não fecha.** O valor global que passa a valer depois de um termo tem de ser o valor
   anterior mais o acréscimo (ou menos a supressão) que o próprio termo declara. Diferença acima
   do limiar (um real) é mudança de valor sem instrumento.
2. **Mudou sem termo.** O valor global ou o acumulado do contrato diferente do valor inicial sem
   nenhum termo publicado.
3. **Prorrogou sem valor.** Termo que prorroga a vigência sem valor publicado: o serviço continua
   e o custo do novo período não tem número no PNCP.

O limite de 25% dos acréscimos fica na conferência de compras (ADITIVO-LIMITE); aqui o corte é o
centavo.
"""

from __future__ import annotations

from collections import defaultdict

from ..nucleo.indicios import Familia, emitir
from ..nucleo.provas import Nivel
from ..nucleo.selos import Selo
from .banco import Base, Linha, Parte, Quadro, moeda

REGRA = "CUSTO-FIXO-SEM-ADITIVO"


def _contratos(base: Base) -> dict[str, dict]:
    if not (base.tem("pncp_contratos_detalhe") and base.tem("contratos_pncp")):
        return {}
    saida = {}
    for cid, orgao, forn, objeto, assinatura, ini, glob, acum, vfim in base.con.execute(
            "select c.pncp_id, c.orgao, c.fornecedor, c.objeto, c.data_assinatura, d.valor_inicial, d.valor_global, "
            "d.valor_acumulado, d.vigencia_fim from contratos_pncp c join pncp_contratos_detalhe d "
            "on d.contrato_id = c.pncp_id where coalesce(c.data_assinatura, c.mes) <= ?",
            (base.ate.isoformat(),)):
        saida[cid] = {"orgao": orgao or "", "fornecedor": forn or "", "objeto": (objeto or "").strip(),
                      "inicial": ini, "global": glob, "acumulado": acum, "vigencia_fim": vfim or ""}
    return saida


def achados(base: Base) -> list[dict]:
    regra = base.mapa.regra(REGRA)
    tol = float(regra.valor if regra.valor is not None else 1.0)
    contratos = _contratos(base)
    termos: dict[str, list[tuple]] = defaultdict(list)
    if base.tem("pncp_termos"):
        for linha in base.con.execute(
                "select contrato_id, sequencial, tipo, data_assinatura, vigencia_fim, valor_acrescido, valor_global, "
                "prazo_aditado_dias, acrescimo_supressao, qualif_vigencia, qualif_reajuste from pncp_termos "
                "where coalesce(data_assinatura, '') <= ? order by contrato_id, sequencial",
                (base.ate.isoformat(),)):
            termos[linha[0]].append(linha[1:])
    saida = []
    for cid, c in contratos.items():
        inicial = c["inicial"]
        if inicial is None or inicial <= 0:
            continue
        lista = termos.get(cid, [])
        anterior = float(inicial)
        for seq, tipo, data, vfim, acresc, glob, prazo, acsup, qvig, qreaj in lista:
            tipo_n = (tipo or "").lower()
            if "rescis" in tipo_n:
                continue
            prorroga = bool(qvig) or bool(prazo) or (vfim and c["vigencia_fim"] and vfim > c["vigencia_fim"])
            if glob is not None and acresc is not None and abs(glob - acresc) <= tol and acresc > 0 \
                    and abs(glob - anterior) > tol and glob < anterior:
                # O PNCP guardou no campo do valor global só o valor do próprio termo: não é o novo total.
                anterior = anterior + acresc
                continue
            if glob is not None and glob > 0:
                if acresc is not None:
                    esperado = anterior + acresc
                elif acsup:                        # supressão declarada sem valor: aceita a redução
                    esperado = glob if glob <= anterior else anterior
                else:
                    esperado = anterior
                if abs(glob - esperado) > tol:
                    saida.append({"tipo": "nao_fecha", "contrato": cid, "data": (data or "")[:10], **c,
                                  "anterior": anterior, "acrescimo": acresc, "novo": glob,
                                  "diferenca": round(glob - esperado, 2), "termo": seq})
                anterior = glob
            elif prorroga and not (acresc or 0) and not (glob or 0) and "apostil" not in tipo_n:
                saida.append({"tipo": "prorroga_sem_valor", "contrato": cid, "data": (data or "")[:10], **c,
                              "anterior": anterior, "acrescimo": acresc, "novo": glob, "diferenca": None,
                              "termo": seq, "ate": vfim})
            elif acresc:
                anterior += acresc
        if not lista:
            atual = max(c["global"] or 0.0, c["acumulado"] or 0.0)
            if atual and abs(atual - inicial) > tol:
                saida.append({"tipo": "sem_termo", "contrato": cid, "data": "", **c, "anterior": inicial,
                              "acrescimo": None, "novo": atual, "diferenca": round(atual - inicial, 2),
                              "termo": None})
    return saida


TITULOS = {
    "nao_fecha": "o valor global depois do termo não fecha com o que o termo declara",
    "sem_termo": "o valor mudou sem nenhum termo publicado",
    "prorroga_sem_valor": "a vigência foi prorrogada sem valor publicado para o novo período",
}


def conferir(base: Base) -> Parte:
    parte = Parte()
    regra = base.mapa.regra(REGRA)
    lista = achados(base)
    if not lista:
        if base.tem("pncp_termos"):
            parte.notas.append("Custo fixo: nenhum contrato com valor mudando além do que os termos declaram.")
        return parte
    q = Quadro(5, "Custo fixo: contratos cujo valor muda além do que o termo publicado declara",
               "Contratos e termos publicados no PNCP pelos órgãos do Município (uma via: o PNCP).",
               ["Contrato", "Fornecedor", "Antes", "Declarado no termo", "Passou a valer", "Diferença"],
               regra=f"{REGRA}: diferença tolerada {moeda(regra.valor)}. {regra.get('justificativa', '')}")
    for a in lista:
        q.linhas.append(Linha(a["contrato"], [a["fornecedor"][:60], moeda(a["anterior"]),
                                              moeda(a["acrescimo"]) if a["acrescimo"] is not None else "sem valor",
                                              moeda(a["novo"]) if a["novo"] else "sem valor",
                                              moeda(a["diferenca"]) if a["diferenca"] is not None else TITULOS[a["tipo"]]],
                              Selo.AZUL, base.coleta("pncp_detalhe")))
        dif = f" (diferença de {moeda(a['diferenca'])})" if a["diferenca"] is not None else ""
        parte.fichas.append(emitir(
            codigo=f"PRC-CUSTOFIXO-{a['contrato']}",
            familia=Familia.PRC,
            titulo=f"Contrato {a['contrato']}: {TITULOS[a['tipo']]}",
            gravidade=regra.gravidade if a["tipo"] != "prorroga_sem_valor" else "media",
            como_deveria=("O valor do contrato só muda por termo aditivo ou apostila publicado no PNCP, e o novo valor "
                          "é o anterior mais o acréscimo declarado (limiar do mapa legal: um real)."),
            norma=regra.norma,
            como_esta=(f"{a['orgao'].title()}; {a['fornecedor']}; {a['objeto'][:160]}. Antes {moeda(a['anterior'])}; "
                       + (f"o termo declara {moeda(a['acrescimo'])}; " if a["acrescimo"] is not None else "")
                       + (f"passou a valer {moeda(a['novo'])}{dif}." if a["novo"] else
                          f"o termo prorroga a vigência até {a.get('ate') or 'data não informada'} sem valor.")),
            niveis=[Nivel.C],
            providencia="Pedir o termo, a planilha de custos e a justificativa da mudança de valor.",
            observacao="indício, não acusação",
        ))
    parte.quadros.append(q)
    return parte
