# Permissões e credenciais necessárias

Este documento lista tudo o que **só você pode fazer**. O sistema está pronto;
sem estes itens ele não roda.

---

## 1. Repositório no GitHub

Crie um repositório e envie o conteúdo desta pasta.

| Item | Valor sugerido |
|---|---|
| Nome | `cmasgyn-vigilancia` |
| Visibilidade | **Privado** |
| Conta | pessoal ou da AMC Jardim América |

**Decisão relevante sobre custo.** Em repositório privado o plano gratuito
concede 2.000 minutos de execução por mês — cerca de 66 minutos por dia, o que
comporta a rotina com folga. Em repositório público não há limite de minutos,
mas todo o acervo coletado fica exposto. Como só se coleta documento já
público, a exposição não viola sigilo algum; ainda assim, recomendo privado
enquanto o sistema estiver em calibragem.

### Permissões dentro do repositório

Em **Settings → Actions → General → Workflow permissions**, marque:

- [x] **Read and write permissions** — sem isso o agente não consegue gravar o
      acervo, o estado nem os boletins de volta no repositório.
- [x] **Allow GitHub Actions to create and approve pull requests** — necessário
      para o workflow mensal do corpus abrir a proposta de atualização.

---

## 2. Chave da API da Anthropic

1. Acesse `https://platform.claude.com`, crie uma organização e gere uma chave.
2. No repositório: **Settings → Secrets and variables → Actions → New repository secret**

| Tipo | Nome | Conteúdo |
|---|---|---|
| Secret | `ANTHROPIC_API_KEY` | a chave gerada |

**Não** use a assinatura do Claude.ai: ela não expõe API. É crédito de API
avulso, separado, e é o que o orçamento de 50% controla.

Defina também um **limite de gasto** no painel da Anthropic. É a sua rede de
proteção independente do código.

---

## 3. Variáveis de configuração

Mesma tela, aba **Variables**:

| Nome | Valor | Para quê |
|---|---|---|
| `LIMITE_TOKENS_JANELA` | ex.: `400000` | Limite de tokens da sua janela na API. Consulte o painel; o agente usará no máximo metade. |
| `CONTATO_EMAIL` | seu e-mail | Vai no cabeçalho `User-Agent` das requisições. Cortesia técnica: o administrador do portal sabe quem está coletando e a quem reclamar antes de bloquear. |

---

## 4. Passo que exige a sua mão: o endereço do Diário Oficial

O padrão de URL das edições do Diário Oficial de Goiânia não é documentado. O
agente **não inventa endereço**. Execute uma vez, na sua máquina:

```bash
pip install -r requirements.txt
python src/descobrir.py
```

O roteiro inspeciona o portal e grava candidatos em
`estado/dom_endpoint.json`. Abra um deles, confirme que é a edição, e escreva o
gabarito no campo `padrao_confirmado`, por exemplo:

```json
{"padrao_confirmado": "https://host/caminho/{ano}/{mes}/{dia}.pdf"}
```

Se nada for encontrado, o roteiro grava em `estado/minuta_lai_dom.txt` uma
minuta de pedido fundada no artigo 8º, § 3º, incisos II e III, da Lei
12.527/2011, requerendo o endereço de acesso automatizado. Protocole no Serviço
de Informação ao Cidadão. O prazo de resposta é de vinte dias, prorrogável por
dez, na forma do artigo 11, §§ 1º e 2º, da mesma lei.

---

## 5. Normas que preciso que você forneça

Em `config/corpus.yml` há itens marcados `CONFIRMAR`. São normas cuja URL
oficial estável eu não pude verificar. **Nenhuma delas será adivinhada.** Duas
são críticas e sem elas metade das regras de pertinência temática não funciona:

- **Lei 7.532/1995** — cria o CMASGyn. É o rol de competências contra o qual
  toda resolução será confrontada.
- **Regimento Interno do CMASGyn** — a URL está no arquivo e provavelmente
  funciona; confirme na primeira execução do corpus.
- **PPA, LDO e LOA vigentes** de Goiânia — indispensáveis para a regra IGD-02,
  que verifica a dotação orçamentária específica do controle social.
- Resoluções do CNAS: 145/2004, 109/2009, 33/2012, 14/2014, 182/2025.

Basta colocar o PDF em `corpus/brutos/` com o nome do `id` do item (por
exemplo, `l7532_1995.pdf`) ou preencher a URL no arquivo de configuração.

---

## 6. Ordem de partida

```bash
# 1. Descobrir o endpoint do Diário Oficial (uma vez)
python src/descobrir.py

# 2. Consolidar o corpus normativo (uma vez, depois mensal)
python src/corpus_build.py
#    Leia relatorios/corpus_pendencias.md e resolva o que faltar.

# 3. Testar a rotina sem gastar token
LIMITE_TOKENS_JANELA=0 python src/run_diario.py
#    Roda coleta, filtro e regras determinísticas; para antes do modelo.

# 4. Enviar ao GitHub e habilitar os workflows na aba Actions.
```

---

## 7. O que eu não faço e não farei

- **Não protocolo nada.** O sistema minuta; quem subscreve é você. O artigo 32
  da Lei 8.906/1994 responsabiliza o advogado por dolo ou culpa no exercício
  profissional, e delegar a subscrição a uma rotina automatizada seria culpa.
- **Não decido severidade final.** O rótulo é triagem, não parecer.
- **Não guardo dado de pessoa natural.** CPF, NIS, RG, telefone, e-mail e nome
  de beneficiário são suprimidos na ingestão, antes de qualquer gravação. CNPJ
  é preservado: é dado de pessoa jurídica e chave do controle social.
