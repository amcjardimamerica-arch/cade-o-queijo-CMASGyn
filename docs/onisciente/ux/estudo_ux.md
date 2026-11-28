# Estudo de UX do Onisciente

Este estudo define como o Onisciente se apresenta a quem o lê: o número de páginas, o caminho até cada
desconformidade, o modo de apresentação para reuniões, a leitura no celular, a acessibilidade, as cores e o
formato dos dados que as outras frentes entregam às telas. Ele parte da linha do tempo da conversa com o dono
(25 a 28 de novembro de 2026) e do protótipo navegável de 25/11, cuja identidade visual (o escudo do Núcleo
de Fiscalização da A.M.C. Jardim América, o azul real, o ouro e o laranja, os títulos em Zilla Slab e os
números em IBM Plex Mono) foi aprovada e é mantida aqui.

O site novo fica em `docs/onisciente/app/`. A página inicial é `docs/onisciente/app/index.html`, publicada
no GitHub Pages do repositório como `…/onisciente/app/`. Ela é gerada por `python -m onisciente telas`, a
partir do banco histórico e dos módulos do sistema, sem rede.

## 1. As premissas que governam o desenho

As premissas vêm da linha do tempo, nas palavras do dono sempre que possível.

> **Correção de 28/11/2026.** O dono pediu: "Remova essa merda de premissa de rio. Eu dei de exemplo como se
> fosse um fluxo para a imagem visual e não para ser usado no sistema inteiro. O sistema deve ter uma premissa
> mais organizada e fácil de entender, com poucos cliques. Não quero premissas literais, mas imagens para
> etapas ou condições." A imagem do rio saiu de tudo o que a pessoa lê (telas, menus, parecer, fichas,
> documentação). O painel passou a se organizar pelas **etapas do gasto público** e a mostrar cada
> situação por uma de **três condições**, sempre com o mesmo ícone. Os módulos internos do Python
> (`onisciente/rio/`) mantêm o nome da pasta; nada do que se mostra usa a palavra.

1. **As etapas do gasto público são a espinha.** Origem do dinheiro, orçamento, contratação, liquidação,
   pagamento e prestação de contas. Cada desconformidade cai na etapa em que acontece, nunca numa lista solta.
2. **Três condições, um código visual.** Toda situação é **conforme**, **alerta** (com a gravidade) ou
   **sem dado**. Cada condição tem o seu ícone, igual em todas as páginas, e a cor só reforça o ícone.
3. **Poucos cliques.** Da página inicial a qualquer desconformidade são no máximo dois cliques.
4. **Linguagem direta.** Cada coisa tem o seu nome técnico: recurso vinculado ou livre, finalidade da lei,
   receita por espécie, diferença da execução. Nada de metáfora no texto; as imagens ficam para as etapas
   e as condições.
5. **É uma trilha, não um cartório.** Nada espera validação humana. O sistema mostra, a fonte prova e a
   ausência acusa. Por isso nenhuma tela tem botão de aprovar, conferir ou validar.
6. **Toda informação carrega a origem**: o endereço lido, a data da leitura, a impressão digital e o selo.
7. **Indícios e fichas como no Cadê o Queijo**, aprimorados, porque foram aprovados pelo dono.
8. **Recortes globais**: alvo, período e secretaria valem em todas as telas; a tela Previsto e realizado
   mostra o passado realizado e o futuro projetado.
9. **Feito para apresentar e para ser temido**: claro, impactante, com a prova a um clique. O alerta é
   indício e não acusação, mas é apresentado com a força da prova.
10. **Acesso por link no navegador**, como o Eldorado e a Bússola: GitHub Pages, sem instalação.

## 2. Quantas páginas e por quê

O Onisciente continua com **treze páginas**: uma página inicial e doze telas. A revisão de 28/11/2026
conferiu se o número devia cair e decidiu mantê-lo, por três razões.

* **O caminho até a desconformidade não depende do número de telas.** Ele passa pela página inicial e pela
  lista das desconformidades filtrada por etapa: dois cliques, qualquer que seja a tela onde o detalhe mora.
