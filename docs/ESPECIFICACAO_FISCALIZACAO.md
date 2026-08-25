# Especificação validada da fiscalização automatizada

## Resultado da validação

O objetivo é manter um sistema contínuo de controle documental de **SEMASDH,
FMAS e CMASGyn**, com dois ciclos independentes:

1. vigilância administrativa diária das publicações e dos atos;
2. fiscalização financeira a cada 30 dias, com conciliação do fluxo do dinheiro.

O sistema não deve apenas pesquisar palavras. Ele deve preservar a evidência,
identificar o ato, confrontá-lo com o corpus normativo vigente e explicar qual
requisito foi atendido, violado ou não pôde ser verificado.

## Produto diário obrigatório

O boletim diário deve responder, mesmo quando nada for encontrado:

- houve edição do Diário Oficial na data?
- a edição foi consultada com sucesso?
- houve ato relacionado à SEMASDH, ao FMAS ou ao CMASGyn?
- qual é a íntegra, edição, página, URL e hash do documento?
- quem praticou o ato e tinha competência?
- qual norma foi invocada e ela estava vigente na data?
- foram cumpridos forma, motivação, procedimento, prazo, quórum e publicidade?
- existe deliberação do conselho quando ela é condição do ato?
- o resultado é conforme, indício de não conformidade ou inconclusivo?
- qual documento falta para concluir?

“Nenhuma publicação localizada” só pode ser usado após consulta bem-sucedida.
Indisponibilidade do portal ou erro da automação deve produzir estado
**inconclusivo**, nunca ausência presumida.

## Produto financeiro obrigatório a cada 30 dias

O relatório cobre uma janela móvel de 30 dias corridos e deve apresentar:

| Bloco | Conteúdo mínimo |
|---|---|
| Entrada | data, valor, conta/fundo, origem, fonte, programa e comprovante |
| Execução | dotação, empenho, liquidação, pagamento, processo e instrumento |
| Saída | data, valor, conta/fundo, destino, objeto e comprovante |
| Conciliação | saldo inicial + entradas - saídas = saldo final |
| Controle | licitação/parceria, fiscal, ateste, conselho e prestação de contas |

Para destinatário pessoa física, a saída pública conserva somente o primeiro
nome. A versão pública também suprime CPF, sobrenomes, endereço e dados
bancários. A ausência de extrato ou comprovante impede converter dotação,
empenho ou liquidação em movimentação de conta.

## Escala de resultado

- **CONFORME COM PROVA** — todos os requisitos aplicáveis foram comprovados por
  documentos íntegros e normas vigentes.
- **INDÍCIO DE NÃO CONFORMIDADE** — há conflito objetivo entre fato e requisito;
  o achado indica a evidência e o dispositivo.
- **INCONCLUSIVO POR DOCUMENTO FALTANTE** — a documentação pública não permite
  concluir; o relatório lista exatamente o que deve ser solicitado.
- **NÃO APLICÁVEL** — o requisito não incide sobre aquele ato ou movimento.

O uso de pontuação serve para qualidade e prioridade. Uma falha de competência,
vigência, prova bancária ou proveniência não pode ser compensada por pontos em
outros itens. A conclusão jurídica definitiva permanece sujeita a revisão
humana qualificada.

## Critério para “100% de transparência ativa”

Transparência integral é uma medida de cobertura documental, não uma declaração
genérica. O percentual deve usar o inventário aplicável ao órgão e ao período:

`itens obrigatórios disponíveis, atuais, íntegros e acessíveis / itens obrigatórios aplicáveis × 100`.

Um arquivo só conta como atendido se puder ser aberto sem autenticação, tiver
período identificável, formato pesquisável, URL estável e data de atualização.
Ausência no repositório significa **não localizado na base auditada**, não prova
de inexistência no órgão.

## Situação funcional do repositório em 25 de agosto de 2026

| Requisito | Situação | Lacuna principal |
|---|---|---|
| Busca diária no DOM e CMASGyn | Parcialmente atendido | rotina agenda apenas dias úteis e ainda depende da disponibilidade/índice do SILEG |
| Dizer se houve publicação | Parcialmente atendido | semáforo precisa adotar todos os estados desta especificação no boletim principal |
| Confrontar ato com leis | Parcialmente atendido | depende de corpus completo, vigente e com revogações verificadas |
| Arquivar evidência com hash | Parcialmente atendido | há proveniência para parte do acervo, mas não cobertura documental integral |
| Relatório financeiro a cada 30 dias | Não atendido como ciclo independente | conciliação atual roda diariamente sobre o acervo acumulado, sem janela e fechamento próprios |
| Entrada, fonte, saída e destino | Implementação inicial | depende de extratos e comprovantes com marcadores bancários explícitos |
| Privacidade de pessoa física | Implementação inicial | regra do primeiro nome precisa ser testada em todos os produtos públicos |
| Medição de transparência ativa | Não atendido | faltava inventário com denominador, estados e evidências por item |

Os critérios executáveis estão em `config/criterios_fiscalizacao.yml`. O
inventário inicial de documentos está em `docs/CHECKLIST_TRANSPARENCIA_ATIVA.md`.

