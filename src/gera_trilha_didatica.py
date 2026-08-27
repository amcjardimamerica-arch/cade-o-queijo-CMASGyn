#!/usr/bin/env python3
"""Gera docs/trilha_didatica_2026.html — a trilha do dinheiro para quem não é da área.

Quatro estações: quem paga, onde o dinheiro fica, em que foi gasto, quem recebeu.
Cores por categoria de despesa e alerta de teto legal.
"""
import json
from pathlib import Path
RAIZ = Path(__file__).resolve().parent.parent

def main():
    L = lambda p: json.loads((RAIZ / p).read_text(encoding="utf-8"))
    dados = {"fluxo": L("dados/fluxo_2026.json"),
             "cat": L("dados/categorias_2026.json"),
             "orc": L("dados/orcamento_assistencia_social.json"),
             "igd": L("dados/igd_controle_social.json")}
    html = TPL.replace("__D__", json.dumps(dados, ensure_ascii=False))
    (RAIZ / "docs" / "trilha_didatica_2026.html").write_text(html, encoding="utf-8")
    print(f"trilha_didatica_2026.html: {len(html)//1024}K")

TPL = r'''<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Para onde foi o dinheiro da assistência social de Goiânia em 2026</title>
<style>
:root{--tinta:#17150f;--papel:#fbf9f4;--cartao:#fff;--linha:#e0dacd;--sutil:#726c60;
--pessoal:#8c2f2f;--contrato:#1c5a94;--repasse:#1f7a4d;--programa:#4c3b8f;--invest:#b8690f;
--nc:#6b665c;--ok:#1f7a4d;--risco:#b8690f;--ilegal:#a32a2a}
*{box-sizing:border-box;margin:0;padding:0}
body{font:16px/1.6 Georgia,'Times New Roman',serif;background:var(--papel);color:var(--tinta);padding:20px}
.w{max-width:1080px;margin:0 auto}
h1{font-size:30px;font-weight:normal;line-height:1.2;letter-spacing:-.5px}
.lead{font-size:17px;color:var(--sutil);margin:10px 0 26px;padding-bottom:18px;border-bottom:2px solid var(--tinta)}
h2{font-size:14px;text-transform:uppercase;letter-spacing:1.5px;font-weight:normal;color:var(--sutil);
margin:34px 0 14px;padding-bottom:6px;border-bottom:1px solid var(--linha)}
.est{background:var(--cartao);border:1px solid var(--linha);border-radius:5px;padding:20px;margin-bottom:16px}
.est .num{display:inline-block;width:26px;height:26px;line-height:26px;text-align:center;
background:var(--tinta);color:var(--papel);border-radius:50%;font-size:14px;margin-right:9px}
.est h3{display:inline;font-size:20px;font-weight:normal}
.est .exp{color:var(--sutil);font-size:15px;margin:9px 0 14px}
.big{font-size:36px;font-variant-numeric:tabular-nums;line-height:1.1;margin:6px 0}
.mini{font-size:13px;color:var(--sutil)}
.paga{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
.q{border:1px solid var(--linha);border-radius:4px;padding:12px;cursor:pointer;transition:.13s;background:#fff}
.q:hover{box-shadow:0 3px 12px rgba(0,0,0,.1);transform:translateY(-2px)}
.q .n{font-size:13px;line-height:1.3;min-height:34px}
.q .v{font-size:19px;font-variant-numeric:tabular-nums;margin-top:5px}
.q .s{font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin-top:4px}
.gv{border-left:4px solid var(--ok)}.gv .v{color:var(--ok)}.gv .s{color:var(--ok)}
.gl{border-left:4px solid var(--risco)}.gl .v{color:var(--risco)}.gl .s{color:var(--risco)}
.tubo{display:flex;height:44px;border-radius:4px;overflow:hidden;margin:14px 0;border:1px solid var(--linha)}
.tubo div{display:flex;align-items:center;justify-content:center;color:#fff;font-size:12px;
cursor:pointer;transition:.13s;text-align:center;padding:0 4px}
.tubo div:hover{filter:brightness(1.15)}
.cats{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:11px;margin-top:14px}
.c{border:1px solid var(--linha);border-top:5px solid;border-radius:4px;padding:13px;cursor:pointer;background:#fff}
.c:hover{box-shadow:0 3px 12px rgba(0,0,0,.1)}
.c .r{font-size:15px}.c .v{font-size:21px;font-variant-numeric:tabular-nums;margin:4px 0}
.c .d{font-size:12.5px;color:var(--sutil);line-height:1.4}
.tetos{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:11px}
.t{border:1px solid var(--linha);border-left:5px solid;border-radius:4px;padding:13px;background:#fff}
.t.d{border-left-color:var(--ilegal);background:#fbeaea}
.t.i{border-left-color:var(--sutil);background:#f4f2ec}
.t .n{font-size:14px}.t .st{font-size:12px;text-transform:uppercase;letter-spacing:.6px;margin:5px 0}
.t .no{font-size:12.5px;color:var(--sutil);line-height:1.45}
table{width:100%;border-collapse:collapse;font-size:14px;background:#fff}
th{text-align:left;font-weight:normal;font-size:11px;text-transform:uppercase;letter-spacing:.6px;
color:var(--sutil);padding:8px;border-bottom:1px solid var(--linha)}
td{padding:9px 8px;border-bottom:1px dotted var(--linha);vertical-align:top}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.cn{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
.tg{display:inline-block;font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;
padding:2px 7px;border-radius:3px;color:#fff}
#bal{position:fixed;z-index:60;max-width:420px;background:#fff;border:2px solid var(--tinta);
border-radius:6px;padding:16px 18px;box-shadow:0 10px 34px rgba(0,0,0,.24);display:none;font-size:14px}
#bal h4{font-size:16px;font-weight:normal;margin-bottom:9px;padding-bottom:7px;border-bottom:1px solid var(--linha)}
#bal dt{font-size:10.5px;text-transform:uppercase;letter-spacing:.6px;color:var(--sutil);margin-top:9px}
#bal .x{position:absolute;top:8px;right:12px;cursor:pointer;font-size:19px;color:var(--sutil)}
.alerta{background:#fbeaea;border-left:5px solid var(--ilegal);padding:14px 17px;margin:16px 0;font-size:15px}
.frase{font-size:19px;line-height:1.5;background:var(--tinta);color:var(--papel);padding:20px 24px;
border-radius:5px;margin:20px 0}
.frase b{color:#ffd98a}
@media(max-width:760px){.big{font-size:28px}h1{font-size:23px}}
</style></head><body><div class="w">
<h1>Para onde foi o dinheiro da<br>assistência social de Goiânia</h1>
<div class="lead">Exercício de 2026. Siga as quatro estações e clique em qualquer caixa para ver
o contrato, o beneficiário e a finalidade. Onde faltar documento, a caixa diz o que falta.</div>

<div class="est"><span class="num">1</span><h3>Quem paga</h3>
 <div class="exp">O dinheiro da assistência social vem de três lugares: do governo federal,
 do governo estadual e do próprio Município. Verde quer dizer que dá para provar de onde veio.
 Laranja quer dizer que a origem não está declarada.</div>
 <div class="big" id="e1v"></div><div class="mini">entraram no Fundo em 2026</div>
 <div class="paga" id="e1" style="margin-top:14px"></div></div>

<div class="est"><span class="num">2</span><h3>Onde o dinheiro fica</h3>
 <div class="exp">Por lei, todo recurso da assistência social precisa passar por uma conta
 específica — o Fundo Municipal. É nessa conta que o Conselho consegue fiscalizar. O que fica
 fora dela escapa do controle.</div>
 <div id="e2"></div></div>

<div class="est"><span class="num">3</span><h3>Em que foi gasto</h3>
 <div class="exp">Cada cor é um tipo de gasto. Clique para ver o que entra em cada um.</div>
 <div class="tubo" id="e3t"></div><div class="cats" id="e3"></div></div>

<div class="est"><span class="num">4</span><h3>Quem recebeu</h3>
 <div class="exp">Nome de empresa e instituição aparece por inteiro. Nome de pessoa aparece
 só o primeiro, por proteção de dado pessoal.</div>
 <div id="e4"></div></div>

<h2>O dinheiro que a lei manda ir para o Conselho</h2>
<div class="est" id="igd"></div>

<h2>Passou de algum limite?</h2>
<div class="tetos" id="tt"></div>

<h2>Resumo em uma frase</h2>
<div class="frase" id="fr"></div>
</div>
<div id="bal"><span class="x" onclick="fx()">×</span><div id="bc"></div></div>
<script>
const D=__D__;
const F=D.fluxo,C=D.cat,O=D.orc;
const brl=v=>v==null?'não informado':'R$ '+Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
const el=i=>document.getElementById(i);
const CAT={PESSOAL:{r:'Gasto com pessoal',c:'var(--pessoal)',d:'Salários, diárias, reembolsos e outras verbas de servidor.'},
 CONTRATUAL_FIXA:{r:'Contratos e serviços',c:'var(--contrato)',d:'Aluguel, limpeza, vigilância, materiais e serviços contratados de empresas.'},
 REPASSE_ENTIDADE:{r:'Repasse a instituições',c:'var(--repasse)',d:'Dinheiro entregue a entidades sociais para prestarem serviço à população.'},
 PROGRAMA:{r:'Programas e serviços',c:'var(--programa)',d:'CRAS, CREAS, acolhimento, Bolsa Família e Cadastro Único.'},
 INVESTIMENTO:{r:'Investimento',c:'var(--invest)',d:'Obras, equipamentos e material permanente.'},
 NAO_CLASSIFICADA:{r:'Sem classificação',c:'var(--nc)',d:'A publicação não diz o suficiente para saber em que foi gasto.'}};
// 1
el('e1v').textContent=brl(F.totais.fundo);
el('e1').innerHTML=F.fontes.map((f,i)=>`<div class="q ${f.status==='comprovada'?'gv':'gl'}" data-t="f" data-i="${i}">
 <div class="n">${f.nome}</div><div class="v">${brl(f.valor)}</div>
 <div class="s">${f.status==='comprovada'?'origem provada':'origem não declarada'}</div></div>`).join('');
// 2
el('e2').innerHTML=F.contas.map((c,i)=>`<div class="q ${c.status==='comprovada'?'gv':'gl'}" data-t="c" data-i="${i}" style="margin-bottom:9px">
 <div class="n">${c.nome}</div><div class="v">${brl(c.valor)}</div>
 <div class="s">${c.status==='comprovada'?'dentro do Fundo — o Conselho fiscaliza':'fora do Fundo — o Conselho não alcança'}</div></div>`).join('')
 +`<div class="alerta"><b>O que isso quer dizer.</b> A conta do Fundo tem ${brl(F.contas[0].valor)}.
 Mas a Secretaria movimenta ${brl(F.contas[1].valor)} numa unidade que fica fora do Fundo —
 ${(F.contas[1].valor/F.contas[0].valor).toFixed(1)} vezes mais, e tudo pago pelo cofre do Município.
 A lei manda que a verba da assistência social vá automaticamente para o Fundo.</div>`;
// 3
const R=C.resumo,tot=Object.values(R).reduce((s,v)=>s+v.valor,0);
el('e3t').innerHTML=Object.entries(R).sort((a,b)=>b[1].valor-a[1].valor).map(([k,v])=>{
 const p=100*v.valor/tot; return p<1?'':`<div data-t="k" data-k="${k}" style="width:${p}%;background:${CAT[k].c}">${p>11?CAT[k].r:''}</div>`;}).join('');
el('e3').innerHTML=Object.entries(R).sort((a,b)=>b[1].valor-a[1].valor).map(([k,v])=>
 `<div class="c" data-t="k" data-k="${k}" style="border-top-color:${CAT[k].c}">
  <div class="r">${CAT[k].r}</div><div class="v" style="color:${CAT[k].c}">${brl(v.valor)}</div>
  <div class="d">${v.n} lançamento(s) · ${v.com_vinculo} com contrato<br>${CAT[k].d}</div></div>`).join('');
// 4
const it=C.itens.filter(x=>x.valor).sort((a,b)=>b.valor-a.valor);
el('e4').innerHTML=`<table><thead><tr><th>Quem recebeu</th><th>Quanto</th><th>Tipo de gasto</th>
 <th>Tem contrato?</th><th>Quando</th></tr></thead><tbody>
 ${it.map((x,i)=>`<tr class="lin" data-i="${i}" style="cursor:pointer">
  <td><span class="cn">${x.cnpj||x.beneficiario_pf||'—'}</span></td>
  <td class="n">${brl(x.valor)}</td>
  <td><span class="tg" style="background:${CAT[x.categoria].c}">${CAT[x.categoria].r}</span></td>
  <td>${x.vinculo&&x.vinculo.length?'<b>'+x.vinculo[0]+'</b>':'<span style="color:var(--ilegal)">não</span>'}</td>
  <td class="n">${(x.data||'').split('-').reverse().join('/')}</td></tr>`).join('')}
 </tbody></table>
 <div class="mini" style="margin-top:10px">Há ainda <b>${F.fanout.lancamentos} pagamentos</b> em que a
 publicação junta vários beneficiários e um valor só. Não dá para saber quanto cada um recebeu.</div>`;
// IGD
const G=D.igd,A=G.afericao,PB=G.base_do_indice;
el('igd').innerHTML=`
 <div class="exp">Parte do dinheiro que o governo federal manda é para custear a gestão do
 Bolsa Família e do Cadastro Único. Desse valor, <b>10% tem que ir para o Conselho</b> que
 fiscaliza a assistência social. É regra de 2025, valendo desde janeiro de 2026.</div>
 <div class="paga">
  <div class="q gv"><div class="n">O governo federal mandou para gestão do programa</div>
   <div class="v">${brl(PB.total)}</div><div class="s">base do cálculo</div></div>
  <div class="q gv"><div class="n">Desse valor, deveria ir para o Conselho</div>
   <div class="v">${brl(G.devido_ao_controle_social)}</div><div class="s">10% — o mínimo da lei</div></div>
  <div class="q gl" style="border-left-color:var(--ilegal)">
   <div class="n">Mas o orçamento reservou, nessa fonte</div>
   <div class="v" style="color:var(--ilegal)">${brl(A.aplicado_na_fonte_do_indice)}</div>
   <div class="s" style="color:var(--ilegal)">só ${A.cumprimento_percentual}% do devido</div></div>
  <div class="q gl" style="border-left-color:var(--ilegal)">
   <div class="n">Está faltando</div>
   <div class="v" style="color:var(--ilegal)">${brl(A.diferenca)}</div>
   <div class="s" style="color:var(--ilegal)">${A.situacao}</div></div>
 </div>
 <div class="alerta"><b>Por que os R$ 240.000 do Estado não resolvem.</b>
 O Conselho tem R$ 256.000 no orçamento, mas R$ 240.000 vêm do governo estadual e só
 R$ 16.000 vêm da fonte federal, que é onde esse dinheiro do programa circula. A regra dos
 10% fala do repasse federal. O dinheiro estadual é bem-vindo e conta como reforço, mas não
 substitui o que a União manda reservar.<br><br>
 <b>E a conta é mensal, não anual.</b> A lei diz "do valor repassado mensalmente". Quem aplica
 tudo em dezembro descumpriu nos outros onze meses. Não existe demonstrativo mensal publicado.<br><br>
 <b>O que acontece se não cumprir:</b> ${G.sancao}.</div>`;
// tetos
el('tt').innerHTML=C.tetos.map(t=>{
 const cls=t.situacao.startsWith('DESCUMPRIDO')?'d':'i';
 return `<div class="t ${cls}"><div class="n">${t.nome}</div>
 <div class="st" style="color:${cls==='d'?'var(--ilegal)':'var(--sutil)'}">${t.situacao}</div>
 ${t.teto?`<div class="mini">Limite: ${brl(t.teto)} · Apurado: ${t.apurado!=null?brl(t.apurado):'—'}</div>`:''}
 <div class="no">${t.nota}</div></div>`;}).join('');
// frase
const dTot=F.totais.despesa_comprovada+F.totais.despesa_sem_vinculo;
el('fr').innerHTML=`Entraram <b>${brl(F.totais.fundo)}</b> no Fundo da assistência social.
 Deu para saber quem recebeu apenas <b>${brl(dTot)}</b> — <b>${(100*dTot/F.totais.fundo).toFixed(1)}%</b>.
 O Município entrou com <b>${brl(9000)}</b> de dinheiro próprio, contra
 <b>${brl(17354000)}</b> que vieram de fora. E o Conselho que deveria fiscalizar tudo isso
 não recebeu <b>${brl(70670.72)}</b> que a lei manda repassar para ele.`;
// balao
function bal(ev,t,c){const b=el('bal');el('bc').innerHTML=`<h4>${t}</h4>${c}`;b.style.display='block';
 const r=b.getBoundingClientRect();let x=ev.clientX+14,y=ev.clientY-24;
 if(x+r.width>innerWidth-12)x=innerWidth-r.width-12;
 if(y+r.height>innerHeight-12)y=innerHeight-r.height-12;if(y<8)y=8;
 b.style.left=x+'px';b.style.top=y+'px';}
function fx(){el('bal').style.display='none';}
document.addEventListener('click',e=>{
 const n=e.target.closest('[data-t]'),l=e.target.closest('.lin');
 if(!n&&!l){if(!e.target.closest('#bal'))fx();return;}
 if(l){const x=it[+l.dataset.i];
  bal(e,'Quem recebeu e por quê',`<dl>
   <dt>Recebeu</dt><dd class="cn">${x.cnpj||x.beneficiario_pf||'—'}</dd>
   <dt>Valor</dt><dd>${brl(x.valor)}</dd>
   <dt>Tipo de gasto</dt><dd>${CAT[x.categoria].r}${x.subcategoria?' — '+x.subcategoria:''}</dd>
   <dt>Como foi classificado</dt><dd>${x.base_classificacao}</dd>
   ${x.vinculo&&x.vinculo.length?`<dt>Contrato ou termo</dt><dd><b>${x.vinculo.join('<br>')}</b></dd>`:
     `<dt style="color:var(--ilegal)">Falta</dt><dd>${x.falta||'Contrato, termo ou convênio que justifique o pagamento'}</dd>`}
   ${x.processo?`<dt>Processo</dt><dd>${x.processo}</dd>`:''}
   ${x.dotacao?`<dt>Dotação</dt><dd>${x.dotacao}</dd>`:''}
   <dt>Para que serviu</dt><dd>${(x.objeto||'não informado na publicação').slice(0,240)}</dd>
   ${x.edicao?`<dt>Onde foi publicado</dt><dd>${x.edicao}</dd>`:''}</dl>`);return;}
 const t=n.dataset.t;
 if(t==='f'){const f=F.fontes[+n.dataset.i];
  bal(e,f.nome,`<dl><dt>Quanto</dt><dd>${brl(f.valor)}</dd><dt>Quem paga</dt><dd>${f.ente}</dd>
   ${f.prova?`<dt>Onde está provado</dt><dd>${f.prova}</dd>`:''}
   ${f.falta?`<dt style="color:var(--risco)">Falta</dt><dd>${f.falta}</dd>`:''}
   ${f.alerta?`<dt style="color:var(--ilegal)">Atenção</dt><dd>${f.alerta}</dd>`:''}</dl>`);}
 else if(t==='c'){const c=F.contas[+n.dataset.i];
  bal(e,c.nome,`<dl><dt>Quanto</dt><dd>${brl(c.valor)}</dd><dt>Base legal</dt><dd>${c.base}</dd>
   <dt>Por que importa</dt><dd>${c.nota}</dd>
   <dt style="color:var(--risco)">Falta</dt><dd>${c.falta}</dd></dl>`);}
 else if(t==='k'){const k=n.dataset.k,v=R[k],ex=C.itens.filter(x=>x.categoria===k&&x.valor).slice(0,6);
  bal(e,CAT[k].r,`<p>${CAT[k].d}</p><dl><dt>Total</dt><dd>${brl(v.valor)}</dd>
   <dt>Lançamentos</dt><dd>${v.n}, sendo ${v.com_vinculo} com contrato publicado</dd>
   ${ex.length?`<dt>Exemplos</dt><dd>${ex.map(x=>`${x.cnpj||x.beneficiario_pf||'—'} — ${brl(x.valor)}`).join('<br>')}</dd>`:''}</dl>`);}
});
</script></body></html>'''

if __name__ == "__main__":
    main()
