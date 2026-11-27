# Estudo do Selo de Transparência (PNTP): fontes, avaliação, métricas, replicação e falhas

Estudo feito em 27/11/2026 para responder à titular: como conferir se Goiânia tem de fato o Selo Diamante,
se o selo pode cair com informação faltando, e como o Onisciente refaz a mesma avaliação como auditor
independente. Tudo o que aqui é número ou regra está gravado em arquivos versionados:

* `regras/pntp/matriz_2026.yml`: a metodologia do ciclo 2026, os 109 critérios e as pendências;
* `regras/pntp/matriz_2025.yml`: o que se sabe do ciclo 2025 (o do selo que a Prefeitura declara);
* `regras/pntp/escolhas.yml`: as escolhas de leitura E01 a E16, cada uma com a leitura oficial, a restritiva,
  a justificativa e o código que a aplica.

Alerta, neste estudo e no parecer, é indício, não acusação.

## 1. O que é o selo e o que Goiânia declara

O Programa Nacional de Transparência Pública (PNTP) é coordenado pela Associação dos Membros dos Tribunais de
Contas (Atricon), com o TCU e o TCE-MT, e executado pelos Tribunais de Contas, cada um com os seus
jurisdicionados. Para Goiânia, quem valida é o Tribunal de Contas dos Municípios do Estado de Goiás (TCM-GO).
O resultado sai num índice de 0 a 100 e num nível; os três níveis de cima (Diamante, Ouro e Prata) dão selo.

A Prefeitura declara o **Selo Diamante do ciclo 2025**, com índice acima de 95% (Jornal Opção, 05/12/2025,
https://www.jornalopcao.com.br/goiania/goiania-recebe-selo-diamante-por-nota-maxima-em-transparencia-publica-772080/,
lida em 27/11/2026). Uma manchete de 06/08/2026 do Mais Goiás fala em 98,08% na validação do TCM-GO no ciclo
2026, mas a página recusou a leitura e o número não foi conferido. O painel por entidade do Radar da
Transparência também recusou a leitura (seção 7).

## 2. Fontes oficiais lidas

| Fonte | Endereço | Lida em | O que trouxe |
|---|---|---|---|
| Cartilha PNTP 2026, 4ª edição, versão de 08/04/2026 (Atricon), cópia do MP-MA | https://www.mpma.mp.br/wp-content/uploads/2026/04/Cartilha-PNTP-2026-versao-08.04.2026.pdf | 27/11/2026 | pesos de exigibilidade, pesos dos itens, pesos das dimensões, faixas, regra dos essenciais, totais por matriz, lista dos critérios, atualidade de 30 dias, série de 3 anos, gravação não obrigatória em 2026 |
| Matriz de Critérios 2026 (planilha do PNTP em PDF), cópia da Prefeitura de Pelotas | https://sistema.pelotas.com.br/transparencia/arquivos/Matriz de Criterios 2026 PDF.pdf | 27/11/2026 | classificação essencial ou recomendada de cada critério; exigência de link com evidência para cada resposta Sim |
| Metodologia PNTP 2026, orientações do TCE-PI | https://www.tcepi.tc.br/wp-content/uploads/2026/04/Metodologia-PNTP-2026.pdf | 27/11/2026 | oito níveis, cinco itens de verificação, matrizes por Poder, mudanças do ciclo e prazos |
| Treinamento PNTP 2026 do TCE-PI | https://www.tcepi.tc.br/wp-content/uploads/2026/04/PNTP-2026-TREINAMENTO.pdf | 27/11/2026 | 4.3 passou de obrigatório a essencial; 16.1 e 16.2 passaram a obrigatórios; 17.1 a 17.3 obrigatórios |
| Cronograma PNTP 2026 (Atricon) | https://cdn.atricon.org.br/uploads/2026/02/Cronograma-PNTP-2026.pdf | 27/11/2026 | datas da autoavaliação, da validação, da garantia da qualidade e do resultado |
| Cartilha PNTP 2025, cópia do TCE-SP | https://tce.sp.gov.br/sites/default/files/publicacoes/Cartilha%20PNTP%202025.pdf | 27/11/2026 | mesmos pesos e mesma regra do Diamante no ciclo 2025; totais do ciclo 2025 |
| Radar da Transparência Pública (Atricon) | https://radardatransparencia.atricon.org.br/ | 27/11/2026 | só o painel nacional; o painel por entidade e os dados abertos do PNTP recusaram a leitura |

As cópias da cartilha e da matriz estão em sítios de terceiros porque o original da Atricon recusou a leitura
nesta data. A sondagem `e_metodo` relê os originais no GitHub.

