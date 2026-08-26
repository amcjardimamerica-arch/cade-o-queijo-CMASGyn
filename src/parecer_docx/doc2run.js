const M=require('./doc2.js');const fs=require('fs');
const {D,FD,NT,OR,F,REC,NOTAS,N,MN,SEV,SELO,BLOCO,R,LINK,P,V,H,TAB,brl,
 Document,Packer,Paragraph,HeadingLevel,AlignmentType,Footer,PageNumber,TableOfContents,
 PageBreak,FootnoteReferenceRun,TextRun}=M;
const c=[];
// CAPA
c.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:1000,after:200},
 children:[R('Parecer de Fiscalização',{b:true,sz:32})]}));
c.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:100},
 children:[R('Assistência Social de Goiânia — Exercício de 2026',{b:true,sz:26})]}));
c.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:500},
 children:[R('Secretaria Municipal de Políticas para as Mulheres, Assistência Social e Direitos Humanos, Fundo Municipal de Assistência Social e Conselho Municipal de Assistência Social',{sz:20})]}));
const s={};D.achados.forEach(a=>s[a.severidade]=(s[a.severidade]||0)+1);
c.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:80},
 children:[R(`${D.achados.length} irregularidades — ${s.critica||0} críticas, ${s.alta||0} altas, ${s.media||0} médias`,{b:true,sz:22})]}));
c.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:80},
 children:[R(`Nível de transparência: ${NT.nivel_geral_percent}% — ${NT.documentos_disponiveis} de ${NT.documentos_disponiveis+NT.documentos_faltantes} documentos disponíveis`,{sz:22})]}));
c.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:1600},
 children:[R(`${D.documentos_requisitados} documentos complementares requisitados`,{sz:20})]}));
c.push(new Paragraph({alignment:AlignmentType.CENTER,children:[R('Goiânia, 26 de agosto de 2026',{sz:22})]}));
c.push(new Paragraph({children:[new PageBreak()]}));
c.push(H('Sumário',HeadingLevel.HEADING_1));
c.push(new TableOfContents('Sumário',{hyperlink:true,headingStyleRange:'1-2'}));
c.push(new Paragraph({children:[new PageBreak()]}));

// I COMO LER
c.push(H('I — Como Ler Este Parecer',HeadingLevel.HEADING_1));
c.push(P('Cada irregularidade é apresentada em cinco campos: o valor envolvido, onde o dado foi encontrado, onde ele deveria estar publicado, quais documentos faltam e uma justificativa em um parágrafo. O fundamento legal vai em nota de rodapé, reduzido.'));
c.push(V());
c.push(P('Três selos indicam o grau de prova. Confirmado significa que duas vias independentes convergem. Indiciário significa uma única via. Sem documento para avaliar significa que a regra existe, foi aplicada, e o dado necessário não está público — o que é, em si, a irregularidade.'));
c.push(V());
c.push(P('Advertências que se repetem a cada uso. Indício de sobrepreço é indício: sobrepreço se demonstra por perícia com preço de mercado. A lista de inscrições no cadastro nacional capta também o cadastro do próprio Município. Dotação e empenho não comprovam saída de dinheiro. Pessoa física aparece apenas pelo primeiro nome.'));
c.push(V());

// II PREVISAO ORCAMENTARIA
c.push(H('II — Previsão Orçamentária de 2026',HeadingLevel.HEADING_1));
c.push(P([R('Valores da Lei Orçamentária Anual 11.590/2026, anexos publicados no Diário Oficial do Município, Edição 8697, de 9 de janeiro de 2026, Edição Extra'),
 R('. Documento consultado em: ',{}),LINK('sileg.goiania.go.gov.br',FD.onde_encontrei.loa2026.url),R('.')]));
c.push(V());
c.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:60},children:[R('Receita prevista do Fundo Municipal',{b:true,sz:20})]}));
const rd=OR.fmas['2026'].receita_detalhada,E=OR.receitas_vinculadas_loa_2026;
c.push(TAB(['Origem','Fonte','Valor previsto'],[
 ['União — Fundo Nacional de Assistência Social','1660',brl(E['1.7.1.6.50.0.1'].valor)],
 ['Estado — Assistência Social','1661',brl(E['1.7.2.9.51.0.1'].valor)],
 ['Estado — Programas de Assistência Social','1665',brl(E['1.7.1.7.52.0.1'].valor)],
 ['Transferências sem fonte identificada','—',brl(rd.transferencias_correntes-E.total_vinculado)],
 ['Rendimento de aplicação financeira','—',brl(rd.receita_patrimonial)],
 ['Transferências de capital','—',brl(rd.transferencias_de_capital)],
 ['Outras receitas correntes','—',brl(rd.outras_receitas_correntes)],
 ['Município — Tesouro','—',brl(rd.tesouro_financiamento_royalties)],
 ['Total previsto','',brl(OR.fmas['2026'].total)]],[4600,1200,2400]));
