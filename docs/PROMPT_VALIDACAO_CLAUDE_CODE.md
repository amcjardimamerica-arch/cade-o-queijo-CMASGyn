# Prompt de validação — colar no Claude Code na raiz do repositório

Copie tudo abaixo da linha e cole no Claude Code, com o repositório aberto.

---

Você é auditor de sistemas de fiscalização de contas públicas. Este repositório monitora a Secretaria Municipal de Políticas para as Mulheres, Assistência Social e Direitos Humanos de Goiânia, o Fundo Municipal de Assistência Social e o Conselho Municipal de Assistência Social.

Sua tarefa é **auditar o sistema, não os dados**. Encontre onde o sistema mente, silencia ou erra. Corrija o que puder corrigir sem alterar a semântica jurídica. Para o que não puder corrigir, abra uma nota explicando por quê.

Trabalhe em ordem. Não pule etapas. Ao terminar cada bloco, escreva o resultado em `docs/VALIDACAO.md` antes de passar ao próximo.

## Bloco 1 — Integridade estrutural

1. Todo JSON em `config/` e `dados/` faz parse? Liste os que falham.
2. Todo `.py` em `scripts/` compila? Liste os erros.
3. Todo `.yml` em `.github/workflows/` e `config/` é YAML válido?
4. Há import de módulo não declarado em `requirements.txt`?
5. Há caminho absoluto codificado que quebre fora deste container?
6. Há arquivo referenciado em código que não existe no repositório? Liste par a par.
7. Há arquivo no repositório que nenhum código lê? Candidato a remoção.

## Bloco 2 — Silêncio que parece regularidade

Este é o risco central de qualquer vigilância automatizada: o coletor quebra, produz zero achados, e zero achados parece conformidade.

8. Se `coletor.py` não baixar nada, o sistema distingue "não houve publicação" de "não consegui buscar"? Mostre a linha exata onde essa distinção é feita. Se não existir, implemente.
9. Os seis estados de coleta de `config/cadencia.yml` estão todos implementados? `PUBLICACAO_LOCALIZADA_COM_ATO`, `PUBLICACAO_LOCALIZADA_SEM_ATO_RELEVANTE`, `SEM_EDICAO_CONFIRMADA`, `FONTE_INDISPONIVEL`, `BUSCA_INCONCLUSIVA`, `DIA_NAO_UTIL`. Aponte cada um no código.
10. Toda varredura de rede tem **caso de controle** — um recurso sabidamente existente testado no mesmo lote? Sem controle, um servidor que limita concorrência produz falso negativo em massa. Se não houver, implemente.
11. O workflow falha em vermelho quando a fonte está indisponível, ou passa em verde com relatório vazio?
12. Existe alerta quando a janela semanal fecha sem nenhuma edição?

## Bloco 3 — Regras probatórias

13. Todo achado carrega selo `CONFIRMADO` ou `INDICIÁRIO`? Encontre achados sem selo.
14. Há algum ponto onde um achado indiciário é apresentado com linguagem de certeza? Cite arquivo e linha.
15. Dotação, empenho e liquidação estão separados de pagamento e de movimentação bancária? Confirme que nenhum código trata dotação como dinheiro que saiu.
16. Há alguma afirmação de sobrepreço derivada de estatística sobre texto? Deve haver zero. Sobrepreço só por perícia com preço de mercado.
17. Ausência de documento no repositório é tratada como inexistência no órgão em algum lugar? Deve ser sempre `INCONCLUSIVO_POR_DOCUMENTO_FALTANTE`.

## Bloco 4 — Privacidade

18. Toda saída que contenha pessoa física exibe **apenas o primeiro nome**? Verifique `financeiro_mensal.py`, `parecer_ia.py` e todos os geradores de relatório.
19. Há CPF, endereço residencial, data de nascimento ou nome completo de pessoa física em qualquer arquivo de `dados/` ou `docs/`? Liste e remova.
20. A minimização acontece na **extração** ou só na **exibição**? Deve ser na extração — o nome completo não pode chegar a ser gravado.
21. Pessoa jurídica mantém razão social e inscrição completas? Não minimize empresa.

## Bloco 5 — Roteamento de modelos

22. `scripts/roteador_ia.py` cobre todas as tarefas que o código efetivamente executa? Encontre chamada de IA que não passa pelo roteador.
23. Alguma tarefa determinística está indo para modelo? Extração de valor, validação de dígito, soma, comparação de percentual e comparação de datas devem ser código puro.
24. Alguma tarefa de juízo profundo está indo para Haiku? Parecer jurídico e auditoria não podem.
25. `recortar()` está sendo chamado em todo envio? Documento inteiro nunca vai para o modelo. Um Diário Oficial tem 14 MB; o trecho relevante tem 2 KB.
26. Opus é chamado mais de 3 vezes por ciclo mensal? Se sim, aponte onde e proponha rebaixamento.
27. Há retentativa infinita ou laço que possa multiplicar chamadas? Implemente teto rígido por execução.
28. Se `ANTHROPIC_API_KEY` estiver ausente, o sistema falha explicitamente ou produz relatório vazio silenciosamente?