## 3. Quem avalia e quando

1. **Autoavaliação** pelo controle interno do próprio ente, de 20/04 a 29/05/2026. O ente responde Sim ou Não
   a cada item de cada critério e, para cada Sim, informa o link da evidência.
2. **Validação** pelo Tribunal de Contas (TCM-GO para Goiânia), de 01/06 a 10/08/2026. O tribunal abre os
   links e confirma ou corrige as respostas.
3. **Garantia da qualidade** pela Atricon, de 31/08 a 09/10/2026, sobre uma **amostra** dos portais já
   validados, não sobre todos.
4. Consolidação até 10/11/2026, resultado em novembro de 2026 no Radar da Transparência, certificados de
   16/11 a 20/12/2026.

Consequência para quem audita: a nota publicada é a autodeclaração do ente conferida pelo tribunal na janela
de junho a agosto. Nada na metodologia obriga a nova conferência depois do selo, e a garantia da qualidade só
alcança uma amostra.

## 4. Matrizes, dimensões e dados pedidos

A Prefeitura responde a três matrizes: a comum (72 critérios: 7 essenciais, 53 obrigatórios e 12
recomendados), a do Executivo (23: 4, 12 e 7) e a de Executivo e Consórcios (1 essencial). O arquivo
`regras/pntp/matriz_2026.yml` traz 97 critérios aplicáveis à Prefeitura; a diferença de um obrigatório na
matriz comum (54 lidos contra 53 oficiais) está registrada como pendência (escolha E14) e muda o índice em
menos de 0,3 ponto.

| Dimensão | Peso | Critérios (essenciais em negrito) | O que se pede |
|---|---|---|---|
| 1. Informações prioritárias | 2 | **1.1**, **1.2**, 1.3, 1.4 | sítio oficial, portal da transparência, acesso na capa, busca |
| 2. Informações institucionais | 2 | 2.1 a 2.9 | estrutura, competências, responsáveis, endereços, horários, atos, perguntas frequentes |
| 3. Receita | 4 | **3.1**, **3.2**, 3.3 | receita prevista e realizada, por natureza; dívida ativa nominal |
| 4. Despesa | 4 | **4.1**, **4.2**, **4.3** | empenhado, liquidado e pago; classificação; empenhos por credor com a licitação |
| 5. Convênios e transferências | 1 | 5.1 a 5.3 | convênios recebidos, repassados e acordos sem repasse |
| 6. Recursos humanos | 3 | 6.1 a 6.7 | servidores, remuneração nominal, tabela de cargos, estagiários, terceirizados, concursos |
| 7. Diárias | 1 | 7.1, 7.2 | diárias por beneficiário e tabela de valores |
| 8. Licitações | 3 | 8.1 a 8.8 | licitações, editais, fases, dispensas, atas de registro de preço, plano anual, sancionados, regulamento |
| 9. Contratos | 3 | 9.1 a 9.4 | contratos e aditivos, íntegra, fiscais, ordem cronológica de pagamentos |
| 10. Obras | 2 | 10.1 a 10.4 | obras, quantitativos, valores pagos, paralisadas |
| 11. Planejamento e prestação de contas | 4 | 11.1 a 11.4, **11.5**, **11.6**, 11.7, **11.8**, **11.9**, **11.10** | balanço, relatório de gestão, parecer do tribunal, julgamento, RGF, RREO, PPA, LDO, LOA |
| 12. Serviço de Informação ao Cidadão | 2 | 12.1 a 12.9 | SIC, e-SIC, norma local, estatísticas, sigilo |
| 13. Acessibilidade | 1 | 13.1 a 13.5 | símbolo, migalhas, contraste, tamanho do texto, mapa |
| 14. Ouvidoria | 1 | 14.1 a 14.3 | atendimento, canal eletrônico, carta de serviços |
| 15. LGPD e governo digital | 1 | 15.1 a 15.6 | encarregado, política de privacidade, serviços digitais, dados abertos, pesquisa de satisfação |
| 16. Renúncia de receita | 1 | 16.1 a 16.4 | desonerações e beneficiários |
| 17. Emendas parlamentares | 1 | 17.1 a 17.3 | emendas recebidas e execução |
| 18. Saúde | 1 | 18.1 a 18.6 | plano de saúde, serviços, filas, medicamentos, conselho de saúde |
| 19. Educação e assistência social | 1 | 19.1 a 19.4 | plano de educação, creches, conselho do Fundeb, **Conselho de Assistência Social (19.4, recomendado)** |

