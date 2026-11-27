// Roda o app.js de uma página gerada num documento de mentira, sem navegador, e devolve em JSON o HTML
// que cada tela desenhou para cada recorte pedido. Uso: node telas_harness.js pagina.html app.js 'c|s' ...
'use strict';
const fs = require('fs');
const vm = require('vm');
const [, , arqPagina, arqApp, ...recortes] = process.argv;
const html = fs.readFileSync(arqPagina, 'utf8');
const app = fs.readFileSync(arqApp, 'utf8');
const scripts = {};
for (const m of html.matchAll(/<script type="application\/json" id="([^"]+)">([\s\S]*?)<\/script>/g)) scripts[m[1]] = m[2];
const pid = (html.match(/<body data-pagina="([^"]+)"/) || [])[1];

function rodar(busca) {
  const elementos = {};
  function el(id) {
    if (!elementos[id]) {
      elementos[id] = {
        id, innerHTML: '', textContent: scripts[id] !== undefined ? scripts[id] : '', value: '', hidden: false,
        dataset: {}, style: { setProperty() {} }, classList: { add() {}, remove() {}, toggle() {} },
        setAttribute() {}, addEventListener() {}, getBoundingClientRect: () => ({ left: 0, top: 0, bottom: 0, width: 0, height: 0 }),
        closest() { return el(id + ':pai'); }, querySelectorAll() { return []; }, querySelector() { return null; },
        offsetHeight: 60, scrollIntoView() {}
      };
    }
    return elementos[id];
  }
  const erros = [];
  const documento = {
    body: { dataset: { pagina: pid }, classList: { toggle() {}, add() {}, remove() {} } },
    documentElement: { dataset: {}, style: { setProperty() {} } },
    getElementById: el, querySelector: (s) => (s === '.topo' ? el('topo') : null), querySelectorAll: () => [],
    addEventListener() {}
  };
  const janela = {
    matchMedia: () => ({ matches: false }), addEventListener() {}, innerWidth: 1200, innerHeight: 800, open() {}
  };
  const ctx = {
    document: documento, window: janela, location: { search: busca, hash: '', href: '' },
    history: { replaceState() {} }, localStorage: { getItem: () => null, setItem() {} },
    URLSearchParams, Intl, JSON, Math, Object, Array, String, Number, Date, isFinite, isNaN, Promise, setTimeout: () => 0, clearTimeout() {},
    navigator: {}, console: { error: (e) => erros.push(String(e && e.stack || e)), log() {} }
  };
  vm.createContext(ctx);
  vm.runInContext(app, ctx, { filename: 'app.js' });
  return { tela: el('tela').innerHTML, sankey: el('sankey-area').innerHTML, contratos: el('lista-contratos').innerHTML,
    fichas: el('lista-fichas').innerHTML, caminho: el('caminho').innerHTML, erros };
}

const saida = {};
for (const r of recortes.length ? recortes : ['']) {
  const [c, s, extra] = r.split('|');
  const p = new URLSearchParams(extra || '');
  if (c) p.set('c', c);
  if (s) p.set('s', s);
  saida[r] = rodar('?' + p.toString());
}
process.stdout.write(JSON.stringify(saida));
