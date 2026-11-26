# Diagnóstico da coleta histórica (2024-11 a 2026-11)

Rodada de 2026-11-26T15:11:55+00:00. Banco: `dados/onisciente/historico.db`.

Vermelho é falha do sistema (a fonte não respondeu). Roxo é lacuna do município (a fonte respondeu e o dado não estava lá). As duas nunca se misturam.

## Motores

| Motor | Chamadas | Certas | Falhas | 429 | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| Normas federais (ctresb/leis) | 21 | 21 | 0 | 0 | 3.4 |
| Repasses federais (FNAS) | 6 | 3 | 3 | 0 | 2.9 |
| Portais e endereços configurados | 25 | 20 | 5 | 0 | 253.3 |
| Contratações (PNCP) | 583 | 83 | 500 | 0 | 1731.5 |
| Diário Oficial pelo Querido Diário | 50 | 0 | 50 | 0 | 210.5 |
| SICONFI (Tesouro Nacional) | 23 | 23 | 0 | 0 | 5.9 |
| SICONFI pelos endereços antigos | 2 | 0 | 2 | 0 | 1.2 |
| Diário Oficial pelo índice do SILEG | 50 | 50 | 0 | 0 | 13.3 |

## O que entrou no banco

- **SICONFI:** 28081 itens; períodos por situação: {"entregue": 19, "no prazo": 1}.
- **Diário Oficial:** edições somadas por via: {"querido_diario": 0, "sileg": 504}.
- **Repasses do FNAS:** 0 linhas, R$ 0,00.
- **PNCP:** 191 contratações e 0 contratos de órgãos do Município (0 da pasta da assistência).
- **Endereços configurados:** 20 de 25 abriram.

## Onde o sistema falha

1. **Repasses federais (FNAS): 3 de 6 chamadas falharam.** Erro mais comum: BadZipFile: File is not a zip file (2 vezes). *Proposta:* Ver a tabela coletas do banco para os endereços exatos.
2. **Contratações (PNCP): 500 de 583 chamadas falharam.** Erro mais comum: não tentado: tempo do motor nesta rodada esgotado (500 vezes). *Proposta:* Ver a tabela coletas do banco para os endereços exatos.
3. **O coletor antigo do SICONFI usa endereços que não respondem mais.** cadeoqueijo/coleta_siconfi.py chama apidatatransparencia.tesouro.gov.br e apidados.tesouro.gov.br (HTTP 404); o endereço novo (apidatalake) respondeu. *Proposta:* Trocar a base do coletor antigo pela apidatalake.tesouro.gov.br.
4. **O Querido Diário não respondeu em 25 de 25 meses.** Meses: 2024-11 a 2026-11. Erro: URLError: [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] ssl/tls alert handshake failure (_ssl.c:1011). *Proposta:* Coletar de dentro do GitHub (rede aberta) e manter a outra via como reserva.
5. **3 de 25 endereços configurados não abriram.** Painel de preenchimento de prestação de contas (HTTP 404); CNAS — Resoluções (Participa + Brasil) (TimeoutError: The read operation timed out); MDS — Índice de Gestão Descentralizada (HTTP 404) *Proposta:* Marcar cada um como morto em config/portais.yml com o substituto, ou corrigir o endereço.
6. **O coletor antigo do PNCP consulta o Brasil inteiro.** cadeoqueijo/coleta_pncp.py tira os CNPJs do Município de dados/destinatarios_2026.json, que não tem nenhum; sem CNPJ, pede todos os contratos do país e filtra por “GOIANIA” só nas 20 primeiras páginas. Por isso recebeu 429 e achou zero contratos. *Proposta:* Usar os órgãos descobertos pela coleta histórica (código IBGE) e consultar por CNPJ, mês a mês.

## Onde o município deixou lacuna

