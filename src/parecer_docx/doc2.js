const fs=require('fs');
const {Document,Packer,Paragraph,TextRun,ExternalHyperlink,HeadingLevel,AlignmentType,Table,TableRow,
 TableCell,WidthType,ShadingType,Footer,PageNumber,TableOfContents,PageBreak,
 FootnoteReferenceRun,convertInchesToTwip}=require('docx');
const B=require('path').resolve(__dirname,'..','..')+'/';
const D=JSON.parse(fs.readFileSync(B+'relatorios/achados_consolidados_2026.json','utf8'));
const FD=JSON.parse(fs.readFileSync(B+'config/fontes_e_destinos.json','utf8'));
const NT=JSON.parse(fs.readFileSync(B+'dados/nivel_transparencia.json','utf8'));
const OR=JSON.parse(fs.readFileSync(B+'dados/orcamento_assistencia_social.json','utf8'));
const F='Bookman Old Style',REC=convertInchesToTwip(0.787);
const brl=v=>v==null?'—':'R$ '+Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
const NOTAS={};let nid=0;
const nota=t=>{nid++;NOTAS[nid]={children:[new Paragraph({spacing:{line:240},
 children:[new TextRun({text:t,font:F,size:14})]})]};return nid;};
const R=(t,o={})=>new TextRun({text:t,font:F,size:o.sz||22,bold:o.b,underline:o.u?{}:undefined,color:o.c,italics:o.i});
const LINK=(t,u)=>new ExternalHyperlink({link:u,children:[new TextRun({text:t,font:F,size:20,
 style:'Hyperlink',underline:{}})]});
const P=(r,o={})=>new Paragraph({alignment:o.al||AlignmentType.JUSTIFIED,
 indent:o.noind?undefined:{firstLine:REC},spacing:{line:276},children:Array.isArray(r)?r:[R(r)]});
const V=()=>new Paragraph({spacing:{line:276},children:[R('')]});
const H=(t,l)=>new Paragraph({heading:l,alignment:AlignmentType.CENTER,spacing:{before:240,after:120},
 children:[R(t,{b:true,sz:l===HeadingLevel.HEADING_1?26:24})]});
const TAB=(cab,linhas,larg)=>new Table({columnWidths:larg,width:{size:larg.reduce((a,b)=>a+b),type:WidthType.DXA},
 rows:[new TableRow({children:cab.map((t,i)=>new TableCell({width:{size:larg[i],type:WidthType.DXA},
  shading:{type:ShadingType.CLEAR,fill:'EAE6DC'},children:[new Paragraph({alignment:AlignmentType.LEFT,
  children:[R(t,{b:true,sz:18})]})]}))}),
 ...linhas.map(ln=>new TableRow({children:ln.map((t,i)=>new TableCell({width:{size:larg[i],type:WidthType.DXA},
  children:[new Paragraph({alignment:i&&/^R\$|^\d/.test(String(t))?AlignmentType.RIGHT:AlignmentType.LEFT,
  children:[R(String(t),{sz:18})]})]}))}))]});

