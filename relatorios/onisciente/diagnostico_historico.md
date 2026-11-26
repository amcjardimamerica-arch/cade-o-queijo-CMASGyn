# Diagnóstico da coleta histórica (2024-11 a 2026-11)

Rodada de 2026-11-26T21:03:08+00:00. Banco: `dados/onisciente/historico.db`.

Vermelho é falha do sistema (a fonte não respondeu). Roxo é lacuna na fonte (ela respondeu e o dado não estava lá). As duas nunca se misturam.

## Motores

| Motor | Chamadas | Certas | Falhas | 429 | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| Normas federais (ctresb/leis) | 21 | 21 | 0 | 0 | 3.4 |
| Repasses federais (FNAS) | 4 | 3 | 1 | 0 | 98.2 |
| Portais e endereços configurados | 25 | 20 | 5 | 0 | 253.3 |
| Contratações (PNCP) | 618 | 617 | 1 | 0 | 17295.3 |
| Diário Oficial pelo Querido Diário | 50 | 0 | 50 | 0 | 210.6 |
| SICONFI (Tesouro Nacional) | 23 | 23 | 0 | 0 | 5.9 |
| SICONFI pelos endereços antigos | 2 | 0 | 2 | 0 | 1.2 |
| Diário Oficial pelo índice do SILEG | 50 | 50 | 0 | 0 | 13.3 |

## O que entrou no banco

- **SICONFI:** 28081 itens; períodos por situação: {"entregue": 19, "no prazo": 1}.
- **Diário Oficial:** edições somadas por via: {"querido_diario": 0, "sileg": 504}.
- **Repasses do FNAS:** 330 linhas, R$ 17.168.303,62.
- **PNCP:** 2328 contratações e 2118 contratos de órgãos do Município (61 da pasta da assistência).
- **Endereços configurados:** 20 de 25 abriram.

## Onde o sistema falha

1. **Repasses federais (FNAS): 1 de 4 chamadas falharam.** Erro mais comum: planilha do ano não publicada na página do FNAS (1 vezes). *Proposta:* Ver a tabela coletas do banco para os endereços exatos.
2. **Contratações (PNCP): 1 de 618 chamadas falharam.** Erro mais comum: RemoteDisconnected: Remote end closed connection without response (1 vezes). *Proposta:* Ver a tabela coletas do banco para os endereços exatos.
3. **O Querido Diário não respondeu em 25 de 25 meses.** Meses: 2024-11 a 2026-11. Erro: URLError: [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] ssl/tls alert handshake failure (_ssl.c:1011). *Proposta:* O servidor recusou o aperto de mão TLS (alerta 40), também para o curl e o openssl com TLS 1.2 e 1.3 na mesma máquina: o bloqueio está do lado da fonte, não nas cifras do robô. A outra via fica como principal, e a coleta mensal tenta de novo e avisa quando a fonte voltar.
4. **3 de 25 endereços configurados não abriram.** Painel de preenchimento de prestação de contas (HTTP 404); CNAS — Resoluções (Participa + Brasil) (TimeoutError: The read operation timed out); MDS — Índice de Gestão Descentralizada (HTTP 404) *Proposta:* Marcar cada um como morto em config/portais.yml com o substituto, ou corrigir o endereço.
5. **O coletor antigo do PNCP consulta o Brasil inteiro.** cadeoqueijo/coleta_pncp.py tira os CNPJs do Município de dados/destinatarios_2026.json, que não tem nenhum; sem CNPJ, pede todos os contratos do país e filtra por “GOIANIA” só nas 20 primeiras páginas. Por isso recebeu 429 e achou zero contratos. *Proposta:* Usar os órgãos descobertos pela coleta histórica (código IBGE) e consultar por CNPJ, mês a mês.

## Onde a fonte respondeu sem o dado

1. **O FNAS ainda não publicou a planilha 2026.** A página de extração de repasses não tem a planilha do ano. *Proposta:* Os repasses do ano ficam sem a via federal até a publicação; a coleta mensal confere de novo.

## Onde o sistema pode melhorar

1. **O domínio educacao procura o anexo “RREO-Anexo 8”, que não veio do SICONFI.** Nenhum período coletado traz um anexo com esse número; a consulta volta vazia e a segunda via do piso fica sem dado. Provavelmente porque esse anexo nasce no SIOPE (educação, FNDE) e não chega à base de dados abertos do SICONFI (a conferir). *Proposta:* Ler o piso direto do SIOPE (educação, FNDE) e manter o SICONFI como conferência.
2. **O domínio saude procura o anexo “RREO-Anexo 12”, que não veio do SICONFI.** Nenhum período coletado traz um anexo com esse número; a consulta volta vazia e a segunda via do piso fica sem dado. Provavelmente porque esse anexo nasce no SIOPS (saúde, Ministério da Saúde) e não chega à base de dados abertos do SICONFI (a conferir). *Proposta:* Ler o piso direto do SIOPS (saúde, Ministério da Saúde) e manter o SICONFI como conferência.
3. **As duas vias do Diário Oficial contam edições diferentes em 25 meses.** Querido Diário × SILEG: 2024-11 (0 × 20); 2024-12 (0 × 20); 2025-01 (0 × 24); 2025-02 (0 × 21); 2025-03 (0 × 20); 2025-04 (0 × 19); 2025-05 (0 × 20); 2025-06 (0 × 20); 2025-07 (0 × 26); 2025-08 (0 × 22); 2025-09 (0 × 24); 2025-10 (0 × 21)… *Proposta:* Conferir edição a edição: a que falta numa via é lida pela outra, e a diferença persistente vira alerta de publicação incompleta.
4. **Sem repasse federal registrado em 11 meses.** Meses sem nenhuma linha de repasse para o município: 2026-01 a 2026-11. *Proposta:* Para os meses do ano corrente, usar o Portal da Transparência da União (transferências) como segunda via enquanto a planilha anual não sai.
5. **1 endereços dados como mortos voltaram a responder.** https://aplicacoes.mds.gov.br/sagi/FV/parcelas.php *Proposta:* Reavaliar se voltam a ser fonte.
6. **Não há verificação mensal em 15 dos 25 meses.** Meses sem verificação do Cadê o Queijo: 2024-11 a 2025-12, 2026-11. *Proposta:* Com o banco histórico, refazer as verificações retroativas desses meses (o motor antigo só roda o exercício corrente).
7. **O coletor antigo do FNAS só conhece as planilhas até 2025.** cadeoqueijo/coleta_federal.py tem os endereços escritos à mão e roda com anos=(2024, 2025) fixos. *Proposta:* Achar as planilhas na própria página do FNAS, como faz a coleta histórica.

## Cobertura mês a mês

✓ coletado com dado · · coletado sem dado · ✗ falhou · … ainda no prazo

| Mês | Diário (QD) | Diário (SILEG) | RREO | RGF | DCA | FNAS | PNCP |
|---|---|---|---|---|---|---|---|
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