c.push(V());
c.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:60},children:[R('Despesa prevista por ação',{b:true,sz:20})]}));
const ac=Object.entries(OR.acoes_fmas_2026).sort((a,b)=>b[1].valor-a[1].valor);
const tac=ac.reduce((x,[,v])=>x+v.valor,0);
c.push(TAB(['Ação','Denominação','Valor','%'],ac.map(([k,v])=>
 [k,v.nome,brl(v.valor),(100*v.valor/tac).toFixed(1)+'%']),[2300,3500,1900,500]));
c.push(V());
c.push(P([R('Fora do Fundo, a unidade orçamentária 3601, do Gabinete da Secretaria, prevê '),
 R(brl(OR.unidades_da_secretaria_2026['3601_gabinete_semasdh'].total),{b:true}),
 R(', integralmente custeados pelo Tesouro Municipal. A função 08, assistência social, soma '),
 R(brl(OR.funcao_08_assistencia_social['2026']),{b:true}),
 R(' — 0,262% do orçamento municipal de '+brl(OR.municipio_2026.receita_total)+'.')]));
c.push(V());

// III NIVEL DE TRANSPARENCIA
c.push(H('III — Nível de Transparência dos Dados',HeadingLevel.HEADING_1));
c.push(P([R('De '+(NT.documentos_disponiveis+NT.documentos_faltantes)+' documentos exigidos pela transparência ativa, '),
 R(NT.documentos_disponiveis+' estão públicos',{b:true}),R(' e '),
 R(NT.documentos_faltantes+' faltam',{b:true}),R('. Nível geral: '),
 R(NT.nivel_geral_percent+'%',{b:true}),R('.')]));
c.push(V());
c.push(TAB(['Bloco','Tem','Falta','Nível'],Object.entries(NT.blocos).map(([k,v])=>
 [k,String(v.tem.length),String(v.falta.length),v.nivel+'%']),[4000,1200,1200,1800]));
c.push(V());
for(const [k,v] of Object.entries(NT.blocos)){
 c.push(P([R(k+'. ',{b:true}),
  R(v.tem.length?('Disponível: '+v.tem.join('; ')+'. '):'Nada disponível. '),
  R('Falta: '+v.falta.join('; ')+'. ',{}),
  R('Deveria estar em: ',{}),
  LINK(FD.onde_deveria_estar[v.onde].nome,FD.onde_deveria_estar[v.onde].url),R('.')]));
 c.push(V());
}
c.push(new Paragraph({children:[new PageBreak()]}));

// III-B FLUXO
const FL=JSON.parse(fs.readFileSync(require('path').resolve(__dirname,'..','..','dados','fluxo_2026.json'),'utf8'));
const TF=FL.totais, dTot=TF.despesa_comprovada+TF.despesa_sem_vinculo;
c.push(H('IV — De Onde Veio, Onde Passou, Para Onde Foi',HeadingLevel.HEADING_1));
c.push(P([R('Entraram '),R(brl(TF.fundo),{b:true}),R(' no Fundo. Destes, '),
 R(brl(TF.fonte_comprovada),{b:true}),R(' têm ente de origem identificado e '),
 R(brl(TF.fonte_nao_comprovada),{b:true}),R(' não têm. Do lado da saída, apenas '),
 R(brl(dTot),{b:true}),R(' puderam ser atribuídos a um beneficiário — '),
 R((100*dTot/TF.fundo).toFixed(1)+'%',{b:true}),
 R(' do movimento do Fundo. Desse pouco, '),R(brl(TF.despesa_comprovada),{b:true}),
 R(' têm contrato ou termo publicado e '),R(brl(TF.despesa_sem_vinculo),{b:true}),
 R(' não têm. E fora do Fundo, sem passar pelo controle do Conselho, corre ainda '),
 R(brl(TF.fora_do_fundo),{b:true}),R(' na unidade do Gabinete.')]));
c.push(V());
c.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:60},
 children:[R('Origem do dinheiro',{b:true,sz:20})]}));
c.push(TAB(['Origem','Fonte','Valor','Comprovação'],FL.fontes.map(f=>
 [f.nome,f.fonte,brl(f.valor),f.status==='comprovada'?'origem identificada':'origem não comprovada']),[3900,900,1900,1500]));
c.push(V());
c.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:60},
 children:[R('Por onde passa',{b:true,sz:20})]}));
c.push(TAB(['Conta ou unidade','Valor','Situação'],FL.contas.map(x=>
 [x.nome,brl(x.valor),x.status==='comprovada'?'dentro do Fundo':'fora do Fundo']),[4900,1900,1400]));
