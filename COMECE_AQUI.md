# Uma única ação sua

O sistema está configurado, testado e dispara sozinho. Falta um interruptor
que só a sua conta pode acionar.

## O interruptor

No repositório:

1. **Configurações** *(Settings)* — barra superior, à direita
2. **Ações** *(Actions)* → **Geral** *(General)* — menu da esquerda
3. Role até o fim, bloco **Permissões de fluxo de trabalho** *(Workflow permissions)*
4. Marque **Permissões de leitura e gravação** *(Read and write permissions)*
5. Marque **Permitir que o GitHub Actions crie e aprove pull requests**
6. **Salvar** *(Save)*

Só isso. Não é preciso criar conta na Anthropic, nem chave de API, nem
configurar o Pages — o próprio fluxo o habilita.

## Por que esse interruptor não pode ser dispensado

O agente coleta, analisa e monta o painel dentro de uma máquina temporária. Se
não puder gravar de volta no repositório, tudo se perde quando a máquina é
destruída. A permissão de escrita é o que faz o trabalho persistir.

O GitHub não permite que um fluxo de trabalho amplie a própria permissão além
do teto definido nas configurações do repositório — precisamente para impedir
que código enviado por terceiros se autorize sozinho. É uma proteção sua, e
funciona contra mim tanto quanto contra qualquer outro.

## O que acontece depois

Nada. O fluxo **Vigilância CMASGyn** roda a cada envio de arquivos e, dali em
diante, de segunda a sexta às 6h20 de Goiânia. A cada execução ele:

- continua a colheita do acervo, 90 edições por vez, até fechar as 379
- apura o semáforo diário da pasta de assistência social
- extrai trechos com proveniência e atualiza a biblioteca de atos
- roda a verificação dupla da publicidade
- reconcilia valores e mapeia a trilha do dinheiro
- executa a bateria de 15 testes
- reconstrói o painel e o publica
- abre um item em **Problemas** *(Issues)* quando há achado de severidade alta

## Como conferir se deu certo

Aba **Ações** *(Actions)* → fluxo **00 · Comece aqui**. Ele escreve um relatório
de prontidão em português dizendo exatamente o que está certo e o que falta.

O painel fica em:

**https://amcjardimamerica-arch.github.io/cmasgyn-vigilancia/**

## Se preferir que eu faça

Há um caminho, e cabe a você decidir: gerar um token de acesso pessoal
detalhado *(fine-grained)*, restrito a este repositório, com permissão de
Administration e Actions, validade de um dia. Com ele eu aciono a configuração
por API.

Não recomendo. O token ficaria registrado no histórico da conversa, e credencial
em texto de conversa é credencial comprometida — ainda que revogada depois.
Seis cliques seus custam menos do que esse risco. Mas a escolha é sua, e se
optar por esse caminho, revogue o token assim que a configuração terminar.
