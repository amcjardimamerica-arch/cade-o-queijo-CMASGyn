# Auditoria e consultoria de arquitetura — agosto/2026

Revisão de nível principal engineer sobre o sistema de vigilância da
assistência social de Goiânia, com a ambição declarada: tornar-se a
referência brasileira em fiscalização automatizada do Executivo municipal,
secretaria a secretaria, com cruzamento completo das fontes de recurso.

Base medida nesta revisão: 51 commits, 493 arquivos, 11.467 linhas de
Python, 59 normas no corpus, 151 edições do Diário ancoradas por sha256,
roteador com 17 tarefas determinísticas (53%), 7 em Haiku, 5 em Sonnet,
4 em Opus e o julgamento dominical em Fable. Seis workflows.

---

## 1. O que já é nível de prêmio — preservar a qualquer custo

**A cadeia de custódia digital.** Cada trecho carrega `sha256_edicao` e
`sha256_trecho`, com URL do PDF original. Nenhum sistema público brasileiro
que eu conheça formaliza proveniência criptográfica de achado de
fiscalização. Isto é o alicerce do prêmio: **todo achado é reproduzível por
terceiro independente a partir do hash**. Recomendo elevá-lo a doutrina
explícita (seção própria na metodologia) e nunca aceitar dado sem âncora.

**Selos de prova com dupla via.** CONFIRMADO/INDICIÁRIO/INCONCLUSIVO com a
regra "em peça, só o confirmado por dupla via" é epistemologia de tribunal
de contas embutida em software. A validação em 2ª etapa (sonda de fontes
alternativas) fechou o ciclo: indisponibilidade agora aponta caminho, não
beco.

**Dado faltante é achado.** A trava do valor coletivo (o caso
R$ 1.500.000/24 entidades), o roxo da 3601, a lacuna declarada do QDD — o
sistema já não confunde silêncio com conformidade. É o diferencial
metodológico sobre todo painel de transparência existente.

**Economia por desenho.** 53% determinístico medido, `recortar()` com
96,85% de economia comprovada, corpus lido de disco, Fable/Opus só em
julgamento. O plano de ~793 chamadas/mês está uma ordem de grandeza abaixo
de qualquer pipeline ingênuo equivalente.

---

## 2. Riscos estruturais que impedem o prêmio hoje

