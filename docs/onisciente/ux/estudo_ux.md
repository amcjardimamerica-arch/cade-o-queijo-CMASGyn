# Estudo de UX do Onisciente

Este estudo define como o Onisciente se apresenta a quem o lê: o número de páginas, o caminho até cada
desconformidade, o modo de apresentação para reuniões, a leitura no celular, a acessibilidade, as cores e o
formato dos dados que as outras frentes entregam às telas. Ele parte da linha do tempo da conversa com o dono
(25 a 27 de novembro de 2026) e do protótipo navegável de 25/11, cuja identidade visual (o escudo do Núcleo
de Fiscalização da A.M.C. Jardim América, o azul real, o ouro e o laranja, os títulos em Zilla Slab e os
números em IBM Plex Mono) foi aprovada e é mantida aqui.

O site novo fica em `docs/onisciente/app/`. A página inicial é `docs/onisciente/app/index.html`, publicada
no GitHub Pages do repositório como `…/onisciente/app/`. Ela é gerada por `python -m onisciente telas`, a
partir do banco histórico e dos módulos do sistema, sem rede.

## 1. As premissas que governam o desenho

As premissas vêm da linha do tempo, nas palavras do dono sempre que possível.

1. **A trilha do dinheiro é a espinha.** Origem (tributo ou transferência), rio de afluentes (água vinculada e
   água livre), secretaria, contrato e empresa, empenho, liquidação, pagamento e prestação de contas. Cada
   desconformidade aparece no ponto da trilha onde acontece, nunca numa lista solta.
2. **É uma trilha, não um cartório.** Nada espera validação humana. O sistema mostra, a fonte prova e a
   ausência acusa. Por isso nenhuma tela tem botão de aprovar, conferir ou validar.
3. **Toda informação carrega a origem**: o endereço lido, a data da leitura, a impressão digital e o selo.
4. **Indícios e fichas como no Cadê o Queijo**, aprimorados, porque foram aprovados pelo dono.
5. **Recortes globais**: alvo, período e secretaria valem em todas as telas, e a Máquina do Tempo mostra o
   passado realizado e o futuro projetado.
6. **Desconformidades por família**, fáceis de achar e de apresentar.
7. **Feito para apresentar e para ser temido**: claro, impactante, com a prova a um clique. O alerta é
   indício e não acusação, mas é apresentado com a força da prova.
8. **Acesso por link no navegador**, como o Eldorado e a Bússola: GitHub Pages, sem instalação.

## 2. Quantas páginas e por quê

O Onisciente tem **treze páginas**: uma página inicial e doze telas. O número sai de duas regras.

