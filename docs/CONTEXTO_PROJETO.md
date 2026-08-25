# Contexto do projeto de pesquisa e fiscalização

## Finalidade

O repositório automatiza a pesquisa documental e a fiscalização da política de
assistência social de Goiânia, com duas trilhas que não devem ser confundidas:

1. **SEMASDH/FMAS** — origem, ingresso, execução e destino dos recursos;
2. **CMASGyn** — deliberações, controle social, publicidade, atas e resoluções.

O sistema coleta documentos, preserva a fonte e o hash, aplica verificações
determinísticas e produz achados. A inteligência artificial é uma camada de
triagem e análise; não substitui a prova documental nem cria fatos ausentes.

## Regra central de prova financeira

O sistema separa quatro categorias:

| Categoria | O que prova |
|---|---|
| Orçamento/dotação | autorização para gastar |
| Empenho | obrigação assumida |
| Liquidação | direito do credor reconhecido |
| Entrada ou saída bancária | movimentação efetiva de conta |

Dotação não é entrada em conta. Empenho não é pagamento. Relatórios que tratam
da conta da SEMASDH/FMAS só podem somar valores quando o acervo contém marcador
expresso de conta e de crédito, débito, transferência ou pagamento.

## Estrutura obrigatória dos relatórios financeiros

Os relatórios e o painel apresentam, em seção própria:

- Entrada de valores em conta da SEMASDH;
- Indicação da fonte do recurso;
- Saída de valores da conta da SEMASDH;
- Indicação do destino do recurso.

Quando o destinatário de uma saída é pessoa física, publica-se somente o
primeiro nome. CPF, sobrenomes e outros identificadores não integram a saída.
Quando a prova não permite identificar fonte ou destino, o campo registra
expressamente “não identificado”. Quando não há movimentação bancária
demonstrada, o relatório não converte orçamento em fluxo: registra “não
demonstrado no acervo”.

## Base normativa

O corpus reúne legislação constitucional, federal, estadual, municipal,
orçamentária e infralegal. As Resoluções nacionais do CNAS têm rotina própria:

1. usa como linha de base a relação oficial de atos vigentes consolidada pela
   Portaria MC nº 833/2022;
2. acrescenta Resoluções do CNAS posteriores;
3. identifica revogações expressas;
4. arquiva o texto oficial pesquisável, a URL e o hash;
5. distingue vigência formal de efeito temporal possivelmente exaurido.

O inventário fica em `docs/INVENTARIO_CNAS.md`; os textos, em
`corpus/cnas_vigentes/`; e o manifesto estruturado, em
`corpus/cnas_manifesto.json`.

## Rigor dos achados

- Ausência de dado é registrada como lacuna, não como prova automática de desvio.
- Sobrepreço depende de comparação tecnicamente válida com preço de mercado.
- Cadastros de pessoa jurídica passam por triagem para excluir cabeçalhos e
  inscrições do próprio Município.
- Conclusão jurídica deve indicar a norma, o dispositivo e a fonte documental.
- Nenhuma peça deve ser protocolada sem revisão do advogado responsável.

## Situação recebida e integração realizada

O material de continuidade continha análises orçamentárias úteis e um pacote de
arquivos ainda não instalado. O repositório já possuía arquitetura mais recente
de coleta, painel, correição e parecer. A integração preserva essa arquitetura e
incorpora apenas o que faltava: contexto consolidado, rotina completa do CNAS e
separação entre execução orçamentária e movimentação de conta.