O Fundo Municipal de Assistência Social não tem critério próprio. O Conselho Municipal de Assistência Social
aparece só no 19.4, recomendado.

## 5. Métricas, pesos, fórmula, essenciais e faixas

**Itens de verificação** de cada critério, com o peso dentro do critério:

* Disponibilidade: 30%;
* Atualidade: 30% (até 30 dias para dado mensal; relatórios periódicos pelo prazo legal);
* Série histórica: 20% (três anos anteriores);
* Gravação de relatórios: 10% (não obrigatória no ciclo 2026);
* Filtro de pesquisa: 10%.

O item que não se aplica ao critério tem o percentual redistribuído entre os demais do mesmo critério.

**Peso de exigibilidade** do critério: essencial 2; obrigatório 1,5; recomendado 1.

**Peso da dimensão**: 4 para Receita, Despesa e Planejamento; 3 para Recursos Humanos, Licitações e
Contratos; 2 para Prioritárias, Institucionais, Obras e SIC; 1 para as demais. Para a Prefeitura a soma é 38.

**Fórmula**:

    índice = 100 × Σ_d [ peso_d × Σ_c (e_c × f_c) / Σ_c (e_c) ] / Σ_d peso_d

em que `e_c` é o peso de exigibilidade do critério, `f_c` a fração atendida pelos itens aplicáveis e `d`
percorre as dimensões com critério aplicável. Quanto cada critério vale no índice, em pontos de 100:

| Critério | Pontos |
|---|---|
| 3.1 Receitas com previsão e realização (essencial) | 3,83 |
| 4.3 Empenhos com credor (essencial) | 3,51 |
| 9.1 Contratos e aditivos | 1,97 |
| 1.1 Sítio oficial (essencial) | 1,50 |
| 11.6 RREO (essencial) | 1,24 |
| 8.1 Licitações | 1,08 |
| 12.3 e-SIC | 0,61 |
| 19.4 Conselho de Assistência Social (recomendado) | 0,53 |
| 15.4 Dados abertos para sistemas externos | 0,49 |

**Faixas**: Diamante de 95 a 100, Ouro de 85 a 94,99 e Prata de 75 a 84,99, as três exigindo 100% dos
critérios essenciais; Elevado com 75 ou mais e algum essencial em falta (sem selo); Intermediário de 50 a
74,99; Básico de 30 a 49,99; Inicial abaixo de 30; Inexistente em zero.

**Resposta à titular, em números**: sim, o selo cai com informação faltando, de duas maneiras.

* Um único critério essencial em falta derruba qualquer selo para Elevado, mesmo com índice de 99.
* Sem essencial em falta, o Diamante tolera até 5 pontos perdidos. Por isso o Conselho de Assistência Social
  pode estar inteiro fora do ar (0,53 ponto) e o selo continuar Diamante.

## 6. Como replicar a avaliação exatamente

1. Carregar a matriz do ciclo: `onisciente/selo/matriz.py` lê `regras/pntp/matriz_2026.yml`, confere pesos,
   classes e faixas (`Matriz.problemas()`) e devolve os critérios da Prefeitura (`do_executivo()`).
2. Ler as páginas: `python -m onisciente selo --sondar` (no GitHub, onde há rede) lê as fontes `e_*` de
   `onisciente/sondagem.py` (portal, Transweb, folha, legislação, e-SIC, sítio do Conselho, Radar) e segue um
   nível de links com os termos dos critérios (`onisciente/selo/coleta.py`). Cada resposta fica guardada com
   a data, no mesmo formato da sondagem.
3. Decidir os cinco itens de cada critério: `onisciente/selo/verificadores.py` procura os termos do critério,
   confere se a página traz o dado, as datas (atualidade), os anos (série), os arquivos (gravação) e os campos
   de filtro. Sem página lida, o item fica não verificável, nunca atendido.
4. Juntar as provas que o Onisciente já tem sem rede (`onisciente/selo/provas.py`): banco histórico,
   SICONFI, PNCP, mapa legal e ausências do parecer.
5. Calcular pela fórmula (`onisciente/selo/formula.py`), em duas leituras e dois modos: a **nota comprovada**
   conta como zero o item sem prova; o **teto** conta como atendido. Se o teto já fica abaixo de 95, ou com um
   essencial em falta, o Diamante declarado não se sustenta, qualquer que seja o resultado da sondagem.
6. Confrontar com o selo declarado e com o Radar e gravar as saídas (`onisciente/selo/avaliador.py` e
   `onisciente/selo/relatorio.py`): `docs/onisciente/selo/goiania.html`,
   `relatorios/onisciente/selo/auditoria.json` e os ofícios.