* **Uma pergunta por tela.** Juntar telas obrigaria a rolar e quebraria o modo apresentação (uma ideia por
  lâmina). Separar mais obrigaria a ir e voltar.
* **Nenhum grupo com mais de três telas.** As telas se agrupam pelas etapas; a pessoa vê de uma vez onde está.

A única página renomeada foi a da origem: `rio.html` virou `origem.html` ("Origem do dinheiro"), e a tela
"Máquina do tempo" passou a se chamar "Previsto e realizado". Os títulos dizem o que a tela mostra.

| Grupo (etapa) | Tela | A pergunta que ela responde | Arquivo |
| --- | --- | --- | --- |
| Início | Início | O que está errado neste mês, em que etapa, e com que condição? | `index.html` |
| Origem do dinheiro | Origem do dinheiro | De onde veio o dinheiro, que parte é vinculada e que parte é livre, e em que função foi empenhado? | `origem.html` |
| Orçamento | Pisos e tetos | Os percentuais da Constituição e da LRF foram cumpridos, pelo cálculo próprio? | `pisos.html` |
| Orçamento | Previsto e realizado | O que foi previsto e realizado desde 2019, e o que se projeta até o fim do PPA? | `tempo.html` |
| Contratação | Contratos e empresas | Quem são as empresas, quem as administra e elas podiam contratar? | `empresas.html` |
| Contratação | Preço e entrega | O preço pago bate com o país, a entrega foi comprovada e a conta foi prestada? | `precos.html` |
| Liquidação e pagamento | Execução | Por quais das nove estações o dinheiro passou com documento? | `trilha.html` |
| Liquidação e pagamento | Pessoal | Quanto se gasta com pessoal, perto de que limite, e o que a lei manda pagar e não foi pago? | `pessoal.html` |
| Prestação de contas | Contas | As contas foram entregues e julgadas no prazo? | `contas.html` |
| Prestação de contas | Transparência | O selo de transparência se sustenta, o que falta publicar e qual ofício já está pronto? | `transparencia.html` |
| Consulta | Desconformidades | Todas as fichas, filtráveis por etapa, condição, família, gravidade, secretaria e período | `indicios.html` |
| Consulta | Secretarias | Quanto cada secretaria contratou, quanto destoa e quão transparente ela é? | `secretarias.html` |
| Consulta | Normas | Qual é a régua de cada conferência e onde está a norma? | `leis.html` |

Os pareceres mensais (`docs/onisciente/parecer_AAAA-MM.html`) e a página do banco histórico
(`docs/onisciente/banco/`) continuam onde estão e ficam ligados na página inicial e no rodapé de todas as
telas.

## 3. Mapa de navegação e hierarquia da informação

A informação desce em quatro níveis, do mais amplo ao mais concreto. Cada nível tem a sua forma visual.

1. **Panorama** (página inicial): a frase do mês, o placar por gravidade e o **diagrama das etapas**, seis
   cartões na ordem do gasto, cada um com o seu ícone e as três condições contadas no recorte (quantos
   pontos conformes, quantos alertas e de que gravidade, quantos sem dado).
2. **Lista da etapa** (`indicios.html?etapa=…`): o cabeçalho da etapa com as telas onde ela aparece em
   detalhe e todas as fichas da etapa, agrupadas por tema, inteiras, sem "mostrar mais".
3. **Ficha** (o indício): título, condição, gravidade, como deveria ser, como está, verificação,
   providência e custódia, no formato do Cadê o Queijo.
4. **Ato e prova** (o original): o endereço lido, a data e a impressão digital, abertos pelo selo.

Qualquer desconformidade fica a **no máximo dois cliques** da página inicial:

* **clique 1**: o cartão da etapa (ou a secretaria, no quadro "Por secretaria", ou as falhas de leitura do
  sistema, logo abaixo das etapas) abre a lista inteira daquela etapa;
* **clique 2**: a ficha abre no lugar, com a prova.

O selo de cada número abre o original guardado, a partir da ficha ou de qualquer tela. Uma trava
(`test_inicio_tem_o_diagrama_das_etapas_e_toda_ficha_a_dois_cliques`) confere que as contagens do diagrama
batem com as listas e que nenhuma ficha do recorte fica fora delas.

