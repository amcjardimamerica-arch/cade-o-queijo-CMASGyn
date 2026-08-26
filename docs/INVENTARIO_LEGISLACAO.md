# Inventário da legislação — o que foi capturado e o que falta

Levantamento de 25/08/2026. Texto integral significa arquivo em `corpus/` e versão pesquisável em `corpus_txt/`.

---

## Capturados — 20 documentos

### Federal — 9 de 9

| Norma | Bytes | Texto integral |
|---|---|---|
| Constituição Federal | 1.839.482 | sim |
| Lei 8.742/1993 — LOAS, compilada | 153.095 | sim |
| Lei 14.601/2023 — Bolsa Família | 115.346 | sim |
| Lei 13.019/2014 — parcerias | 371.411 | sim |
| Lei 14.133/2021 — licitações | 649.450 | sim |
| Lei 12.527/2011 — acesso à informação | 109.489 | sim |
| Lei 4.320/1964 — normas de finanças | 124.645 | sim |
| Lei Complementar 101/2000 — responsabilidade fiscal | 254.717 | sim |
| Lei 9.784/1999 — processo administrativo | 74.941 | sim |

### Municipal — 2 de 6

| Norma | Bytes | Texto integral |
|---|---|---|
| Lei 7.531/1995 — cria o Fundo | 13.832 | sim |
| Lei 9.009/2010 — rege o CMASGyn | 33.111 | sim |

### Orçamentária — 7 de 9

| Peça | Bytes | Texto integral |
|---|---|---|
| LOA 2026 — Lei 11.590, texto | 776.366 | sim |
| LOA 2026 — anexos, 220 páginas | 3.759.777 | sim |
| LOA 2025 — Lei 11.315, texto | 357.865 | sim |
| LOA 2025 — anexos, 213 páginas | 2.363.402 | sim |
| LDO 2026 — Lei 11.589, anexos | 1.677.942 | sim |
| LDO 2025 — Lei 11.230, anexos | 2.144.662 | sim |
| LDO 2024 — Lei 11.026, anexos | 3.193.632 | sim |

Total capturado: 18,0 MB brutos, 2,0 MB em texto pesquisável.

---

## Não capturados — 26 documentos

### Motivo A — servidor fora do ar (21 documentos)

`aplicacoes.mds.gov.br/snas/regulacao` devolveu **HTTP 503**.
`gov.br/mds/.../cnas/resolucoes` devolveu **HTTP 404** — endereço mudou e não localizei o novo.

Não é bloqueio a robô nem limitação de rede: o servidor não respondeu. Catalogadas por número e tema em `config/catalogo_cnas.json`, sem texto.

| Norma | Uso | Criticidade |
|---|---|---|
| Resolução CNAS/MDS 202/2025 | piso de 10% do IGD ao Conselho | **crítica** |
| Resolução CNAS 33/2012 | NOB/SUAS, blocos de financiamento | crítica |
| Resolução CNAS 14/2014 | inscrição de entidades | crítica |
| Resolução CNAS 109/2009 | tipificação dos serviços | alta |
| Resolução CNAS 269/2006 | NOB-RH, equipes de referência | alta |
| Resolução CNAS 17/2011 | profissionais de nível superior | alta |
| Resolução CNAS 145/2004 | Política Nacional | alta |
| Resolução CNAS 27/2011 e 32/2011 | uso do cofinanciamento | alta |
| Resolução CNAS 18/2014 | benefícios eventuais | alta |
| Resolução CNAS 11/2015 | representação de usuários | alta |
| Resolução CNAS 6/2023 | reordenamento do cofinanciamento | alta |
| Portaria MDS 1.041/2024 | 3% do IGD | alta |
| Portaria MDS 113/2015 e 36/2014 | cofinanciamento e IGD-SUAS | média |
| Outras 6 de uso corrente | — | média |

**Efeito:** o achado do piso de 10% do IGD está fundamentado em enunciado catalogado, não em texto conferido. Marcado com advertência no parecer.

### Motivo B — nunca publicados (3 conjuntos)

| Documento | Situação |
|---|---|
| Resoluções do CMASGyn, 2023–2026 | zero localizadas por qualquer via |
| Atas de plenária do CMASGyn | zero |
| Regimento Interno vigente do CMASGyn | não localizado |

Não é falha de captura. O sítio próprio do conselho não apresenta documento posterior a dezembro de 2023. A ausência viola o Artigo 10, caput e parágrafo 2º, da Lei municipal 9.009/2010. **A ausência é o achado.**

### Motivo C — não localizei o endereço (2 documentos)

| Norma | Situação |
|---|---|
| LOA 2024 e LDO 2023 | número da lei não identificado; o índice anual do sileg devolve HTTP 403 |

Resolve-se com uma busca dirigida. Baixa prioridade: a série de 3 anos já está coberta pelas LDO 2024–2026 e LOA 2025–2026.

### Motivo D — pendentes de busca dirigida (4 documentos)

| Norma | Relevância |
|---|---|
| Lei municipal 8.248/2004 — Lei de Parceria | citada pelo Artigo 2º, IX, da Lei 9.009/2010; conferir recepção pela Lei 13.019/2014 |
| Lei Complementar municipal 273/2014 | institui o teto de 30% para pessoal |
| Lei municipal 8.537/2007 | renomeia FUMDEC para Secretaria |
| Lei Complementar municipal 382/2025 | reestrutura a Secretaria — citada na LOA 2026 |

O conteúdo relevante das três primeiras já está confirmado por transcrição indireta na base legal. Falta o texto integral.

---

## Resumo

| | Documentos | % |
|---|---|---|
| Capturados com texto integral | 20 | 43,5% |
| Não capturados | 26 | 56,5% |
| **Total mapeado** | **46** | |

**Por motivo da falha:**
- Servidor do Ministério fora do ar: 21 (80,8% das falhas)
- Nunca publicados pelo Município: 3 (11,5%)
- Endereço não localizado: 2 (7,7%)

**Bloqueio único de maior impacto:** os portais do Ministério do Desenvolvimento Social. Um servidor derruba 21 dos 26 documentos ausentes.
