# Passo a passo completo

Guia em português, na ordem exata de execução. Os nomes dos menus aparecem em
português com o termo em inglês entre parênteses, porque o GitHub às vezes
mistura os dois na mesma tela.

**Tempo estimado:** 90 minutos na primeira vez. Depois disso o sistema roda
sozinho.

**Ordem obrigatória:** as fases 1 a 4 acontecem no seu computador. Só depois de
o teste seco passar é que vale a pena subir para o GitHub. Não pule.

---

# FASE 1 — Preparar o seu computador

## 1.1 Instalar o Python

1. Acesse `https://www.python.org/downloads/`
2. Baixe a versão **3.12** ou superior.
3. Ao executar o instalador, **marque a caixa "Add Python to PATH"** na primeira
   tela. É o erro mais comum: sem isso, nada funciona depois.
4. Clique em "Install Now".

Para conferir, abra o **Prompt de Comando** (tecle `Windows`, digite `cmd`,
`Enter`) e digite:

```
python --version
```

Deve aparecer algo como `Python 3.12.4`. Se aparecer erro, reinstale marcando a
caixa do PATH.

## 1.2 Instalar o Git

1. Acesse `https://git-scm.com/download/win`
2. Baixe e instale aceitando todas as opções padrão.

Conferir:

```
git --version
```

## 1.3 Instalar o Tesseract, para reconhecimento óptico

Necessário apenas se o Diário Oficial vier escaneado como imagem.

1. Acesse `https://github.com/UB-Mannheim/tesseract/wiki`
2. Baixe o instalador de 64 bits.
3. Durante a instalação, na tela de idiomas, **marque "Portuguese"**.
4. Anote a pasta de instalação, normalmente
   `C:\Program Files\Tesseract-OCR`.

## 1.4 Descompactar o projeto

1. Descompacte `cmasgyn-vigilancia.zip` em um lugar de fácil acesso, por
   exemplo `C:\vigilancia\cmasgyn-vigilancia`.
2. Abra o Prompt de Comando e entre na pasta:

```
cd C:\vigilancia\cmasgyn-vigilancia
```

## 1.5 Instalar as bibliotecas

```
pip install -r requirements.txt
```

Demora alguns minutos. Se der erro de permissão, tente:

```
pip install --user -r requirements.txt
```

---

# FASE 2 — Descobrir o endereço do Diário Oficial

O endereço dos arquivos do Diário Oficial de Goiânia não é publicado. O sistema
**não inventa endereço** — ele procura e mostra os candidatos para você
confirmar.

## 2.1 Rodar a descoberta

```
python src\descobrir.py
```

O programa vai listar na tela alguns endereços candidatos e gravar todos em
`estado\dom_endpoint.json`.

## 2.2 Confirmar qual é o certo

1. Copie um dos endereços listados e cole no navegador.
2. Se abrir uma edição do Diário Oficial em PDF, é esse.
3. Observe como a data aparece no endereço. Exemplo fictício:

```
https://algumsite.goiania.go.gov.br/diarios/2026/08/2026-08-22.pdf
```

## 2.3 Escrever o gabarito

1. Abra o arquivo `estado\dom_endpoint.json` no Bloco de Notas.
2. Localize a linha `"padrao_confirmado": null`
3. Substitua o `null` pelo endereço, trocando a data pelos marcadores
   `{ano}`, `{mes}` e `{dia}`:

```json
"padrao_confirmado": "https://algumsite.goiania.go.gov.br/diarios/{ano}/{mes}/{ano}-{mes}-{dia}.pdf"
```

4. Salve e feche.

## 2.4 Se nenhum candidato funcionar

O programa terá gravado uma minuta de pedido em
`estado\minuta_lai_dom.txt`, fundada no artigo 8º, § 3º, incisos II e III, da
Lei 12.527/2011.

1. Abra o arquivo, revise o texto.
2. Protocole no Serviço de Informação ao Cidadão da Prefeitura:
   `https://www.goiania.go.gov.br/ouvidoria-e-sic/servico-informacao-cidadao/`
3. O prazo de resposta é de vinte dias, prorrogável por dez, na forma do artigo
   11, §§ 1º e 2º, da mesma lei.