// notas curtas, um artigo cada
const N={};
const put=(k,t)=>{N[k]=nota(t);};
put('cf37','Artigo 37, caput, da Constituição Federal: a administração pública obedecerá ao princípio da publicidade.');
put('lai8','Artigo 8º da Lei 12.527/2011: é dever do órgão divulgar informação de interesse coletivo independentemente de requerimento.');
put('lai8p3','Artigo 8º, § 3º, incisos III e VI, da Lei 12.527/2011: acesso automatizado em formato aberto e informação atualizada.');
put('lai8p1','Artigo 8º, § 1º, inciso III, da Lei 12.527/2011: divulgação obrigatória do registro das despesas.');
put('lc48','Artigo 48 da Lei Complementar 101/2000: orçamentos, prestações de contas, Relatório Resumido da Execução Orçamentária e Relatório de Gestão Fiscal são instrumentos de transparência, com ampla divulgação.');
put('lc48a','Artigo 48-A, inciso I, da Lei Complementar 101/2000: divulgação de todo ato da execução da despesa, com processo, bem ou serviço, beneficiário e procedimento licitatório.');
put('l4320_6','Artigo 6º da Lei 4.320/1964: todas as receitas e despesas constarão da Lei de Orçamento pelos seus totais.');
put('l4320_13','Artigo 13 da Lei 4.320/1964: a despesa será discriminada por categoria econômica, grupo, modalidade e elemento.');
put('l4320_43','Artigo 43, § 1º, inciso I, da Lei 4.320/1964: crédito adicional por superávit financeiro exige superávit apurado em balanço patrimonial.');
put('l4320_58','Artigo 58 da Lei 4.320/1964: empenho é o ato que cria para o Estado obrigação de pagamento.');
put('l4320_63','Artigo 63 da Lei 4.320/1964: a liquidação consiste na verificação do direito adquirido pelo credor, com base em títulos e documentos comprobatórios.');
put('loas30','Artigo 30, parágrafo único, da Lei 8.742/1993: é condição para transferência do Fundo Nacional a comprovação orçamentária de recursos próprios alocados no Fundo.');
put('loas30a','Artigo 30-A da Lei 8.742/1993: o cofinanciamento se efetua mediante alocação de recursos próprios nos fundos nas três esferas.');
put('loas12a','Artigo 12-A, § 4º, da Lei 8.742/1993: percentual do Índice de Gestão Descentralizada deve custear apoio ao Conselho, vedado o pagamento de pessoal efetivo e gratificações.');
put('res202','Artigo 6º da Resolução CNAS/MDS 202/2025: no mínimo 10% do valor repassado mensalmente pelo Índice de Gestão Descentralizada ao controle social.');
put('res202p4','Artigo 6º, § 4º, da Resolução CNAS/MDS 202/2025: dotação orçamentária específica de fortalecimento do controle social no Quadro de Detalhamento de Despesas, a partir de 2026.');
put('res202p5','Artigo 6º, § 5º, da Resolução CNAS/MDS 202/2025: prestação de contas a cada quatro meses ao Conselho.');
put('res202p6','Artigo 6º, § 6º, da Resolução CNAS/MDS 202/2025: em caso de descumprimento, o ente terá seus repasses bloqueados até comprovar o cumprimento.');
put('l14601','Artigo 14, § 7º, da Lei 14.601/2023: no mínimo 3% dos recursos do Índice destinados ao apoio ao Conselho de Assistência Social.');
put('l7531p1','Artigo 2º, § 1º, da Lei municipal 7.531/1995: a dotação do órgão responsável pela assistência social será automaticamente transferida ao Fundo.');
put('l7531p4','Artigo 4º, parágrafo único, da Lei municipal 7.531/1995: até 30% dos recursos do Tesouro Municipal podem custear pessoal e custeio das finalidades essenciais.');
put('l7531_5','Artigo 5º da Lei municipal 7.531/1995: o repasse a entidades far-se-á por intermédio do Fundo.');
put('l9009_10','Artigo 10, § 2º, da Lei municipal 9.009/2010: as Resoluções do Conselho serão publicadas no Diário Oficial do Município.');
put('l9009_10c','Artigo 10, caput, da Lei municipal 9.009/2010: todas as sessões do Conselho serão públicas.');
put('l9009_4b','Artigo 2º, inciso IV, alínea b, da Lei municipal 9.009/2010: compete ao Conselho apreciar mensalmente as contas e os relatórios do Fundo.');
put('l9009_9','Artigo 2º, inciso IX, da Lei municipal 9.009/2010: compete ao Conselho apreciar previamente os contratos e convênios.');
put('l9009_8','Artigo 8º da Lei municipal 9.009/2010: o órgão gestor prestará apoio técnico, administrativo e financeiro ao Conselho.');
put('l13019','Artigos 29, 42 e 63 da Lei 13.019/2014: emenda parlamentar dispensa chamamento, mas não dispensa plano de trabalho nem prestação de contas.');
put('l14133','Artigo 193, inciso II, da Lei 14.133/2021: a Lei 8.666/1993 está revogada desde 30 de dezembro de 2023.');
put('l9784','Artigo 50 da Lei 9.784/1999: os atos administrativos deverão ser motivados, com indicação dos fatos e fundamentos jurídicos.');
put('cf37II','Artigo 37, incisos II e V, da Constituição Federal: investidura depende de concurso; cargo em comissão destina-se a direção, chefia e assessoramento.');
put('l8906','Artigo 32 da Lei 8.906/1994: o advogado é responsável pelos atos que praticar com dolo ou culpa.');
const MN={'PUB-01':['cf37','lai8p3'],'PUB-02':['l9009_10'],'ATA-01':['l9009_10c'],
 'CTA-01':['l9009_4b'],'CTA-02':['res202p5'],'LEG-01':['l14133'],
 'REC-01':['loas30','loas30a'],'REC-02':['l4320_6','lc48a'],'REC-03':['l4320_43','lc48'],
 'DES-01':['l4320_13'],'DES-02':['l4320_58','l4320_63','lc48a'],'FMAS-01':['l7531p1','l7531_5'],
 'IGD-01':['res202','res202p6','l14601'],'IGD-02':['res202p4','l9009_8'],'EMD-01':['l13019','l9009_9'],
 'SYS-02':['l4320_13'],'SYS-03':['lc48a'],'SYS-05':['lc48a'],
 'PES-01':['lai8p1','lc48a'],'PES-02':['l7531p4'],'PES-03':['cf37','l9784'],'PES-04':['l4320_63'],
 'PES-07':['loas12a'],'PES-08':['cf37II'],'PES-09':['cf37II']};
const SEV={critica:'Crítica',alta:'Alta',media:'Média'};
const SELO={CONFIRMADO:'Confirmado',INDICIARIO:'Indiciário',
 INCONCLUSIVO_POR_DOCUMENTO_FALTANTE:'Sem documento para avaliar'};
const BLOCO={ADM:'Atos administrativos e publicidade',FIN:'Receita e despesa',
 PES:'Pessoal e diárias',SYS:'Confiabilidade dos dados'};
module.exports={D,FD,NT,OR,F,REC,NOTAS,nota,N,MN,SEV,SELO,BLOCO,R,LINK,P,V,H,TAB,brl,
 Document,Packer,Paragraph,TextRun,ExternalHyperlink,HeadingLevel,AlignmentType,Footer,
 PageNumber,TableOfContents,PageBreak,FootnoteReferenceRun,convertInchesToTwip,WidthType};