Sem rede: `python -m onisciente selo --hoje 2026-11-27`.

## 7. Margens de interpretação e as duas leituras

Onde a metodologia deixa margem, o Onisciente aplica a leitura mais exigente e guarda também a oficial. As
16 escolhas estão em `regras/pntp/escolhas.yml`; as principais:

* E01: cada Sim só vale com prova lida e datada pelo Onisciente, nunca a autoavaliação;
* E02: na restritiva, o essencial só conta atendido com todos os itens, não só a disponibilidade;
* E03: a gravação, fora da conta oficial em 2026, entra na restritiva;
* E04: na restritiva, só formato aberto (CSV, JSON, XML, ODS, TXT) conta como gravável;
* E05: na restritiva, receita e despesa com no máximo 7 dias;
* E06 e E07: série com o ano corrente e ao menos dois filtros;
* E08 e E09: link vazio e página só com JavaScript não valem;
* E10: o critério só se cumpre se todas as unidades gestoras, inclusive os fundos, aparecem;
* E12: a dimensão suplementar O (peso 4), com os critérios O.1 a O.6;
* E13: o índice é truncado, nunca arredondado para cima na fronteira de 95;
* E15: todos os critérios, sem amostra.

## 8. Resultado do Onisciente hoje, sem rede (27/11/2026)

| Leitura | Índice | Nível | Essenciais em falta |
|---|---|---|---|
| Oficial, só com provas | 5,24% | Inicial | nenhum provado |
| Oficial, teto | 100,00% | Diamante | nenhum provado |
| Restritiva, só com provas | 4,62% | Inicial | |
| Restritiva, teto | 76,41% | Elevado | 3.1, 4.1, 4.3 e O.2 |

Leitura: pela metodologia oficial o Diamante **não está confirmado** (as páginas ainda não foram lidas pela
sondagem do selo), mas também não está derrubado. Pela leitura restritiva o padrão **cai para Elevado mesmo no
melhor caso**, porque o Fundo Municipal de Assistência Social não tem empenhos, liquidações, pagamentos nem
receita realizada publicados (ausências do parecer de outubro de 2026), e o FMAS recebeu
R$ 17.168.303,62 do Fundo Nacional em 2024 e 2025. O Radar não foi lido para Goiânia.

## 9. Onde a metodologia permite falhas e como o Onisciente valida cada uma

Cada falha abaixo traz o que o PNTP deixa passar, a conferência do Onisciente e o módulo ou critério que a faz.

1. **Qualidade e veracidade do dado.** O PNTP confere se o dado está lá, não se está certo: um portal com
   valores errados ou incompletos pontua igual. *Validação*: os valores são cruzados com fontes nacionais
   independentes. Notas fiscais dos contratos no PNCP (critério O.1, `onisciente/selo/provas.py`, função
   `_notas_fiscais`, que usa o achado `nf_ausente` de `onisciente/conferencias/compras.py`); demonstrativos no
   SICONFI (critério O.4, função `_siconfi`); e os gastos fora do padrão já apontados pelas conferências
   (dispensas no teto, fracionamento, emergenciais, aditivos, concentração, preço acima da curva), mostrados
   junto do selo por `onisciente/selo/avaliador.py` (`_alertas_cruzados`). O selo não mede nenhum deles.
2. **Atualidade real.** Basta ao avaliador ver uma data recente na tela, que pode ser a data de atualização da
   página e não a do dado; e a avaliação é feita uma vez, entre abril e agosto. *Validação*: a atualidade é a
   data mais nova encontrada no próprio dado, medida contra a data da leitura gravada no índice da sondagem;
   na restritiva, 7 dias para receita e despesa (E05). Módulo `onisciente/selo/verificadores.py`
   (`atualidade`, `datas`), refeito a cada rodada pelo ciclo permanente.
3. **Fundos e conselhos.** O Fundo Municipal de Assistência Social não tem critério; o Conselho entra só no
   19.4, recomendado, que vale 0,53 ponto. O portal pode ter o Diamante com o fundo e o conselho opacos.
   *Validação*: nove obrigações legais conferidas uma a uma (F1 a F5 para o Fundo, C1 a C4 para o Conselho,
   com a LC 101, a LAI, a Lei 14.133, a Lei 13.019, a LOAS e as leis municipais 7.531/1995 e 9.009/2010), em
   `onisciente/selo/fundos.py`; na restritiva elas viram os critérios O.2 (essencial) e O.3, e a falta de
   uma unidade gestora derruba o critério do portal (E10, `onisciente/selo/provas.py`, `AUSENCIA_CRITERIO`).
   Ausência de dado é alerta de descumprimento de transparência.
