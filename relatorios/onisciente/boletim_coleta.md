# Coleta em andamento: boletim de 2026-11-27T12:22+00:00

Desde 2026-11-27T10:02:25+00:00: 1121 chamadas registradas.
Última chamada: 2026-11-27T12:22:18+00:00 (preco 247711 2026-1).

## Por fonte

| fonte | situação | chamadas |
|---|---|---|
| dadosabertos.compras.gov.br | ok | 626 |
| dadosabertos.compras.gov.br | TimeoutError | 1 |
| pncp.gov.br/api/consulta | HTTP 404 ({"path":"/pncp-consulta/v1/instrumentoscobranca/inclusao","m) | 282 |
| pncp.gov.br/api/consulta | ok | 204 |
| pncp.gov.br/api/consulta | RemoteDisconnected | 1 |
| pncp.gov.br/api/pncp | HTTP 301 | 7 |

## Tempo das respostas boas (segundos)

| fonte | n | mediana | p90 | máximo |
|---|---|---|---|---|
| dadosabertos.compras.gov.br | 626 | 1.5 | 3.1 | 243.9 |
| pncp.gov.br/api/consulta | 204 | 23.4 | 30.6 | 45.7 |

## O que o banco tem agora

| tabela | linhas |
|---|---|
| pncp_amparos | 2328 |
| pncp_contratos_detalhe | 2118 |
| pncp_termos | 65 |
| pncp_itens | 6640 |
| pncp_cobrancas | 0 |
| pncp_nf_itens | 0 |
| precos_referencia | 64207 |

## Lido por inteiro (acumulado)

- amparos: 54
- cobrancas: 800
- compra: 846
- contrato: 2118
- itens: 216
- itens da compra: 71
- preco: 600
- termos: 2118
