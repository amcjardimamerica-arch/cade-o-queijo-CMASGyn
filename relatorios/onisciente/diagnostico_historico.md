# Diagnóstico da coleta histórica (2023-11 a 2026-11)

Rodada de 2026-11-28T10:15:39+00:00. Banco: `dados/onisciente/historico.db`.

Vermelho é falha do sistema (a fonte não respondeu). Roxo é lacuna na fonte (ela respondeu e o dado não estava lá). As duas nunca se misturam.

## Motores

| Motor | Chamadas | Certas | Falhas | 429 | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| Cadastro das empresas na Receita Federal (CNPJ e QSA) | 1355 | 1353 | 2 | 0 | 547.0 |
| Normas federais (ctresb/leis) | 21 | 21 | 0 | 0 | 4.0 |
| Cota-parte do Estado (Secretaria da Economia de Goiás) | 8 | 8 | 0 | 0 | 49.6 |
| Execução item a item no portal de Goiânia (TransWeb) | 184 | 184 | 0 | 0 | 200.9 |
| Repasses federais (FNAS) | 5 | 4 | 1 | 0 | 168.4 |
| FNDE (liberações da educação) | 1642 | 1642 | 0 | 0 | 1289.0 |
| Fundo Nacional de Saúde (repasses fundo a fundo) | 114 | 98 | 16 | 0 | 689.5 |
| Portais e endereços configurados | 25 | 20 | 5 | 0 | 253.3 |
| Impedimentos (CEPIM e inidôneos do TCU) | 3 | 1 | 2 | 0 | 1.7 |
| Matriz de Saldos Contábeis (SICONFI) | 36 | 36 | 0 | 0 | 61.6 |
| Contratações (PNCP) | 1063 | 1026 | 37 | 0 | 21399.7 |
| Detalhe das compras e contratos (PNCP e Compras.gov.br) | 13822 | 13822 | 0 | 0 | 61283.7 |
| Diário Oficial pelo Querido Diário | 74 | 24 | 50 | 0 | 319.6 |
| Empresas punidas (CEIS e CNEP) | 4 | 4 | 0 | 0 | 1.4 |
| SICONFI (Tesouro Nacional) | 33 | 33 | 0 | 0 | 24.1 |
| SICONFI pelos endereços antigos | 2 | 0 | 2 | 0 | 1.2 |
| Diário Oficial pelo índice do SILEG | 74 | 74 | 0 | 0 | 25.1 |
| Leis de Goiânia baixadas do SILEG | 47 | 47 | 0 | 0 | 25.2 |
| Procura das leis não localizadas no SILEG | 15 | 15 | 0 | 0 | 6.8 |
| Demonstrativo da educação (SIOPE) | 23 | 22 | 1 | 0 | 185.4 |
| Demonstrativo da saúde (SIOPS) | 25 | 25 | 0 | 0 | 38.9 |
| Decisões do TCM-GO | 12 | 6 | 6 | 0 | 20.6 |
| Decisões do TCU | 6 | 5 | 1 | 1 | 131.5 |
| Transferências constitucionais (Tesouro) | 2 | 0 | 2 | 0 | 248.0 |
| Transferegov (transferências especiais e convênios) | 13 | 1 | 12 | 0 | 223.8 |
| Transferências federais (Portal da Transparência) | 36 | 36 | 0 | 0 | 39.8 |

## O que entrou no banco

- **SICONFI:** 42807 itens; períodos por situação: {"entregue": 29, "no prazo": 1}.
- **Diário Oficial:** edições somadas por via: {"querido_diario": 273, "sileg": 771}.
- **Repasses do FNAS:** 506 linhas, R$ 32.634.427,33.
- **PNCP:** 2328 contratações e 2263 contratos de órgãos do Município (61 da pasta da assistência).
- **Endereços configurados:** 20 de 25 abriram.

## Onde o sistema falha

1. **Repasses federais (FNAS): 1 de 5 chamadas falharam.** Erro mais comum: planilha do ano não publicada na página do FNAS (1 vezes). *Proposta:* Ver a tabela coletas do banco para os endereços exatos.
2. **Contratações (PNCP): 37 de 1063 chamadas falharam.** Erro mais comum: não tentado: tempo do motor nesta rodada esgotado (37 vezes). *Proposta:* Ver a tabela coletas do banco para os endereços exatos.
3. **O Querido Diário não respondeu em 25 de 37 meses.** Meses: 2024-11 a 2026-11. Erro: URLError: [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] ssl/tls alert handshake failure (_ssl.c:1011). *Proposta:* O servidor recusou o aperto de mão TLS (alerta 40), também para o curl e o openssl com TLS 1.2 e 1.3 na mesma máquina: o bloqueio está do lado da fonte, não nas cifras do robô. A outra via fica como principal, e a coleta mensal tenta de novo e avisa quando a fonte voltar.
4. **3 de 25 endereços configurados não abriram.** Painel de preenchimento de prestação de contas (HTTP 404); CNAS — Resoluções (Participa + Brasil) (TimeoutError: The read operation timed out); MDS — Índice de Gestão Descentralizada (HTTP 404) *Proposta:* Marcar cada um como morto em config/portais.yml com o substituto, ou corrigir o endereço.
5. **O coletor antigo do PNCP consulta o Brasil inteiro.** cadeoqueijo/coleta_pncp.py tira os CNPJs do Município de dados/destinatarios_2026.json, que não tem nenhum; sem CNPJ, pede todos os contratos do país e filtra por “GOIANIA” só nas 20 primeiras páginas. Por isso recebeu 429 e achou zero contratos. *Proposta:* Usar os órgãos descobertos pela coleta histórica (código IBGE) e consultar por CNPJ, mês a mês.