* **Uma pergunta por tela.** Cada tela responde a uma pergunta que o dono faria numa reunião ("de onde veio o
  dinheiro?", "quem recebeu?", "o que falta publicar?"). Duas perguntas na mesma tela obrigam a rolar e
  quebram a apresentação; uma pergunta espalhada em duas telas obriga a ir e voltar.
* **Nenhum grupo com mais de quatro telas.** As doze telas se organizam em quatro trechos do rio, e cada
  trecho cabe de uma vez na memória de quem navega.

| Trecho do rio | Tela | A pergunta que ela responde | Arquivo |
| --- | --- | --- | --- |
| Início | Em uma frase | O que está errado neste mês, em uma frase, e onde fica cada desconformidade? | `index.html` |
| Nascente | O rio | De onde veio o dinheiro, que parte é vinculada e que parte é livre, e para onde correu? | `rio.html` |
| Nascente | Leis | Qual é a régua de cada conferência e onde está a norma? | `leis.html` |
| Leito | Trilha | Por quais das nove estações o dinheiro passou com documento? | `trilha.html` |
| Leito | Secretarias | Quanto cada secretaria contratou, quanto destoa e quão transparente ela é? | `secretarias.html` |
| Leito | Pisos e tetos | Os percentuais da Constituição e da LRF foram cumpridos, pelo cálculo próprio? | `pisos.html` |
| Leito | Pessoal | Quanto se gasta com pessoal, perto de que limite, e o que a lei manda pagar e não foi pago? | `pessoal.html` |
| Foz | Preço e entrega | O preço pago bate com o país, a entrega foi comprovada e a conta foi prestada? | `precos.html` |
| Foz | Contratos e empresas | Quem são as empresas, quem as administra e elas podiam contratar? | `empresas.html` |
| Foz | Contas | As contas foram entregues e julgadas no prazo? | `contas.html` |
| Margens | Indícios | Quais são todas as fichas, filtráveis por família, gravidade, secretaria e período? | `indicios.html` |
| Margens | Transparência | O selo de transparência se sustenta, o que falta publicar e qual ofício já está pronto? | `transparencia.html` |
| Margens | Máquina do tempo | O que foi previsto e realizado desde 2019, e o que se projeta até o fim do PPA? | `tempo.html` |

Os pareceres mensais (`docs/onisciente/parecer_AAAA-MM.html`) e a página do banco histórico
(`docs/onisciente/banco/`) continuam onde estão e ficam ligados na página inicial e no rodapé de todas as
telas.

## 3. Mapa de navegação e hierarquia da informação

A informação desce em quatro níveis, do mais amplo ao mais concreto. Cada nível tem a sua forma visual.

1. **Panorama** (página inicial): a frase do mês, o placar por gravidade, a nota de integridade da trilha e o
   **rio-mapa**, uma faixa horizontal com as nove estações em que cada desconformidade aparece como um marco
   no ponto da trilha onde acontece.
2. **Tela** (uma pergunta): os números grandes da pergunta, o gráfico principal e a lista do que destoa.
3. **Ficha** (o indício): título, gravidade, como deveria ser, como está, verificação, providência e
   custódia, no formato do Cadê o Queijo.
4. **Ato e prova** (o original): o endereço lido, a data e a impressão digital, abertos pelo selo.

Qualquer desconformidade fica a no máximo três cliques da página inicial:

* **clique 1**: no quadro das famílias da página inicial (ou no marco do rio-mapa), a família leva à tela e
  à seção exata, já filtrada;
* **clique 2**: na tela, a linha ou o marco abre a ficha;
* **clique 3**: na ficha ou em qualquer número, o selo abre o original guardado.

O endereço de cada página leva os recortes na própria URL (`?c=2026-10&s=01393989000103`), então um link
mandado por mensagem abre exatamente o que quem mandou estava vendo.

### Navegação persistente

* **Barra do topo**: escudo e nome, seletores de alvo, período e secretaria, botão Apresentar e alternância
  de tema claro e escuro.
* **Régua do rio**: logo abaixo do topo, os quatro trechos (Nascente, Leito, Foz e Margens) com as telas de
  cada um. Cada tela mostra o número de desconformidades do recorte atual, para que a pessoa veja onde está o
  problema antes de clicar.
* **Caminho de volta**: cada tela termina com a tela anterior e a próxima na ordem da trilha, para que a
  leitura possa seguir o dinheiro do começo ao fim sem voltar ao menu.

## 4. Onde aparece cada família de desconformidade

| Família | Onde aparece primeiro | Onde está a prova | Estado hoje |
| --- | --- | --- | --- |
| **Selo de transparência** | Transparência, no topo: o selo declarado (Diamante) contra o selo refeito pelo Onisciente, critério por critério | cada critério abre o endereço que o comprovaria ou mostra o roxo da ausência | aguarda a frente do selo (formato na seção 9) |
| **Preços** | Preço e entrega, vértice Preço do triângulo; Indícios, família PRC | cada item abre a compra no PNCP e a mediana nacional do Compras.gov | com dado real (bloco 4) |
| **Contratos e empresas (Receita e QSA)** | Contratos e empresas: cada fornecedor com idade da empresa, quadro de sócios, sanções e contratos | o cartão do CNPJ e as listas CEIS e CNEP | concentração e contratos com dado real; QSA e sanções aguardam a frente das empresas |
| **FNAS** | O rio, cartão do afluente FNAS (fonte 1660): o que a União mandou contra o que entrou na fonte da assistência | planilha do FNAS e Portal da Transparência | com dado real |
| **COSIP** | O rio, cartão do afluente COSIP (fonte 1751, Lei Complementar 386/2025): o leito da iluminação pública contra as funções onde foi empenhada | matriz de saldos contábeis do mês | com dado real |
| **Notas fiscais nunca publicadas** | Preço e entrega, vértice Entrega do triângulo, em roxo, com os órgãos que nunca publicaram nota | a leitura do PNCP de cada órgão, mês a mês | com dado real |
| **Execução** | Trilha: as estações de empenho, liquidação e pagamento; o percurso empenho a empenho | o portal de execução, quando coletado | agregado real pela matriz; empenho a empenho aguarda a frente da execução |
| **Pessoal** | Pessoal: a despesa com pessoal contra 54% da receita corrente líquida, o que a lei manda pagar e não foi pago | RGF de cada quadrimestre | com dado real |
| **Contas** | Contas: cada entrega ao Tesouro com prazo e atraso; as contas anuais com os prazos da Lei Orgânica | o extrato de entregas do SICONFI | com dado real (entregas); julgamento pela Câmara aguarda fonte |
| **Leis e ofícios** | Leis (a régua) e Transparência (os ofícios prontos e a escada contra a não resposta) | o texto da norma no ctresb/leis ou no Sileg | com dado real |

Os nomes seguem o que já existe no repositório: **COSIP** é a Contribuição para o Custeio do Serviço de
Iluminação Pública, fonte de recursos 1751, regida pela Lei Complementar municipal 386/2025 (no mapa legal,
"Contribuição de iluminação pública (COSIP)"); **FNAS** é o Fundo Nacional de Assistência Social, fonte 1660,
conferido pela origem no Portal da Transparência e pela planilha de repasses do próprio FNAS.

## 5. Modo apresentação

Feito para reuniões da Associação, do Conselho e da oposição.

* O botão **Apresentar** (ou a tecla **P**) põe a tela em tela cheia e mostra **uma ideia por vez**: cada
  bloco marcado como lâmina vira um slide, com o título grande, o número principal em destaque e a fonte no
  rodapé.
* As **setas** (e a barra de espaço) avançam e voltam. Ao fim da última lâmina de uma tela, a seta leva à
  primeira lâmina da tela seguinte na ordem da trilha, então uma reunião inteira cabe numa sequência só.
* **Esc** sai do modo. Um contador discreto mostra a lâmina atual e o total.
* No modo apresentação o fundo é sempre escuro e o contraste é reforçado, para projetor.
* A URL guarda o modo (`&apresentar=1`), para que a apresentação possa ser aberta já pronta.

## 6. Leitura no celular

* As telas são feitas para 360 pixels de largura antes de tudo. Os gráficos largos (o rio, a linha do tempo)
  rolam de lado dentro do próprio quadro, e a página nunca rola de lado.
* Os seletores viram uma barra recolhível no topo, com o recorte atual sempre visível em uma linha.
* A régua do rio vira uma faixa que rola de lado, com a tela atual centralizada.
* A origem de um número abre com um toque (no lugar do passar de mouse), num balão que fica até o próximo
  toque, com o botão de abrir o original.
* Tabelas longas viram cartões empilhados abaixo de 640 pixels.

## 7. Acessibilidade (WCAG AA)

* Contraste mínimo de 4,5:1 para texto e 3:1 para elementos gráficos, nos dois temas.
* **Nada depende só da cor.** Cada selo tem forma e palavra além da cor: o verde é um círculo cheio com
  "duas vias", o azul um círculo com "uma via", o roxo um quadrado pulsante com "não publicado" e o vermelho
  um triângulo com "leitura falhou". Cada gravidade tem rótulo escrito.
* Tudo funciona pelo teclado: a ordem de tabulação segue a leitura, o foco é visível em ouro, os gráficos têm
  descrição em texto e uma tabela equivalente.
* O pulso do roxo para quando o sistema pede menos movimento.
* Os textos estão em português do Brasil, com frases inteiras, sem siglas soltas na primeira menção.

## 8. Cores com significado fixo

As mesmas cores querem dizer a mesma coisa em todas as telas, no parecer e no modo apresentação.

| Sentido | Cor (claro / escuro) | Forma | Uso |
| --- | --- | --- | --- |
| **Conforme** | verde #15803D / #34C26B | círculo cheio | duas vias batem, limite cumprido, estação acesa |
| **Indício** | laranja #E07B00 / #FF9F2E | losango | desconformidade de gravidade alta ou média |
| **Indício crítico** | vermelho #E01B0E / #FF4A3D | losango com borda dupla | desconformidade de gravidade crítica |
| **Alerta** | ouro #B57C05 / #F5B82E | anel | limite de alerta ou prudencial, ritmo abaixo do esperado |
| **Ausência de dado** | roxo #7E22CE / #B57BFF, pulsante | quadrado | a lei manda publicar e não está publicado |
| **Uma via** | azul #2563EB / #6EA0FF | círculo | o número vem de uma via oficial |
| **Leitura falhou** | vermelho escuro #B91C1C / #F05252 | triângulo | o dado existe, mas a leitura não o alcançou |

As cores do rio são de outra família, para não se confundirem com as de juízo: água **vinculada** em
petróleo (#0E7490), água **livre** em ouro claro (#C98A06), esfera federal, estadual e municipal em verde,
azul e laranja suaves.

## 9. A metáfora do rio como espinha da navegação

* A página inicial abre com o **rio-mapa**: os afluentes à esquerda (tributos e transferências), o leito
  no meio (a fonte, vinculada ou livre) e as nove estações em sequência até a foz (a prestação de contas).
* Os quatro trechos do rio são o menu: **Nascente** (de onde vem e qual é a régua), **Leito** (por onde passa
  e quem guarda), **Foz** (quem recebe e se prestou contas) e **Margens** (o que transbordou, o que falta e o
  que se projeta).
* Na tela do rio, o Sankey tem três modos: **Todo o rio**, **Vinculada** e **Livre**. Os tributos vinculados
  e os livres entram como afluentes; o leito separa a água pela fonte; a foz abre as funções de governo onde
  a água foi empenhada. A diferença entre o que entrou e o que foi empenhado aparece como água parada.
* A COSIP e o FNAS ganham cartões próprios ao lado do rio, porque são os dois afluentes vinculados em que o
  sistema já achou água fora do leito.

## 10. A origem de cada dado

Todo número das telas é desenhado por uma única função, e essa função exige a chave da fonte. Por isso não
existe número sem origem.

* **Passar o mouse ou tocar** mostra o balão da origem: o nome da fonte, a data da leitura, a impressão
  digital (sha256) e o selo.
* **Clicar** abre o original guardado. Quando a coleta guardou a resposta crua e ela ainda bate com a
  impressão digital, a cópia vai junto com o site e o clique abre a cópia; senão, abre o endereço exato que o
  motor leu.
* Quando um número não tem original guardado, o balão diz isso com todas as letras ("o original deste
  número não está guardado no banco").

## 11. Estado vazio: aguardando a coleta

As telas que dependem de dados ainda em construção pelas outras frentes leem um arquivo JSON simples em
`relatorios/onisciente/entradas/`. Enquanto o arquivo não existe, a seção mostra um quadro sereno com o
nome da coleta que falta ("Aguardando a coleta das empresas na Receita Federal"), o que ela vai mostrar e a
fonte de onde virá. O quadro usa o roxo da ausência apenas quando a falta é do Município; quando a falta é do
próprio sistema (coleta ainda não feita), usa o cinza neutro, porque a falha do sistema nunca é imputada ao
Município.

### Formatos de entrada (para a integração)

Todos os arquivos são UTF-8, com datas em `AAAA-MM-DD`, meses em `AAAA-MM` e valores em reais com ponto
decimal. Todo registro traz `url` (o endereço lido), `lido_em` e, quando houver, `sha256`; é daí que sai o
selo de cada número. Campos desconhecidos são ignorados.

**`selo_transparencia.json`** (frente do selo):

```json
{
  "programa": "Programa Nacional de Transparência Pública (PNTP)",
  "ciclo": "2025",
  "declarado": {"nivel": "Diamante", "nota": 97.5, "url": "https://...", "lido_em": "2026-11-20"},
  "auditado": {"nivel": "Prata", "nota": 71.2},
  "criterios": [
    {"id": "1.1", "criterio": "Divulga a receita prevista e realizada", "peso": "essencial",
     "declarado": true, "auditado": "cumpre | falha | sem_dado", "prova_url": "https://...",
     "lido_em": "2026-11-20", "nota": "texto curto do que o Onisciente viu"}
  ],
  "por_orgao": [{"cnpj": "01393989000103", "orgao": "Fundo Municipal de Assistência Social",
                 "nota": 12.0, "nivel": "Inexistente", "nota_texto": "o Conselho não tem portal"}]
}
```

**`empresas.json`** (frente das empresas; Receita Federal, QSA e sanções):

```json
{
  "empresas": [
    {"cnpj": "08932623000104", "razao": "...", "abertura": "2023-05-02", "situacao": "ATIVA",
     "capital": 10000.0, "cnae": "texto da atividade principal",
     "socios": [{"nome": "...", "qualificacao": "Sócio-Administrador", "desde": "2023-05-02"}],
     "sancoes": [{"cadastro": "CEIS | CNEP", "inicio": "2024-01-10", "fim": "2026-01-10", "orgao": "..."}],
     "alertas": [{"tipo": "empresa_recente | sem_experiencia | sancionada | socio_servidor | endereco_comum",
                  "gravidade": "critica | alta | media", "texto": "frase inteira"}],
     "url": "https://...", "lido_em": "2026-11-27", "sha256": "..."}
  ]
}
```

Os contratos de cada empresa vêm do banco (PNCP) pelo CNPJ; o arquivo não precisa repeti-los. CPF de sócio
nunca é publicado: só nome e qualificação, como a Receita divulga.

**`execucao.json`** (frente da execução; empenho a empenho):

```json
{
  "empenhos": [
    {"numero": "2026NE000123", "data": "2026-03-04", "orgao_cnpj": "01393989000103", "credor": "...",
     "credor_cnpj": "...", "fonte": "1660", "funcao": "08", "natureza": "33503900", "valor": 120000.0,
     "contrato": "01393989000103-2-000003/2026",
     "eventos": [{"estacao": "empenho | liquidacao | pagamento", "data": "2026-03-04", "valor": 120000.0,
                  "documento": "nota de empenho 123", "url": "https://...", "lido_em": "2026-11-27"}],
     "url": "https://...", "lido_em": "2026-11-27"}
  ]
}
```

**`federais.json`** (frente das transferências federais: FNS, FNDE, Transferegov):

```json
{
  "repasses": [
    {"origem": "FNS | FNDE | FNAS | Transferegov", "mes": "2026-03", "programa": "...", "valor": 1000.0,
     "fonte_destino": "1600", "registrado": 950.0, "url": "https://...", "lido_em": "2026-11-27"}
  ]
}
```

Os quatro arquivos são escritos por `onisciente/telas/entradas.py`, chamado pelo próprio
`python -m onisciente telas`, a partir do que as outras frentes deixam no repositório e no banco: a auditoria
do selo (`relatorios/onisciente/selo/auditoria.json`, com as leituras oficial e restritiva, comprovada e teto,
e as obrigações F1 a F5 do Fundo e C1 a C4 do Conselho em `por_orgao`), a conferência das empresas (com a
cobertura e os cadastros de sanção não conferidos), os eventos da execução (`despesa_eventos`) e os repasses
federais (FNS, FNDE, FNAS e Transferegov, com a situação de cada origem). Cada arquivo traz `situacao`:
`dado` ou `coleta_nao_feita`. A segunda, e também uma lista vazia, aparece em cinza com o motivo, como falha
do próprio sistema, nunca em roxo.

Com o arquivo presente, a seção correspondente troca o quadro de espera pelo dado, com os mesmos selos,
filtros e recortes das demais telas. Basta rodar `python -m onisciente telas` de novo.

## 12. Como o desenho foi construído

* **Gerador**: `python -m onisciente telas` (módulo `onisciente/telas/`). Ele lê o banco histórico, os
  panoramas mensais de `relatorios/onisciente/` e os arquivos de entrada da seção 11, e escreve as treze
  páginas em `docs/onisciente/app/`, com `app.css`, `app.js` e o escudo. Com `--brutos`, publica também as
  respostas cruas cuja impressão digital bate com o banco, em `docs/onisciente/app/originais/`.
* **Uma página, três camadas de dados**: o recorte comum (alvo, competências, secretarias, temas), o índice de
  todas as fichas (para os contadores da régua e do quadro das famílias em qualquer recorte) e os dados da
  própria tela, cada número como `{"v": valor, "f": chave da fonte}`. A tabela das fontes vai junto, só com
  as chaves que a página usa.
* **Os temas do quadro da página inicial** são catorze, porque além das dez famílias pedidas (selo, preços,
  contratos e empresas, FNAS, COSIP, notas fiscais, execução, pessoal, contas, leis e ofícios) há quatro que
  já têm fichas reais: água fora do leito, pisos e tetos, orçamento e receita, e falhas do próprio sistema
  (estas em cinza, nunca imputadas ao Município). Cada ficha cai em um tema pelo código, e cada tema mora numa
  tela e numa seção.
* **Séries no parecer mensal**: `onisciente/telas/graficos.py` desenha, em SVG embutido e sem biblioteca, as
  séries do exercício (o Município, o FNAS e a pasta), cada barra com a origem na dica.
* **Travas**: `testes/test_telas.py` monta um banco pequeno e confere as treze páginas, a fonte de cada
  número, os três modos do rio, os filtros dos indícios, os recortes, o estado vazio e a chegada das entradas,
  a ausência de CPF e o desenho de cada tela rodando o próprio `app.js` no Node.