4. Enquanto aguarda, siga para a Fase 3. O restante do sistema funciona sem o
   Diário Oficial — apenas com o acervo do CMASGyn.

---

# FASE 3 — Montar o corpus normativo

Este é o passo que exige mais atenção da sua parte, e é o que determina a
qualidade de toda a análise futura.

## 3.1 Rodar a consolidação

```
python src\corpus_build.py
```

Demora de cinco a quinze minutos. O programa baixa cada norma, extrai o texto e
grava tudo em um único arquivo, `corpus\corpus.md`.

## 3.2 Ler o relatório de pendências

Abra `relatorios\corpus_pendencias.md`. Ali estão as normas que **não** foram
incorporadas, porque eu não pude verificar o endereço oficial delas.

Cinco são críticas:

| Norma | Por que importa |
|---|---|
| **Lei 7.532/1995** | Cria o CMASGyn. É o rol de competências contra o qual cada resolução será confrontada. Sem ela, a verificação de pertinência temática fica cega. |
| **Regimento Interno do CMASGyn** | Define o prazo de publicação das atas e o quórum. |
| **PPA, LDO e LOA vigentes** | Necessários para verificar a dotação específica do controle social. |
| **Resoluções CNAS 14/2014 e 33/2012** | Requisitos de inscrição de entidades e norma operacional. |
| **Resolução CNAS 202/2025** | O piso de 10% do IGD. |

## 3.3 Resolver cada pendência

Há dois caminhos. Escolha o mais fácil para cada norma.

**Caminho A — você tem o PDF.** Coloque o arquivo na pasta `corpus\brutos\` com
o nome exato do `id` que aparece no relatório. Exemplo: se o relatório diz
`l7532_1995`, o arquivo deve se chamar `l7532_1995.pdf`.

**Caminho B — você tem o endereço.** Abra `config\corpus.yml` no Bloco de
Notas, ache a linha do item e substitua `CONFIRMAR` pelo endereço:

```yaml
- {id: l7532_1995, nome: "Lei 7.532/1995 — cria o CMASGyn", url: "https://endereco-real-aqui", critico: true}
```

Onde procurar cada uma:

- Leis municipais de Goiânia: `http://sileg.goiania.go.gov.br/`
- Resoluções do CNAS: `https://www.gov.br/participamaisbrasil/resolucoes12`
- Leis federais: `https://www.planalto.gov.br`
- LOA, LDO e PPA: `https://www.goiania.go.gov.br/transparencia/`

## 3.4 Rodar de novo

```
python src\corpus_build.py
```

Repita até o relatório de pendências não listar mais nenhum item crítico. Não
precisa zerar tudo — os itens marcados `obrigatorio: false` podem ficar de fora.

## 3.5 Conferir o resultado

Abra `corpus\manifesto.json`. Você verá quantas normas entraram e o tamanho
estimado em tokens. Algo entre 80.000 e 200.000 tokens é o esperado.

---

# FASE 4 — Teste seco, sem gastar nada

Roda a coleta, o filtro e todas as verificações determinísticas, e para antes
de chamar qualquer modelo. Custo zero.

**No Prompt de Comando:**

```
set LIMITE_TOKENS_JANELA=0
python src\run_diario.py
```

**No PowerShell:**

```
$env:LIMITE_TOKENS_JANELA=0
python src\run_diario.py
```

O que observar:

- O programa deve baixar arquivos do sítio do CMASGyn.
- Deve imprimir quantos trechos passaram no filtro.
- Deve gerar um boletim em `relatorios\boletim_AAAA-MM-DD.md`.

**Abra o boletim e leia.** Se ele já apontar achados razoáveis, o filtro está
calibrado. Se apontar dezenas de achados absurdos, ajuste o léxico em
`config\termos.yml` antes de prosseguir. Melhor calibrar agora, de graça.

---

# FASE 5 — Criar a chave da API da Anthropic

Atenção: a assinatura do Claude.ai **não serve**. É preciso crédito de API,
que é separado.

1. Acesse `https://platform.claude.com`
2. Crie uma conta ou entre com a que já tem.
3. Vá em **Billing** e adicione crédito. Comece com 20 dólares — dá para meses
   de operação neste volume.
