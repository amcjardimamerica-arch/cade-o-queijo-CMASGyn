# Histórico da conversa e requisitos consolidados

## Metadados

- Projeto: Vigilância automatizada SEMASDH/FMAS e CMASGyn
- Repositório: `amcjardimamerica-arch/cmasgyn-vigilancia`
- Data de consolidação: 25 de agosto de 2026
- Anexos recebidos: `files.zip` e `files (1).zip`
- Segurança: o token GitHub enviado na conversa foi deliberadamente omitido e
  deve ser revogado. Nenhuma credencial integra este histórico.

## Pedido inicial do usuário

O usuário informou que vinha construindo, em outro assistente, um repositório
automatizado de pesquisa e fiscalização. Pediu a leitura do trabalho anexado,
a compreensão do objetivo e a continuidade no GitHub.

Requisitos declarados:

- diagnosticar e arquivar a legislação usada pelo sistema;
- levantar e arquivar todas as resoluções nacionais vigentes do CNAS;
- estruturar os relatórios financeiros com:
  - entrada de valores em conta da SEMASDH;
  - indicação da fonte do recurso;
  - saída do valor da conta da SEMASDH;
  - indicação do destino do recurso;
- em saída para pessoa física, exibir somente o primeiro nome.

## Esclarecimento posterior do usuário

O sistema pretendido deve fiscalizar contas públicas e atos administrativos da
Secretaria de Assistência Social, do Fundo e do Conselho de Assistência Social.

O usuário determinou:

1. buscas diárias no Diário Oficial e nas fontes institucionais;
2. relatório diário dizendo se encontrou ou não publicação;
3. validação dos atos contra o repositório de leis vigente;
4. relatório financeiro a cada 30 dias para aferir a regularidade dos gastos;
5. critérios de qualidade para a fiscalização administrativa e financeira;
6. lista dos documentos faltantes para alcançar transparência ativa integral.

## Validação realizada

O pedido foi traduzido em dois ciclos independentes:

- fiscalização administrativa diária, com estados distintos para publicação
  encontrada, edição sem ato relevante, ausência confirmada, fonte
  indisponível, busca inconclusiva e dia não útil;
- fiscalização financeira em janela móvel de 30 dias, separando orçamento,
  empenho, liquidação, pagamento e movimentação bancária.

Foram fixadas quatro conclusões possíveis: conforme com prova, indício de não
conformidade, inconclusivo por documento faltante e não aplicável. Falha de
consulta, ausência de íntegra ou falta de prova bancária são bloqueios e não
podem ser compensados por pontuação.

“100% de transparência ativa” passou a significar cobertura mensurável do
inventário aplicável, considerando disponibilidade, atualidade, integridade,
formato, URL e acesso sem autenticação. Documento não localizado no repositório
não é tratado automaticamente como documento inexistente no órgão.

## Implementação no repositório

- rotina de corpus nacional vigente do CNAS e inventário normativo;
- separação entre execução orçamentária e movimentação bancária;
- minimização de beneficiário pessoa física para o primeiro nome;
- critérios estruturados em `config/criterios_fiscalizacao.yml`;
- especificação em `docs/ESPECIFICACAO_FISCALIZACAO.md`;
- checklist em `docs/CHECKLIST_TRANSPARENCIA_ATIVA.md`;
- relatório administrativo executável em `src/relatorio_administrativo.py`;
- fechamento independente de 30 dias em `src/relatorio_financeiro_30d.py`;
- workflow `.github/workflows/financeiro-30-dias.yml`;
- geração do relatório administrativo pelo workflow diário;
- testes para estados probatórios, privacidade e janela de 30 dias.

## Regra metodológica permanente

O sistema automatizado produz evidências e indícios para controle social. Ele
não transforma ausência de dados em prova de ilegalidade e não substitui a
revisão humana necessária a uma conclusão jurídica definitiva.