O endereço de cada página leva os recortes na própria URL (`?c=2026-10&s=01393989000103&etapa=origem`),
então um link mandado por mensagem abre exatamente o que quem mandou estava vendo.

### Navegação persistente

* **Barra do topo**: escudo e nome, seletores de alvo, período e secretaria, botão Apresentar e alternância
  de tema claro e escuro.
* **Barra das etapas**: logo abaixo do topo, os grupos (Início, Origem do dinheiro, Orçamento, Contratação,
  Liquidação e pagamento, Prestação de contas, Consulta), cada um com o ícone da etapa e as suas telas. Cada
  tela mostra o número de desconformidades do recorte atual.
* **Faixa das condições**: no alto de cada tela, quantos alertas e quantos sem dado os temas daquela tela
  têm no recorte, com o atalho para a lista.
* **Caminho**: cada tela termina com a tela anterior e a próxima na ordem das etapas, para que a leitura siga
  o gasto do começo ao fim sem voltar ao menu; a última volta às etapas.

### As etapas, as condições e os ícones

| Etapa | O que confere | Ícone | Temas |
| --- | --- | --- | --- |
| Origem do dinheiro | Receita e repasses, recurso vinculado ou livre | pilha de moedas com seta | vinculado fora da finalidade, COSIP, FNAS |
| Orçamento | Previsão, dotação, pisos e tetos | calculadora | pisos e tetos, orçamento e receita |
| Contratação | Licitação, contrato, empresa e preço | documento com assinatura | contratos e empresas, preços |
| Liquidação | A entrega comprovada por nota fiscal | caixa | notas fiscais |
| Pagamento | O dinheiro que saiu e o que deixou de sair | cédula | execução, pessoal |
| Prestação de contas | Contas entregues, julgadas e publicadas | prancheta com visto | contas, selo de transparência, normas e ofícios |

| Condição | Ícone | Quando |
| --- | --- | --- |
| **Conforme** | círculo com visto, verde | o documento está publicado e a conferência não achou desconformidade |
| **Alerta** | triângulo com exclamação; vermelho crítico, laranja alto, amarelo médio | indício de desconformidade |
| **Sem dado** | quadrado tracejado com interrogação; roxo quando falta documento do Município, cinza quando é leitura do próprio sistema | a lei manda publicar e não está publicado, ou o sistema ainda não leu |

Os ícones são SVG próprios, desenhados uma vez em cada página (um bloco de símbolos no começo do corpo) e
usados por referência, sem biblioteca nem endereço externo. Os selos de origem dos números (duas vias, uma
via, não publicado, leitura falhou, aguardando coleta) usam o ícone da condição correspondente.

## 4. Onde aparece cada família de desconformidade

| Família | Onde aparece primeiro | Onde está a prova | Estado hoje |
| --- | --- | --- | --- |
| **Selo de transparência** | Transparência, no topo: o selo declarado (Diamante) contra o selo refeito pelo Onisciente, critério por critério | cada critério abre o endereço que o comprovaria ou mostra o roxo da ausência | aguarda a frente do selo (formato na seção 9) |
| **Preços** | Preço e entrega, vértice Preço do triângulo; Indícios, família PRC | cada item abre a compra no PNCP e a mediana nacional do Compras.gov | com dado real (bloco 4) |
| **Contratos e empresas (Receita e QSA)** | Contratos e empresas: cada fornecedor com idade da empresa, quadro de sócios, sanções e contratos | o cartão do CNPJ e as listas CEIS e CNEP | concentração e contratos com dado real; QSA e sanções aguardam a frente das empresas |
| **FNAS** | Origem do dinheiro, cartão da fonte vinculada FNAS (fonte 1660): o que a União mandou contra o que entrou na fonte da assistência | planilha do FNAS e Portal da Transparência | com dado real |
| **COSIP** | Origem do dinheiro, cartão da fonte vinculada COSIP (fonte 1751, Lei Complementar 386/2025): as funções que a lei permite contra as funções onde foi empenhada | matriz de saldos contábeis do mês | com dado real |
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

