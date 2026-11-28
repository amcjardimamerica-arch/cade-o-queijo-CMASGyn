"""Travas do rastreio com as folhas retiradas pela máscara (28/11/2026), depois da revogação.

Revogação (decisão do usuário de 28/11/2026, 11:18Z, config/decisoes_usuario.yml, P-01: "Os dados devem ser
públicos e não mascarar"): a máscara do CPF e a retirada do hash por privacidade saíram. Nenhuma abertura do Banco
mascara nem retira mais nada, e o ``restaurar-fonte`` devolve o hash das folhas retiradas numa rodada
``restauracao_fonte``. Saíram daqui, revogadas pela mesma decisão (não para fazer teste passar):

* test_depois_da_migracao_nenhum_hash_do_rastreio_bate_com_uma_linha_de_cpf_completo (exigia o hash fora do
  rastreio; agora ele volta);
* test_a_marca_fica_no_lugar_do_hash_com_a_rodada_e_o_selo_novo e
  test_rodada_de_mascara_antiga_tem_as_folhas_retiradas_numa_rodada_propria (exigiam a migração da máscara e a
  retirada na abertura do Banco);
* test_o_hash_retirado_nao_fica_nos_bytes_do_arquivo (privacidade do hash, revogada).

Ficam as que defendem a verificação do que já está no banco real: as rodadas antigas de máscara retiraram folhas,
e a cadeia continua verificável com elas, acusando adulteração. A máscara antiga é refeita aqui como as rodadas
antigas faziam (uma rodada ``mascara_cpf`` aberta direto no rastreio), só para reproduzir o banco real.

Os CPFs daqui são fictícios (dígito verificador válido, gerado pelo próprio teste).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from onisciente import historico, mascara_banco, mascara_cpf, rastreio
from onisciente.coletores import motores_federais as mf


def _cpf(base9: str) -> str:
    d = [int(x) for x in base9]
    for _ in range(2):
        s = sum(v * p for v, p in zip(d, range(len(d) + 1, 1, -1)))
        d.append(0 if s % 11 < 2 else 11 - s % 11)
    return "".join(map(str, d))


CPF_A = _cpf("529982247")
CPF_B = _cpf("111444777")
CPF_C = _cpf("390533447")
CPF_D = _cpf("861234570")
CNPJ = "12345678000195"


def _linhas_com_cpf(con) -> set[bytes]:
    """O hash de toda linha do banco que tem CPF completo (o que não pode sobrar no rastreio)."""
    achados = set()
    for t in rastreio.tabelas_de_dados(con):
        for _, campos in rastreio._linhas(con, t):
            if any(isinstance(v, str) and mascara_banco.cpfs_no_valor(k, v) for k, v in campos.items()):
                achados.add(rastreio._digest(t, campos))
    return achados


def _hashes_no_rastreio(caminho: Path) -> tuple[set[bytes], str]:
    """Tudo o que o rastreio.db guarda: os BLOBs de 32 bytes e todo o texto (onde um hash em hex caberia)."""
    con = sqlite3.connect(f"file:{rastreio.caminho_do_rastreio(caminho)}?mode=ro", uri=True)
    blobs: set[bytes] = set()
    textos: list[str] = []
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
        for linha in con.execute(f'SELECT * FROM "{t}"'):
            for v in linha:
                if isinstance(v, bytes):
                    blobs.add(v)
                    textos.append(v.hex())
                elif v is not None:
                    textos.append(str(v))
    con.close()
    return blobs, "\n".join(textos).lower()


def _vazados(caminho: Path, digests: set[bytes]) -> list[str]:
    """Os hashes que ainda estão no rastreio.db: nas tabelas ou nos bytes crus do arquivo (o SQLite deixa o
    conteúdo apagado nas páginas livres se ninguém zerar)."""
    blobs, texto = _hashes_no_rastreio(caminho)
    cru = rastreio.caminho_do_rastreio(caminho).read_bytes()
    return sorted(h.hex()[:16] for h in digests if h in blobs or h.hex() in texto or h in cru)


def _montar(tmp_path: Path) -> tuple[Path, set[bytes]]:
    """Um banco gravado antes da máscara (direto pela conexão, como as rodadas antigas): sanções, contratos,
    impedimentos e uma tabela de despesa mascarada por outro coletor. Uma linha com CPF foi refeita por uma
    coleta antes da máscara (o selo dela ficou descartado por uma rodada comum). Devolve o caminho e o hash de
    cada versão de linha com CPF completo que passou pelo banco."""
    b = historico.Banco(tmp_path / "historico.db")
    mf.preparar(b)
    b.con.execute("CREATE TABLE IF NOT EXISTS impedimentos (cnpj_cpf TEXT, cadastro TEXT, inicio TEXT, fim TEXT, "
                  "orgao TEXT, tipo TEXT, nome TEXT, processo TEXT, fonte TEXT, data_base TEXT)")
    b.con.execute("CREATE TABLE despesa_avulsa (credor TEXT, valor REAL, empenho INTEGER)")
    b.con.commit()
    b.fechar()
    b = historico.Banco.abrir(tmp_path / "historico.db")
    c = b.con
    vistos: set[bytes] = set()
    rid = rastreio.abrir_rodada(c, ["sancoes"])
    b.inserir("coletas", {"motor": "sancoes", "alvo": "CEIS", "mes": "2026-10", "url": "https://x/ceis", "ok": 1,
                          "http": 200, "bytes": 10, "sha256": "e" * 64})
    c.execute("INSERT INTO sancoes (cnpj_cpf, cadastro, nome, inicio) VALUES (?, 'CEIS', ?, '2025-01-01')",
              (CPF_A, f"FULANO {CPF_A}"))
    c.execute("INSERT INTO sancoes (cnpj_cpf, cadastro, nome, inicio) VALUES (?, 'CEIS', 'EMPRESA', '2025-01-01')",
              (CNPJ,))
    c.execute("INSERT INTO sancoes (cnpj_cpf, cadastro, nome, inicio) VALUES (?, 'CNEP', 'VELHO', '2024-01-01')",
              (CPF_D,))
    c.execute("INSERT INTO contratos_pncp (pncp_id, fornecedor_ni, fornecedor) VALUES ('k1', ?, 'CICLANO')",
              (CPF_C,))
    c.execute("INSERT INTO impedimentos (cnpj_cpf, cadastro, nome) VALUES (?, 'TCU', 'BELTRANO')", (CPF_B,))
    c.execute("INSERT INTO despesa_avulsa VALUES (?, 1234.5678901234567, 7)", (f"{CPF_B} BELTRANO",))
    c.execute("INSERT INTO despesa_avulsa VALUES ('EMPRESA LTDA', 0.1, 8)")
    rastreio.fechar_rodada(c, rid)
    vistos |= _linhas_com_cpf(c)
    # A coleta seguinte refaz a sanção do CPF_D (o selo antigo fica descartado por uma rodada comum).
    rid = rastreio.abrir_rodada(c, ["sancoes"])
    c.execute("UPDATE sancoes SET inicio = '2024-02-01' WHERE cnpj_cpf = ?", (CPF_D,))
    rastreio.fechar_rodada(c, rid)
    vistos |= _linhas_com_cpf(c)
    # Outro coletor (como o da despesa de Goiânia) mascara a tabela dele numa rodada de máscara.
    rid = rastreio.abrir_rodada(c, ["execucao_goiania"], "mascara_cpf", detalhe={"nota": "despesa avulsa"})
    c.execute("UPDATE despesa_avulsa SET credor = ? WHERE credor LIKE ?", (f"{mascara_cpf.mascara(CPF_B)} BELTRANO",
                                                                          f"{CPF_B}%"))
    c.commit()
    rastreio.fechar_rodada(c, rid)
    mascarar_como_antes(c)
    assert len(vistos) == 6
    b.fechar()
    return tmp_path / "historico.db", vistos


def mascarar_como_antes(c, tabelas=("sancoes", "contratos_pncp", "impedimentos")) -> int:
    """O que a abertura do Banco fazia entre ee68c14 e a revogação de 28/11/2026 (mascara_banco.migrar): uma
    rodada ``mascara_cpf`` que troca o CPF pela máscara e, ao fechar, retira o hash das folhas antigas. Só para
    reproduzir o banco real nas travas; nenhum módulo do onisciente faz isso mais (P-01)."""
    rid = rastreio.abrir_rodada(c, ["mascara_banco"], rastreio.MODO_MASCARA,
                                detalhe={"nota": "reprodução da máscara antiga"})
    n = 0
    for t in tabelas:
        cols = [x[1] for x in c.execute(f"PRAGMA table_info({t})")]
        for rowid, *vals in c.execute(f"SELECT rowid, * FROM {t}").fetchall():
            linha = dict(zip(cols, vals))
            nova = mascara_banco.mascarar_linha(t, linha)
            mudou = {k: v for k, v in nova.items() if linha.get(k) != v}
            if mudou:
                c.execute(f"UPDATE {t} SET {', '.join(f'{k} = ?' for k in mudou)} WHERE rowid = ?",
                          [*mudou.values(), rowid])
                n += 1
    c.commit()
    rastreio.fechar_rodada(c, rid)
    return n


def test_verificacao_integra_com_folhas_retiradas_e_acusa_adulteracao(tmp_path):
    caminho, _ = _montar(tmp_path)
    b = historico.Banco.abrir(caminho)
    c = b.con
    v = rastreio.verificar_cadeia(c)
    assert v["ok"], v
    # Poucas folhas retiradas numa tabela (aqui, uma a três): a raiz guardada ainda deixa testar candidatos;
    # a verificação avisa, sem acusar adulteração.
    assert any(not p["grave"] and "candidatos" in p["motivo"] for p in v["problemas"])
    primeira = c.execute("SELECT id, raiz, tabelas FROM rastreio_rodadas WHERE modo = 'coleta' ORDER BY id").fetchone()

    def acusa(sql, args=()):
        c.execute("SAVEPOINT adulterar")
        c.execute(sql, args)
        try:
            return [p for p in rastreio.verificar_cadeia(c)["problemas"] if p["grave"]]
        finally:
            c.execute("ROLLBACK TO adulterar")
            c.execute("RELEASE adulterar")

    # A raiz gravada da rodada que perdeu folhas, trocada: o hash da rodada não confere.
    assert acusa("UPDATE rastreio_rodadas SET raiz = ? WHERE id = ?", ("0" * 64, primeira[0]))
    # A raiz da tabela que perdeu folhas, trocada no registro da rodada: idem.
    assert acusa("UPDATE rastreio_rodadas SET tabelas = replace(tabelas, '\"sancoes\": [', '\"sancoes\": [9') "
                 "WHERE id = ?", (primeira[0],))
    # Um selo que ficou na tabela que perdeu folhas, apagado: a contagem não fecha.
    sid = c.execute("SELECT id FROM rastreio_tabelas WHERE nome = 'sancoes'").fetchone()[0]
    problemas = acusa("DELETE FROM rastreio_selos WHERE tabela = ? AND rodada = ? AND descartada IS NULL",
                      (sid, primeira[0]))
    assert problemas and problemas[0]["tabelas"] == ["sancoes"]
    # Um selo apagado e disfarçado de retirada (marca inventada): a marca não está declarada.
    h, origem = c.execute("SELECT hash, origem FROM rastreio_selos WHERE tabela = ? AND rodada = ? AND "
                          "descartada IS NULL", (sid, primeira[0])).fetchone()
    c.execute("SAVEPOINT disfarce")
    c.execute("DELETE FROM rastreio_selos WHERE tabela = ? AND hash = ?", (sid, h))
    ultima = c.execute("SELECT max(id) FROM rastreio_rodadas").fetchone()[0]
    c.execute("INSERT INTO rastreio_retiradas (tabela, rodada, origem, n, descartada, retirada_por, motivo) VALUES "
              "(?, ?, ?, 1, NULL, ?, ?)", (sid, primeira[0], origem, ultima, rastreio.MOTIVO_MASCARA))
    disfarce = [p for p in rastreio.verificar_cadeia(c)["problemas"] if p["grave"]]
    c.execute("ROLLBACK TO disfarce")
    c.execute("RELEASE disfarce")
    assert any("retiradas" in p["motivo"] for p in disfarce)
    # Uma marca apagada: o total declarado não fecha.
    assert acusa("DELETE FROM rastreio_retiradas WHERE id = (SELECT min(id) FROM rastreio_retiradas)")
    # As outras tabelas da mesma rodada continuam com a raiz refeita: um selo trocado lá é acusado.
    cid = c.execute("SELECT id FROM rastreio_tabelas WHERE nome = 'coletas'").fetchone()[0]
    assert acusa("UPDATE rastreio_selos SET hash = zeroblob(32) WHERE tabela = ? AND rodada = ?",
                 (cid, primeira[0]))
    assert rastreio.verificar(c)["integro"]
    b.fechar()


@pytest.mark.parametrize("valor", [1234.5678901234567, 0.1, 1e-300])
def test_o_selo_novo_acha_a_linha_mesmo_com_numero_real(tmp_path, valor):
    """A marca aponta o selo novo pelo conteúdo de antes, guardado pelo gatilho: o número real volta igual."""
    b = historico.Banco(tmp_path / "historico.db")
    b.con.execute("CREATE TABLE avulsa (credor TEXT, valor REAL, dado BLOB)")
    b.con.commit()
    rid = rastreio.abrir_rodada(b.con, [])
    b.con.execute("INSERT INTO avulsa VALUES (?, ?, ?)", (CPF_A, valor, b"\x00\x01"))
    rastreio.fechar_rodada(b.con, rid)
    rid = rastreio.abrir_rodada(b.con, [], "mascara_cpf")
    b.con.execute("UPDATE avulsa SET credor = ?", (mascara_cpf.mascara(CPF_A),))
    rastreio.fechar_rodada(b.con, rid)
    (m,) = rastreio.retiradas(b.con)
    assert m["novo"] == rastreio.hash_do_registro(b.con, "avulsa", 1)
    b.fechar()


