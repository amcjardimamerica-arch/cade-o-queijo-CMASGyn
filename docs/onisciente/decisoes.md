# Decisões de arquitetura do Onisciente

Cada decisão tem a data, o que foi decidido, por quê e a trava (o teste que falha se a decisão
deixar de valer). Mudar uma decisão é registrar outra aqui, com a nova trava.

## 2026-11-27: o banco continua em SQLite (requisito 156, DuckDB ou Parquet)

**Decidido.** O banco histórico fica em SQLite (`dados/onisciente/historico.db`). Não migra para
DuckDB nem para Parquet agora.

**Por quê.** Medido em 27/11/2026 no banco real, com os dois anos coletados (2024-11 a 2026-11):

| Medida | Valor |
|---|---|
| Tamanho do arquivo | 69 MB |
| Maior tabela | `precos_referencia`, 176.057 linhas |
| Consulta de referência: preço homologado de cada item de catálogo, mês a mês, contra o preço nacional médio do mesmo catálogo (2.587 grupos) | 0,13 s |
| MSC por fonte e função (61.032 linhas) | 0,04 s |
| Diagnóstico completo do banco | 0,05 s |

O volume é pequeno para um banco colunar fazer diferença; as consultas do parecer e do
diagnóstico respondem em décimos de segundo. O SQLite vem com o Python, não pede pacote no
fluxo do GitHub (o contêiner de trabalho não instala nada), abre com qualquer ferramenta e
a coleta incremental da agenda (`onisciente/agenda.py`) usa `ATTACH` para somar uma janela
ao banco sem refazer nada. Com a série estendida até 2019 o banco deve ficar perto de 3,5
vezes o tamanho de hoje, cerca de 250 MB, ainda folgado.

**Quando rever.** Se o arquivo passar de 500 MB ou a consulta de referência passar de 2 s.
As duas medidas são a trava: `testes/test_agenda.py::test_sqlite_atende_o_tamanho_e_a_consulta_de_referencia`.
Se ela falhar, a decisão volta para a mesa (DuckDB lendo o próprio SQLite, ou Parquet por
exercício para as tabelas de itens e preços).

## 2026-11-27: as leis vêm do ctresb/leis e do Sileg direto, sem o leis-mcp (requisito 95)

**Decidido.** O leis-mcp (o servidor MCP do repositório ctresb/leis) não é usado e não é
preciso.

**Por quê.** O que o leis-mcp serve é o mesmo arquivo Markdown do repositório ctresb/leis, com
o cabeçalho que diz se a norma está revogada. O motor `normas` (`onisciente/historico.py`,
com `onisciente/coletores/leis.py`) já lê esse arquivo direto do endereço público
(`raw.githubusercontent.com/ctresb/leis/main/`) e confere o campo `revogada` de cada norma
citada no mapa legal, toda semana, no fluxo `onisciente-agenda-leis.yml`. As leis de Goiânia,
que o ctresb/leis não tem por inteiro, vêm do Sileg da Prefeitura, pelo endereço oficial de
cada norma e pelo índice do Sileg. Um servidor MCP exigiria um cliente MCP rodando no fluxo do
GitHub, uma dependência a mais sem nenhum dado a mais, e o sistema precisa rodar sozinho.

**Trava.** `testes/test_leis.py::test_leis_vem_do_ctresb_e_do_sileg_sem_leis_mcp`: o motor de
normas busca cada lei federal no endereço público do ctresb/leis e cada lei municipal no Sileg,
e nenhum código do Onisciente depende de MCP.