c.push(V());
c.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:60},
 children:[R('Despesas com vínculo jurídico publicado',{b:true,sz:20})]}));
const dc=FL.despesas.filter(x=>x.tipo==='comprovada');
c.push(TAB(['Data','Beneficiário','Valor','Contrato ou termo'],dc.map(x=>
 [x.data.split('-').reverse().join('/'),x.cnpj,brl(x.valor),x.vinculo.join(' · ')]),[1200,2000,1700,3300]));
c.push(V());
c.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:60},
 children:[R('Despesas sem vínculo identificado',{b:true,sz:20})]}));
const ds=FL.despesas.filter(x=>x.tipo==='sem_vinculo');
c.push(TAB(['Data','Beneficiário','Valor','O que falta'],ds.map(x=>
 [x.data.split('-').reverse().join('/'),x.cnpj,brl(x.valor),'Contrato, termo ou convênio']),[1200,2000,1700,3300]));
c.push(V());
c.push(P([R('Há ainda '),R(String(FL.fanout.lancamentos),{b:true}),
 R(' lançamentos cujo valor não é atribuível a um beneficiário: a publicação lista várias inscrições e um único valor. Atribuir esse valor a cada inscrição multiplicaria o gasto. Permanecem sem destinatário conhecido até que os empenhos sejam publicados individualmente.')]));
c.push(V());
c.push(P([R('A versão interativa desta trilha, com o detalhe de cada contrato, está em '),
 LINK('docs/fluxo_2026.html no repositório','https://github.com/amcjardimamerica-arch/cmasgyn-vigilancia/blob/main/docs/fluxo_2026.html'),
 R('. Verde indica fonte comprovada; laranja, origem não comprovada; azul, despesa com vínculo; vermelho, despesa sem vínculo.')]));
c.push(new Paragraph({children:[new PageBreak()]}));

// IV IRREGULARIDADES
c.push(H('V — Irregularidades Apuradas',HeadingLevel.HEADING_1));
let at='';
for(const a of D.achados){
 if(a.bloco!==at){at=a.bloco;c.push(H(BLOCO[a.bloco],HeadingLevel.HEADING_2));}
 const fd=FD.por_achado[a.codigo]||{};
 c.push(new Paragraph({heading:HeadingLevel.HEADING_3,alignment:AlignmentType.CENTER,
  spacing:{before:220,after:100},children:[R(`${a.codigo} — ${a.titulo}`,{b:true,sz:22})]}));
 // valor
 c.push(P([R('Valor envolvido. ',{b:true}),
  fd.valor!=null?R(brl(fd.valor),{b:true}):R('Não quantificável sem os documentos faltantes.'),
  fd.valor!=null?R(' — '+(a.codigo==='IGD-01'?'quantia que deveria ter sido aplicada no controle social e prestada contas':
    a.codigo==='REC-01'?'aporte próprio do Município, contra R$ 17.354.000,00 recebidos da União e do Estado':
    a.codigo==='CTA-01'?'movimento do Fundo cujas contas deveriam ter sido apreciadas mensalmente':
    a.codigo==='CTA-02'?'base do Índice de Gestão Descentralizada sujeita a prestação quadrimestral':
    a.codigo==='PES-02'?'teto mensal de pessoal sobre a receita do Tesouro no Fundo':
    a.codigo==='REC-02'?'transferências recebidas sem identificação do ente de origem':
    a.codigo==='REC-03'?'rendimento de aplicação, indício de recurso parado sem execução':
    a.codigo==='DES-01'?'concentrados numa única ação genérica, sem detalhamento de destino':
    a.codigo==='DES-02'?'movimento anual do Fundo sem empenho, liquidação e pagamento públicos':
    a.codigo==='FMAS-01'?'previstos na unidade do Gabinete, fora do Fundo e fora do controle do Conselho':
    a.codigo==='IGD-02'?'dotação do Conselho na Lei Orçamentária, sem execução publicada':
    a.codigo==='EMD-01'?'em emendas parlamentares destinadas à assistência social, sem plano de trabalho público':
    a.codigo==='SYS-02'?'classificados em grupo econômico divergente do rótulo do próprio registro':
    a.codigo==='PES-07'?'do Índice cuja aplicação em pessoal é vedada e não pode ser verificada':
    'quantia sem comprovação regular')):R('')]));
 // onde encontrei
 const enc=(fd.encontrei||[]).map(k=>FD.onde_encontrei[k]).filter(Boolean);
 if(enc.length){
  const rr=[R('Onde o dado foi encontrado. ',{b:true})];
  enc.forEach((e,i)=>{rr.push(R(e.nome+(e.local?', '+e.local:'')+' — '));rr.push(LINK('acessar',e.url));
   rr.push(R(i<enc.length-1?'; ':'.'));});
  c.push(P(rr));
 }
 // onde deveria estar
 const dev=(fd.deveria||[]).map(k=>FD.onde_deveria_estar[k]).filter(Boolean);
 if(dev.length){
  const rr=[R('Onde deveria estar publicado. ',{b:true})];
  dev.forEach((e,i)=>{rr.push(LINK(e.nome,e.url));rr.push(R(i<dev.length-1?'; ':'.'));});
  c.push(P(rr));
 }
 // documentos que faltam
 if(a.documentos_complementares&&a.documentos_complementares.length){
  c.push(P([R('Documentos que faltam. ',{b:true}),
   R(a.documentos_complementares.map((d,i)=>`${i+1}) ${d}`).join('; ')+'.')]));
 }
 // justificativa em um paragrafo, com rodape
 const runs=[R('Justificativa. ',{b:true}),R(a.detalhe.replace(/\s+/g,' ').trim())];
 (MN[a.codigo]||[]).forEach(k=>{if(N[k])runs.push(new FootnoteReferenceRun(N[k]));});
 c.push(P(runs));
 c.push(P([R('Selo: ',{i:true}),R(SELO[a.selo],{i:true}),R('. Severidade: ',{i:true}),
   R(SEV[a.severidade]||a.severidade,{i:true}),R('.',{i:true})]));
 c.push(V());
}

