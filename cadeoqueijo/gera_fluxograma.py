#!/usr/bin/env python3
"""Gera docs/fluxograma_2026.html — o caminho do dinheiro em setas e pizzas.

Três estágios, uma paleta só: a cor de uma origem é a mesma na pizza, na seta e
no destino. Quem paga, por onde passa, quem recebe — cada um com inscrição e
nome. Cruzamento com a fonte federal em cada nó que tiver contraparte.
"""
import json
from pathlib import Path
RAIZ = Path(__file__).resolve().parent.parent

import sys as _s; _s.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from marca import LOGO_URI as _LOGO
_FAIXA_MARCA = ('<div style="display:flex;gap:14px;align-items:center;max-width:1180px;margin:0 auto 6px;padding:10px 8px 0"><img src="' + _LOGO + '" alt="Núcleo de Fiscalização" style="width:72px;height:auto"><div style="font:700 11px/1.5 Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#6b6660">Núcleo de Fiscalização — A.M.C. Jardim América<br>Vigilância da assistência social — Município de Goiânia</div></div>')


def main():
    L = lambda p: json.loads((RAIZ / p).read_text(encoding="utf-8"))
    d = {"fluxo": L("dados/fluxo_2026.json"), "dest": L("dados/destinatarios_2026.json"),
         "cat": L("dados/categorias_2026.json"), "fed": L("dados/repasses_federais.json"),
         "igd": L("dados/igd_controle_social.json")}
    try: d["dupla"] = L("relatorios/dupla_etapa_2026.json")
    except Exception: d["dupla"] = None
    html = TPL.replace("__D__", json.dumps(d, ensure_ascii=False))
    (RAIZ / "docs" / "fluxograma_2026.html").write_text(html, encoding="utf-8")
    print(f"  fluxograma_2026.html: {len(html)//1024}K")

