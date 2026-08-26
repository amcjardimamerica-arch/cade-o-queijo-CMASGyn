# Corpus legal — o que está no repositório

Levantamento de 25/08/2026. Todo texto é literal, extraído da fonte oficial, com cabeçalho de origem. Sem resumo, sem interpretação, sem alteração.

---

## Resumo

| | Quantidade |
|---|---|
| Resoluções do CNAS e da CIT com texto integral | **268** |
| Leis federais com texto integral | 9 |
| Leis municipais com texto integral | 6 |
| Peças orçamentárias | 7 |
| **Total de documentos** | **290** |
| Volume de texto pesquisável | 4,6 MB |

---

## Resoluções do Conselho Nacional — 268 com texto integral

| Órgão | Quantidade |
|---|---|
| CNAS/MDS | 126 |
| CNAS | 5 |
| Comissão Intergestores Tripartite | 16 |
| Demais atos correlatos do colegiado | 121 |

Distribuição: 2016 (3), 2017 (8), 2018 (4), 2019 (22), 2020 (17), 2021 (10), 2023 (38), 2024 (46), 2025 (42), 2026 (22).

Índice completo de 547 matérias em `corpus/cnas/indice_dou.json`, incluindo pautas, atas e retificações.

### A via que funcionou

**Diário Oficial da União.** Os portais do Ministério caem, mudam de endereço e encerram plataformas. O Diário permanece e é a fonte autoritativa.

1. Busca estruturada em `in.gov.br/consulta/-/buscar/dou`, com janelas de data e `delta=50`. A paginação é inoperante; o recorte por data contorna o teto.
2. Texto integral em `in.gov.br/web/dou/-/{slug}`, extraído do corpo da matéria.
3. Cabeçalho gravado com data de publicação, edição, seção, página e URL de origem.

### Vias de contingência, validadas

**Documento individual do Participa+Brasil.** A plataforma foi encerrada e os índices retornam apenas a casca, mas os blobs sobrevivem: `gov.br/participamaisbrasil/blob/baixar/{id}`. Foi por aí que veio a Resolução 202/2025, identificador 73611. A Resolução 100/2023 está no identificador 26369.

**PDF da página do Diário antigo.** `pesquisa.in.gov.br/imprensa/servlet/INPDFViewer?jornal=1&pagina=N&data=DD/MM/AAAA` devolve a página digitalizada. Cobre matéria anterior a 2016, exigindo data e página exatas.

O `scripts/captura_cnas.py` tenta as três em cascata.

### O que ainda falta

O arquivo estruturado do Diário começa em 2016 para este termo de busca. Permanecem sem texto integral as anteriores:

| Resolução | Tema |
|---|---|
| 145/2004 | Política Nacional de Assistência Social |
| 269/2006 | Norma Operacional Básica de Recursos Humanos |
| 109/2009 | Tipificação Nacional dos Serviços Socioassistenciais |
| 17/2011 | Profissionais de nível superior nas equipes |
| 27/2011 e 32/2011 | Blocos de financiamento e uso do cofinanciamento |
| 33/2012 | Norma Operacional Básica do SUAS |
| 14/2014 | Parâmetros de inscrição de entidades |
| 18/2014 | Benefícios eventuais |
| 15/2014 | Revogada pelo Artigo 17 da Resolução 202/2025 |
| 11/2015 | Representação de usuários |

Cada uma tem data de publicação conhecida. A terceira via resolve, bastando localizar a página do Diário de cada data.

---

## Leis federais — 9

Constituição Federal · Lei 8.742/1993, compilada · Lei 14.601/2023 · Lei 13.019/2014 · Lei 14.133/2021 · Lei 12.527/2011 · Lei 4.320/1964 · Lei Complementar 101/2000 · Lei 9.784/1999

## Leis municipais de Goiânia — 6

| Norma | Conteúdo |
|---|---|
| Lei 7.531/1995 | Cria o Fundo Municipal de Assistência Social |
| Lei 9.009/2010 | Rege o CMASGyn; revogou a Lei 7.532/1995 |
| Lei Complementar 273/2014 | Teto de 30% para pessoal |
| Lei 8.293/2004 | Administração do Fundo |
| Lei 8.248/2004 | Lei de Parceria |
| Lei 8.537/2007 | Renomeia a FUMDEC |

## Peças orçamentárias — 7

Lei Orçamentária Anual de 2026 (Lei 11.590) e de 2025 (Lei 11.315), com anexos. Lei de Diretrizes Orçamentárias de 2026 (Lei 11.589), 2025 (Lei 11.230) e 2024 (Lei 11.026).

Falta: Lei Orçamentária de 2024 e Lei de Diretrizes de 2023. O índice anual do sítio municipal responde HTTP 403; é preciso localizar o número de cada lei.

---

## Duas correções apuradas na leitura dos textos

**Confirmado.** O Artigo 4º da Lei Complementar 273/2014 realmente acrescenta o parágrafo único ao Artigo 4º da Lei 7.531/1995, com o teto de 30% para pessoal. A mesma Lei Complementar aplica teto idêntico a outros fundos — inclusive ao do Meio Ambiente, com redação quase igual. Não confundir.

**Norma nova.** A Lei municipal 8.293/2004, Artigo 19, parágrafo único, na redação dada pelo Artigo 16 da Lei Complementar 273/2014, determina que a administração do Fundo Municipal de Assistência Social cabe ao órgão gestor **em conjunto com o Secretário Municipal de Finanças**, sob orientação e controle do Conselho.

Isso cria responsabilidade solidária do Secretário de Finanças pela administração do Fundo, e amplia o polo passivo de qualquer representação sobre a gestão — inclusive quanto ao aporte próprio de R$ 9.000 apurado na Lei Orçamentária de 2026.
