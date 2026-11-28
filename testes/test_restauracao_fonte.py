"""Travas da restauração do dado da fonte (decisão do usuário de 28/11/2026, 11:18Z, config/decisoes_usuario.yml,
P-01): ``python -m onisciente restaurar-fonte`` devolve o que o sistema mascarou, prova cada linha pelo rastreio
antigo, devolve o hash das folhas retiradas sem reescrever rodada antiga e lista o que precisa ser lido de novo.

O banco daqui é montado como o real: uma coleta com o CPF inteiro (a "versão do git" antes da máscara), depois a
máscara antiga (rodadas ``mascara_cpf`` que retiraram as folhas) e uma coleta já mascarada, sem original.
Os CPFs são fictícios ou o número de exemplo dos validadores públicos de CPF.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from onisciente import historico, rastreio
from onisciente import restauracao_fonte as R
from onisciente.coletores import goiania_transweb as G
from onisciente.coletores import motores_federais as mf
from test_retirada_privacidade import CNPJ, CPF_A, CPF_C, mascarar_como_antes

CPF_EXEMPLO = "52998224725"
FORMATADO = "529.982.247-25"


def _evento(emp, doc, credor, hist="", data="2025-03-10", tipo="empenho", sha="a" * 64):
    return {"tipo": tipo, "empenho": emp, "data": data, "orgao": "SAUDE", "valor": 100.0, "documento": doc,
            "credor": credor, "historico": hist, "consulta": "despesas_favorecido", "sha256": sha,
            "coletado_em": "2026-11-27"}


def _copiar_versao(origem: Path, destino: Path) -> Path:
    destino.mkdir(parents=True)
    for nome in R.ARQUIVOS:
        if (origem / nome).exists():
            shutil.copy(origem / nome, destino / nome)
    if (origem / "despesa").is_dir():
        (destino / "despesa").mkdir()
        for gz in (origem / "despesa").glob("*.jsonl.gz"):
            shutil.copy(gz, destino / "despesa" / gz.name)
    return destino


def _montar(tmp_path: Path):
    pasta = tmp_path / "banco"
    b = historico.Banco(pasta / "historico.db")
    mf.preparar(b)
    G.criar_tabelas(b.con)
    b.con.commit()
    b.fechar()
    b = historico.Banco.abrir(pasta / "historico.db")
    c = b.con
    rid = rastreio.abrir_rodada(c, ["sancoes", "execucao_goiania"])
    b.inserir("coletas", {"motor": "sancoes", "alvo": "CEIS", "mes": "2026-10", "url": "https://x/ceis", "ok": 1,
                          "http": 200, "bytes": 10, "sha256": "e" * 64})
    b.inserir("sancoes", {"cnpj_cpf": CPF_A, "cadastro": "CEIS", "nome": f"FULANO {CPF_A}", "inicio": "2025-01-01"})
    b.inserir("sancoes", {"cnpj_cpf": CNPJ, "cadastro": "CEIS", "nome": "EMPRESA", "inicio": "2025-01-01"})
    b.inserir("contratos_pncp", {"pncp_id": "k1", "fornecedor_ni": CPF_C, "fornecedor": "CICLANO"})
    G.gravar(c, [_evento("1", CPF_EXEMPLO, f"FULANO DE TAL {CPF_EXEMPLO}", f"TOMADOR CPF:{FORMATADO}"),
                 _evento("2", "31537116000198", "GMS LTDA", f"PROCESSO DE FULANO CPF {FORMATADO}"),
                 _evento("3", "31537116000198", "GMS LTDA", "SEM CPF"),
                 _evento("9", CPF_EXEMPLO, "FULANO DE TAL")])
    c.commit()
    rastreio.fechar_rodada(c, rid)
    b.fechar()
    antiga = _copiar_versao(pasta, tmp_path / "v_antes")          # o que o git guardou antes da máscara
    b = historico.Banco.abrir(pasta / "historico.db")
    c = b.con
    # A coleta seguinte relê o empenho 9 (outro sha256) e tira o 3: o selo antigo dele fica descartado.
    rid = rastreio.abrir_rodada(c, ["execucao_goiania"])
    c.execute("UPDATE despesa_eventos SET sha256 = ? WHERE empenho = '9'", ("b" * 64,))
    c.execute("DELETE FROM despesa_eventos WHERE empenho = '3'")
    c.commit()
    rastreio.fechar_rodada(c, rid)
    b.fechar()
    segunda = _copiar_versao(pasta, tmp_path / "v_releitura")     # a versão seguinte do git, ainda sem máscara
    b = historico.Banco.abrir(pasta / "historico.db")
    c = b.con
    # A máscara antiga: a do banco (sanções e contratos) e a da despesa (coletor D2), cada uma na sua rodada.
    assert mascarar_como_antes(c, ("sancoes", "contratos_pncp")) == 2
    rid = rastreio.abrir_rodada(c, ["execucao_goiania"], rastreio.MODO_MASCARA)
    for rowid, doc, credor, hist in c.execute("SELECT rowid, documento, credor, historico FROM despesa_eventos")\
            .fetchall():
        c.execute("UPDATE despesa_eventos SET documento = ?, credor = ?, historico = ? WHERE rowid = ?",
                  (G.documento_gravavel(doc), G.texto_gravavel(credor), G.texto_gravavel(hist), rowid))
    c.commit()
    rastreio.fechar_rodada(c, rid)
    # Uma coleta depois da máscara: o empenho 7 só existe mascarado (sem original no git).
    rid = rastreio.abrir_rodada(c, ["execucao_goiania"])
    G.gravar(c, [_evento("7", "***.111.222-**", "BELTRANO", data="2026-02-01")])
    # E o empenho 9 relido já mascarado (outro sha256): a linha refeita nunca existiu inteira; a prova é a
    # linha antiga, que só difere dela na proveniência.
    c.execute("UPDATE despesa_eventos SET sha256 = ? WHERE empenho = '9'", ("c" * 64,))
    c.commit()
    rastreio.fechar_rodada(c, rid)
    b.fechar()
    return pasta / "historico.db", {"v_antes": antiga, "v_releitura": segunda}


def _antigos(caminho: Path, antiga: dict) -> R.Antigos:
    b = historico.Banco.abrir(caminho)
    atuais = dict(b.con.execute("SELECT id, hash FROM rastreio_rodadas WHERE hash IS NOT NULL"))
    b.con.close()
    return R.ler_antigos(antiga, atuais)


def test_restaura_o_que_o_sistema_mascarou_com_prova_e_lista_o_que_reler(tmp_path):
    caminho, antiga = _montar(tmp_path)
    assert R.mascarados_pelo_sistema(caminho) == {("sancoes", "cnpj_cpf"): 1, ("sancoes", "nome"): 1,
                                                  ("contratos_pncp", "fornecedor_ni"): 1,
                                                  ("despesa_eventos", "documento"): 3,
                                                  ("despesa_eventos", "credor"): 1,
                                                  ("despesa_eventos", "historico"): 2}
    b = historico.Banco.abrir(caminho)
    c = b.con
    retiradas = len(rastreio.retiradas(c))
    assert retiradas >= 6                                # as folhas com CPF e as descartadas antes, por precaução
    antes = c.execute("SELECT id, raiz, tabelas, hash FROM rastreio_rodadas ORDER BY id").fetchall()
    plano = R.planejar(c, _antigos(caminho, antiga))
    devolucao = R.planejar_devolucao(c, _antigos(caminho, antiga))
    por = {(r["tabela"], r["prova"]) for r in plano.restaurar}
    assert {r["tabela"] for r in plano.restaurar} == {"sancoes", "contratos_pncp", "despesa_eventos"}
    assert ("despesa_eventos", "linha_antiga") in por       # o empenho 9, relido mascarado com outro sha256
    assert ("sancoes", "hash") in por and ("despesa_eventos", "hash") in por
    assert plano.reler["despesa_eventos"]["sem original no git"] == 1
    assert plano.reler["despesa_eventos"]["mês 2026-02"] == 1
    assert devolucao["provados"] == retiradas and devolucao["sem_prova"] == {}
    feito = R.aplicar(b, plano, devolucao)
    assert sum(feito["linhas"].values()) == len(plano.restaurar) and not feito["conflitos"]
    v = rastreio.verificar(c)
    assert v["integro"], v
    assert v["cadeia"]["devolvidas"]["total"] == retiradas
    assert not any("candidatos" in p["motivo"] for p in v["cadeia"]["problemas"])   # nada mais retirado
    # As rodadas antigas não mudaram; a nova é a da restauração, com as devoluções declaradas.
    depois = c.execute("SELECT id, raiz, tabelas, hash FROM rastreio_rodadas ORDER BY id").fetchall()
    assert depois[:len(antes)] == antes
    modo, detalhe = c.execute("SELECT modo, detalhe FROM rastreio_rodadas ORDER BY id DESC LIMIT 1").fetchone()
    assert modo == R.MODO and '"devolvidas"' in detalhe
    assert rastreio.retiradas(c) and len(rastreio.retiradas(c)) == retiradas          # as marcas ficam
    # O dado da fonte voltou; o empenho 7 continua como veio (vai para a releitura).
    docs = dict(c.execute("SELECT empenho, documento FROM despesa_eventos"))
    assert docs == {"1": CPF_EXEMPLO, "2": "31537116000198", "9": CPF_EXEMPLO, "7": "***.111.222-**"}
    assert c.execute("SELECT credor, historico FROM despesa_eventos WHERE empenho = '1'").fetchone() == \
        (f"FULANO DE TAL {CPF_EXEMPLO}", f"TOMADOR CPF:{FORMATADO}")
    assert c.execute("SELECT cnpj_cpf, nome FROM sancoes WHERE cadastro = 'CEIS' AND nome LIKE 'FULANO%'")\
        .fetchone() == (CPF_A, f"FULANO {CPF_A}")
    assert c.execute("SELECT fornecedor_ni FROM contratos_pncp").fetchone() == (CPF_C,)
    b.fechar()
    assert R.mascarados_pelo_sistema(caminho) == {("despesa_eventos", "documento"): 1}
    # Abrir de novo não muda nada, e rodar de novo não acha mais nada para restaurar nem para devolver.
    b = historico.Banco.abrir(caminho)
    assert R.planejar(b.con, _antigos(caminho, antiga)).restaurar == []
    assert R.planejar_devolucao(b.con, _antigos(caminho, antiga))["provados"] == 0
    assert rastreio.verificar(b.con)["integro"]
    b.fechar()


def test_devolucao_adulterada_e_acusada(tmp_path):
    caminho, antiga = _montar(tmp_path)
    b = historico.Banco.abrir(caminho)
    c = b.con
    R.aplicar(b, R.planejar(c, _antigos(caminho, antiga)), R.planejar_devolucao(c, _antigos(caminho, antiga)))

    def acusa(sql, args=()):
        c.execute("SAVEPOINT adulterar")
        c.execute(sql, args)
        try:
            return [p for p in rastreio.verificar_cadeia(c)["problemas"] if p["grave"]]
        finally:
            c.execute("ROLLBACK TO adulterar")
            c.execute("RELEASE adulterar")

    assert acusa("DELETE FROM rastreio_devolvidas WHERE retirada = (SELECT min(retirada) FROM rastreio_devolvidas)")
    assert acusa("UPDATE rastreio_selos SET hash = zeroblob(32) WHERE hash = (SELECT hash FROM rastreio_devolvidas "
                 "LIMIT 1)")
    assert not [p for p in rastreio.verificar_cadeia(c)["problemas"] if p["grave"]]
    b.fechar()


def test_folha_que_nao_refaz_a_raiz_nao_volta(tmp_path):
    caminho, antiga = _montar(tmp_path)
    antigos = _antigos(caminho, antiga)
    # Uma versão "antiga" com um hash trocado não prova nada: a raiz da rodada original não fecha.
    for chave, selos in antigos.selos.items():
        if chave[0] == "sancoes":
            h = next(iter(selos))
            selos[bytes(32)] = selos.pop(h)
    b = historico.Banco.abrir(caminho)
    d = R.planejar_devolucao(b.con, antigos)
    assert d["sem_prova"] and all(g["tabela"] != "sancoes" for g in d["grupos"])
    b.con.close()


def test_o_comando_sem_gravar_nao_muda_o_banco(tmp_path, monkeypatch):
    caminho, antiga = _montar(tmp_path)
    monkeypatch.setattr(R, "versoes", lambda de: list(antiga))
    monkeypatch.setattr(R, "extrair", lambda commit, cache: antiga[commit])
    arquivos = {p: p.read_bytes() for p in caminho.parent.rglob("*") if p.is_file() and p.suffix in (".db", ".gz")}
    r = R.rodar(caminho, "v_antes", cache=tmp_path / "cache")
    assert r["restauradas"]["despesa_eventos"]["total"] == 3 and r["folhas"]["provadas_pela_raiz"] >= 6
    assert {p: p.read_bytes() for p in arquivos} == arquivos
    r = R.rodar(caminho, "v_antes", cache=tmp_path / "cache", gravar=True)
    assert r["verificacao"]["integro"] and r["aplicado"]["linhas"]["despesa_eventos"] == 3


def test_linha_que_volta_em_parte_tambem_vai_para_a_releitura():
    """Uma linha coletada entre a máscara do documento (24fc099) e a do credor (91240af): o git guarda o credor
    inteiro e o documento já mascarado. O credor volta, provado pelo hash; o documento segue mascarado e a linha
    entra na contagem do que ler de novo (decisão do usuário de 28/11/2026, 11:18Z, P-01)."""
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE despesa_eventos (tipo, empenho, data, orgao, valor, documento, credor, historico, "
                "consulta, sha256, coletado_em)")
    antiga = _evento("5", "***.982.247-**", f"FULANO DE TAL {FORMATADO}")
    atual = {**antiga, "credor": G.texto_gravavel(antiga["credor"])}
    assert atual["credor"] != antiga["credor"] and R.tem_mascara(atual["credor"])
    con.execute(f"INSERT INTO despesa_eventos ({', '.join(atual)}) VALUES ({', '.join('?' * len(atual))})",
                list(atual.values()))
    antigos = R.Antigos(linhas={"despesa_eventos": {R._chave(R.mascarar("despesa_eventos", antiga)):
                                                    [("vX", antiga)]}},
                        folhas={"despesa_eventos": {rastreio._digest("despesa_eventos", antiga)}})
    plano = R.planejar(con, antigos)
    assert [(r["prova"], r["valores"]) for r in plano.restaurar] == [("hash", {"credor": antiga["credor"]})]
    assert plano.reler["despesa_eventos"]["voltou em parte; o resto sem original no git"] == 1
    assert plano.reler["despesa_eventos"]["coluna documento"] == 1
    assert plano.reler["despesa_eventos"]["mês 2025-03"] == 1