TPL = r'''<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fluxograma do dinheiro — assistência social de Goiânia, 2026</title>
<style>
:root{--tinta:#16150f;--papel:#fbfaf6;--linha:#ded8ca;--sutil:#6f6a5e;
--c1:#1f7a4d;--c2:#2f6ea8;--c3:#7a4fa8;--c4:#b8690f;--c5:#0f7a72;--c6:#8c2f2f;--c7:#8a7320;--c8:#5b5f66;
--alerta:#a32a2a;--ok:#1f7a4d}
*{box-sizing:border-box;margin:0;padding:0}
body{font:15px/1.55 Georgia,'Times New Roman',serif;background:var(--papel);color:var(--tinta);padding:20px}
.w{max-width:1240px;margin:0 auto}
h1{font-size:27px;font-weight:normal;letter-spacing:-.4px}
.lead{color:var(--sutil);font-size:14px;margin:8px 0 22px;padding-bottom:16px;border-bottom:2px solid var(--tinta)}
h2{font-size:13px;text-transform:uppercase;letter-spacing:1.4px;font-weight:normal;color:var(--sutil);
margin:30px 0 12px;padding-bottom:5px;border-bottom:1px solid var(--linha)}
.grade{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;margin-bottom:8px}
.et{text-align:center}
.et h3{font-size:16px;font-weight:normal;margin-bottom:2px}
.et .tot{font-size:22px;font-variant-numeric:tabular-nums}
.et .sub{font-size:12px;color:var(--sutil)}
svg{display:block;width:100%;height:auto}
.pz{cursor:pointer;transition:.12s}.pz:hover{opacity:.82}
.no{fill:#fff;stroke:var(--linha);stroke-width:1}
.rot{font:11px Georgia,serif;fill:var(--tinta)}
.rotp{font:10px Georgia,serif;fill:var(--sutil)}
.val{font:12px Georgia,serif;font-variant-numeric:tabular-nums}
.cx{border:1px solid var(--linha);border-left-width:5px;background:#fff;border-radius:3px;
padding:9px 11px;margin-bottom:6px;cursor:pointer;transition:.12s}
.cx:hover{transform:translateX(2px);box-shadow:0 2px 9px rgba(0,0,0,.09)}
.cx .n{font-size:12.5px;line-height:1.3}
.cx .v{font-size:15px;font-variant-numeric:tabular-nums}
.cx .m{font-size:10.5px;color:var(--sutil);margin-top:2px}
.leg{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;margin:10px 0}
.leg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
#bal{position:fixed;z-index:70;max-width:430px;background:#fff;border:2px solid var(--tinta);
border-radius:5px;padding:15px 17px;box-shadow:0 10px 32px rgba(0,0,0,.24);display:none;font-size:13.5px}
#bal h4{font-size:15px;font-weight:normal;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid var(--linha)}
#bal dt{font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:var(--sutil);margin-top:8px}
#bal .x{position:absolute;top:7px;right:11px;cursor:pointer;color:var(--sutil);font-size:18px}
.cn{font-family:ui-monospace,Menlo,monospace;font-size:12px}
table{width:100%;border-collapse:collapse;font-size:13px;background:#fff}
th{text-align:left;font-weight:normal;font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;
color:var(--sutil);padding:7px;border-bottom:1px solid var(--linha)}
td{padding:8px 7px;border-bottom:1px dotted var(--linha);vertical-align:top}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.chip{display:inline-block;font-size:10px;text-transform:uppercase;letter-spacing:.5px;padding:1px 6px;
border-radius:2px;border:1px solid currentColor}
.aviso{border-left:5px solid var(--alerta);background:#fbeaea;padding:12px 15px;margin:12px 0;font-size:13.5px}
.okbox{border-left:5px solid var(--ok);background:#eaf5ee;padding:12px 15px;margin:12px 0;font-size:13.5px}
@media(max-width:900px){.grade{grid-template-columns:1fr}}
</style></head><body>{_FAIXA_MARCA}<div class="w">
<h1>Fluxograma do dinheiro</h1>
<div class="lead">Assistência social de Goiânia, 2026. Cada origem tem uma cor, e a cor acompanha o
dinheiro da pizza à seta e ao destino. Clique em qualquer fatia, seta ou caixa.</div>

<h2>Estágio 1 · De onde veio</h2>
<div class="grade"><div class="et" style="grid-column:1/2">
 <h3>Origem</h3><div class="tot" id="t1"></div><div class="sub">entraram no Fundo</div></div></div>
<div class="grade"><div><svg id="p1" viewBox="0 0 300 300"></svg></div>
 <div style="grid-column:2/4"><div id="l1"></div></div></div>

<h2>Estágio 2 · Por onde passou</h2>
<svg id="fx" viewBox="0 0 1180 460"></svg>

<h2>Estágio 3 · Para onde foi</h2>
<div class="grade"><div><svg id="p3" viewBox="0 0 300 300"></svg></div>
 <div style="grid-column:2/4"><div id="l3"></div></div></div>

<h2>Quem pagou e quem recebeu</h2>
<div id="tab"></div>

<h2>Cruzamento com a fonte federal</h2>
<div id="cruz"></div>

<h2>Auditoria de dupla etapa</h2>
<div id="dup"></div>
</div>
<div id="bal"><span class="x" onclick="fx2()">×</span><div id="bc"></div></div>
<script>
const D=__D__;
const F=D.fluxo,DE=D.dest,FED=D.fed,IGD=D.igd;
const brl=v=>v==null?'—':'R$ '+Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
const el=i=>document.getElementById(i);
const PAL=['var(--c1)','var(--c2)','var(--c3)','var(--c4)','var(--c5)','var(--c6)','var(--c7)','var(--c8)'];
F.fontes.forEach((f,i)=>f._cor=PAL[i%PAL.length]);
const TOT=F.totais.fundo;
el('t1').textContent=brl(TOT);

function pizza(svgId,itens,onClick){
 const s=el(svgId),R=118,cx=150,cy=150;let ang=-Math.PI/2,h='';
 const tot=itens.reduce((a,b)=>a+b.valor,0);
 itens.forEach((it,i)=>{
  const a2=ang+2*Math.PI*it.valor/tot,gr=a2-ang>Math.PI?1:0;
  const x1=cx+R*Math.cos(ang),y1=cy+R*Math.sin(ang),x2=cx+R*Math.cos(a2),y2=cy+R*Math.sin(a2);
  h+=`<path class="pz" data-i="${i}" data-g="${svgId}" d="M${cx},${cy} L${x1},${y1} A${R},${R} 0 ${gr},1 ${x2},${y2} Z" fill="${it.cor}" stroke="#fff" stroke-width="2"/>`;
  const p=100*it.valor/tot;
  if(p>4.5){const am=(ang+a2)/2,lx=cx+R*.65*Math.cos(am),ly=cy+R*.65*Math.sin(am);
   h+=`<text x="${lx}" y="${ly}" text-anchor="middle" fill="#fff" font="bold 12px Georgia" style="font:600 12px Georgia;pointer-events:none">${p.toFixed(0)}%</text>`;}
  ang=a2;});
 h+=`<circle cx="${cx}" cy="${cy}" r="46" fill="var(--papel)"/>
  <text x="${cx}" y="${cy-4}" text-anchor="middle" style="font:11px Georgia;fill:var(--sutil)">total</text>
  <text x="${cx}" y="${cy+13}" text-anchor="middle" style="font:13px Georgia;fill:var(--tinta)">${(tot/1e6).toFixed(1)} mi</text>`;
 s.innerHTML=h;
}
// pizza 1 e lista
const it1=F.fontes.map((f,i)=>({nome:f.nome,valor:f.valor,cor:f._cor,ref:i,t:'f'}));
pizza('p1',it1);
el('l1').innerHTML=it1.map(x=>`<div class="cx" data-t="f" data-i="${x.ref}" style="border-left-color:${x.cor}">
 <div class="n">${x.nome}</div><div class="v" style="color:${x.cor}">${brl(x.valor)}</div>
 <div class="m">${(100*x.valor/TOT).toFixed(1)}% do Fundo · fonte ${F.fontes[x.ref].fonte} · ${F.fontes[x.ref].status==='comprovada'?'origem provada':'origem não declarada'}</div></div>`).join('');
// pizza 3: destinos
const R3=D.cat.resumo,CATC={PESSOAL:'var(--c6)',CONTRATUAL_FIXA:'var(--c2)',REPASSE_ENTIDADE:'var(--c1)',
 PROGRAMA:'var(--c3)',INVESTIMENTO:'var(--c4)',NAO_CLASSIFICADA:'var(--c8)'};
const CATN={PESSOAL:'Pessoal',CONTRATUAL_FIXA:'Contratos e serviços',REPASSE_ENTIDADE:'Repasse a instituições',
 PROGRAMA:'Programas',INVESTIMENTO:'Investimento',NAO_CLASSIFICADA:'Sem classificação'};
const it3=Object.entries(R3).filter(([,v])=>v.valor>0).sort((a,b)=>b[1].valor-a[1].valor)
 .map(([k,v])=>({nome:CATN[k]||k,valor:v.valor,cor:CATC[k]||'var(--c8)',ref:k,t:'k'}));
pizza('p3',it3);
const T3=it3.reduce((a,b)=>a+b.valor,0);
el('l3').innerHTML=it3.map(x=>`<div class="cx" data-t="k" data-k="${x.ref}" style="border-left-color:${x.cor}">
 <div class="n">${x.nome}</div><div class="v" style="color:${x.cor}">${brl(x.valor)}</div>
 <div class="m">${(100*x.valor/T3).toFixed(1)}% do que foi atribuído · ${R3[x.ref].n} lançamento(s) · ${R3[x.ref].com_vinculo} com contrato</div></div>`).join('')
 +`<div class="aviso" style="margin-top:10px">Do Fundo de ${brl(TOT)}, só <b>${brl(T3)}</b> —
 ${(100*T3/TOT).toFixed(1)}% — puderam ser atribuídos a um destinatário. O resto do caminho não é público.</div>`;
// fluxograma com setas
(function(){
 const W=1180,esq=30,mx=470,dir=900,largo=230;
 let y=40,h='';
 const alt=f=>Math.max(20,270*f.valor/TOT);
 // nos de origem
 const pos={};
 F.fontes.forEach((f,i)=>{const a=alt(f);pos[i]={y:y,h:a};
  h+=`<rect class="pz" data-t="f" data-i="${i}" x="${esq}" y="${y}" width="${largo}" height="${a}" rx="3" fill="${f._cor}" opacity=".92"/>`;
  if(a>15)h+=`<text class="rot" x="${esq+8}" y="${y+a/2+4}" fill="#fff" style="pointer-events:none">${f.nome.slice(0,30)}</text>`;
  y+=a+5;});
 const fim=y;
 // no central: conta do Fundo
 const cy0=45,ch=fim-50;
 h+=`<rect class="pz" data-t="c" data-i="0" x="${mx}" y="${cy0}" width="${largo}" height="${ch}" rx="4" fill="#fff" stroke="var(--c3)" stroke-width="3"/>
  <text class="rot" x="${mx+largo/2}" y="${cy0+ch/2-14}" text-anchor="middle" style="font:13px Georgia">Conta do Fundo</text>
  <text class="val" x="${mx+largo/2}" y="${cy0+ch/2+6}" text-anchor="middle" style="font:15px Georgia">${brl(TOT)}</text>
  <text class="rotp" x="${mx+largo/2}" y="${cy0+ch/2+24}" text-anchor="middle">unidade 3650</text>`;
 // setas origem -> conta
 F.fontes.forEach((f,i)=>{const p=pos[i],y1=p.y+p.h/2,y2=cy0+ch/2;
  h+=`<path d="M${esq+largo},${y1} C${(esq+largo+mx)/2},${y1} ${(esq+largo+mx)/2},${y2} ${mx-8},${y2}"
   stroke="${f._cor}" stroke-width="${Math.max(1.5,p.h/9)}" fill="none" opacity=".5"/>
   <polygon points="${mx-8},${y2-4} ${mx},${y2} ${mx-8},${y2+4}" fill="${f._cor}" opacity=".7"/>`;});
 // destinos
 let dy=45;
 it3.forEach((x,i)=>{const a=Math.max(22,240*x.valor/T3);
  h+=`<rect class="pz" data-t="k" data-k="${x.ref}" x="${dir}" y="${dy}" width="${largo}" height="${a}" rx="3" fill="${x.cor}" opacity=".92"/>`;
  h+=`<text class="rot" x="${dir+8}" y="${dy+a/2+4}" fill="#fff" style="pointer-events:none">${x.nome.slice(0,26)}</text>`;
  const y2=cy0+ch/2;
  h+=`<path d="M${mx+largo},${y2} C${(mx+largo+dir)/2},${y2} ${(mx+largo+dir)/2},${dy+a/2} ${dir-8},${dy+a/2}"
   stroke="${x.cor}" stroke-width="${Math.max(1.5,a/9)}" fill="none" opacity=".5"/>
   <polygon points="${dir-8},${dy+a/2-4} ${dir},${dy+a/2} ${dir-8},${dy+a/2+4}" fill="${x.cor}" opacity=".7"/>`;
  dy+=a+5;});
 // fora do fundo
 const fo=F.contas[1];
 h+=`<rect class="pz" data-t="c" data-i="1" x="${mx}" y="${fim+18}" width="${largo}" height="52" rx="4" fill="#fbeaea" stroke="var(--alerta)" stroke-width="2" stroke-dasharray="5,3"/>
  <text class="rot" x="${mx+largo/2}" y="${fim+40}" text-anchor="middle" fill="var(--alerta)">Fora do Fundo — unidade 3601</text>
  <text class="val" x="${mx+largo/2}" y="${fim+58}" text-anchor="middle" fill="var(--alerta)">${brl(fo.valor)}</text>`;
 h+=`<text class="rotp" x="${esq}" y="26">QUEM PAGA</text>
  <text class="rotp" x="${mx}" y="26">ONDE PASSA</text>
  <text class="rotp" x="${dir}" y="26">QUEM RECEBE</text>`;
 el('fx').setAttribute('viewBox',`0 0 ${W} ${Math.max(fim+90,420)}`);
 el('fx').innerHTML=h;
})();
// tabela pagador x recebedor
el('tab').innerHTML=`<table><thead><tr><th>Papel</th><th>Inscrição</th><th>Nome</th><th>Valor</th><th>Vínculo</th></tr></thead><tbody>
 ${F.fontes.map(f=>`<tr><td><span class="chip" style="color:${f._cor}">paga</span></td>
  <td class="cn">${f.ente==='União'?'00.394.411/0001-09':f.ente==='Município'?'01.612.092/0001-23':'—'}</td>
  <td>${f.nome}</td><td class="n">${brl(f.valor)}</td>
  <td>${f.status==='comprovada'?'fonte '+f.fonte:'origem não declarada'}</td></tr>`).join('')}
 ${DE.destinatarios.map(x=>`<tr><td><span class="chip" style="color:var(--c1)">recebe</span></td>
  <td class="cn">${x.cnpj}</td><td>${x.razao_social||'não consultada'}${x.nome_fantasia?' <span style="color:var(--sutil)">('+x.nome_fantasia+')</span>':''}</td>
  <td class="n">${brl(x.valor_total_no_exercicio)}</td>
  <td>${x.instrumentos.length?x.instrumentos.join('<br>'):'<span style="color:var(--alerta)">sem vínculo</span>'}</td></tr>`).join('')}
 </tbody></table>`;
// cruzamento federal
const cps=FED.igd.competencias;
el('cruz').innerHTML=`<p style="margin-bottom:8px">Lado federal: planilha de repasses do Fundo Nacional, com ordem bancária do SIAFI.
 Lado municipal: Quadro de Detalhamento de Despesas. O piso de 10% incide sobre <b>cada competência</b>.</p>
 <table><thead><tr><th>Competência</th><th>Índice repassado</th><th>Devido ao Conselho</th><th>Reservado</th><th>Situação</th></tr></thead><tbody>
 ${cps.map(c=>`<tr><td>${c.competencia}</td><td class="n">${brl(c.igd_repassado)}</td>
  <td class="n">${brl(c.devido_ao_controle_social)}</td><td class="n">sem demonstrativo</td>
  <td><span class="chip" style="color:var(--alerta)">descumprido</span></td></tr>`).join('')}
 </tbody></table>
 <div class="aviso">Em ${cps.length} competências a União repassou ${brl(FED.igd.total)} de Índice.
 O piso de 10% torna devidos <b>${brl(FED.igd.devido_ao_controle_social_10)}</b>. O orçamento reserva
 <b>${brl(IGD.dotacao_do_conselho.federal_fonte_do_indice)}</b> na fonte federal — ${IGD.afericao.cumprimento_percentual}%.</div>`;
// dupla etapa
const DU=D.dupla;
el('dup').innerHTML=DU?`<div class="okbox"><b>${DU.acionados} achados</b> acionaram segunda via independente.
 <b>${DU.convergiram}</b> convergiram e mantêm o selo, <b>${DU.divergiram}</b> divergiram e foram rebaixados,
 <b>${DU.indisponiveis}</b> não puderam ser reconferidos.<br><br>
 A segunda via só roda sobre suspeita de uso indevido. Achado de mera ausência documental não a aciona:
 falta de documento já é conclusiva, não há o que reconferir.</div>
 <table><thead><tr><th>Achado</th><th>Gatilho</th><th>Segunda via</th><th>Resultado</th></tr></thead><tbody>
 ${DU.resultados.map(r=>`<tr><td><b>${r.codigo}</b> ${r.titulo.slice(0,48)}</td><td>${r.gatilho}</td>
  <td>${r.segunda_via.via}</td><td><span class="chip" style="color:${r.segunda_via.resultado==='CONFIRMA'?'var(--ok)':'var(--alerta)'}">${r.segunda_via.resultado}</span></td></tr>`).join('')}
 </tbody></table>`:'<div class="okbox">Nenhum gatilho de dupla etapa neste ciclo.</div>';
// baloes
function bal(ev,t,c){const b=el('bal');el('bc').innerHTML=`<h4>${t}</h4>${c}`;b.style.display='block';
 const r=b.getBoundingClientRect();let x=(ev.clientX||200)+14,y=(ev.clientY||200)-20;
 if(x+r.width>innerWidth-12)x=innerWidth-r.width-12;
 if(y+r.height>innerHeight-12)y=innerHeight-r.height-12;if(y<8)y=8;
 b.style.left=x+'px';b.style.top=y+'px';}
function fx2(){el('bal').style.display='none';}
document.addEventListener('click',e=>{
 const n=e.target.closest('[data-t],.pz');
 if(!n){if(!e.target.closest('#bal'))fx2();return;}
 let t=n.dataset.t,i=+n.dataset.i,k=n.dataset.k;
 if(!t&&n.dataset.g){const g=n.dataset.g;const src=g==='p1'?it1:it3;const x=src[+n.dataset.i];t=x.t;i=x.ref;k=x.ref;}
 if(t==='f'){const f=F.fontes[i];
  bal(e,f.nome,`<dl><dt>Valor</dt><dd>${brl(f.valor)} — ${(100*f.valor/TOT).toFixed(1)}% do Fundo</dd>
  <dt>Quem paga</dt><dd>${f.ente}</dd><dt>Código da fonte</dt><dd>${f.fonte}</dd>
  ${f.prova?`<dt>Prova</dt><dd>${f.prova}</dd>`:''}
  ${f.falta?`<dt style="color:var(--alerta)">Falta</dt><dd>${f.falta}</dd>`:''}
  ${f.piso_controle_social?`<dt style="color:var(--alerta)">Piso de 10% ao Conselho</dt><dd>
   Devido ${brl(f.piso_controle_social.devido)} · reservado ${brl(f.piso_controle_social.aplicado_na_fonte)} ·
   falta <b>${brl(f.piso_controle_social.falta)}</b><br>${f.piso_controle_social.sancao}</dd>`:''}
  ${f.alerta?`<dt>Observação</dt><dd>${f.alerta}</dd>`:''}</dl>`);}
 else if(t==='c'){const c=F.contas[i];
  bal(e,c.nome,`<dl><dt>Valor</dt><dd>${brl(c.valor)}</dd><dt>Base legal</dt><dd>${c.base}</dd>
  <dt>Por que importa</dt><dd>${c.nota}</dd><dt style="color:var(--alerta)">Falta</dt><dd>${c.falta}</dd></dl>`);}
 else if(t==='k'){const v=R3[k],ex=D.cat.itens.filter(x=>x.categoria===k&&x.valor).slice(0,7);
  bal(e,CATN[k]||k,`<dl><dt>Total</dt><dd>${brl(v.valor)} — ${(100*v.valor/T3).toFixed(1)}%</dd>
  <dt>Lançamentos</dt><dd>${v.n}, sendo ${v.com_vinculo} com contrato publicado</dd>
  ${ex.length?`<dt>Quem recebeu</dt><dd>${ex.map(x=>{const dd=DE.destinatarios.find(y=>y.cnpj===x.cnpj);
   return `<span class="cn">${x.cnpj||'—'}</span> ${dd&&dd.razao_social?dd.razao_social.slice(0,32):''} — ${brl(x.valor)}`;}).join('<br>')}</dd>`:''}</dl>`);}
});
</script></body></html>'''
TPL = TPL.replace("{_FAIXA_MARCA}", _FAIXA_MARCA)


if __name__ == "__main__":
    main()