## Bloco 6 — Fidelidade jurídica

Confira contra `config/base_legal.json`. Não busque legislação na internet.

29. Alguma citação a **Lei municipal 7.532/1995**? Está revogada pelo artigo 21 da Lei 9.009/2010. Deve haver zero ocorrências.
30. Alguma citação a **Lei 10.836/2004** como base do IGD-PBF? Migrou para a Lei 14.601/2023, artigo 14, parágrafo 7º.
31. Alguma afirmação de percentual constitucional mínimo de impostos para assistência social? **Não existe.** Saúde tem 15% pelo artigo 198, parágrafo 2º, inciso III; educação tem 25% pelo artigo 212; o artigo 204, parágrafo único, alcança só Estados e o Distrito Federal.
32. O piso do IGD ao controle social está em **10%**, incidindo sobre o repasse **mensal**, conforme o artigo 6º da Resolução CNAS/MDS 202/2025? Verifique se algum código ainda usa 3% ou aplica sobre total anual.
33. O sistema afere o **parágrafo 4º do artigo 6º** — dotação específica no Quadro de Detalhamento de Despesas a partir de 2026? É obrigação autônoma e diretamente auditável.
34. O sistema afere o **parágrafo 5º** — prestação de contas quadrimestral ao Conselho?
35. O teto de 30% para pessoal está aplicado **só sobre recursos do Tesouro Municipal**, como manda o artigo 4º, parágrafo único, da Lei municipal 7.531/1995? Recurso federal não entra no numerador nem no denominador.
36. Toda citação escreve "Artigo" por extenso e o número da lei em algarismos? Nada de "art." nem de sigla.

## Bloco 7 — Defeitos conhecidos

Estes foram medidos em 24/08/2026. Confirme que estão corrigidos.

37. **SYS-02** — natureza da despesa lida de posição diferente do valor. Foram 105 registros, 29 trocando grupo econômico, R$ 10.858.000,00, 20,18% do total. Escreva um teste que falhe se um registro tiver campo `natureza` iniciando em 33 e rótulo iniciando em 44.
38. **SYS-03** — soma de repasses a entidades excedia o total da função em 3,41 vezes. Implemente trava: a soma não pode exceder o total.
39. **SYS-04** — um valor replicado em N inscrições inflava R$ 72.337.125,48. Publicação com N inscrições e 1 valor gera **um** registro marcado `valor_de_publicacao_nao_atribuido`.
40. **SYS-05** — inscrições sem validação de dígito verificador. Implemente e aplique `config/triagem_cnpj.json`.
41. **SYS-06** — a métrica de integridade lia 100% e nunca alertava. Deve medir percentual de eventos que completam da primeira à última estação, não a existência de ao menos um evento por estação.
42. A lista negra de `config/triagem_cnpj.json` é aplicada antes de qualquer agregação? O cadastro do próprio Município aparecia como entidade beneficiária.

## Bloco 8 — Cobertura

43. Cada parâmetro de `config/parametros_fiscalizacao.json` tem código que o afere, ou está declarado como impedido por dado faltante? Não deve haver parâmetro órfão — declarado e nunca avaliado.
44. Cada lacuna de `dados/completude.json` aponta o requerimento que a resolve?
45. `config/catalogo_cnas.json` registra, para cada resolução sem texto, o motivo da falha?
46. O destilado `docs/CONSULTA.md` respeita o teto de caracteres? Se estourar, corta pelo fim, nunca pelo topo — achado crítico fica sempre visível.

## Bloco 9 — Testes

47. Escreva testes para: os seis estados de coleta; a minimização de primeiro nome; a trava de soma; a validação de dígito; o cálculo de 10% sobre repasse mensal; o teto de 30% sobre base do Tesouro; e o roteamento de cada tarefa à camada correta.
48. Escreva um teste que simule fonte indisponível e verifique que o resultado é `FONTE_INDISPONIVEL`, e **não** `SEM_EDICAO_CONFIRMADA`.
49. Rode a suíte. Reporte o que falha.

## Entrega

Escreva `docs/VALIDACAO.md` com, para cada item de 1 a 49: situação (conforme, corrigido, não corrigido), o que foi alterado, e o arquivo tocado. Ao final, liste separadamente o que exige decisão humana e não pode ser resolvido por código.

Não altere valores apurados nem conclusões jurídicas. Corrija mecanismo, não achado.