* As telas são feitas para 360 pixels de largura antes de tudo (conferidas a 375). Os gráficos largos (o
  diagrama da receita, a linha do tempo) rolam de lado dentro do próprio quadro, e a página nunca rola de lado.
* O diagrama das etapas vira uma lista vertical: cada etapa numa linha, com o ícone à esquerda e as três
  condições logo abaixo do nome.
* Os seletores viram uma barra recolhível no topo, com o recorte atual sempre visível em uma linha.
* A barra das etapas vira uma faixa que rola de lado dentro de si, com o ícone de cada grupo.
* A origem de um número abre com um toque (no lugar do passar de mouse), num balão que fica até o próximo
  toque, com o botão de abrir o original.
* Tabelas longas viram cartões empilhados abaixo de 640 pixels.

## 7. Acessibilidade (WCAG AA)

* Contraste mínimo de 4,5:1 para texto e 3:1 para elementos gráficos, nos dois temas.
* **Nada depende só da cor.** Cada condição tem ícone e palavra além da cor: conforme é o círculo com
  visto, alerta o triângulo com exclamação e sem dado o quadrado tracejado com interrogação. Cada selo de
  origem leva o ícone da sua condição e a palavra ("duas vias", "uma via", "não publicado", "leitura
  falhou"). Cada gravidade tem rótulo escrito. Cada cartão de etapa tem a descrição completa para leitor de
  tela.
* Tudo funciona pelo teclado: a ordem de tabulação segue a leitura, o foco é visível em ouro, os gráficos têm
  descrição em texto e uma tabela equivalente.
* O pulso do roxo para quando o sistema pede menos movimento.
* Os textos estão em português do Brasil, com frases inteiras, sem siglas soltas na primeira menção.

## 8. Cores com significado fixo

As mesmas cores querem dizer a mesma coisa em todas as telas, no parecer e no modo apresentação. A cor sempre
acompanha um ícone; nunca vem sozinha.

| Sentido | Cor (claro / escuro) | Ícone | Uso |
| --- | --- | --- | --- |
| **Conforme** | verde #15803D / #34C26B | círculo com visto | duas vias batem, limite cumprido, estação com documento |
| **Alerta alto ou médio** | laranja #E07B00 / #FF9F2E; amarelo #A16207 / #E3B341 | triângulo com exclamação | desconformidade de gravidade alta ou média |
| **Alerta crítico** | vermelho #E01B0E / #FF4A3D | triângulo com exclamação | desconformidade de gravidade crítica |
| **Sem dado do Município** | roxo #7E22CE / #B57BFF, pulsante no selo | quadrado tracejado com interrogação | a lei manda publicar e não está publicado |
| **Sem dado do sistema** | cinza #64748B / #8B98B8 | quadrado tracejado com interrogação | coleta ainda não feita ou leitura que falhou; nunca imputada ao Município |
| **Uma via** | azul #2563EB / #6EA0FF | círculo com visto | o número vem de uma via oficial |

As cores das fontes de recurso são de outra família, para não se confundirem com as de juízo: recurso
**vinculado** em petróleo (#0E7490), recurso **livre** em ouro claro (#C98A06), esfera federal, estadual e
municipal em verde, azul e laranja suaves.

## 9. A origem do dinheiro em detalhe

* A tela **Origem do dinheiro** mostra a receita realizada por espécie (à esquerda), separada pela fonte em
  recurso vinculado ou livre (no meio), e o empenhado por função de governo (à direita). O diagrama tem três
  modos: **Todas as fontes**, **Vinculada** e **Livre**. A diferença entre o que entrou e o que foi empenhado
  aparece como "arrecadado e não empenhado".
* A COSIP e o FNAS ganham cartões próprios, com as funções que a lei permite e o que foi empenhado fora da
  finalidade, porque são as duas fontes vinculadas em que o sistema já achou desvio.
* No parecer mensal, a seção 2 se chama "Origem do dinheiro", e a tabela que antes falava em "margens" se
  chama "diferença da execução" (previsto e não empenhado, empenhado e não liquidado, liquidado e não pago,
  pago sem vínculo publicado).

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

### Rastreio por hash (pedido da titular de 28/11/2026)

"Ao coletar as informações gere um código hash para rastreio dos dados e validação de cada informação
obtida." As telas mostram os hashes do rastreio (`onisciente/rastreio.py`) sem pedir nada à rede:

* **Ícone próprio** de "verificado por hash": uma cerquilha dentro de um hexágono, no mesmo traço dos ícones
  das condições e com forma diferente deles (o círculo, o triângulo e o quadrado são das condições). Verde
  quando confere com o selo do rastreio, vermelho quando a cadeia não confere, cinza quando o rastreio ainda
  não começou.
* **Em cada ficha**: o hash do achado com 12 caracteres na linha de resumo e o hash completo no `title`; no
  corpo, o hash do achado e o das provas (o próprio hash quando há uma prova, a raiz de Merkle quando há
  várias), cada um com o botão "copiar", que copia o hash inteiro.
* **No balão de origem de cada número**: o hash da resposta (o sha256 que a coleta guardou) e, quando o banco
  já tem o rastreio, o hash do registro da coleta e se ele confere com o selo da rodada.
* **Busca por hash** na tela de indícios (o rodapé de todas as telas leva a ela): o começo do hash, com 4
  caracteres ou mais, acha a ficha (pelo hash do achado ou das provas) ou a fonte (pela resposta ou pelo
  registro). O que não está nas telas fica para `python -m onisciente rastreio --hash`, que procura em todos
  os registros do banco.
* **No rodapé de todas as telas**: o topo da cadeia (a última rodada, o hash dela e a raiz de Merkle) e se a
  cadeia confere. Sem o arquivo `rastreio.db` ao lado do banco (banco ainda não migrado), o rodapé diz, em
  cinza e sem erro, que o rastreio começa na próxima coleta. As telas só leem: nunca criam o arquivo.

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
* **Uma página, três camadas de dados**: o recorte comum (alvo, competências, secretarias, temas, etapas), o
  índice de todas as fichas com a etapa e a condição de cada uma (para os contadores da barra e do diagrama
  das etapas em qualquer recorte) e os dados da
  própria tela, cada número como `{"v": valor, "f": chave da fonte}`. A tabela das fontes vai junto, só com
  as chaves que a página usa.
* **Os temas** são catorze, porque além das dez famílias pedidas (selo, preços, contratos e empresas, FNAS,
  COSIP, notas fiscais, execução, pessoal, contas, normas e ofícios) há quatro que já têm fichas reais:
  vinculado fora da finalidade, pisos e tetos, orçamento e receita, e falhas do próprio sistema (estas em
  cinza, nunca imputadas ao Município). Cada ficha cai em um tema pelo código, cada tema numa etapa, e cada
  tema mora numa tela e numa seção. A condição da ficha é "sem dado" quando ela acusa falta de publicação
  ou falha de leitura, e "alerta" nos demais casos.
* **Linguagem direta**: `onisciente/linguagem.py` guarda a régua (`metaforas`) e a troca dos textos
  guardados antes de 28/11/2026 (`direto`), aplicada a tudo o que vai para as telas e ao parecer, sem mudar
  número nenhum.
* **Séries no parecer mensal**: `onisciente/telas/graficos.py` desenha, em SVG embutido e sem biblioteca, as
  séries do exercício (o Município, o FNAS e a pasta), cada barra com a origem na dica.
* **Travas**: `testes/test_telas.py` monta um banco pequeno e confere as treze páginas, a fonte de cada
  número, os três modos da origem do dinheiro, os filtros dos indícios, os recortes, o estado vazio e a chegada das entradas,
  a ausência de CPF e o desenho de cada tela rodando o próprio `app.js` no Node. Desde 28/11/2026 também
  conferem que nenhuma página, o `app.js` e o parecer usam a metáfora do rio, que o diagrama das etapas leva a
  toda ficha em dois cliques e que cada condição tem o mesmo ícone em todas as páginas
  (`testes/test_linguagem_direta.py` e as últimas travas de `testes/test_telas.py`).