// V PROVIDENCIAS
c.push(new Paragraph({children:[new PageBreak()]}));
c.push(H('VI — Providências',HeadingLevel.HEADING_1));
[['Requerer os documentos faltantes','à Secretaria, com fundamento nos artigos 10 e 11 da Lei 12.527/2011. Prazo de resposta de vinte dias, prorrogável por dez.',FD.onde_deveria_estar.acesso_informacao],
 ['Representar ao Tribunal de Contas dos Municípios','quanto ao aporte próprio de nove mil reais, ao piso do Índice de Gestão Descentralizada e à interrupção da publicação oficial.',FD.onde_deveria_estar.tcmgo],
 ['Comunicar à Secretaria Nacional de Assistência Social','o descumprimento da condição de repasse, que autoriza a suspensão de R$ 8.250.000,00.',null],
 ['Provocar o próprio Conselho','a deliberar sobre a apreciação mensal das contas e sobre a aplicação do Índice, matéria de sua competência privativa.',FD.onde_deveria_estar.sitio_conselho]
].forEach(([t,d,l])=>{const rr=[R(t+'. ',{b:true}),R(d)];
 if(l){rr.push(R(' Canal: '));rr.push(LINK(l.nome,l.url));rr.push(R('.'));}
 c.push(P(rr));c.push(V());});

c.push(H('VII — Ressalva',HeadingLevel.HEADING_1));
c.push(P([R('Este parecer resulta de análise automatizada sobre acervo público, revisada quanto ao método. Não substitui a revisão do advogado constituído'),
 new FootnoteReferenceRun(N.l8906),R(', nem constitui peça processual antes dela.')]));

const doc=new Document({creator:'AMC Jardim América',title:'Parecer de Fiscalização — 2026',
 footnotes:NOTAS,
 styles:{default:{document:{run:{font:F,size:22},paragraph:{spacing:{line:276}}}},
  paragraphStyles:[
   {id:'Heading1',name:'Heading 1',basedOn:'Normal',next:'Normal',quickFormat:true,
    run:{font:F,size:26,bold:true},paragraph:{alignment:AlignmentType.CENTER,spacing:{before:240,after:120},outlineLevel:0}},
   {id:'Heading2',name:'Heading 2',basedOn:'Normal',next:'Normal',quickFormat:true,
    run:{font:F,size:24,bold:true},paragraph:{alignment:AlignmentType.CENTER,spacing:{before:240,after:120},outlineLevel:1}},
   {id:'Heading3',name:'Heading 3',basedOn:'Normal',next:'Normal',quickFormat:true,
    run:{font:F,size:22,bold:true},paragraph:{alignment:AlignmentType.CENTER,spacing:{before:200,after:100},outlineLevel:2}}]},
 sections:[{properties:{page:{size:{width:11906,height:16838},
   margin:{top:1134,right:1134,bottom:1134,left:1701}}},
  footers:{default:new Footer({children:[new Paragraph({alignment:AlignmentType.CENTER,
   children:[new TextRun({children:[PageNumber.CURRENT],font:F,size:18})]})]})},
  children:c}]});
Packer.toBuffer(doc).then(b=>{fs.writeFileSync(require('path').resolve(__dirname,'..','..','relatorios','Parecer_Fiscalizacao_2026.docx'),b);
 console.log('gerado',b.length,'bytes');});