1. **O FNAS ainda não publicou a planilha 2026.** A página de extração de repasses não tem a planilha do ano. *Proposta:* Os repasses do ano ficam sem a via federal até a publicação; a coleta mensal confere de novo.
2. **Nenhum contrato do Município no PNCP em 25 meses.** Meses: 2024-11 a 2026-11. Órgãos procurados: 17. *Proposta:* A Lei 14.133/2021 (art. 94) manda divulgar o contrato no PNCP; confirmar no portal municipal antes de tratar como ausência.

## Onde o sistema pode melhorar

1. **O domínio educacao procura o anexo “RREO-Anexo 8”, que o SICONFI não usa.** O Tesouro chama o anexo de outro nome; a consulta com o nome errado volta vazia e a segunda via do piso fica sem dado. *Proposta:* Conferir o nome na lista de anexos do banco (tabela siconfi_anexos).
2. **O domínio saude procura o anexo “RREO-Anexo 12”, que o SICONFI não usa.** O Tesouro chama o anexo de outro nome; a consulta com o nome errado volta vazia e a segunda via do piso fica sem dado. *Proposta:* Conferir o nome na lista de anexos do banco (tabela siconfi_anexos).
3. **As duas vias do Diário Oficial contam edições diferentes em 25 meses.** Querido Diário × SILEG: 2024-11 (0 × 20); 2024-12 (0 × 20); 2025-01 (0 × 24); 2025-02 (0 × 21); 2025-03 (0 × 20); 2025-04 (0 × 19); 2025-05 (0 × 20); 2025-06 (0 × 20); 2025-07 (0 × 26); 2025-08 (0 × 22); 2025-09 (0 × 24); 2025-10 (0 × 21)… *Proposta:* Conferir edição a edição: a que falta numa via é lida pela outra, e a diferença persistente vira alerta de publicação incompleta.
4. **1 endereços dados como mortos voltaram a responder.** https://aplicacoes.mds.gov.br/sagi/FV/parcelas.php *Proposta:* Reavaliar se voltam a ser fonte.
5. **Não há verificação mensal em 15 dos 25 meses.** Meses sem verificação do Cadê o Queijo: 2024-11 a 2025-12, 2026-11. *Proposta:* Com o banco histórico, refazer as verificações retroativas desses meses (o motor antigo só roda o exercício corrente).
6. **O coletor antigo do FNAS só conhece as planilhas até 2025.** cadeoqueijo/coleta_federal.py tem os endereços escritos à mão e roda com anos=(2024, 2025) fixos. *Proposta:* Achar as planilhas na própria página do FNAS, como faz a coleta histórica.

## Cobertura mês a mês

✓ coletado com dado · · coletado sem dado · ✗ falhou · … ainda no prazo

| Mês | Diário (QD) | Diário (SILEG) | RREO | RGF | DCA | FNAS | PNCP |
|---|---|---|---|---|---|---|---|
| 2024-11 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2024-12 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2025-01 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2025-02 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2025-03 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2025-04 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2025-05 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2025-06 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2025-07 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2025-08 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2025-09 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2025-10 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2025-11 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2025-12 | ✗ | ✓ | ✓ | ✓ | ✓ | · | · |
| 2026-01 | ✗ | ✓ | ✓ | ✓ |  | · | · |
| 2026-02 | ✗ | ✓ | ✓ | ✓ |  | · | · |
| 2026-03 | ✗ | ✓ | ✓ | ✓ |  | · | · |
| 2026-04 | ✗ | ✓ | ✓ | ✓ |  | · | · |
| 2026-05 | ✗ | ✓ | ✓ | ✓ |  | · | · |
| 2026-06 | ✗ | ✓ | ✓ | ✓ |  | · | · |
| 2026-07 | ✗ | ✓ | ✓ | ✓ |  | · | · |
| 2026-08 | ✗ | ✓ | ✓ | ✓ |  | · | · |
| 2026-09 | ✗ | ✓ | … |  |  | · | · |
| 2026-10 | ✗ | ✓ | … |  |  | · | · |
| 2026-11 | ✗ | ✓ |  |  |  | · | · |