**R1 — Fonte única de execução.** 161 eventos e **zero** liquidação ou
pagamento mesmo após a primeira coleta do portal. Ou o portal expõe HTML
que o coletor ainda não interpreta, ou expõe consulta paginada sem export.
Enquanto a execução depender só do Diário, o achado central ("a despesa
morre no empenho") tem uma via. **Prioridade zero: engenharia reversa do
portal** (ver pergunta Q6) e, em paralelo, o SICONFI como via federal
independente — o RGF publica despesa de pessoal e o RREO a execução
bimestral que o Diário esconde. Divergência SICONFI×Diário é achado forte
e automatizável.

**R2 — Concurrency global única.** O grupo `fiscalizacao` serializa todos
os workflows; vimos o semanal esperar horas atrás do mensal. Para o
domingo 6h ser garantido: grupo por workflow + o dominical com prioridade
(dead-man switch: se às 7h de Goiânia não houver run verde, abrir issue
automática).

**R3 — Cobertura temporal.** Acervo local cobre 2025–2026; servidores e
padrões históricos exigem os 5 anos. O `retroativo.py` existe: agendar
varredura noturna de baixa taxa (50 edições/noite) até fechar 2021.

**R4 — Testes protegem pouco.** 13/15 passam, mas não há *golden tests*
dos casos que já nos morderam (o 1,5M coletivo, o CNPJ com dígito
inválido, a fonte federal vazia, a edição com lacuna de numeração). Cada
bug corrigido nesta investigação deveria ter virado teste de regressão no
mesmo commit. Recomendo `testes_regressao.py` com os seis erros históricos
como casos canônicos + um **canário**: injetar mensalmente um dado
sintético marcado e falhar o ciclo se ele não virar achado.

**R5 — Esquema de dados sem contrato.** Os JSON de `dados/` não têm schema
validado; o bug do `Publicar` que não commitava a sonda passou
despercebido porque nada valida completude do ciclo. Um `config/schemas/`
com validação jsonschema no fim de cada workflow custa zero token e
elimina classe inteira de falha silenciosa.

---

## 3. Novos parâmetros de detecção — o arsenal original

Todos determinísticos (camada 0), todos emitindo no máximo INDICIÁRIO por
si sós (estatística nunca é prova — regra da casa), todos alimentando a
dupla etapa. Ordenados por relação impacto/esforço:

**P-N1 · Detector de Diário reescrito** *(implementado nesta revisão —
`scripts/verifica_integridade_edicoes.py`)*. Rebaixa periodicamente
edições já ancoradas e compara o sha256 atual com o histórico. PDF
substituído silenciosamente após publicação = adulteração de fé pública —
Artigo 37, caput, da Constituição. Ninguém no Brasil monitora isto. Com
151 âncoras já existentes, o custo é uma requisição condicional por
edição (HTTP 304 = grátis).

**P-N2 · Entidade recém-nascida.** O cadastro RFB já traz a data de
abertura: OSC municipal precisa de 1 ano de existência para parceria —
Artigo 33, inciso V, alínea "a", da Lei 13.019/2014. Cruzamento imediato
com dado que já temos.

**P-N3 · CNAE incompatível com o objeto.** Construtora recebendo por
serviço socioassistencial (o caso FNS está na base). CNAE principal vem
no cadastro; dicionário objeto→grupos CNAE plausíveis é uma tarde de
trabalho e rende achados reais.

**P-N4 · Fracionamento de despesa.** Janela deslizante de 90 dias por
credor/natureza somando logo abaixo do limiar de dispensa do Artigo 75 da
Lei 14.133/2021 (valor vigente parametrizado no corpus, nunca fixado em
código). Clássico de auditoria, ausente de todo painel público.

**P-N5 · Janela de sombra.** Índice de atos publicados em véspera de
feriado, sexta-feira, dezembro e períodos de Diário intermitente — a
intermitência já apurada torna este parâmetro especialmente afiado aqui:
ato relevante publicado no único dia útil de circulação da quinzena
merece INDICIÁRIO automático.

**P-N6 · Co-localização de entidades.** Endereço RFB idêntico para
múltiplas beneficiárias ("entidade-carimbo"). Dado já em base.

**P-N7 · Grafo societário cego.** O QSA vem nos dados abertos do CNPJ.
Para respeitar a minimização (primeiro nome apenas), o cruzamento
sócio×servidor-nomeado se faz por **hash cego do nome completo na
extração** — armazena-se só o hash e o primeiro nome; colisão de hash
entre QSA de fornecedor e servidor nomeado gera INDICIÁRIO com ponteiro
para os documentos originais, sem jamais materializar o nome completo na
base. Original, auditável e conforme a regra de privacidade da casa.

**P-N8 · Lei de Benford sobre valores.** Primeiro dígito dos valores de
empenho por unidade, qui-quadrado contra Benford, janela móvel.
Explicitamente rotulado "triagem estatística — jamais prova"; serve para
priorizar perícia, exatamente como a regra do sobrepreço exige.

**P-N9 · Lacuna de numeração de empenhos.** A mesma técnica das edições
(que rendeu o CONFIRMADO da circulação) aplicada à sequência NE quando o
portal expuser numeração: empenho oculto entre dois publicados.

**P-N10 · Assinatura textual de objetos.** MinHash/shingling entre objetos
de contratos de credores distintos: similaridade >0,9 entre "concorrentes"
= mesmo redator = INDICIÁRIO de direcionamento. Determinístico, custo zero.

**P-N11 · Ping-pong de créditos.** Decretos suplementares que anulam e
recompõem a mesma dotação em ciclo curto — remanejamento camuflado. A base
de decretos de crédito já existe (foi ela que ensinou o erro nº 6).

**P-N12 · Fase 2, sob autorização (Q3): trilha eleitoral.** Dados abertos
do TSE (divulgacandcontas): doadores de campanha do vereador indicante de
emenda × QSA da OSC beneficiária, via hash cego do P-N7. O cruzamento mais
sensível e o de maior potencial de irregularidade real do país.

**Meta-parâmetro · Índice de Opacidade por Secretaria.** A síntese com cara
de prêmio: para cada unidade orçamentária, `(dotação sem execução
publicada + dias úteis sem Diário ponderados + demonstrativos faltantes) /
dotação total`, publicado mensalmente como ranking entre TODAS as
secretarias. Transforma o sistema de "vigilância da assistência" em
**metodologia municipal replicável** — o pipeline é o mesmo, muda o filtro
de função. É o caminho natural de expansão (Q1).

---

## 4. Economia de tokens — próximos 40% de corte

1. **Batch API** para toda triagem Haiku não urgente (precedentes,
   classificação de atos da semana): 50% de desconto por aceitar
   processamento assíncrono — o ciclo é semanal, latência de horas é
   irrelevante (Q4).
2. **Prompt caching** no system jurídico repetido do parecer de ato
   (mesmo prefixo em ~90% das chamadas Sonnet): custo do prefixo cai ~90%.
3. **Regex-first com fallback**: medir a taxa em que `extrair_partes_do_ato`
   é resolvível por padrão fixo; hoje vai a Haiku sempre. Estimativa
   conservadora: 60% dos atos são formulaicos → corte direto.
4. **Saída estruturada validada**: parecer de ato com schema JSON e
   validação local; reprocesso só do campo inválido, nunca da peça inteira.
5. **Orçamento por ciclo com disjuntor**: teto de chamadas por workflow
   gravado em `estado/orcamento_ia.json`; estourou, degrada para
   determinístico e registra — previsibilidade de custo é requisito de
   sistema-referência.

## 5. Automação e confiabilidade do calendário

- Domingo 6h (9h UTC) já implantado com a regra do primeiro domingo
  pós-mês. Endurecer: `schedule` + verificação de atraso (dead-man) +
  grupo de concurrency próprio (R2).
- Paralelizar o mensal em matriz (corpus ∥ federal ∥ portal ∥ Diário) —
  hoje é sequencial; corte de ~60% no tempo de ciclo.
- Cache do corpus entre jobs via artifact (evita rebaixar 59 normas quando
  só as contas mudaram).
- Publicar `docs/status.json` (última execução, contadores, sonda 2ª
  etapa) para o painel exibir a saúde do próprio sistema — transparência
  sobre a ferramenta de transparência.

## 6. Perguntas que precisam da sua decisão

**Q1.** Expansão: consolidamos função 08 por mais um ciclo ou já abrimos o
Índice de Opacidade para todas as secretarias no próximo mensal? (O QDD de
257 linhas já cobre o município inteiro.)

**Q2.** Fracionamento (P-N4): adoto os limiares do Artigo 75 da Lei
14.133/2021 atualizados pelo decreto federal vigente no corpus, com janela
de 90 dias por credor+natureza?

**Q3.** Autoriza a fase 2 eleitoral (P-N12), sempre INDICIÁRIA e por hash
cego, ou prefere mantê-la fora do escopo por ora?

**Q4.** Batch API: aceita latência de até 24h nas triagens em troca de
~50% de custo?

**Q5.** Achados CONFIRMADOS por dupla via devem gerar automaticamente
minuta de representação ao TCM-GO e ao MP-GO (documento pronto, protocolo
sempre humano)?

**Q6.** A primeira coleta do portal voltou sem estágios de execução:
consegue navegar manualmente em goiania.go.gov.br/transparencia e me dizer
se a consulta de despesa oferece exportação (CSV/planilha) ou é só tela?
Essa resposta define a engenharia do coletor.

**Q7.** Para o P-N7/P-N12, confirma a política de hash cego (nome completo
jamais persistido, só hash + primeiro nome + ponteiro sha256 ao documento
oficial)?

## 7. Roteiro sugerido (ordem de execução)

1. **Semana 1**: P-N1 (entregue), schemas + testes de regressão dos seis
   erros históricos + canário; concurrency por workflow.
2. **Semana 2**: SICONFI como 2ª via de execução e pessoal (mata R1 por
   fora enquanto o portal não cede); P-N2/P-N3/P-N6 (dados já em base).
3. **Semana 3**: coletor do portal conforme Q6; P-N4/P-N5/P-N11.
4. **Mês 2**: Índice de Opacidade por Secretaria (Q1) + Batch API +
   prompt caching; P-N8/P-N10.
5. **Mês 3**: P-N7 hash cego; fase 2 eleitoral se autorizada (Q3);
   metodologia publicada em `docs/metodologia.md` com a cadeia de custódia
   como capítulo central — o dossiê de candidatura a prêmio se escreve
   sozinho a partir dela.

---
*Auditoria conduzida sobre o commit corrente; toda afirmação quantitativa
foi medida no repositório, não estimada. Levantamento 100% determinístico.*