4. **Coerência do portal com PNCP, SICONFI e MSC.** O PNTP não compara o portal com as bases nacionais: o
   município pode publicar uma coisa no portal e outra no PNCP ou no SICONFI. *Validação*: O.1 confere as
   notas fiscais no PNCP e O.4 a entrega e o prazo dos demonstrativos no SICONFI
   (`onisciente/selo/provas.py`). A comparação dos valores do portal com a Matriz de Saldos Contábeis (MSC)
   do SICONFI ainda não está feita: fica como pendência declarada (requisito 193) e, até lá, conta como não
   verificável, nunca como atendida.
5. **Cumprimento só de forma.** O menu com o nome do dado e o link vazio, o dado velho com página nova, o PDF
   escaneado no lugar de planilha, a consulta que só abre com JavaScript. *Validação*: link vazio, E08
   (`tem_dado`); PDF em vez de formato aberto, E04 (`gravacao`); dado desatualizado, E05 (`atualidade`);
   página só com JavaScript, E09 (`casca_javascript`), tudo em `onisciente/selo/verificadores.py`. O critério
   15.4 (dados abertos para sistemas externos) cai na restritiva quando o dado só aparece por script.
6. **Amostragem e autodeclaração.** A nota parte do que o próprio ente declarou; o tribunal valida e a
   Atricon refaz só uma amostra. *Validação*: o Onisciente avalia todos os critérios aplicáveis, sem amostra,
   e não aceita a autoavaliação como prova (E01 e E15, `onisciente/selo/avaliador.py`, `avaliar` e
   `combinar`). A nota comprovada e o teto mostram o que ainda falta ver, e o ofício ao TCM-GO pede os papéis
   de trabalho da validação (respostas, links e notas por critério), em `onisciente/selo/relatorio.py`
   (`oficios`).
7. **Essencial cumprido pela metade.** A regra fala em 100% dos essenciais, mas o essencial pode ser marcado
   como atendido só por estar disponível, ainda que velho ou sem série. *Validação*: E02, na restritiva o
   essencial exige todos os itens (`onisciente/selo/formula.py`, `essencial_atendido`).
8. **Gravação fora da conta em 2026.** Sem o item, o dado preso em tela não perde ponto. *Validação*: E03,
   a restritiva mantém os 10% (`onisciente/selo/formula.py`, `itens_da_leitura`).
9. **Fronteira das faixas.** Um índice de 94,996 arredondado vira 95,00 e Diamante. *Validação*: E13, a
   restritiva trunca (`onisciente/selo/formula.py`, `indice`).
10. **Documento fora do portal.** Lei orçamentária só no sistema de legislação, sem os anexos no portal, pode
    ser aceita. *Validação*: E11, a restritiva exige o documento com os anexos no portal; normas que regem o
    gasto e não foram localizadas em fonte oficial derrubam o critério O.5 (`onisciente/selo/provas.py`,
    `do_mapa`).
11. **Canal de pedido de acesso que funciona só no dia da avaliação.** *Validação*: o endereço do e-SIC é
    sondado a cada rodada; sem resposta, cai o 12.3 na restritiva e o critério O.6
    (`onisciente/selo/provas.py`, `dos_relatorios`).
12. **Critério que não se verifica por máquina** (12.4, pedido eletrônico simples). *Validação*: fica não
    verificável e vira pergunta no ofício (E16).
13. **Selo sem prazo de validade prático.** O selo de um ciclo é exibido até o resultado do seguinte, mesmo se
    o portal piorar. *Validação*: a auditoria roda de novo a cada ciclo permanente e o parecer mensal mostra a
    nota do dia (`onisciente/selo/relatorio.py`, `secao_parecer`).

## 10. Limites e pendências

* O painel 6 do Radar e os dados abertos do PNTP recusaram a leitura em 27/11/2026; a sondagem `e_radar`
  relê no GitHub.
* A planilha oficial com os itens aplicáveis por critério e a fundamentação individual não saiu na extração
  do PDF; os campos `itens` e `base_legal` da matriz são do Onisciente e estão marcados como tal.
* A diferença de um obrigatório na matriz comum (E14) espera a planilha oficial.
* O confronto de valores com a MSC está pendente (seção 9, item 4).
* O cruzamento de empresas e sócios com a Receita Federal é de outra frente e não entra aqui.
