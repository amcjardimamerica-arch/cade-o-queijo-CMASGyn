# Cadê o Queijo — a lógica do sistema, para quem vier depois

Este documento existe para que QUALQUER secretaria, de QUALQUER município,
possa ser fiscalizada com esta mesma máquina — herdando os aprendizados,
não os repetindo. A premissa vem da parlenda que dá nome ao projeto: o
queijo sumiu, e a resposta nunca é "sumiu"; é seguir a cadeia — o rato, o
gato, o cachorro, o pau, o fogo, a água, o boi — até alguém não ter para
quem apontar. Fiscalização é isso: cada resposta abre a pergunta seguinte,
e o sistema evolui adicionando elos, nunca encurtando a trilha.

## As trilhas (uma pergunta da parlenda por trilha, cada uma com ciclo próprio)

| Trilha | Pergunta | O que busca | Ciclo |
|---|---|---|---|
| **do Queijo** | cadê o dinheiro? | contas, receita, execução, duas contas da pasta | mensal (dia 1º) + eco no domingo pós-mês |
| **do Rato** | quem comeu? | destinatários, QSA, vínculos societários e de parentesco | semanal + enriquecimento contínuo |
| **do Gato** | quem pega o rato? | leis, normas e regulamentos aplicáveis (corpus) | mensal, ANTES das contas (a régua vem antes da medição) |
| **do Mato** | onde se escondeu? | julgados de tribunais de contas e casos de outros estados | mensal, pasta própria, nunca fundamenta — inspira |
| **do Fogo** | quem queima? | o julgamento dominical, 6h de Goiânia, modelo avançado | domingos + 1º domingo pós-mês |

## Doutrina inegociável (o que faz este sistema diferente)

1. **Cadeia de custódia**: nenhum dado entra sem âncora — sha256 do
   documento original + URL + data. A âncora vive no HISTÓRICO GIT, que é
   imutável. Todo achado é reproduzível por terceiro independente.
2. **Dupla verificação**: todo achado carrega selo. CONFIRMADO exige duas
   vias INDEPENDENTES (fontes que não derivam uma da outra). Uma via =
   INDICIÁRIO. Regra aplicada sem o documento = INCONCLUSIVO — e isso é
   ACHADO, não silêncio.
3. **Alarme de ausência**: informação que deveria existir e não existe
   dispara sinal próprio (o ROXO nos relatórios), com três respostas
   obrigatórias: o que falta, qual parâmetro fica impedido, onde obter
   (com a sonda de 2ª etapa dizendo se a fonte alternativa está no ar).
4. **Singularidade**: todo dado grande (PDF, planilha) é convertido em
   registro escrito simples, categorizado, com identidade única (hash) —
   nunca dois registros para o mesmo fato, nunca um fato sem registro.
5. **Fonte única não conclui**: estatística prioriza perícia, nunca a
   substitui. Indício de sobrepreço é indício. Precedente inspira
   providência, não fundamenta parecer.
6. **Coletivo não vira individual**: valor único para N beneficiários é
   registrado UMA vez, com a lista completa e a observação de que a falta
   de individualização é, ela própria, desconformidade.
7. **Determinístico primeiro**: 53% das tarefas não tocam modelo. Modelo
   barato faz triagem; modelo caro faz UM julgamento por domingo. Falha
   de fonte degrada limpo e fica registrada — nunca inventa.

## Os erros que já cometemos (testados em `testes_regressao.py` — não os repita)

1. Escrever código e não executar antes de afirmar que funciona.
2. Aceitar diagnóstico de terceiro sem caso de controle próprio.
3. Varredura em massa sem um caso sabidamente existente no mesmo lote.
4. Corrigir o resultado (o JSON) em vez da origem (o script que o gera).
5. Concluir que o dado não existe porque UM endereço caiu.
6. Somar totais sem separar por fonte — o agregado esconde o descumprido.
7. Passo de publicação que não commita o artefato novo (o ciclo "roda"
   e o resultado evapora) — todo relatório novo entra no `git add` E no
   contrato de ciclo (`src/valida_ciclo.py`).

## Como replicar para outra secretaria (checklist de bootstrap)

1. Novo repositório a partir deste (Q1: um por secretaria, sob demanda).
2. Trocar em `config/`: função orçamentária, unidades (a "conta especial"
   e a "conta do gabinete" da nova pasta), fundo correspondente e conselho
   de controle social, se houver.
3. Rodar `python3 testes_regressao.py` — TEM que passar antes do 1º ciclo.
4. Rodar o mensal de legislação ANTES do de contas (o Gato antes do Queijo).
5. Ativar as sondas de 2ª etapa e o detector de Diário reescrito desde o
   dia zero — a âncora só protege o que foi ancorado.
6. Manter a regra dos selos e do roxo intacta: é ela que faz o relatório
   valer como instrumento de exigência no mundo real (Artigo 5º, incisos
   XXXIII e XXXIV, da Constituição da República — direito de petição e de
   informação, exercido por associação no seu papel fiscalizador).