## Onde a fonte respondeu sem o dado

1. **O FNAS ainda não publicou a planilha 2026.** A página de extração de repasses não tem a planilha do ano. *Proposta:* Os repasses do ano ficam sem a via federal até a publicação; a coleta mensal confere de novo.
2. **Nenhum contrato do Município no PNCP em 5 meses.** Meses: 2023-11 a 2024-03. Órgãos procurados: 32. *Proposta:* A Lei 14.133/2021 (art. 94) manda divulgar o contrato no PNCP; confirmar no portal municipal antes de tratar como ausência.

## Onde o sistema pode melhorar

1. **Decisões do TCU pediu para ir mais devagar.** 1 respostas 429 (muitas requisições). *Proposta:* Aumentar a pausa entre chamadas e coletar em janelas menores, todo dia, em vez de tudo de uma vez.
2. **O domínio educacao procura o anexo “RREO-Anexo 8”, que não veio do SICONFI.** Nenhum período coletado traz um anexo com esse número; a consulta volta vazia e a segunda via do piso fica sem dado. Provavelmente porque esse anexo nasce no SIOPE (educação, FNDE) e não chega à base de dados abertos do SICONFI (a conferir). *Proposta:* Ler o piso direto do SIOPE (educação, FNDE) e manter o SICONFI como conferência.
3. **O domínio saude procura o anexo “RREO-Anexo 12”, que não veio do SICONFI.** Nenhum período coletado traz um anexo com esse número; a consulta volta vazia e a segunda via do piso fica sem dado. Provavelmente porque esse anexo nasce no SIOPS (saúde, Ministério da Saúde) e não chega à base de dados abertos do SICONFI (a conferir). *Proposta:* Ler o piso direto do SIOPS (saúde, Ministério da Saúde) e manter o SICONFI como conferência.
4. **As duas vias do Diário Oficial contam edições diferentes em 31 meses.** Querido Diário × SILEG: 2023-12 (23 × 22); 2024-03 (22 × 21); 2024-05 (22 × 21); 2024-06 (23 × 21); 2024-07 (25 × 27); 2024-10 (25 × 22); 2024-11 (0 × 20); 2024-12 (0 × 20); 2025-01 (0 × 24); 2025-02 (0 × 21); 2025-03 (0 × 20); 2025-04 (0 × 19)… *Proposta:* Conferir edição a edição: a que falta numa via é lida pela outra, e a diferença persistente vira alerta de publicação incompleta.
5. **Sem repasse federal registrado em 11 meses.** Meses sem nenhuma linha de repasse para o município: 2026-01 a 2026-11. *Proposta:* Para os meses do ano corrente, usar o Portal da Transparência da União (transferências) como segunda via enquanto a planilha anual não sai.
6. **Educação: 5º bimestre de 2026 ainda não publicado no SIOPE.** O prazo de 30 dias depois do bimestre ainda corre. *Proposta:* A próxima coleta confere de novo; passado o prazo, vira lacuna.
7. **1 endereços dados como mortos voltaram a responder.** https://aplicacoes.mds.gov.br/sagi/FV/parcelas.php *Proposta:* Reavaliar se voltam a ser fonte.
8. **Não há verificação mensal em 27 dos 37 meses.** Meses sem verificação do Cadê o Queijo: 2023-11 a 2025-12, 2026-11. *Proposta:* Com o banco histórico, refazer as verificações retroativas desses meses (o motor antigo só roda o exercício corrente).
9. **O coletor antigo do FNAS só conhece as planilhas até 2025.** cadeoqueijo/coleta_federal.py tem os endereços escritos à mão e roda com anos=(2024, 2025) fixos. *Proposta:* Achar as planilhas na própria página do FNAS, como faz a coleta histórica.

## Cobertura mês a mês

✓ coletado com dado · · coletado sem dado · ✗ falhou · … ainda no prazo

| Mês | Diário (QD) | Diário (SILEG) | RREO | RGF | DCA | FNAS | PNCP |
|---|---|---|---|---|---|---|---|
| 2023-11 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · |
| 2023-12 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · |
| 2024-01 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · |
| 2024-02 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · |
| 2024-03 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | · |
| 2024-04 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2024-05 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2024-06 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2024-07 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2024-08 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2024-09 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2024-10 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2024-11 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2024-12 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2025-01 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2025-02 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2025-03 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2025-04 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2025-05 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2025-06 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2025-07 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2025-08 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2025-09 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2025-10 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2025-11 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2025-12 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2026-01 | ✗ | ✓ | ✓ | ✓ |  | · | ✓ |
| 2026-02 | ✗ | ✓ | ✓ | ✓ |  | · | ✓ |
| 2026-03 | ✗ | ✓ | ✓ | ✓ |  | · | ✓ |
| 2026-04 | ✗ | ✓ | ✓ | ✓ |  | · | ✓ |
| 2026-05 | ✗ | ✓ | ✓ | ✓ |  | · | ✓ |
| 2026-06 | ✗ | ✓ | ✓ | ✓ |  | · | ✓ |
| 2026-07 | ✗ | ✓ | ✓ | ✓ |  | · | ✓ |
| 2026-08 | ✗ | ✓ | ✓ | ✓ |  | · | ✓ |
| 2026-09 | ✗ | ✓ | … |  |  | · | ✓ |
| 2026-10 | ✗ | ✓ | … |  |  | · | ✓ |
| 2026-11 | ✗ | ✓ |  |  |  | · | ✓ |