4. **Defina um limite de gasto** na mesma tela. É a sua rede de proteção,
   independente do código.
5. Vá em **API Keys** e clique em **Create Key**.
6. **Copie a chave agora.** Ela só aparece uma vez. Cole em algum lugar seguro
   temporariamente.
7. Ainda no painel, anote o seu limite de tokens por minuto. Aparece em
   **Limits** ou **Rate limits**. Você vai precisar desse número.

---

# FASE 6 — Criar o repositório no GitHub

## 6.1 Criar

1. Entre em `https://github.com`
2. Clique no **+** no canto superior direito, depois em
   **Novo repositório** *(New repository)*.
3. Preencha:

| Campo | Valor |
|---|---|
| **Nome do repositório** *(Repository name)* | `cmasgyn-vigilancia` |
| **Descrição** *(Description)* | Monitoramento do CMASGyn |
| Visibilidade | **Privado** *(Private)* |

4. **Não marque** nenhuma caixa de inicialização — nem README, nem .gitignore,
   nem licença. O projeto já traz os seus.
5. Clique em **Criar repositório** *(Create repository)*.

**Sobre privado ou público.** Em repositório privado o plano gratuito dá 2.000
minutos de execução por mês, cerca de 66 minutos por dia — folgado para esta
rotina. Em repositório público não há limite de minutos, mas todo o acervo fica
exposto. Como só se coleta documento já público, não há sigilo violado; ainda
assim, mantenha privado enquanto calibra.

## 6.2 Enviar os arquivos

Na pasta do projeto, no Prompt de Comando:

```
git init
git add .
git commit -m "sistema de vigilancia do CMASGyn"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/cmasgyn-vigilancia.git
git push -u origin main
```

Substitua `SEU_USUARIO` pelo seu nome de usuário no GitHub.

Na primeira vez, o Git vai abrir uma janela pedindo autorização. Entre com a sua
conta do GitHub e autorize.

Atualize a página do repositório no navegador. Os arquivos devem estar lá.

---

# FASE 7 — Liberar as permissões do robô

Sem isto, o agente coleta mas não consegue gravar nada de volta.

1. No seu repositório, clique em **Configurações** *(Settings)*, na barra
   superior, à direita.
2. No menu da esquerda, clique em **Ações** *(Actions)* e depois em
   **Geral** *(General)*.
3. Role até o fim da página, até o bloco
   **Permissões de fluxo de trabalho** *(Workflow permissions)*.
4. Marque a opção
   **Permissões de leitura e gravação** *(Read and write permissions)*.
5. Marque também a caixa
   **Permitir que o GitHub Actions crie e aprove pull requests**
   *(Allow GitHub Actions to create and approve pull requests)*.
6. Clique em **Salvar** *(Save)*.

---

# FASE 8 — Cadastrar a chave e as variáveis

## 8.1 A chave secreta

1. Ainda em **Configurações** *(Settings)*.
2. No menu da esquerda: **Segredos e variáveis** *(Secrets and variables)*,
   depois **Ações** *(Actions)*.
3. Na aba **Segredos** *(Secrets)*, clique em
   **Novo segredo do repositório** *(New repository secret)*.
4. Preencha:

| Campo | Valor |
|---|---|
| **Nome** *(Name)* | `ANTHROPIC_API_KEY` |
| **Segredo** *(Secret)* | cole a chave da Fase 5 |

5. Clique em **Adicionar segredo** *(Add secret)*.

Depois de salvo, a chave nunca mais aparece na tela. É assim que deve ser.

## 8.2 As duas variáveis

1. Na mesma tela, clique na aba **Variáveis** *(Variables)*.
2. Clique em **Nova variável do repositório** *(New repository variable)*.
3. Cadastre a primeira:

| Campo | Valor |
|---|---|
| **Nome** | `LIMITE_TOKENS_JANELA` |
| **Valor** | o número que você anotou na Fase 5, passo 7. Na dúvida, use `400000` |

4. Cadastre a segunda:

| Campo | Valor |
|---|---|
| **Nome** | `CONTATO_EMAIL` |
| **Valor** | o seu e-mail profissional |

O e-mail vai no cabeçalho das requisições. É cortesia técnica: o administrador
do portal municipal sabe quem está coletando e a quem falar antes de bloquear.

