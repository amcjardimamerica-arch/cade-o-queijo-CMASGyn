# Vigilância do CMASGyn

Agente de monitoramento do Conselho Municipal de Assistência Social de Goiânia
e dos órgãos municipais correlatos. Coleta diária, verificação de conformidade
contra corpus normativo congelado e produção de boletim de achados.

> **Leia primeiro o arquivo [PERMISSOES.md](PERMISSOES.md).** O sistema não roda
> sem as credenciais e as duas confirmações que só você pode dar.

---

## O que ele faz

**Diariamente**, de segunda a sexta:

1. Baixa a edição do Diário Oficial do Município, preservando o PDF assinado.
2. Varre o acervo do CMASGyn — resoluções, plenárias, atas — versionando cada
   arquivo por SHA-256.
3. Suprime dados de pessoa natural na ingestão e recorta apenas os trechos que
   casam no léxico de gatilho.
4. Roda quinze verificações determinísticas sem custo de token.
5. Escalona ao modelo apenas o que sobrou, em três níveis de custo crescente.
6. Expurga o que não referencia o conselho após trinta dias.
7. Emite boletim e abre issue quando há achado de severidade alta.

**Mensalmente**, no dia 1º: reconsolida o corpus normativo e abre um pull
request para a sua revisão.

**De hora em hora**: verifica se há fila pendente e se a janela de tokens já
renovou. Havendo ambos, retoma de onde parou.

---

## O que ele verifica

| Eixo | Regras |
|---|---|
| Publicidade das atas | Prazo regimental, acesso sem autenticação, formato legível por máquina, conteúdo mínimo com quórum e votação |
| Resoluções | Continuidade da numeração, publicação no Diário Oficial, **alteração silenciosa de ato já publicado**, pertinência temática, respaldo jurídico, padronização com norma federal |
| Entidades inscritas | Motivação do deferimento ou indeferimento, coerência entre inscrição e repasse do Fundo |
| IGD | Piso destinado ao controle social, dotação orçamentária específica, prestação de contas quadrimestral, transparência ativa, saldo sem reprogramação |
| Fundo e parcerias | Execução sem deliberação prévia, convocação da conferência no biênio |

A detecção de **alteração silenciosa** é o achado que nenhum acompanhamento
humano produz: comparação de hash entre versões do mesmo arquivo, com
arquivamento da versão anterior. A partir do dia em que o sistema entra em
operação, toda reedição retroativa de resolução ou ata fica documentada.

### Sobre o percentual do IGD

Regra aplicada, com a antinomia registrada:

- **Até 2025** — piso de 3%, conforme a Portaria MDS 1.041/2024, artigo 11,
  § 1º, e a Resolução CNAS 33/2012, artigo 121, inciso VII.
- **Desde janeiro de 2026** — piso de **10%** do valor repassado mensalmente
  pelo IGD/SUAS e pelo IGD/PBF, conforme o artigo 6º da Resolução CNAS/MDS
  202/2025, que revogou a Resolução CNAS 15/2014. O descumprimento sujeita o
  ente ao bloqueio dos repasses.

A Portaria MDS 1.041/2024 ainda enuncia 3%. A resolução do CNAS é posterior e
específica. A antinomia está anotada em `config/regras.yml` e pode ser arguida
conforme o interesse do caso.

---

## As doze regras de economia de token

| | Regra | Efeito |
|---|---|---|
| R1 | Portão por expressão regular | Nada sobe ao modelo sem casar no léxico |
| R2 | Recorte de janela | Envia-se o entorno do acerto, nunca o documento |
| R3 | Deduplicação por hash | Documento já analisado não retorna |
| R4 | Cache do corpus, TTL de uma hora | Leitura a 10% do custo de entrada, e fora do limite por minuto |
| R5 | Escalonamento em três níveis | Só sobe de nível o que o anterior aprovou |
| R6 | Batch API na triagem e extração | Metade do preço |
| R7 | GET condicional | HTTP 304 encerra a fonte sem custo algum |
| R8 | Saída JSON curta | `max_tokens` apertado por nível |
| R9 | Teto de 50% da janela | Parada planejada com fila e retomada |
| R10 | Retenção de trinta dias | Só permanece o que referencia o conselho |
| R11 | OCR condicional | Só quando a camada de texto é pobre |
| R12 | Corpus congelado | A rotina diária não pesquisa norma nova |

A regra R4 é a de maior alcance. O corpus normativo — algo entre cem e duzentos
mil tokens — é prefixo estável marcado com `cache_control`. Ele vai sempre no
início do prompt, o conteúdo variável sempre depois. Sem cache, cada validação
pagaria o corpus inteiro a preço cheio; com cache, paga um décimo. Por isso a
atualização normativa é mensal e deliberada: **um byte alterado no corpus
invalida o cache e decuplica o custo do dia**.

---

## Roteamento de modelos

| Nível | Modelo | Tarefa | Volume esperado |
|---|---|---|---|
| Triagem | `claude-haiku-4-5` | Decisão binária de relevância | 100% dos trechos filtrados |
| Extração | `claude-sonnet-5` | Estruturação em JSON | ~15% |
| Validação | `claude-opus-5` | Confronto jurídico com o corpus | ~3% |
| Redação | `claude-opus-5` | Minuta de ofício, pedido ou representação | acionamento manual |

Triagem e extração são assíncronas e vão pela Batch API. Validação é síncrona:
queremos o achado no mesmo dia.

---

## Custo estimado

Regime estacionário, após a primeira semana de calibragem:

| Item | Volume diário | Observação |
|---|---|---|
| Edição do Diário Oficial | 1 | 40 a 80 páginas |
| Trechos após o filtro | 5 a 30 | O portão descarta acima de 95% |
| Chamadas de triagem | 5 a 30 | Batch, modelo mais barato |
| Chamadas de extração | 1 a 5 | Batch |
| Chamadas de validação | 0 a 3 | Síncronas, com corpus cacheado |
| Minutos de execução | 8 a 15 | Dentro dos 66 minutos diários do plano gratuito |

O item caro não é o token: é o reconhecimento óptico de edições escaneadas, que
consome processamento. Daí a regra R11.

---

## Estrutura

```
config/     fontes, léxico, corpus, regras, roteamento de modelos
src/        coleta, filtro, conformidade, orçamento, orquestração
prompts/    um por nível de modelo
corpus/     normas consolidadas + manifesto com hashes  (gerado)
acervo/     documentos coletados, com versões anteriores (gerado)
estado/     registros, fila e controle de orçamento      (gerado)
relatorios/ boletins diários e achados                   (gerado)
```

---

## Fixação probatória

Cada documento é guardado como veio, íntegro. O PDF assinado do Diário Oficial
carrega a assinatura ICP-Brasil e a presunção do artigo 10, § 1º, da Medida
Provisória 2.200-2/2001 — presunção que só sobrevive no arquivo original. O
texto extraído por reconhecimento óptico é conveniência de busca, jamais o
documento que instrui a inicial.

O registro de estado guarda, para cada arquivo: URL de origem, instante da
coleta, SHA-256 e o histórico de versões. Mesmo o que é expurgado pela regra de
retenção deixa lápide — data, endereço e hash —, de modo que se possa provar
que naquela edição nada havia de relevante.

---

## Limites

Este sistema produz indícios e minutas. Não produz peças processuais nem
juízos definitivos. O artigo 32 da Lei 8.906/1994 responsabiliza o advogado por
dolo ou culpa no exercício profissional: **nenhum documento deve ser protocolado
sem revisão humana**.
