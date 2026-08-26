#!/usr/bin/env python3
"""Gera docs/fluxo_2026.html — trilha visual do dinheiro.

Verde: fonte comprovada. Laranja: fonte sem comprovação de origem.
Azul: despesa com vínculo jurídico. Vermelho: despesa sem vínculo.
Balões intermediários: conta do Fundo e unidade fora do Fundo.
"""
import json
from pathlib import Path
RAIZ = Path(__file__).resolve().parent.parent

def brl(v):
    return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def main():
    F = json.loads((RAIZ/"dados"/"fluxo_2026.json").read_text(encoding="utf-8"))
    html = TEMPLATE.replace("__DADOS__", json.dumps(F, ensure_ascii=False))
    (RAIZ/"docs"/"fluxo_2026.html").write_text(html, encoding="utf-8")
    print(f"fluxo_2026.html: {len(html)//1024}K")

TEMPLATE = r'''<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>De onde veio, onde passou, para onde foi — assistência social de Goiânia, 2026</title>
<style>
:root{--tinta:#1a1a18;--papel:#faf8f4;--linha:#ddd7cb;--sutil:#6b665c;
--verde:#1f7a4d;--verdeF:#e6f4ec;--azul:#1c5a94;--azulF:#e4eef8;
--laranja:#b8690f;--laranjaF:#fdf0dd;--verm:#a32a2a;--vermF:#fbe9e9;--conta:#4c3b8f;--contaF:#eeeaf9}
*{box-sizing:border-box;margin:0;padding:0}
body{font:15px/1.55 Georgia,'Times New Roman',serif;background:var(--papel);color:var(--tinta);padding:22px}
.w{max-width:1240px;margin:0 auto}
h1{font-size:25px;font-weight:normal;letter-spacing:-.3px}
.sub{color:var(--sutil);font-size:13.5px;margin:4px 0 20px;padding-bottom:14px;border-bottom:1px solid var(--linha)}
h2{font-size:17px;font-weight:normal;margin:26px 0 10px;padding-bottom:5px;border-bottom:1px solid var(--linha)}
.leg{display:flex;gap:16px;flex-wrap:wrap;margin:14px 0;font-size:13px}
.leg i{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.fluxo{display:grid;grid-template-columns:1fr 34px 1fr 34px 1fr;gap:10px;align-items:start;margin:16px 0}
.faixa h3{font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:normal;
color:var(--sutil);margin-bottom:8px;text-align:center}
.no{border:1px solid var(--linha);border-left-width:4px;background:#fff;padding:9px 11px;border-radius:3px;
margin-bottom:7px;cursor:pointer;transition:.12s;position:relative}
.no:hover{transform:translateX(2px);box-shadow:0 2px 8px rgba(0,0,0,.09)}
.no.on{box-shadow:0 0 0 2px var(--tinta)}
.no .t{font-size:13px;line-height:1.35}
.no .v{font-size:15px;font-variant-numeric:tabular-nums;margin-top:3px}
.no .m{font-size:11px;color:var(--sutil);margin-top:2px}
.vd{border-left-color:var(--verde);background:var(--verdeF)} .vd .v{color:var(--verde)}
.lj{border-left-color:var(--laranja);background:var(--laranjaF)} .lj .v{color:var(--laranja)}
.az{border-left-color:var(--azul);background:var(--azulF)} .az .v{color:var(--azul)}
.vm{border-left-color:var(--verm);background:var(--vermF)} .vm .v{color:var(--verm)}
.ct{border-left-color:var(--conta);background:var(--contaF);border-width:2px;border-left-width:5px}
.ct .v{color:var(--conta);font-size:17px}
.seta{display:flex;align-items:center;justify-content:center;padding-top:60px;color:#c3bcae;font-size:20px}
#balao{position:fixed;z-index:50;max-width:400px;background:#fff;border:1px solid var(--tinta);
border-radius:4px;padding:13px 15px;box-shadow:0 6px 22px rgba(0,0,0,.18);display:none;font-size:13px;line-height:1.5}
#balao h4{font-size:14px;font-weight:normal;margin-bottom:7px;padding-bottom:5px;border-bottom:1px solid var(--linha)}
#balao dt{font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--sutil);margin-top:7px}
#balao dd{margin-left:0}
#balao .fecha{position:absolute;top:7px;right:10px;cursor:pointer;color:var(--sutil);font-size:16px}
.pill{display:inline-block;font-size:10px;text-transform:uppercase;letter-spacing:.5px;padding:1px 7px;
border-radius:2px;border:1px solid currentColor;margin-right:4px}
.barra{display:flex;height:26px;border-radius:3px;overflow:hidden;margin:8px 0;border:1px solid var(--linha)}
.barra div{display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff}
.aviso{border-left:3px solid var(--verm);background:var(--vermF);padding:10px 14px;margin:12px 0;font-size:13.5px}
.nota{font-size:12.5px;color:var(--sutil);margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th{text-align:left;font-weight:normal;color:var(--sutil);font-size:10.5px;text-transform:uppercase;
letter-spacing:.5px;padding:6px;border-bottom:1px solid var(--linha)}
td{padding:6px;border-bottom:1px dotted var(--linha)}
td.n{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.cnpj{font-family:ui-monospace,Menlo,monospace;font-size:12px}
@media(max-width:900px){.fluxo{grid-template-columns:1fr}.seta{transform:rotate(90deg);padding:4px 0}}
</style></head><body><div class="w">
<h1>De onde veio, onde passou, para onde foi</h1>
<div class="sub">Fundo Municipal de Assistência Social de Goiânia · exercício 2026 · clique em qualquer caixa para ver a prova ou o que falta</div>

<div class="leg">
 <span><i style="background:var(--verde)"></i>Fonte comprovada</span>
 <span><i style="background:var(--laranja)"></i>Fonte sem comprovação de origem</span>
 <span><i style="background:var(--conta)"></i>Conta ou unidade onde o dinheiro passa</span>
 <span><i style="background:var(--azul)"></i>Despesa com vínculo jurídico</span>
 <span><i style="background:var(--verm)"></i>Despesa sem vínculo comprovado</span>
</div>

<div class="fluxo">
 <div class="faixa"><h3>1 · De onde veio</h3><div id="fon"></div></div>
 <div class="seta">→</div>
 <div class="faixa"><h3>2 · Onde passou</h3><div id="con"></div></div>
 <div class="seta">→</div>
 <div class="faixa"><h3>3 · Para onde foi</h3><div id="des"></div></div>
</div>

<h2>Leitura em uma linha</h2>
<div id="resumo"></div>

<h2>Despesas com vínculo jurídico comprovado</h2>
<div id="tcom"></div>
<h2>Despesas sem vínculo comprovado</h2>
<div id="tsem"></div>
</div>
<div id="balao"><span class="fecha" onclick="fecha()">×</span><div id="bc"></div></div>
<script>
const D=__DADOS__;
const brl=v=>v==null?'—':'R$ '+Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
const el=i=>document.getElementById(i);
const CLS={comprovada:'vd',nao_comprovada:'lj'};
let sel=null;
// 1 fontes
el('fon').innerHTML=D.fontes.map((f,i)=>`<div class="no ${CLS[f.status]}" data-t="f" data-i="${i}">
 <div class="t">${f.nome}</div><div class="v">${brl(f.valor)}</div>
 <div class="m">fonte ${f.fonte} · ${f.ente}</div></div>`).join('');
// 2 contas
el('con').innerHTML=D.contas.map((c,i)=>`<div class="no ct" data-t="c" data-i="${i}">
 <div class="t">${c.nome}</div><div class="v">${brl(c.valor)}</div>
 <div class="m">unidade ${c.unidade}</div></div>`).join('');
// 3 despesas: comprovadas, sem vinculo, acoes sem execucao
let h='';
D.despesas.filter(x=>x.tipo==='comprovada').forEach((x,i)=>{h+=`<div class="no az" data-t="d" data-i="${i}">
 <div class="t">${x.vinculo[0]||'com vínculo'}</div><div class="v">${brl(x.valor)}</div>
 <div class="m"><span class="cnpj">${x.cnpj}</span> · ${x.data.split('-').reverse().join('/')}</div></div>`;});
D.despesas.filter(x=>x.tipo==='sem_vinculo').forEach((x,i)=>{h+=`<div class="no vm" data-t="s" data-i="${i}">
 <div class="t">Pagamento sem vínculo identificado</div><div class="v">${brl(x.valor)}</div>
 <div class="m"><span class="cnpj">${x.cnpj}</span> · ${x.data.split('-').reverse().join('/')}</div></div>`;});
h+=`<div class="no vm" data-t="x" data-i="0"><div class="t">${D.fanout.lancamentos} lançamentos não atribuíveis</div>
 <div class="v">valor indeterminado</div><div class="m">fan-out de publicação</div></div>`;
D.acoes.forEach((a,i)=>{h+=`<div class="no vm" data-t="a" data-i="${i}">
 <div class="t">${a.nome}</div><div class="v">${brl(a.valor)}</div>
 <div class="m">ação ${a.id} · sem execução publicada</div></div>`;});
el('des').innerHTML=h;
// balao
function balao(ev,titulo,corpo){
 const b=el('balao');el('bc').innerHTML=`<h4>${titulo}</h4>${corpo}`;
 b.style.display='block';
 const r=b.getBoundingClientRect();
 let x=ev.clientX+14,y=ev.clientY-20;
 if(x+r.width>innerWidth-12)x=innerWidth-r.width-12;
 if(y+r.height>innerHeight-12)y=innerHeight-r.height-12;
 if(y<8)y=8;
 b.style.left=x+'px';b.style.top=y+'px';
}
function fecha(){el('balao').style.display='none';
 document.querySelectorAll('.no.on').forEach(n=>n.classList.remove('on'));sel=null;}
document.addEventListener('click',e=>{
 const n=e.target.closest('.no');
 if(!n){if(!e.target.closest('#balao'))fecha();return;}
 document.querySelectorAll('.no.on').forEach(o=>o.classList.remove('on'));n.classList.add('on');
 const t=n.dataset.t,i=+n.dataset.i;
 if(t==='f'){const f=D.fontes[i];
  balao(e,f.nome,`<span class="pill" style="color:var(--${f.status==='comprovada'?'verde':'laranja'})">
   ${f.status==='comprovada'?'fonte comprovada':'origem não comprovada'}</span>
   <dl><dt>Valor previsto</dt><dd>${brl(f.valor)}</dd>
   <dt>Ente de origem</dt><dd>${f.ente}</dd>
   <dt>Código da fonte</dt><dd>${f.fonte}</dd>
   ${f.prova?`<dt>Onde está a prova</dt><dd>${f.prova}</dd>`:''}
   ${f.falta?`<dt>Documento que falta</dt><dd>${f.falta}</dd>`:''}
   ${f.alerta?`<dt>Observação</dt><dd>${f.alerta}</dd>`:''}</dl>`);}
 else if(t==='c'){const c=D.contas[i];
  balao(e,c.nome,`<span class="pill" style="color:var(--conta)">onde o dinheiro passa</span>
   <dl><dt>Valor</dt><dd>${brl(c.valor)}</dd>
   <dt>Unidade orçamentária</dt><dd>${c.unidade}</dd>
   <dt>Base legal</dt><dd>${c.base}</dd>
   <dt>Por que importa</dt><dd>${c.nota}</dd>
   <dt>Documento que falta</dt><dd>${c.falta}</dd></dl>`);}
 else if(t==='d'){const x=D.despesas.filter(y=>y.tipo==='comprovada')[i];
  balao(e,'Despesa com vínculo comprovado',
   `<span class="pill" style="color:var(--azul)">vínculo jurídico identificado</span>
   <dl><dt>Contrato, termo ou convênio</dt><dd><b>${x.vinculo.join('<br>')}</b></dd>
   <dt>Valor</dt><dd>${brl(x.valor)}</dd>
   <dt>Beneficiário</dt><dd class="cnpj">${x.cnpj}</dd>
   <dt>Data da publicação</dt><dd>${x.data.split('-').reverse().join('/')}</dd>
   ${x.processo?`<dt>Processo</dt><dd>${x.processo}</dd>`:''}
   ${x.dotacao?`<dt>Dotação</dt><dd>${x.dotacao}</dd>`:''}
   <dt>Objeto</dt><dd>${(x.objeto||'—').slice(0,200)}</dd>
   <dt>Edição do Diário</dt><dd>${x.edicao}</dd></dl>
   <div class="nota">Vínculo publicado. Falta o empenho, a liquidação e o pagamento para comprovar a saída do dinheiro.</div>`);}
 else if(t==='s'){const x=D.despesas.filter(y=>y.tipo==='sem_vinculo')[i];
  balao(e,'Despesa sem vínculo comprovado',
   `<span class="pill" style="color:var(--verm)">sem contrato ou termo identificado</span>
   <dl><dt>Valor</dt><dd>${brl(x.valor)}</dd>
   <dt>Beneficiário</dt><dd class="cnpj">${x.cnpj}</dd>
   <dt>Data da publicação</dt><dd>${x.data.split('-').reverse().join('/')}</dd>
   ${x.processo?`<dt>Processo</dt><dd>${x.processo}</dd>`:''}
   <dt>Objeto</dt><dd>${(x.objeto||'—').slice(0,200)}</dd>
   <dt>Documento que falta</dt><dd>${x.falta}</dd></dl>`);}
 else if(t==='x'){
  balao(e,`${D.fanout.lancamentos} lançamentos não atribuíveis`,
   `<span class="pill" style="color:var(--verm)">valor não atribuível</span>
   <dl><dt>O que aconteceu</dt><dd>${D.fanout.nota}</dd>
   <dt>Documento que falta</dt><dd>Relação de empenhos por credor, com valor individualizado</dd></dl>`);}
 else if(t==='a'){const a=D.acoes[i];
  balao(e,a.nome,`<span class="pill" style="color:var(--verm)">sem execução publicada</span>
   <dl><dt>Dotação prevista</dt><dd>${brl(a.valor)}</dd>
   <dt>Ação orçamentária</dt><dd>${a.id}</dd>
   <dt>Documento que falta</dt><dd>${a.falta}</dd></dl>`);}
});
// resumo
const T=D.totais;
const pc=100*T.fonte_comprovada/(T.fonte_comprovada+T.fonte_nao_comprovada);
const dTot=T.despesa_comprovada+T.despesa_sem_vinculo;
el('resumo').innerHTML=`
 <div class="barra">
  <div style="width:${pc}%;background:var(--verde)">${pc.toFixed(0)}% origem comprovada</div>
  <div style="width:${100-pc}%;background:var(--laranja)">${(100-pc).toFixed(0)}%</div></div>
 <p>Entraram <b>${brl(T.fonte_comprovada+T.fonte_nao_comprovada)}</b> no Fundo. Destes,
 <b style="color:var(--verde)">${brl(T.fonte_comprovada)}</b> têm ente de origem identificado e
 <b style="color:var(--laranja)">${brl(T.fonte_nao_comprovada)}</b> não têm.</p>
 <div class="barra" style="margin-top:12px">
  <div style="width:${100*T.despesa_comprovada/dTot}%;background:var(--azul)">${(100*T.despesa_comprovada/dTot).toFixed(0)}% com vínculo</div>
  <div style="width:${100*T.despesa_sem_vinculo/dTot}%;background:var(--verm)">${(100*T.despesa_sem_vinculo/dTot).toFixed(0)}%</div></div>
 <p>Do que foi possível atribuir a um beneficiário — apenas <b>${brl(dTot)}</b> de todo o exercício —
 <b style="color:var(--azul)">${brl(T.despesa_comprovada)}</b> têm contrato ou termo publicado e
 <b style="color:var(--verm)">${brl(T.despesa_sem_vinculo)}</b> não têm.</p>
 <div class="aviso"><b>O essencial em uma frase.</b> ${brl(T.fonte_comprovada+T.fonte_nao_comprovada)} entraram,
 ${brl(dTot)} saíram com destinatário conhecido — <b>${(100*dTot/T.fundo).toFixed(1)}%</b>.
 O resto do caminho não é público. E fora do Fundo, sem passar pelo controle do Conselho,
 corre ainda <b>${brl(T.fora_do_fundo)}</b> na unidade do Gabinete.</div>`;
// tabelas
const tb=(arr,cor)=>`<table><thead><tr><th>Data</th><th>Beneficiário</th><th>Valor</th>
 <th>${cor==='az'?'Contrato ou termo':'Documento que falta'}</th></tr></thead><tbody>
 ${arr.map(x=>`<tr><td class="n">${x.data.split('-').reverse().join('/')}</td>
 <td class="cnpj">${x.cnpj}</td><td class="n">${brl(x.valor)}</td>
 <td>${cor==='az'?'<b>'+x.vinculo.join('<br>')+'</b>':x.falta}</td></tr>`).join('')}</tbody></table>`;
el('tcom').innerHTML=tb(D.despesas.filter(x=>x.tipo==='comprovada'),'az');
el('tsem').innerHTML=tb(D.despesas.filter(x=>x.tipo==='sem_vinculo'),'vm');
</script></body></html>'''

if __name__ == "__main__":
    main()