---

# FASE 9 — Ligar e testar

## 9.1 Habilitar os fluxos de trabalho

1. Clique na aba **Ações** *(Actions)* do repositório.
2. Se aparecer um aviso, clique no botão verde
   **Eu entendo meus fluxos de trabalho, prossiga e habilite-os**
   *(I understand my workflows, go ahead and enable them)*.
3. Você verá três fluxos na coluna da esquerda:

| Fluxo | Quando roda |
|---|---|
| **Vigilância diária** | Segunda a sexta, 6h10 de Goiânia |
| **Corpus normativo mensal** | Dia 1º de cada mês |
| **Retomada após renovação do limite** | De hora em hora, só se houver fila |

## 9.2 Primeira execução manual

1. Clique em **Vigilância diária**.
2. À direita, clique em **Executar fluxo de trabalho**
   *(Run workflow)*, e confirme no botão verde.
3. Aguarde. Atualize a página; a execução aparece na lista.
4. Clique nela para acompanhar. Cada etapa abre e mostra o que está fazendo.

## 9.3 Ler o resultado

Terminada a execução, volte à aba **Código** *(Code)* e entre na pasta
`relatorios`. O boletim do dia estará lá.

Se houver achado de severidade alta, o sistema abre automaticamente um item na
aba **Problemas** *(Issues)* com o boletim inteiro.

---

# FASE 10 — Rotina de acompanhamento

## Todo dia, dois minutos

Olhe a aba **Problemas** *(Issues)*. Se não há nada novo, não há achado de
severidade alta. Nada mais a fazer.

## Toda semana, quinze minutos

1. Abra a pasta `relatorios` e leia os boletins da semana.
2. Marque os achados que merecem providência.
3. Para gerar a minuta correspondente, rode localmente:

```
python src\redigir.py --achado RES-02 --data 2026-08-22
```

## Todo mês, meia hora

1. No dia 1º, o sistema abre um **pull request** com o corpus atualizado.
2. Abra, veja o que mudou, e clique em **Merge pull request** para aceitar.
3. **Leia antes de aceitar.** Alterar o corpus muda a base de toda análise
   futura e invalida o cache de prompt — o custo do dia seguinte sobe.

## Uma vez, depois da primeira semana

Assim que o Regimento Interno do CMASGyn entrar no corpus, procure o artigo que
fixa o prazo de publicação das atas. Abra `config\regras.yml`, ache a regra
`ATA-01` e ajuste o campo `prazo_dias` para o prazo regimental real. Deixei 30
dias como valor provisório.

---

# Problemas comuns

**"python não é reconhecido como comando"**
O Python foi instalado sem marcar "Add Python to PATH". Reinstale marcando a
caixa.

**O corpus fica com poucas normas**
Normal na primeira rodada. Leia `relatorios\corpus_pendencias.md` e resolva os
itens críticos, conforme a Fase 3.

**A execução no GitHub falha em "Verificar corpus normativo"**
O arquivo `corpus\corpus.md` não subiu. Verifique se ele existe na sua pasta
local e refaça o `git add .`, `git commit` e `git push`.

**A execução falha com erro de autenticação**
A chave `ANTHROPIC_API_KEY` está errada ou sem crédito. Confira na Fase 8 e no
painel da Anthropic.

**A execução falha ao gravar os arquivos**
As permissões da Fase 7 não foram salvas. Repita e confirme que
**Permissões de leitura e gravação** está marcado.

**O boletim aponta achados demais e sem sentido**
O léxico está largo. Abra `config\termos.yml` e acrescente padrões ao bloco
`exclusoes`, no fim do arquivo.

**Acabaram os minutos do GitHub no mês**
Só ocorre se a rotina estiver demorando muito, quase sempre por causa de
reconhecimento óptico pesado. Ou aguarde o mês virar, ou torne o repositório
público — em repositório público não há limite de minutos.

---

# Lembrete final

Este sistema produz indícios e minutas. Não produz peça processual nem juízo
definitivo. O artigo 32 da Lei 8.906/1994 responsabiliza o advogado por dolo ou
culpa no exercício profissional: **nada é protocolado sem a sua revisão**.
