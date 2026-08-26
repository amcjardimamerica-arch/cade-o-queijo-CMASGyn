# Legislação faltante e a causa de cada falha

Levantamento de 25/08/2026, após nova tentativa de captura.

---

## 1. O que mudou nesta rodada

**Capturada a Resolução CNAS/MDS 202/2025 com texto integral** — a peça mais crítica do conjunto, fundamento do achado do IGD. Publicada no Diário Oficial da União de 28/07/2025, Edição 140, Seção 1, Página 87.

O caminho que funcionou: `gov.br/participamaisbrasil/blob/baixar/73611`. Os índices da plataforma estão mortos, mas os documentos individuais ainda respondem quando se conhece o identificador.

**Catálogo ampliado de 20 para 77 resoluções.**

## 2. O que a Resolução 202/2025 acrescenta ao caso

O texto integral trouxe quatro dispositivos que eu não conhecia e que mudam a fiscalização:

**Artigo 6º, parágrafo 4º.** As gestões municipais **deverão incluir no Quadro de Detalhamento de Despesas dotação orçamentária específica de fortalecimento do controle social a partir de 2026.** Obrigação autônoma, diretamente auditável. É preciso conferir se a ação 3650.0824401082591 da Lei Orçamentária de Goiânia atende ao requisito de especificidade, ou se é dotação genérica de manutenção.

**Artigo 6º, parágrafo 5º.** Prestação de contas **a cada quatro meses** ao próprio Conselho, detalhando o monitoramento e as medidas tomadas em caso de acúmulo de saldo. Novo parâmetro, com prazo próprio.

**Artigo 6º, parágrafo 6º.** **Sanção expressa: em caso de descumprimento o ente federado terá seus repasses bloqueados** até comprovar o cumprimento. Somada ao artigo 30 da Lei 8.742/1993, são dois fundamentos autônomos de suspensão.

**Artigo 6º, caput.** O percentual incide sobre o valor repassado **mensalmente**, não sobre o total anual. O cálculo tem de ser mês a mês.

E o artigo 17 revoga a Resolução CNAS 15/2014, o que confirma que os 3% do artigo 121, inciso VII, da Resolução 33/2012 estão superados.

## 3. Situação do catálogo

| | Quantidade |
|---|---|
| Resoluções catalogadas | 77 |
| Com texto integral no repositório | 1 |
| Sem texto | 76 |

Das 76 sem texto: 60 são recentes (2023 a 2026), capturadas com número, data e ementa; 16 são históricas de uso corrente, catalogadas por número e tema.

## 4. Por que não consegui o texto das demais

### Causa 1 — plataforma oficial encerrada

O Participa+Brasil, que hospedava as resoluções do Conselho Nacional, **foi encerrado**. A página exibe aviso expresso de encerramento e remete a uma nova plataforma, o Brasil Participativo, cujo endereço das resoluções não localizei.

Consequência: as 24 páginas de índice que baixei retornam apenas a casca da página, sem a listagem. Os blobs individuais sobrevivem, mas exigem o identificador numérico, que só o índice fornecia.

**É a causa principal. Derruba a via oficial inteira.**

### Causa 2 — servidores fora do ar

| Endereço | Resposta |
|---|---|
| `aplicacoes.mds.gov.br/snas/regulacao` | HTTP 503 |
| `gov.br/mds/pt-br/orgaos-colegiados/cnas` | HTTP 503 |
| `blog.mds.gov.br/redesuas/resolucoes-cnas` | HTTP 503 |
| `in.gov.br/consulta` (Diário Oficial da União) | HTTP 503 |
| `gov.br/mds/.../participacao-social/cnas` | HTTP 404, endereço movido |

Cinco fontes, cinco falhas. Não é bloqueio a robô nem limite de rede: os servidores não responderam.

### Causa 3 — cobertura parcial da fonte alternativa

O `blogcnas.com` funciona e foi de onde vieram as 60 recentes. Mas suas páginas por ano só expõem 2023 em diante. As páginas de gestões anteriores tratam de composição do colegiado, não de resoluções. As resoluções de 2004 a 2022 não estão acessíveis por ali.

## 5. O que falta, por prioridade

### Crítico — sem texto, o parâmetro não se sustenta

| Norma | Uso | Parâmetro |
|---|---|---|
| Resolução CNAS 33/2012 | NOB/SUAS, blocos de financiamento; artigo 121, VII, superado | financiamento |
| Resolução CNAS 14/2014 | parâmetros de inscrição de entidades | CMAS-PROC-06 |
| Resolução CNAS 109/2009 | Tipificação Nacional dos Serviços | classificação de serviço |

### Alto

Resolução CNAS 269/2006 (equipes de referência), 17/2011 (nível superior), 27/2011 e 32/2011 (cofinanciamento), 18/2014 (benefícios eventuais), 11/2015 (representação de usuários), 6/2023 (reordenamento), 145/2004 (Política Nacional), 157/2023 (Regimento Interno do Conselho Nacional), Portaria MDS 1.041/2024 e Portaria MDS 113/2015.

### Municipal

Lei 8.248/2004 (Lei de Parceria), Lei Complementar 273/2014 (teto de 30%), Lei 8.537/2007, Lei Complementar 382/2025 (reestrutura a Secretaria). O conteúdo relevante das três primeiras já está confirmado por transcrição indireta na base legal; falta o texto.

### Orçamentária

Lei Orçamentária Anual de 2024 e Lei de Diretrizes Orçamentárias de 2023 — número da lei não identificado, e o índice anual do sítio municipal responde HTTP 403. Baixa prioridade: a série de três anos já está coberta.

## 6. Como completar

**Via que funciona hoje.** Localizar o identificador do blob e baixar por `gov.br/participamaisbrasil/blob/baixar/{id}`. Foi assim que a 202/2025 veio. Exige descobrir o identificador de cada uma — trabalho de sondagem numérica, viável mas lento.

**Via a testar.** Localizar o endereço das resoluções na nova plataforma Brasil Participativo. Se existir listagem com identificadores, resolve o conjunto inteiro de uma vez.

**Via de contingência.** Diário Oficial da União pela data de publicação, quando o `in.gov.br` voltar. Cada resolução tem data conhecida no catálogo, o que torna a busca direta.

O `scripts/captura_cnas.py`, chamado pelo ciclo mensal legal, tenta as três vias e registra o motivo de cada falha no catálogo. O repositório passa a saber por que não tem o que não tem.

## 7. Ressalva de método

Enquanto uma resolução não tiver texto integral no repositório, ela é usada **apenas pelo enunciado catalogado, com selo INDICIÁRIO**. Nenhuma peça cita dispositivo cujo texto não esteja conferido.

A Resolução 202/2025 saiu dessa condição nesta rodada. O achado do piso de 10% do IGD passa a ter fundamento conferido, e ganhou três dispositivos novos que o reforçam.
