/* Onisciente: as telas. Desenha cada tela a partir dos dados embutidos na página.
   Toda conta que depende do recorte (período e secretaria) está nas funções puras de L, que os testes
   rodam no Node; o resto é desenho. Nenhum número é desenhado sem a chave da sua fonte. */
(function () {
  'use strict';

  // ===========================================================================================
  // L: lógica pura (sem página). Exportada para os testes.
  // ===========================================================================================
  var L = {};
  var MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro',
    'outubro', 'novembro', 'dezembro'];
  var CURTOS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  var NF2 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  var NF1 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  var NF0 = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });

  L.brl = function (v) { return 'R$ ' + NF2.format(v); };
  L.brlCurto = function (v) {
    var a = Math.abs(v);
    if (a >= 1e9) return 'R$ ' + NF1.format(v / 1e9) + ' bi';
    if (a >= 1e6) return 'R$ ' + NF1.format(v / 1e6) + ' mi';
    if (a >= 1e4) return 'R$ ' + NF0.format(v / 1e3) + ' mil';
    return L.brl(v);
  };
  L.pct = function (v) { return NF2.format(v) + '%'; };
  L.int = function (v) { return NF0.format(v); };
  L.mes = function (c) { if (!c) return ''; var p = c.split('-'); return MESES[+p[1] - 1] + ' de ' + p[0]; };
  L.mesCurto = function (c) { var p = c.split('-'); return CURTOS[+p[1] - 1] + '/' + p[0].slice(2); };
  L.menos = function (c, n) {
    var p = c.split('-'), t = (+p[0]) * 12 + (+p[1] - 1) - n;
    return Math.floor(t / 12) + '-' + ('0' + (t % 12 + 1)).slice(-2);
  };
  L.data = function (iso) { if (!iso) return ''; var p = iso.slice(0, 10).split('-'); return p[2] + '/' + p[1] + '/' + p[0]; };

  // --- fichas e recortes ---------------------------------------------------------------------
  function g(fi, curto, longo) { return fi[curto] !== undefined ? fi[curto] : fi[longo]; }
  L.periodoDa = function (fi) {
    var cs = fi.cs;
    if (cs && cs.length) return [cs[0], cs[cs.length - 1]];
    return [fi.de || '0000-00', fi.ate || fi.de || '9999-99'];
  };
  L.ativa = function (fi, c) {
    if (fi.cs && fi.cs.length) return fi.cs.indexOf(c) >= 0;
    var p = L.periodoDa(fi);
    return p[0] <= c && c <= p[1];
  };
  L.noPeriodo = function (fi, de, ate) { var p = L.periodoDa(fi); return p[0] <= ate && p[1] >= de; };
  L.daSecretaria = function (fi, s) { return !s || (g(fi, 's', 'secretarias') || []).indexOf(s) >= 0; };
  L.filtrar = function (lista, f) {
    f = f || {};
    var texto = (f.texto || '').toLowerCase();
    return lista.filter(function (fi) {
      if (!L.daSecretaria(fi, f.s)) return false;
      if (f.de || f.ate) { if (!L.noPeriodo(fi, f.de || '0000-00', f.ate || '9999-99')) return false; }
      else if (f.c && !L.ativa(fi, f.c)) return false;
      if (f.familias && f.familias.length && f.familias.indexOf(g(fi, 'f', 'familia')) < 0) return false;
      if (f.gravidades && f.gravidades.length && f.gravidades.indexOf(g(fi, 'g', 'gravidade')) < 0) return false;
      if (f.temas && f.temas.length && f.temas.indexOf(g(fi, 't', 'tema')) < 0) return false;
      if (f.etapas && f.etapas.length && f.etapas.indexOf(L.etapa(fi)) < 0) return false;
      if (f.condicoes && f.condicoes.length && f.condicoes.indexOf(L.condicao(fi)) < 0) return false;
      if (f.estacao && f.estacoesDaFamilia) {
        var est = f.estacoesDaFamilia[g(fi, 'f', 'familia')] || [];
        if (est.indexOf(+f.estacao) < 0) return false;
      }
      if (texto) {
        var alvo = [fi.codigo || fi.k, fi.titulo, fi.como_esta, fi.norma].join(' ').toLowerCase();
        if (alvo.indexOf(texto) < 0) return false;
      }
      return true;
    });
  };
  // A condição de cada ficha (alerta ou sem dado) e a etapa do gasto público em que ela cai.
  L.condicao = function (fi) { return g(fi, 'cd', 'condicao') || 'alerta'; };
  L.etapa = function (fi) { return g(fi, 'e', 'etapa') || ''; };
  L.contar = function (indice, c, s) {
    var out = {};
    L.filtrar(indice, { c: c, s: s }).forEach(function (fi) {
      var t = out[fi.t] || (out[fi.t] = { n: 0, critica: 0, alta: 0, media: 0, alerta: 0, sem_dado: 0 });
      t.n++; t[fi.g] = (t[fi.g] || 0) + 1; t[L.condicao(fi)]++;
    });
    return out;
  };
  // Cada etapa com as três condições: conforme (estação da etapa com documento publicado no mês e tema da
  // etapa sem ficha no recorte), alerta (ficha de indício, com a gravidade) e sem dado (ficha de ausência).
  L.contarEtapas = function (indice, c, s, etapas, comDocumento) {
    var cont = L.contar(indice, c, s), doc = (comDocumento || {})[c] || [], out = {};
    (etapas || []).forEach(function (e) {
      var x = { conforme: 0, alerta: 0, sem_dado: 0, critica: 0, alta: 0, media: 0, n: 0 };
      e.estacoes.forEach(function (n) { if (doc.indexOf(n) >= 0) x.conforme++; });
      e.temas.forEach(function (t) {
        var y = cont[t];
        if (!y) { x.conforme++; return; }
        x.alerta += y.alerta; x.sem_dado += y.sem_dado; x.n += y.n;
        x.critica += y.critica || 0; x.alta += y.alta || 0; x.media += y.media || 0;
      });
      out[e.id] = x;
    });
    return out;
  };
  L.contarPagina = function (contagem, temas, pagina) {
    var r = { n: 0, critica: 0 };
    Object.keys(contagem).forEach(function (t) {
      if (pagina === 'index' || (temas[t] && temas[t].pagina === pagina)) {
        r.n += contagem[t].n; r.critica += contagem[t].critica || 0;
      }
    });
    return r;
  };

  // --- origem do dinheiro: receita por espécie, fonte e empenho por função ---------------------
  L.mesesDoAno = function (meses, c) {
    return Object.keys(meses).filter(function (m) { return m.slice(0, 4) === c.slice(0, 4) && m <= c; }).sort();
  };
  var CLASSES = { vinculada: 'Vinculada', livre: 'Livre', sem_catalogo: 'Sem catálogo' };
  L.somarRio = function (dados, c, modo, funcao, nomesFuncao) {
    modo = modo || 'todo';
    var ms = L.mesesDoAno(dados.meses, c), ai = {}, bf = {};
    ms.forEach(function (m) {
      dados.meses[m].a.forEach(function (x) {
        if (modo !== 'todo' && x[1] !== modo) return;
        var k = x[0] + '|' + x[1]; ai[k] = (ai[k] || 0) + x[2];
      });
      dados.meses[m].b.forEach(function (x) {
        if (modo !== 'todo' && x[0] !== modo) return;
        var k = x[0] + '|' + x[1]; bf[k] = (bf[k] || 0) + x[2];
      });
    });
    var links = [], entra = {}, sai = {}, af = {}, fz = {};
    Object.keys(ai).forEach(function (k) {
      var v = ai[k]; if (v <= 0.005) return;
      var p = k.split('|'); af[p[0]] = (af[p[0]] || 0) + v; entra[p[1]] = (entra[p[1]] || 0) + v;
      links.push({ de: 'a' + p[0], para: 'l' + p[1], v: v, cl: p[1] });
    });
    // as espécies pequenas viram "Demais receitas"
    var ordemAf = Object.keys(af).sort(function (x, y) { return af[y] - af[x]; });
    var manterAf = {}; ordemAf.slice(0, 11).forEach(function (i) { manterAf[i] = 1; });
    var fozLinks = [];
    Object.keys(bf).forEach(function (k) {
      var v = bf[k]; if (v <= 0.005) return;
      var p = k.split('|'); sai[p[0]] = (sai[p[0]] || 0) + v;
      var destino = (!funcao || p[1] === funcao) ? p[1] : 'demais';
      fz[destino] = (fz[destino] || 0) + v;
      fozLinks.push({ de: 'l' + p[0], para: 'f' + destino, v: v, cl: p[0] });
    });
    var ordemFz = Object.keys(fz).filter(function (f) { return f !== 'demais'; }).sort(function (x, y) { return fz[y] - fz[x]; });
    var manterFz = {}; ordemFz.slice(0, funcao ? 1 : 11).forEach(function (f) { manterFz[f] = 1; });
    function junta(lista) {
      var m = {};
      lista.forEach(function (l) { var k = l.de + '>' + l.para + '>' + l.cl; if (m[k]) m[k].v += l.v; else m[k] = { de: l.de, para: l.para, v: l.v, cl: l.cl }; });
      return Object.keys(m).map(function (k) { return m[k]; });
    }
    links = links.map(function (l) { var i = l.de.slice(1); return manterAf[i] ? l : { de: 'aoutras', para: l.para, v: l.v, cl: l.cl }; });
    fozLinks = fozLinks.map(function (l) { var f = l.para.slice(1); return (manterFz[f] || f === 'demais') ? l : { de: l.de, para: 'fdemais', v: l.v, cl: l.cl }; });
    links = junta(links).concat(junta(fozLinks));
    Object.keys(CLASSES).forEach(function (cl) {
      var dif = (entra[cl] || 0) - (sai[cl] || 0);
      if (dif > 0.005 && entra[cl]) links.push({ de: 'l' + cl, para: 'fparada', v: dif, cl: 'parada' });
      else if (dif < -0.005) links.push({ de: 'aanteriores', para: 'l' + cl, v: -dif, cl: cl });
    });
    var nos = {};
    function no(id, col, nome) { if (!nos[id]) nos[id] = { id: id, col: col, nome: nome, entra: 0, sai: 0 }; return nos[id]; }
    links.forEach(function (l) {
      var a = no(l.de, l.de[0] === 'a' ? 0 : 1, ''), b = no(l.para, l.para[0] === 'l' ? 1 : 2, '');
      a.sai += l.v; b.entra += l.v;
    });
    Object.keys(nos).forEach(function (id) {
      var n = nos[id], r = id.slice(1);
      n.v = Math.max(n.entra, n.sai);
      if (id[0] === 'a') n.nome = r === 'outras' ? 'Demais receitas' : r === 'anteriores' ? 'Saldo de anos anteriores e ajustes' : dados.especies[+r].nome;
      if (id[0] === 'a' && dados.especies[+r]) n.esfera = dados.especies[+r].esfera;
      if (id[0] === 'l') n.nome = CLASSES[r] || r;
      if (id[0] === 'f') n.nome = r === 'parada' ? 'Arrecadado e não empenhado' : r === 'demais' ? 'Demais funções' : ((nomesFuncao && nomesFuncao[r]) || 'Função ' + r);
      n.especial = (r === 'parada' || r === 'demais' || r === 'outras' || r === 'anteriores');
    });
    var total = 0; links.forEach(function (l) { if (l.de[0] === 'a') total += l.v; });
    return { nos: nos, links: links, meses: ms, total: total, entra: entra, sai: sai };
  };
  L.layoutSankey = function (grafo, W, H) {
    var cols = [[], [], []], pad = 10, nw = 14;
    Object.keys(grafo.nos).forEach(function (id) { cols[grafo.nos[id].col].push(grafo.nos[id]); });
    cols.forEach(function (c) { c.sort(function (a, b) { return (a.especial - b.especial) || (b.v - a.v); }); });
    var k = Infinity;
    cols.forEach(function (c) {
      if (!c.length) return;
      var s = c.reduce(function (t, n) { return t + n.v; }, 0);
      k = Math.min(k, (H - pad * (c.length - 1)) / (s || 1));
    });
    if (!isFinite(k)) k = 0;
    var xs = [210, W / 2 - nw / 2, W - 250];
    cols.forEach(function (c, i) {
      var y = 0;
      c.forEach(function (n) { n.x = xs[i]; n.y = y; n.h = Math.max(1, n.v * k); n.w = nw; y += n.h + pad; n.oe = 0; n.os = 0; });
    });
    var ls = grafo.links.slice().sort(function (a, b) {
      return (grafo.nos[a.para].y - grafo.nos[b.para].y) || (grafo.nos[a.de].y - grafo.nos[b.de].y);
    });
    ls.forEach(function (l) {
      var a = grafo.nos[l.de], b = grafo.nos[l.para], w = Math.max(1, l.v * k);
      l.w = w; l.y0 = a.y + a.os + w / 2; a.os += w;
    });
    ls.sort(function (a, b) { return grafo.nos[a.de].y - grafo.nos[b.de].y; });
    ls.forEach(function (l) { var b = grafo.nos[l.para]; l.y1 = b.y + b.oe + l.w / 2; b.oe += l.w; });
    var alto = 0; cols.forEach(function (c) { c.forEach(function (n) { alto = Math.max(alto, n.y + n.h); }); });
    return { cols: cols, links: ls, k: k, alto: alto };
  };

  // --- séries -------------------------------------------------------------------------------
  // Busca por hash: o começo (4 caracteres hexadecimais ou mais) do hash de um achado, das provas dele, da
  // resposta de uma fonte (sha256) ou do registro da coleta (rastreio). Sem rede: só o que as telas levam.
  L.hexDe = function (t) { return String(t === undefined || t === null ? '' : t).toLowerCase().replace(/[^0-9a-f]/g, ''); };
  L.buscarHash = function (q, fichas, hashes, limite) {
    var p = L.hexDe(q), out = [], vistos = {};
    if (p.length < 4) return out;
    function poe(x) { var k = x.t + '|' + x.h + '|' + (x.ficha || x.k); if (!vistos[k]) { vistos[k] = 1; out.push(x); } }
    (fichas || []).forEach(function (fi) {
      var r = fi.rastreio || {};
      var itens = [['achado', r.achado], ['apoio', r.apoio]].concat((r.provas || []).map(function (h) { return ['prova', h]; }));
      itens.forEach(function (x) {
        if (!x[1] || x[1].indexOf(p) !== 0) return;
        if (x[0] === 'prova' && x[1] === r.apoio) return;
        var per = L.periodoDa(fi);
        poe({ h: x[1], t: x[0], ficha: fi.codigo, r: fi.titulo, de: per[0], ate: per[1] });
      });
    });
    (hashes || []).forEach(function (e) {
      if (e.h && e.h.indexOf(p) === 0) poe({ h: e.h, t: e.t, k: e.k, r: e.r, p: e.p, u: e.u, v: e.v });
    });
    return out.slice(0, limite || 20);
  };
  L.janela = function (c, n) { return [L.menos(c, n - 1), c]; };
  L.somaPorMes = function (mapa, de, ate) {
    var n = 0, v = 0;
    Object.keys(mapa || {}).forEach(function (m) { if (m >= de && m <= ate) { n += mapa[m][0]; v += mapa[m][1].v; } });
    return [n, v];
  };

  if (typeof module !== 'undefined' && module.exports) { module.exports = L; return; }

  // ===========================================================================================
  // Página: dados, recorte e componentes
  // ===========================================================================================
  function json(id) { var el = document.getElementById(id); return el ? JSON.parse(el.textContent) : null; }
  var C = json('d-comum'), D = json('d-tela'), F = json('d-fontes') || {}, IND = json('d-indice') || [];
  var PID = document.body.dataset.pagina;
  var TEMAS = C.temas || {};
  var ORDEM = C.paginas.map(function (p) { return p.id; });
  var SEC = {}; C.secretarias.forEach(function (s) { SEC[s.id] = s; });
  var depois = [];

  function esc(t) {
    return String(t === undefined || t === null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function lerStorage(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function gravarStorage(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* sem armazenamento */ } }

  // --- recorte --------------------------------------------------------------------------------
  var U = new URLSearchParams(location.search);
  var salvo = {}; try { salvo = JSON.parse(lerStorage('onisciente.recorte') || '{}'); } catch (e) { salvo = {}; }
  var S = {
    c: U.get('c') || salvo.c || C.padrao,
    s: U.has('s') ? U.get('s') : (salvo.s || '')
  };
  if (C.competencias.indexOf(S.c) < 0) S.c = C.padrao;
  if (S.s && !SEC[S.s]) S.s = '';
  function funcaoDoRecorte() { return S.s && SEC[S.s] ? SEC[S.s].funcao : null; }
  function qs(extra) {
    var p = new URLSearchParams();
    p.set('c', S.c); if (S.s) p.set('s', S.s);
    Object.keys(extra || {}).forEach(function (k) { if (extra[k] !== null && extra[k] !== undefined && extra[k] !== '') p.set(k, extra[k]); });
    return '?' + p.toString();
  }
  function link(pagina, extra, ancora) { return pagina + '.html' + qs(extra) + (ancora ? '#' + ancora : ''); }

  // --- números com origem ---------------------------------------------------------------------
  function fmt(v, modo) {
    if (modo === 'pct') return L.pct(v);
    if (modo === 'int') return L.int(v);
    if (modo === 'brl') return L.brl(v);
    if (modo === 'dias') return L.int(v) + (Math.round(v) === 1 ? ' dia' : ' dias');
    if (modo === 'pp') return NF2.format(v) + ' p.p.';
    if (modo === 'dec') return NF1.format(v);
    return L.brlCurto(v);
  }
  function num(n, modo, extraClasse) {
    if (!n || n.v === null || n.v === undefined) return '<span class="nd">sem dado</span>';
    var f = F[n.f] || {};
    return '<span class="n' + (f.u ? '' : ' sem') + (extraClasse ? ' ' + extraClasse : '') + '" tabindex="0" role="button" data-f="' +
      esc(n.f) + '" data-v="' + n.v + '"' + (n.s ? ' data-s="' + n.s + '"' : '') + ' data-m="' + (modo || 'curto') + '">' +
      fmt(n.v, modo) + '</span>';
  }
  function origem(chave, texto) {
    if (!chave) return '';
    var f = F[chave] || {};
    return '<span class="n' + (f.u ? '' : ' sem') + '" tabindex="0" role="button" data-f="' + esc(chave) + '">' +
      esc(texto || f.r || 'origem') + '</span>';
  }
  // Os ícones moram uma vez em cada página (símbolos SVG); aqui só se usam. As três condições têm sempre o
  // mesmo ícone: conforme (círculo com visto), alerta (triângulo com exclamação) e sem dado (quadrado tracejado
  // com interrogação). A cor diz o resto: a gravidade do alerta e, no sem dado, roxo quando falta documento do
  // Município e cinza quando a leitura é do próprio sistema.
  function ic(nome, classe) {
    return '<svg class="ic' + (classe ? ' ' + classe : '') + '" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="#i-' + nome + '"/></svg>';
  }
  var COND = { conforme: ['conforme', 'conforme'], alerta: ['alerta', 'alerta'], sem_dado: ['semdado', 'sem dado'] };
  function icCond(cd, classe) { return ic((COND[cd] || COND.alerta)[0], 'cond ' + cd + (classe ? ' ' + classe : '')); }
  // O hash: 12 caracteres na tela, o completo no title e um botão que copia o completo. O ícone próprio
  // (cerquilha no hexágono) marca o que é verificado por hash; verde quando confere com o selo do rastreio.
  function hashCurto(h, rotulo, copiavel) {
    if (!h) return '';
    return '<code class="hash" title="' + esc(rotulo + ': ' + h) + '">' + esc(h.slice(0, 12)) + '</code>' +
      (copiavel === false ? '' : '<button type="button" class="copiar" data-copiar="' + esc(h) + '" aria-label="Copiar por inteiro: ' + esc(rotulo) + '">copiar</button>');
  }
  function icHash(estado) { return ic('hash', 'hash' + (estado ? ' ' + estado : '')); }
  var SELOS = {
    verde: ['verde', 'duas vias', 'conforme'], azul: ['azul', 'uma via', 'conforme'], roxo: ['roxo', 'não publicado', 'sem_dado'],
    vermelho: ['vermelho', 'leitura falhou', 'sem_dado'], cinza: ['cinza', 'aguardando coleta', 'sem_dado'],
    alerta: ['alerta', 'alerta', 'alerta'], indicio: ['indicio', 'indício', 'alerta'], critica: ['critica', 'indício crítico', 'alerta'],
    ok: ['verde', 'conforme', 'conforme']
  };
  function selo(s, texto) {
    var x = SELOS[s] || SELOS.azul;
    return '<span class="selo ' + x[0] + '">' + ic(COND[x[2]][0]) + esc(texto || x[1]) + '</span>';
  }
  function seloVias(o) { return o.divergencia ? selo('indicio', 'as vias divergem') : selo(o.selo, o.selo === 'verde' ? 'duas vias batem' : null); }
  var GRAV = { critica: 'crítica', alta: 'alta', media: 'média' };
  function grav(gv) { return '<span class="grav ' + esc(gv) + '">' + (GRAV[gv] || esc(gv)) + '</span>'; }
  function vazio(titulo, texto, roxo) {
    return '<div class="vazio' + (roxo ? ' roxo' : '') + '">' + ic('semdado', 'grande') +
      '<div><h3>' + esc(titulo) + '</h3><p>' + esc(texto) + '</p></div></div>';
  }
  function painel(id, titulo, sub, corpo, opts) {
    opts = opts || {};
    return '<section class="painel' + (opts.lamina === false ? '' : ' lamina') + (opts.classe ? ' ' + opts.classe : '') + '"' +
      (id ? ' id="' + id + '"' : '') + ' aria-labelledby="t-' + (id || titulo.length) + '"><header><div>' +
      (opts.eyebrow ? '<p class="eyebrow">' + esc(opts.eyebrow) + '</p>' : '') +
      '<h2 id="t-' + (id || titulo.length) + '">' + esc(titulo) + '</h2>' + (sub ? '<p class="sub">' + sub + '</p>' : '') +
      '</div>' + (opts.direita || '') + '</header>' + corpo + '</section>';
  }
  function kpi(rot, valor, det, classe) {
    return '<div class="kpi ' + (classe || '') + '"><span class="rot">' + esc(rot) + '</span><span class="val">' + valor +
      '</span>' + (det ? '<span class="det">' + det + '</span>' : '') + '</div>';
  }
  function nomeSec(id) { return SEC[id] ? SEC[id].nome : id; }
  // A coleta do próprio sistema que ainda não trouxe nada: quadro cinza, nunca roxo, porque a falha é do sistema.
  function coleta(nome) { var c = (C.coletas || {})[nome]; return c && c.situacao === 'coleta_nao_feita' ? c : null; }
  function naoFeita(c, titulo, texto) {
    return vazio('Coleta ainda não feita: ' + titulo, (c.motivo ? 'Motivo: ' + c.motivo + '. ' : '') +
      'É uma falha do próprio sistema, não do Município. ' + texto, false);
  }
  function nomeFuncao(f) { return (C.funcoes && C.funcoes[f]) || ('Função ' + f); }

  // --- a dica (balão da origem) ---------------------------------------------------------------
  var dica = document.getElementById('dica'), fixa = null, timer = null;
  var toque = window.matchMedia && window.matchMedia('(hover: none)').matches;
  function mostrar(el, fixar) {
    var f = F[el.dataset.f] || { r: 'Fonte não registrada', n: 'o original deste número não está guardado no banco' };
    var v = el.dataset.v !== undefined ? +el.dataset.v : null;
    var s = el.dataset.s || f.s;
    var html = '<b>' + esc(f.r) + '</b>';
    if (v !== null && !isNaN(v) && (!el.dataset.m || el.dataset.m === 'curto' || el.dataset.m === 'brl')) html += '<div class="mono">' + L.brl(v) + '</div>';
    html += '<div>' + selo(s) + (f.q ? ' lido em ' + L.data(f.q) : '') + '</div>';
    if (f.h) html += '<div class="h">' + icHash() + 'hash da resposta (sha256) ' + hashCurto(f.h, 'hash da resposta (sha256)', !!fixar) + '</div>';
    if (f.hr) html += '<div class="h">' + icHash(f.hv ? 'ok' : '') + 'hash do registro ' + hashCurto(f.hr, 'hash do registro da coleta', !!fixar) +
      (f.hv ? ' <span class="confere">confere com o selo da rodada</span>' : '') + '</div>';
    if (f.n) html += '<div class="' + (f.u ? '' : 'falta') + '">' + esc(f.n) + '</div>';
    if (f.u) html += '<div class="acao"><a href="' + esc(f.u) + '" target="_blank" rel="noopener">Abrir o original' + (f.c ? ' guardado' : '') + '</a>' +
      (fixar ? '<button type="button" data-fechar>Fechar</button>' : '') + '</div>';
    else if (fixar) html += '<div class="acao"><button type="button" data-fechar>Fechar</button></div>';
    dica.innerHTML = html; dica.hidden = false;
    var r = el.getBoundingClientRect(), d = dica.getBoundingClientRect();
    var x = Math.min(Math.max(8, r.left), window.innerWidth - d.width - 8);
    var y = r.bottom + 8; if (y + d.height > window.innerHeight - 8) y = Math.max(8, r.top - d.height - 8);
    dica.style.left = x + 'px'; dica.style.top = y + 'px';
    fixa = fixar ? el : null;
  }
  function esconder() { if (!fixa) dica.hidden = true; }
  document.addEventListener('mouseover', function (e) {
    var el = e.target.closest && e.target.closest('[data-f]');
    if (el && !toque) { clearTimeout(timer); if (!fixa) mostrar(el, false); }
  });
  document.addEventListener('mouseout', function (e) {
    var el = e.target.closest && e.target.closest('[data-f]');
    if (el && !toque) { timer = setTimeout(esconder, 220); }
  });
  dica.addEventListener('mouseenter', function () { clearTimeout(timer); });
  dica.addEventListener('mouseleave', function () { timer = setTimeout(esconder, 220); });
  document.addEventListener('focusin', function (e) { var el = e.target.closest && e.target.closest('[data-f]'); if (el) mostrar(el, false); });
  document.addEventListener('focusout', function (e) { if (e.target.closest && e.target.closest('[data-f]')) timer = setTimeout(esconder, 220); });
  function ativar(el) {
    var f = F[el.dataset.f] || {};
    if (toque || !f.u) { mostrar(el, true); return; }
    window.open(f.u, '_blank', 'noopener');
  }
  function copiar(bt) {
    var t = bt.dataset.copiar;
    function feito() { bt.textContent = 'copiado'; setTimeout(function () { bt.textContent = 'copiar'; }, 1600); }
    function manual() {
      var ta = document.createElement('textarea'); ta.value = t; ta.setAttribute('readonly', '');
      ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select();
      try { if (document.execCommand('copy')) feito(); else window.prompt('Copie o hash:', t); } catch (e) { window.prompt('Copie o hash:', t); }
      document.body.removeChild(ta);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t).then(feito, manual);
    else manual();
  }
  document.addEventListener('click', function (e) {
    var cp = e.target.closest && e.target.closest('[data-copiar]');
    if (cp) { e.preventDefault(); e.stopPropagation(); copiar(cp); return; }
    if (e.target.closest('[data-fechar]')) { fixa = null; dica.hidden = true; return; }
    var el = e.target.closest('[data-f]');
    if (el) { e.preventDefault(); e.stopPropagation(); ativar(el); return; }
    if (fixa && !e.target.closest('#dica')) { fixa = null; dica.hidden = true; }
  });
  document.addEventListener('keydown', function (e) {
    var el = e.target.closest && e.target.closest('[data-f]');
    if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); ativar(el); }
  });

  // ===========================================================================================
  // Componentes de desenho
  // ===========================================================================================
  function ficha(fi) {
    var secs = (fi.secretarias || []).map(nomeSec).join(', ') || 'Município inteiro';
    var per = L.periodoDa(fi), periodo = per[0] === per[1] ? L.mes(per[0]) : L.mes(per[0]) + ' a ' + L.mes(per[1]);
    var cust = (fi.custodia || []).filter(function (o) { return o.url; }).map(function (o) {
      return '<li><a href="' + esc(o.url) + '" target="_blank" rel="noopener">' + esc(o.url) + '</a>' +
        (o.quando ? ', lido em ' + L.data(o.quando) : '') + (o.sha256 ? ' · resposta ' + hashCurto(o.sha256, 'hash da resposta (sha256)') : '') +
        (o.registro ? ' · registro ' + hashCurto(o.registro, 'hash do registro') : '') + '</li>';
    }).join('');
    var ra = fi.rastreio || {};
    var rastro = ra.achado ? '<div class="larga rastreio"><h4>' + icHash() + 'Rastreio</h4><p>Hash do achado ' + hashCurto(ra.achado, 'hash do achado') +
      (ra.apoio ? ' · hash das provas ' + hashCurto(ra.apoio, (ra.provas || []).length > 1 ? 'raiz de Merkle das provas' : 'hash da prova') +
        ((ra.provas || []).length > 1 ? ' <span class="nota">(raiz de ' + ra.provas.length + ' provas)</span>' : '')
        : ' · <span class="nota">sem prova guardada: a falta do documento é o próprio achado</span>') +
      '</p><p class="nota">Calculado sobre a ficha publicada no panorama do mês, como no parecer: qualquer mudança no texto da ficha muda o hash. A busca por hash fica na tela de indícios.</p></div>' : '';
    var corpo = [
      ['Como deveria ser', fi.como_deveria], ['Como está', fi.como_esta], ['Norma', fi.norma],
      ['Providência', fi.providencia], ['Caso semelhante', fi.caso], ['Observação', fi.observacao]
    ].filter(function (x) { return x[1]; }).map(function (x, i) {
      return '<div class="' + (i === 1 ? 'larga' : '') + '"><h4>' + x[0] + '</h4><p>' + esc(x[1]) + '</p></div>';
    }).join('');
    var prova = fi.fonte ? '<div class="larga custodia"><h4>Prova</h4>' + origem(fi.fonte) + '</div>' :
      cust ? '<div class="larga custodia"><h4>Prova guardada</h4><ul>' + cust + '</ul></div>' :
        '<div class="larga custodia"><h4>Prova</h4><p>' + selo('roxo', 'documento não publicado') + ' A ficha nasce da ausência do documento que a lei manda publicar.</p></div>';
    var cd = L.condicao(fi);
    var hs = ra.achado ? '<span class="hash-curto" title="' + esc('hash do achado: ' + ra.achado) + '">' + icHash() + esc(ra.achado.slice(0, 12)) + '</span>' : '';
    return '<details class="ficha ' + esc(fi.gravidade) + ' ' + cd + '" id="ficha-' + esc(fi.codigo).replace(/[^A-Za-z0-9_-]/g, '_') + '" data-codigo="' + esc(fi.codigo) + '">' +
      '<summary>' + icCond(cd, fi.tema === 'sistema' ? 'sistema' : fi.gravidade) + '<h3>' + esc(fi.titulo) + '</h3>' + (cd === 'sem_dado' ? '<span class="grav semdado">sem dado</span>' : grav(fi.gravidade)) +
      '<p class="meta"><span class="cod">' + esc(fi.codigo) + '</span><span>' + esc(fi.verificacao || '') + '</span><span>' +
      esc(secs) + '</span><span>' + esc(periodo) + '</span>' + hs + '</p></summary><div class="corpo">' + corpo + prova + rastro + '</div></details>';
  }
  function blocoFichas(lista, titulo, sub, id) {
    var f = L.filtrar(lista || [], { c: S.c, s: S.s });
    var ord = { critica: 0, alta: 1, media: 2 };
    f.sort(function (a, b) { return (ord[a.gravidade] - ord[b.gravidade]) || (a.codigo < b.codigo ? -1 : 1); });
    var corpo = f.length ? '<div class="fichas">' + f.slice(0, 40).map(ficha).join('') + '</div>' +
      (f.length > 40 ? '<p class="nota">Mostrando 40 de ' + f.length + '. <a href="' + link('indicios') + '">Ver todas em Indícios</a>.</p>' : '')
      : '<p class="sub">' + selo('ok', 'nenhum indício') + ' Nenhuma ficha deste tema no recorte escolhido.</p>';
    return painel(id || 'fichas', titulo || 'As fichas desta tela', sub || (f.length + ' ficha(s) no recorte, como no Cadê o Queijo: como deveria ser, como está, a norma e a prova.'), corpo, { lamina: false });
  }

  // gráfico de séries genérico (barras e linhas), com a origem em cada ponto
  function grafico(o) {
    var W = o.largura || 760, H = o.altura || 260, m = { e: 64, d: 14, t: 14, b: 34 };
    var n = o.x.length, iw = W - m.e - m.d, ih = H - m.t - m.b;
    var max = o.max || 0;
    o.series.forEach(function (s) { s.vals.forEach(function (v) { if (v && v.v > max) max = v.v; }); });
    (o.linhas || []).forEach(function (l) { if (l.v > max) max = l.v; });
    max = max * 1.08 || 1;
    var mn = o.min || 0;
    function y(v) { return m.t + ih - (v - mn) / (max - mn) * ih; }
    var bw = iw / Math.max(n, 1), barras = o.series.filter(function (s) { return s.tipo !== 'linha'; });
    var out = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(o.titulo || '') + '">';
    for (var i = 0; i <= 4; i++) {
      var v = mn + (max - mn) * i / 4, yy = y(v);
      out += '<line class="eixo" x1="' + m.e + '" x2="' + (W - m.d) + '" y1="' + yy + '" y2="' + yy + '"/>' +
        '<text x="' + (m.e - 6) + '" y="' + (yy + 4) + '" text-anchor="end">' + (o.fmt === 'pct' ? NF1.format(v) + '%' : L.brlCurto(v).replace('R$ ', '')) + '</text>';
    }
    o.x.forEach(function (rot, i) {
      if (n > 14 && i % Math.ceil(n / 12)) return;
      out += '<text x="' + (m.e + bw * i + bw / 2) + '" y="' + (H - 12) + '" text-anchor="middle">' + esc(rot) + '</text>';
    });
    if (o.agora !== undefined && o.agora >= 0) {
      var xa = m.e + bw * o.agora + bw / 2;
      out += '<line class="agora" x1="' + xa + '" x2="' + xa + '" y1="' + m.t + '" y2="' + (m.t + ih) + '"/>';
    }
    barras.forEach(function (s, j) {
      var w = (bw * 0.76) / barras.length;
      s.vals.forEach(function (v, i) {
        if (!v) return;
        var x = m.e + bw * i + bw * 0.12 + w * j, yy = y(Math.max(v.v, mn));
        out += '<rect class="' + s.cl + ' n" data-f="' + esc(v.f) + '" data-v="' + v.v + '" data-m="' + (o.fmt || 'curto') + '" tabindex="0" x="' + x.toFixed(1) +
          '" y="' + yy.toFixed(1) + '" width="' + Math.max(1, w - 2).toFixed(1) + '" height="' + Math.max(0, y(mn) - yy).toFixed(1) + '"><title>' +
          esc(s.nome + ', ' + o.x[i] + ': ' + fmt(v.v, o.fmt)) + '</title></rect>';
      });
    });
    o.series.filter(function (s) { return s.tipo === 'linha'; }).forEach(function (s) {
      var pts = [];
      s.vals.forEach(function (v, i) { if (v) pts.push([m.e + bw * i + bw / 2, y(v.v), v]); });
      if (pts.length > 1) out += '<polyline class="' + s.cl + '" points="' + pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ') + '"/>';
      pts.forEach(function (p) {
        out += '<circle class="n" r="5" cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" data-f="' + esc(p[2].f) + '" data-v="' + p[2].v + '" data-m="' + (o.fmt || 'curto') +
          '" tabindex="0" style="fill:var(--surface);stroke:currentColor;stroke-width:2.5" color="' + (s.cor || 'var(--royal)') + '"><title>' + esc(s.nome + ': ' + fmt(p[2].v, o.fmt)) + '</title></circle>';
      });
    });
    (o.linhas || []).forEach(function (l) {
      out += '<line class="' + l.cl + '" x1="' + m.e + '" x2="' + (W - m.d) + '" y1="' + y(l.v) + '" y2="' + y(l.v) + '"/>' +
        '<text x="' + (W - m.d - 4) + '" y="' + (y(l.v) - 5) + '" text-anchor="end" style="fill:var(--ink-2)">' + esc(l.rot) + '</text>';
    });
    out += '</svg>';
    var leg = '<p class="legenda">' + o.series.map(function (s) {
      return '<span><i style="background:' + (s.cor || 'var(--royal)') + '"></i>' + esc(s.nome) + '</span>';
    }).join('') + (o.linhas || []).map(function (l) { return '<span>' + esc(l.rot) + '</span>'; }).join(' · ') + '</p>';
    return '<div class="serie rola">' + out + '</div>' + leg;
  }

  // ===========================================================================================
  // As telas
  // ===========================================================================================
  var T = {};

  // --- Início -------------------------------------------------------------------------------
  T.index = function () {
    var ini = D.inicio.por_c[S.c] || {};
    var cont = L.contar(IND, S.c, S.s), tot = { critica: 0, alta: 0, media: 0, n: 0 };
    Object.keys(cont).forEach(function (t) { tot.n += cont[t].n; ['critica', 'alta', 'media'].forEach(function (g2) { tot[g2] += cont[t][g2] || 0; }); });
    var frase = (!S.s || (SEC[S.s] && SEC[S.s].pasta)) && ini.frase ? ini.frase :
      'Em ' + L.mes(S.c) + (S.s ? ', em ' + nomeSec(S.s) : ', no Município inteiro') + ', o Onisciente tem ' + tot.n +
      ' indício(s) abertos, ' + tot.critica + ' de gravidade crítica.';
    var placar = ['critica', 'alta', 'media'].map(function (g2) {
      return '<a class="' + g2 + '" href="' + link('indicios', { g: g2 }) + '"><b>' + tot[g2] + '</b><span>' + GRAV[g2] + '</span></a>';
    }).join('');
    var h = '<section class="painel frase lamina" aria-label="Em uma frase"><div><p class="eyebrow">Em uma frase · ' + esc(L.mes(S.c)) +
      (ini.dominio && (!S.s || SEC[S.s].pasta) ? ' · ' + esc(ini.dominio) : '') + '</p><blockquote>' + esc(frase) + '</blockquote>' +
      (ini.parecer ? '<p class="sub" style="margin-top:8px"><a href="' + ini.parecer + '">Abrir o parecer de ' + esc(L.mes(S.c)) + '</a></p>' : '') +
      '</div><div><div class="placar" aria-label="Indícios por gravidade">' + placar + '</div><p class="nota" style="margin-top:6px;text-align:center">fichas abertas: ' + esc(S.s ? nomeSec(S.s) : 'Município inteiro') + '</p></div></section>';
    h += painel('etapas', 'As etapas do gasto público', 'Cada etapa mostra, no recorte, o que está conforme, o que tem alerta e o que está sem dado. O clique abre a lista das desconformidades daquela etapa, e cada ficha da lista abre com a prova.', etapas(), { eyebrow: 'Por onde o dinheiro passa' });
    h += '<section class="grade gk lamina painel" aria-label="Os números do recorte"><h2 class="sr">Os números do recorte</h2>' +
      kpi('Arrecadado no ano', num(ini.receita), 'janeiro a ' + esc(L.mes(S.c)) + ', Município inteiro') +
      kpi('Empenhado no ano', num(ini.empenhado), 'exceto intraorçamentário') +
      kpi('Vinculado fora da finalidade', num(ini.fora_do_leito), 'recurso vinculado empenhado fora da finalidade da lei', ini.fora_do_leito && ini.fora_do_leito.v ? 'critico' : 'bom') +
      kpi('Contratos em 12 meses', ini.contratos ? L.int(ini.contratos[0]) + ' · ' + num(ini.contratos[1]) : '<span class="nd">sem dado</span>', 'publicados no PNCP pelo Município') +
      (ini.integridade ? kpi('Integridade da trilha', num(ini.integridade, 'dec') + '<small> de 100</small>', 'na pasta fiscalizada; com o que foi medido, o máximo possível é ' + NF1.format(ini.integridade_max || 0), 'ruim') : '') +
      '</section>';
    if (!S.s) h += painel('por-secretaria', 'Por secretaria', 'As secretarias com mais desconformidades no recorte. O clique abre a lista de cada uma.', porSecretaria());
    h += painel('legenda', 'Como ler as condições', '', legendaCondicoes() +
      '<p class="sub" style="margin-top:12px">Ao lado de cada número, o selo diz de onde ele veio: ' +
      ['verde', 'azul', 'roxo', 'vermelho', 'cinza'].map(function (s) { return selo(s); }).join(' ') +
      '. Passe o mouse (ou toque) em qualquer número sublinhado para ver a origem; o clique abre o original.</p>' +
      '<p class="sub" style="margin-top:6px"><a href="../index.html">Pareceres mensais</a> · <a href="../banco/index.html">O banco de dados</a></p>', { lamina: false });
    return h;
  };
  // O diagrama das etapas: um cartão por etapa, na ordem do gasto, com as três condições contadas no recorte.
  function etapas() {
    var et = C.etapas || [], cont = L.contarEtapas(IND, S.c, S.s, et, D.estacoes_com_documento);
    var sis = L.filtrar(IND, { c: S.c, s: S.s, temas: ['sistema'] }).length;
    var out = '<ol class="etapas">' + et.map(function (e, i) {
      var x = cont[e.id];
      var estado = x.alerta ? (x.critica ? 'critica' : 'alerta') : x.sem_dado ? 'semdado' : 'conforme';
      var rot = 'Etapa ' + (i + 1) + ', ' + e.nome + ': ' + x.conforme + ' conforme, ' + x.alerta + ' alerta(s), ' + x.sem_dado + ' sem dado';
      return '<li><a class="etapa ' + estado + '" data-etapa="' + e.id + '" href="' + link('indicios', { etapa: e.id }) + '" aria-label="' + esc(rot) + '">' +
        '<span class="etapa-topo">' + ic(e.id, 'etapa-ic') + '<span class="etapa-n">' + (i + 1) + '</span></span>' +
        '<b class="etapa-nome">' + esc(e.nome) + '</b><span class="etapa-confere">' + esc(e.confere) + '</span>' +
        '<span class="conds">' +
        '<span class="cd conforme">' + icCond('conforme') + '<b>' + x.conforme + '</b><small>conforme</small></span>' +
        '<span class="cd alerta' + (x.critica ? ' critica' : '') + '">' + icCond('alerta', x.critica ? 'critica' : '') + '<b>' + x.alerta + '</b><small>alerta' + (x.critica ? ', ' + x.critica + ' crítico' : '') + '</small></span>' +
        '<span class="cd sem_dado">' + icCond('sem_dado') + '<b>' + x.sem_dado + '</b><small>sem dado</small></span>' +
        '</span></a></li>';
    }).join('') + '</ol>';
    out += '<p class="etapa-sistema"><a href="' + link('indicios', { tema: 'sistema' }) + '">' + icCond('sem_dado', 'sistema') +
      '<span><b>' + sis + '</b> falha(s) de leitura do próprio sistema</span></a> <span class="nota">Não são do Município: é o que o Onisciente ainda não conseguiu ler.</span></p>';
    return out;
  }
  function porSecretaria() {
    var por = {};
    L.filtrar(IND, { c: S.c }).forEach(function (fi) {
      (fi.s || []).forEach(function (s) { var x = por[s] || (por[s] = { n: 0, critica: 0, sem_dado: 0 }); x.n++; if (fi.g === 'critica') x.critica++; if (L.condicao(fi) === 'sem_dado') x.sem_dado++; });
    });
    var ids = Object.keys(por).filter(function (s) { return SEC[s]; }).sort(function (a, b) { return por[b].n - por[a].n || (nomeSec(a) < nomeSec(b) ? -1 : 1); });
    if (!ids.length) return '<p class="sub">' + selo('ok', 'nenhuma ficha por secretaria') + ' Nenhuma ficha deste mês é atribuída a uma secretaria; as do Município inteiro estão nas etapas acima.</p>';
    return '<ul class="por-sec">' + ids.slice(0, 10).map(function (s) {
      var x = por[s];
      return '<li><a href="' + link('indicios', { s: s }) + '"><span class="nome">' + esc(nomeSec(s)) + '</span><span class="q">' +
        icCond(x.n - x.sem_dado ? 'alerta' : 'sem_dado', x.critica ? 'critica' : '') + '<b>' + x.n + '</b> ficha(s)' + (x.critica ? ', ' + x.critica + ' crítica(s)' : '') + '</span></a></li>';
    }).join('') + '</ul>' + (ids.length > 10 ? '<p class="nota">As 10 primeiras de ' + ids.length + '. As demais estão em <a href="' + link('secretarias') + '">Secretarias</a>.</p>' : '');
  }
  function legendaCondicoes() {
    return '<ul class="conds-legenda">' +
      '<li>' + icCond('conforme') + '<div><b>Conforme</b><span>O documento está publicado e a conferência não achou desconformidade.</span></div></li>' +
      '<li>' + icCond('alerta', 'critica') + '<div><b>Alerta</b><span>Indício de desconformidade. A cor diz a gravidade: vermelho crítico, laranja alto, amarelo médio.</span></div></li>' +
      '<li>' + icCond('sem_dado') + '<div><b>Sem dado</b><span>O que a lei manda publicar e não está publicado, ou o que o sistema ainda não conseguiu ler (em cinza).</span></div></li></ul>';
  }
  // Uma faixa no alto de cada tela: as condições dos temas desta tela no recorte, com o atalho para a lista.
  function faixa() {
    var temas = Object.keys(TEMAS).filter(function (t) { return TEMAS[t].pagina === PID; });
    if (!temas.length) return '';
    var f = L.filtrar(IND, { c: S.c, s: S.s, temas: temas }), al = 0, sd = 0, cr = 0;
    f.forEach(function (fi) { if (L.condicao(fi) === 'sem_dado') sd++; else { al++; if (fi.g === 'critica') cr++; } });
    return '<p class="faixa-cond" aria-label="Condições desta tela no recorte">' +
      (f.length ? '' : '<span class="cd conforme">' + icCond('conforme') + 'conforme: nenhuma ficha no recorte</span>') +
      (al ? '<span class="cd alerta">' + icCond('alerta', cr ? 'critica' : '') + '<b>' + al + '</b> alerta(s)' + (cr ? ', ' + cr + ' crítico(s)' : '') + '</span>' : '') +
      (sd ? '<span class="cd sem_dado">' + icCond('sem_dado') + '<b>' + sd + '</b> sem dado</span>' : '') +
      (f.length ? '<a href="' + link('indicios', { tema: temas.join(',') }) + '">Ver na lista</a>' : '') + '</p>';
  }

  // --- Origem do dinheiro --------------------------------------------------------------------
  var modoRio = U.get('modo') || 'todo';
  T.origem = function () {
    var rc = D.por_c[S.c];
    if (!rc) return vazio('Sem matriz para este período', 'A matriz de saldos contábeis de ' + L.mes(S.c) + ' não está no banco.', false);
    var h = painel('sankey', 'Receita, fonte e empenho', 'Receita realizada de janeiro a ' + esc(L.mes(S.c)) +
      ' por espécie, separada em recurso vinculado e livre pela fonte, e o empenhado por função de governo.',
      '<div id="sankey-area"></div>', {
        eyebrow: 'Origem do dinheiro',
        direita: '<div class="modos" role="group" aria-label="Fontes mostradas">' + [['todo', 'Todas as fontes'], ['vinculada', 'Vinculada'], ['livre', 'Livre']].map(function (m) {
          return '<button type="button" data-modo="' + m[0] + '" aria-pressed="' + (modoRio === m[0]) + '">' + m[1] + '</button>';
        }).join('') + '</div>'
      });
    h += '<div class="grade g2">' + vinculo(rc.cosip, 'cosip', 'COSIP: a iluminação pública', rc.cosip.lei) +
      vinculo(rc.fnas, 'fnas', 'FNAS: o Fundo Nacional de Assistência Social', 'Lei 8.742/1993, arts. 28 a 30') + '</div>';
    h += painel('origem', 'O que a União diz que mandou e o que entrou', 'Cada transferência conferida em duas vias: o Portal da Transparência (o que saiu da União) e a matriz do Município (o que entrou na fonte).',
      '<div class="rola"><table class="t cartoes"><thead><tr><th>Transferência</th><th class="num">União</th><th class="num">Município</th><th class="num">Diferença</th><th>Selo</th></tr></thead><tbody>' +
      rc.origem.map(function (o) {
        var a = o.vias[0], b = o.vias[1];
        var dif = a && b && a.valor && b.valor ? { v: a.valor.v - b.valor.v, f: b.valor.f } : null;
        return '<tr><td data-r="Transferência"><b>' + esc(o.titulo) + '</b><br><span class="nota">' + esc(o.norma || '') + '</span></td><td class="num" data-r="União">' + (a ? num(a.valor) : '') +
          '</td><td class="num" data-r="Município">' + (b ? num(b.valor) : '') + '</td><td class="num" data-r="Diferença">' + (dif ? num(dif) : '') + '</td><td data-r="Selo">' + seloVias(o) + '</td></tr>';
      }).join('') + '</tbody></table></div>');
    var fed = D.federais, orig = D.federais_origens;
    var origens = orig ? '<p class="nota" style="margin-top:10px">' + Object.keys(orig).sort().map(function (k) {
      var o = orig[k];
      return o.situacao === 'dado' ? selo('verde', k + ': ' + L.int(o.linhas) + ' linha(s) lida(s)')
        : selo('cinza', k + ': coleta ainda não feita') + (o.motivo ? ' <span class="nota">(' + esc(o.motivo) + ')</span>' : '');
    }).join(' ') + '</p>' : '';
    if (!fed) {
      var cf = coleta('federais');
      h += painel('federais', 'Os repasses federais, programa por programa', '', (cf ? naoFeita(cf, 'transferências federais',
        'Quando a coleta do FNS, do FNDE e do Transferegov trouxer as linhas, cada repasse aparece aqui, programa por programa. A conferência por transferência, acima, já usa o Portal da Transparência.')
        : vazio('Aguardando a coleta das transferências federais',
        'Quando a frente das transferências entregar os repasses do Fundo Nacional de Saúde, do FNDE, do FNAS e do Transferegov, programa por programa, cada repasse aparece aqui ao lado do que o Município registrou na fonte de destino. A conferência por transferência, acima, já usa o Portal da Transparência.')) + origens, { lamina: false });
    } else {
      var fl = fed.filter(function (r) { return r.mes.slice(0, 4) === S.c.slice(0, 4) && r.mes <= S.c; });
      h += painel('federais', 'Os repasses federais, programa por programa', fl.length + ' repasse(s) de janeiro a ' + esc(L.mes(S.c)) + '. O valor abre a leitura do órgão que repassou.',
        origens + (fl.length ? '<div class="rola"><table class="t cartoes"><thead><tr><th>Origem e programa</th><th>Mês</th><th class="num">Repassado</th><th class="num">Registrado</th><th>Fonte de destino</th></tr></thead><tbody>' +
          fl.map(function (r) {
            var dif = r.registrado && Math.abs(r.valor.v - r.registrado.v) > 0.5;
            return '<tr><td data-r="Programa"><b>' + esc(r.origem) + '</b> ' + esc(r.programa) + '</td><td data-r="Mês">' + esc(L.mesCurto(r.mes)) + '</td><td class="num" data-r="Repassado">' + num(r.valor) +
              '</td><td class="num" data-r="Registrado">' + (r.registrado ? num(r.registrado) : selo('cinza', 'não cruzado por programa')) + (dif ? ' ' + selo('indicio', 'diverge') : '') + '</td><td data-r="Fonte">' + esc(r.fonte || '') + '</td></tr>';
          }).join('') + '</tbody></table></div>' : '<p class="sub">Nenhum repasse no período.</p>'), { lamina: false });
    }
    h += painel('desvios', 'Recurso vinculado fora da finalidade', 'Dinheiro que a lei amarra a uma finalidade e foi empenhado em função de governo que a lei não permite para ele. ' +
      'Indício, não acusação: a prova é a própria matriz contábil do Município.',
      rc.desvios.length ? '<div class="rola"><table class="t cartoes"><thead><tr><th>Fonte</th><th>Onde foi empenhada</th><th class="num">Valor</th><th>Norma</th></tr></thead><tbody>' +
        rc.desvios.filter(function (d) { return !funcaoDoRecorte() || d.funcao === funcaoDoRecorte(); }).map(function (d) {
          return '<tr><td data-r="Fonte"><b>' + esc(d.fonte) + '</b> ' + esc(d.nome) + '</td><td data-r="Função">' + esc(nomeFuncao(d.funcao)) + ' (' + esc(d.funcao) + ')</td><td class="num" data-r="Valor">' +
            num(d.valor) + '</td><td data-r="Norma">' + esc(d.norma) + '</td></tr>';
        }).join('') + '</tbody></table></div>' : '<p>' + selo('ok', 'na finalidade') + ' Nenhum recurso vinculado fora da finalidade no recorte.</p>');
    if (rc.sem_catalogo && rc.sem_catalogo.length) {
      h += painel('sem-catalogo', 'Fontes que o catálogo ainda não classifica', 'Recurso que o Onisciente ainda não sabe se é vinculado ou livre; aparece em cinza no diagrama.',
        '<p>' + rc.sem_catalogo.slice(0, 12).map(function (x) { return '<span class="mono">' + esc(x[0]) + '</span> ' + num(x[1]); }).join(' · ') + '</p>', { lamina: false });
    }
    h += blocoFichas(D.fichas, 'As fichas da origem do dinheiro', 'Recurso vinculado fora da finalidade, COSIP e FNAS no recorte.');
    depois.push(desenharSankey);
    return h;
  };
  function vinculo(a, id, titulo, lei) {
    if (!a) return '';
    var fun = funcaoDoRecorte();
    var total = a.empenhado.reduce(function (t, x) { return t + x[1].v; }, 0) || 1;
    var barras = a.empenhado.map(function (x) {
      return '<div class="barra-l' + (x[2] ? '' : ' fora') + '"' + (fun && fun === x[0] ? ' style="outline:2px solid var(--gold);border-radius:6px"' : '') + '><span>' + esc(nomeFuncao(x[0])) +
        '</span><span class="trilho"><i style="width:' + (x[1].v / total * 100).toFixed(1) + '%"></i></span><span class="r">' + num(x[1]) +
        (x[2] ? '' : ' fora da finalidade') + '</span></div>';
    }).join('');
    var o = a.origem;
    var extra = '';
    if (o) extra = '<p style="margin-top:10px">' + seloVias(o) + ' União: ' + num(o.vias[0] && o.vias[0].valor) + ' · Município: ' + num(o.vias[1] && o.vias[1].valor) + '</p>';
    if (a.planilha) extra += '<p class="sub">Planilha de repasses do FNAS no ano: ' + num(a.planilha) + '</p>';
    return painel(id, titulo, 'Fonte ' + esc(a.fonte) + ', ' + esc(a.nome) + '. Funções permitidas pela lei: ' +
      (a.funcoes.length ? a.funcoes.map(function (f) { return esc(nomeFuncao(f)); }).join(', ') : 'não definido') + '.',
      '<p class="lei">' + esc(lei || a.norma || '') + '</p><div class="grade gk" style="margin-top:10px">' + kpi('Entrou na fonte no ano', num(a.receita), 'receita realizada na fonte, janeiro até o período') +
      kpi('Fora da finalidade', num({ v: a.desvios.reduce(function (t, d) { return t + d.valor.v; }, 0), f: a.receita.f }), 'empenhado em outras funções',
        a.desvios.length ? 'critico' : 'bom') + '</div><div class="barras">' + barras + '</div>' + extra,
      { classe: 'vinculo-card', eyebrow: 'Fonte vinculada' });
  }
  function desenharSankey() {
    var area = document.getElementById('sankey-area'); if (!area) return;
    var g2 = L.somarRio(D, S.c, modoRio, funcaoDoRecorte(), C.funcoes);
    var fa = (D.por_c[S.c] || {}).fonte;
    if (!g2.links.length) { area.innerHTML = vazio('Sem receita neste recorte', 'Nenhuma receita ou empenho deste tipo no período.'); return; }
    var W = 1000, H = Math.max(380, Object.keys(g2.nos).length * 22), lay = L.layoutSankey(g2, W, H);
    var out = '<div class="rola"><svg class="sankey" viewBox="-4 -26 ' + (W + 8) + ' ' + (lay.alto + 34) + '" role="img" aria-label="Receita, fonte e empenho: ' + esc(L.brl(g2.total)) + ' de receita">';
    out += '<text class="col" x="' + (lay.cols[0][0] ? 210 : 0) + '" y="-10" text-anchor="end">Receita por espécie</text><text class="col" x="' + (W / 2) + '" y="-10" text-anchor="middle">Fonte</text><text class="col" x="' + (W - 250) + '" y="-10">Empenho por função</text>';
    lay.links.forEach(function (l) {
      var a = g2.nos[l.de], b = g2.nos[l.para], x0 = a.x + a.w, x1 = b.x, xm = (x0 + x1) / 2;
      out += '<path class="' + l.cl + ' n" data-f="' + esc(fa) + '" data-v="' + l.v + '" tabindex="-1" d="M' + x0 + ',' + l.y0.toFixed(1) + ' C' + xm + ',' + l.y0.toFixed(1) + ' ' + xm + ',' + l.y1.toFixed(1) + ' ' + x1 + ',' + l.y1.toFixed(1) +
        '" stroke-width="' + l.w.toFixed(1) + '"><title>' + esc(a.nome + ' para ' + b.nome + ': ' + L.brl(l.v)) + '</title></path>';
    });
    lay.cols.forEach(function (col, i) {
      col.forEach(function (n) {
        var cor = n.id[0] === 'l' ? (n.id === 'lvinculada' ? 'var(--vinc)' : n.id === 'llivre' ? 'var(--livre)' : 'var(--semcat)') :
          n.id === 'fparada' ? 'var(--parado)' : n.esfera ? 'var(--' + n.esfera + ')' : 'var(--ink-3)';
        out += '<g class="no"><rect x="' + n.x + '" y="' + n.y.toFixed(1) + '" width="' + n.w + '" height="' + n.h.toFixed(1) + '" fill="' + cor + '"/>';
        var tx = i === 0 ? n.x - 6 : n.x + n.w + 6, anc = i === 0 ? 'end' : 'start', ty = n.y + n.h / 2;
        if (n.h > 9 || i === 1) {
          out += '<text x="' + tx + '" y="' + (ty - 1).toFixed(1) + '" text-anchor="' + anc + '">' + esc(n.nome.length > 34 ? n.nome.slice(0, 33) + '…' : n.nome) + '</text>' +
            '<text class="v n" data-f="' + esc(fa) + '" data-v="' + n.v + '" tabindex="0" x="' + tx + '" y="' + (ty + 12).toFixed(1) + '" text-anchor="' + anc + '">' + L.brlCurto(n.v) + '</text>';
        }
        out += '</g>';
      });
    });
    out += '</svg></div>';
    out += '<p class="legenda"><span><i style="background:var(--vinc)"></i>Recurso vinculado</span><span><i style="background:var(--livre)"></i>Recurso livre</span>' +
      '<span><i style="background:var(--semcat)"></i>Fonte sem catálogo</span><span><i style="background:var(--parado)"></i>Arrecadado e não empenhado</span>' +
      '<span><i style="background:var(--federal)"></i>Federal</span><span><i style="background:var(--estadual)"></i>Estadual</span><span><i style="background:var(--municipal)"></i>Municipal</span></p>';
    if (funcaoDoRecorte()) out += '<p class="nota">Com ' + esc(nomeSec(S.s)) + ' no recorte, o empenho destaca a função ' + esc(nomeFuncao(funcaoDoRecorte())) + ' e junta as demais; a receita é a do Município inteiro, porque a receita não tem secretaria.</p>';
    var linhasTab = Object.keys(g2.nos).map(function (id) { return g2.nos[id]; }).sort(function (a, b) { return a.col - b.col || b.v - a.v; });
    out += '<details style="margin-top:8px"><summary>Em tabela (' + g2.meses.length + ' mês(es), ' + (modoRio === 'todo' ? 'todas as fontes' : 'recurso ' + (modoRio === 'vinculada' ? 'vinculado' : 'livre')) + ')</summary><table class="t"><thead><tr><th>Coluna</th><th>Item</th><th class="num">Valor</th></tr></thead><tbody>' +
      linhasTab.map(function (n) { return '<tr><td>' + ['Receita', 'Fonte', 'Empenho'][n.col] + '</td><td>' + esc(n.nome) + '</td><td class="num">' + num({ v: n.v, f: fa }) + '</td></tr>'; }).join('') + '</tbody></table></details>';
    area.innerHTML = out;
    area.closest('section').querySelectorAll('[data-modo]').forEach(function (b) {
      b.onclick = function () {
        modoRio = b.dataset.modo;
        area.closest('section').querySelectorAll('[data-modo]').forEach(function (x) { x.setAttribute('aria-pressed', x === b); });
        var u = new URLSearchParams(location.search); u.set('modo', modoRio); history.replaceState(null, '', '?' + u.toString() + location.hash);
        desenharSankey();
      };
    });
  }

  // --- Leis ---------------------------------------------------------------------------------
  T.leis = function () {
    var fun = funcaoDoRecorte();
    var regras = D.regras.slice().sort(function (a, b) { return (b.funcao === fun) - (a.funcao === fun) || (a.familia < b.familia ? -1 : 1); });
    var h = painel('regras', 'A régua de cada conferência', 'Cada regra que o Onisciente confere, com o parâmetro e a norma. ' + D.regras.length + ' regras na versão ' + esc(D.versao) + ' do mapa legal.',
      '<div class="filtros" style="margin-bottom:10px"><label class="sr" for="busca-lei">Buscar</label><input type="search" id="busca-lei" placeholder="Buscar regra ou norma"></div>' +
      '<div class="rola"><table class="t cartoes" id="tab-regras"><thead><tr><th>Regra</th><th class="num">Parâmetro</th><th>Norma</th><th>Família</th></tr></thead><tbody>' +
      regras.map(function (r) {
        return '<tr data-busca="' + esc((r.titulo + ' ' + r.norma + ' ' + r.id).toLowerCase()) + '"' + (fun && r.funcao === fun ? ' class="marcada"' : '') + '><td data-r="Regra"><b>' + esc(r.titulo) + '</b><br><span class="nota mono">' + esc(r.id) +
          '</span></td><td class="num" data-r="Parâmetro">' + (r.valor ? num(r.valor, r.unidade === '%' || r.unidade === 'percentual' ? 'pct' : 'int') + (r.unidade && r.unidade !== '%' && r.unidade !== 'percentual' ? ' ' + esc(r.unidade) : '') : '') +
          '</td><td data-r="Norma">' + esc(r.norma) + '</td><td data-r="Família">' + esc(r.familia || '') + '</td></tr>';
      }).join('') + '</tbody></table></div>');
    var areas = {};
    D.normas.forEach(function (n) { (areas[n.area] = areas[n.area] || []).push(n); });
    h += painel('normas', 'O acervo de normas', 'O texto de cada norma no acervo ctresb/leis ou no Sileg. O selo diz se a norma foi localizada e se foi revogada.',
      Object.keys(areas).sort().map(function (a) {
        return '<h3 style="margin:14px 0 6px;font-size:16px">' + esc(a) + '</h3><div class="rola"><table class="t cartoes"><tbody>' + areas[a].map(function (n) {
          var est = n.revogada ? selo('vermelho', 'revogada') : n.localizada ? selo('verde', 'localizada') : selo('roxo', 'não localizada');
          return '<tr data-busca="' + esc((n.norma + ' ' + n.assunto).toLowerCase()) + '"><td data-r="Norma"><b>' + esc(n.norma) + '</b><br><span class="sub">' + esc(n.assunto) + '</span></td><td data-r="Parâmetro">' + esc(n.parametro || '') +
            '</td><td data-r="Situação">' + est + '</td><td data-r="Texto">' + n.links.map(function (l) { return '<a href="' + esc(l[1]) + '" target="_blank" rel="noopener">' + esc(l[0]) + '</a>'; }).join('<br>') + '</td></tr>';
        }).join('') + '</tbody></table></div>';
      }).join(''), { lamina: false });
    depois.push(function () {
      var b = document.getElementById('busca-lei');
      if (b) b.oninput = function () {
        var t = b.value.toLowerCase();
        document.querySelectorAll('[data-busca]').forEach(function (tr) { tr.hidden = t && tr.dataset.busca.indexOf(t) < 0; });
      };
    });
    return h;
  };

  // --- Trilha -------------------------------------------------------------------------------
  var funTrilha = U.get('f');
  T.trilha = function () {
    var fun = funTrilha || funcaoDoRecorte() || '*';
    var ex = (D.exemplos[S.c] || {})[fun];
    var opcoes = '<option value="*">Todas as funções</option>' + D.funcoes.map(function (f) {
      return '<option value="' + f + '"' + (f === fun ? ' selected' : '') + '>' + esc(nomeFuncao(f)) + '</option>';
    }).join('');
    var seletor = '<label class="filtros"><span class="sr">Função de governo</span><select id="sel-funcao">' + opcoes + '</select></label>';
    if (!ex) return painel('estacoes', 'As nove estações', '', vazio('Sem matriz para ' + L.mes(S.c), 'A trilha agregada sai da matriz de saldos contábeis do mês, que não está no banco.'), { direita: seletor });
    var desc = {}; D.estacoes.forEach(function (e) { desc[e.n] = e; });
    var h = painel('estacoes', 'As nove estações em ' + L.mes(S.c), 'O dinheiro de ' + (fun === '*' ? 'todas as funções' : 'Função ' + esc(nomeFuncao(fun))) +
      ' no mês, estação por estação. Estação acesa tem documento publicado com o nível mínimo de prova; apagada é o que falta.',
      '<div class="estacoes">' + ex.linhas.map(function (l) {
        var e = desc[l.n], cls = l.acesa ? 'acesa' : (l.n === 9 ? 'apagada' : 'espera');
        var extra = l.vinculada ? '<span class="nota">vinculada ' + num(l.vinculada) + ' · livre ' + num(l.livre) + '</span>' : '';
        if (l.variacao) extra += '<span class="nota">créditos: ' + num(l.variacao) + '</span>';
        return '<div class="estacao ' + cls + '" id="est-' + l.n + '"><span class="pino" aria-hidden="true">' + l.n + '</span><div class="txt"><h3>' + esc(e.nome) + '</h3>' +
          '<span class="v">' + (l.valor ? num(l.valor) : (l.n === 9 ? selo('roxo') : selo('cinza', 'sem valor'))) + '</span>' + extra + '<p>' + esc(l.nota) + '</p><p class="nota">Prova: ' + esc(e.prova) + '</p></div></div>';
      }).join('') + '</div>' + (ex.ordem && ex.ordem.length ? '<p class="nota">' + selo('indicio', 'ordem violada') + ' ' + esc(ex.ordem.join('; ')) + '</p>' : ''),
      { direita: seletor, eyebrow: 'Liquidação e pagamento' });
    // o ano inteiro: estações por mês
    var meses = Object.keys(D.exemplos).filter(function (m) { return m.slice(0, 4) === S.c.slice(0, 4); }).sort();
    h += painel('ano', 'O ano estação por estação', 'Cada linha é um mês; cada casa, uma estação. Cheia é estação com documento; vazia é estação sem documento no mês.',
      '<div class="rola"><table class="t"><thead><tr><th>Mês</th>' + D.estacoes.map(function (e) { return '<th class="num" title="' + esc(e.nome) + '">' + e.n + '</th>'; }).join('') + '</tr></thead><tbody>' +
      meses.map(function (m) {
        var x = (D.exemplos[m] || {})[fun]; if (!x) return '';
        return '<tr' + (m === S.c ? ' class="marcada"' : '') + '><td>' + esc(L.mesCurto(m)) + '</td>' + x.linhas.map(function (l) {
          return '<td class="num">' + (l.acesa ? '<span class="selo verde" title="' + esc(desc[l.n].nome) + ' com documento"><i></i></span>' : '<span class="selo ' + (l.n === 9 ? 'roxo' : 'cinza') + '" title="' + esc(desc[l.n].nome) + ' sem documento"><i></i></span>') + '</td>';
        }).join('') + '</tr>';
      }).join('') + '</tbody></table></div>');
    var exe = D.execucao;
    var ce = coleta('execucao');
    if (!exe && ce) {
      h += painel('empenhos', 'Empenho a empenho', '', naoFeita(ce, 'execução, empenho a empenho',
        'Quando a coleta do portal da transparência do Município trouxer os empenhos, cada um aparece aqui com a sua trilha completa. Por enquanto a trilha acima é o agregado da matriz contábil, que é prova oficial do Tesouro.'));
    } else if (!exe) {
      h += painel('empenhos', 'Empenho a empenho', '', vazio('Aguardando a coleta da execução, empenho a empenho',
        'Quando a frente da execução entregar os empenhos do portal da transparência do Município (número, credor, contrato, liquidação e pagamento), cada empenho aparece aqui com a sua trilha completa. Por enquanto a trilha acima é o agregado da matriz contábil, que é prova oficial do Tesouro.'));
    } else {
      var lista = exe.filter(function (e) { return e.mes === S.c && (!S.s || e.orgao === S.s) && (fun === '*' || e.funcao === fun); });
      h += painel('empenhos', 'Empenho a empenho', lista.length + ' empenho(s) no recorte, cada um com as suas estações.',
        lista.length ? '<div class="rola"><table class="t cartoes"><thead><tr><th>Empenho</th><th>Credor</th><th class="num">Valor</th><th>Estações</th></tr></thead><tbody>' +
          lista.slice(0, 200).map(function (e) {
            return '<tr><td data-r="Empenho"><b class="mono">' + esc(e.numero) + '</b><br><span class="nota">' + esc(L.data(e.data)) + (e.contrato ? ', contrato ' + esc(e.contrato) : ', sem contrato informado') + '</span></td><td data-r="Credor">' + esc(e.credor) +
              '</td><td class="num" data-r="Valor">' + num(e.valor) + '</td><td data-r="Estações">' + ['empenho', 'liquidacao', 'pagamento'].map(function (st) {
                var ev = e.eventos.filter(function (x) { return x.estacao === st; })[0];
                return ev ? selo('verde', st === 'liquidacao' ? 'liquidação' : st) + ' ' + num(ev.valor) : selo('roxo', (st === 'liquidacao' ? 'liquidação' : st) + ' ausente');
              }).join('<br>') + '</td></tr>';
          }).join('') + '</tbody></table></div>' : vazio('Nenhum empenho neste recorte', 'A execução entregue não tem empenho do mês e da secretaria escolhidos.'));
    }
    h += blocoFichas(D.fichas, 'As fichas da execução', 'Empenho, liquidação e pagamento sem rastro publicado.');
    depois.push(function () {
      var sel = document.getElementById('sel-funcao');
      if (sel) sel.onchange = function () { funTrilha = sel.value; var u = new URLSearchParams(location.search); u.set('f', funTrilha); history.replaceState(null, '', '?' + u.toString()); desenhar(); };
    });
    return h;
  };

  // --- Secretarias --------------------------------------------------------------------------
  T.secretarias = function () {
    var jan = L.janela(S.c, D.janela);
    var linhas = C.secretarias.map(function (s) {
      var o = D.orgaos[s.id] || { contratos: {}, achados: {} };
      return { s: s, c: L.somaPorMes(o.contratos, jan[0], jan[1]), a: L.somaPorMes(o.achados, jan[0], jan[1]), semNota: o.sem_nota, chaveC: o.contratos, chaveA: o.achados, t: (D.transparencia || {})[s.id] };
    }).sort(function (a, b) { return b.c[1] - a.c[1]; });
    function n2(mapa, x) { var k = Object.keys(mapa || {})[0]; return { v: x, f: k ? mapa[k][1].f : '' }; }
    var h = painel('quadro', 'As secretarias em 12 meses', 'De ' + esc(L.mes(jan[0])) + ' a ' + esc(L.mes(jan[1])) + '. O clique numa linha põe a secretaria no recorte de todas as telas.',
      '<div class="rola"><table class="t cartoes"><thead><tr><th>Órgão</th><th>Função</th><th class="num">Contratos</th><th class="num">Valor contratado</th><th class="num">Indícios de compras</th><th>Notas fiscais</th><th>Transparência</th></tr></thead><tbody>' +
      linhas.map(function (x) {
        return '<tr class="clic' + (x.s.id === S.s ? ' marcada' : '') + '" data-sec="' + x.s.id + '" tabindex="0"><td data-r="Órgão"><b>' + esc(x.s.nome) + '</b>' + (x.s.pasta ? ' ' + selo('alerta', 'pasta fiscalizada') : '') +
          '</td><td data-r="Função">' + (x.s.funcao ? esc(nomeFuncao(x.s.funcao)) : '<span class="nota">não identificada</span>') + '</td><td class="num" data-r="Contratos">' + L.int(x.c[0]) +
          '</td><td class="num" data-r="Valor">' + (x.c[0] ? num(n2(x.chaveC, x.c[1])) : '') + '</td><td class="num" data-r="Indícios">' + (x.a[0] ? '<b style="color:var(--indicio)">' + L.int(x.a[0]) + '</b>' : '0') +
          '</td><td data-r="Notas fiscais">' + (x.semNota ? selo('roxo', 'nenhuma publicada') : selo('cinza', 'sem leitura')) + '</td><td data-r="Transparência">' +
          (x.t ? (x.t.nota ? num(x.t.nota, 'int') + ' ' : '') + (x.t.obrigacoes && x.t.obrigacoes.length ? selo(x.t.obrigacoes.some(function (o) { return o.alerta; }) ? 'roxo' : 'ok', x.t.nivel || '') : esc(x.t.nivel || '')) : selo('cinza', 'aguardando o selo')) + '</td></tr>';
      }).join('') + '</tbody></table></div>');
    if (S.s && SEC[S.s]) {
      var s = SEC[S.s], fun = s.funcao, ex = (D.execucao || {})[fun] || {};
      var meses = Object.keys(ex).filter(function (m) { return m.slice(0, 4) === S.c.slice(0, 4); }).sort();
      h += painel('detalhe', s.nome, fun ? 'A execução da função ' + esc(nomeFuncao(fun)) + ' no ano, mês a mês, pela matriz contábil. A matriz traz a função, não o órgão: é a função inteira.' : 'A função deste órgão não foi identificada pelo nome.',
        fun && meses.length ? grafico({
          titulo: 'Execução mensal', x: meses.map(L.mesCurto), agora: meses.indexOf(S.c),
          series: [{ nome: 'Empenhado', cl: 'b1', cor: 'var(--royal)', vals: meses.map(function (m) { return ex[m].emp; }) },
          { nome: 'Liquidado', cl: 'b3', cor: 'var(--vinc)', vals: meses.map(function (m) { return ex[m].liq; }) },
          { nome: 'Pago', cl: 'b2', cor: 'var(--gold)', vals: meses.map(function (m) { return ex[m].pago; }) }]
        }) : vazio('Sem execução para mostrar', 'A matriz do ano não tem a função deste órgão.'), { eyebrow: 'Secretaria no recorte' });
    }
    depois.push(function () {
      document.querySelectorAll('[data-sec]').forEach(function (tr) {
        var ir = function (e) { if (e.target.closest('[data-f]')) return; mudar({ s: tr.dataset.sec === S.s ? '' : tr.dataset.sec }); };
        tr.onclick = ir; tr.onkeydown = function (e) { if (e.key === 'Enter') ir(e); };
      });
    });
    return h;
  };

  // --- Pisos e tetos ------------------------------------------------------------------------
  T.pisos = function () {
    var d = D.por_c[S.c];
    if (!d) return vazio('Sem medição para este período', 'Não há demonstrativo no banco para ' + L.mes(S.c) + '.');
    var fun = funcaoDoRecorte();
    var h = painel('medidas', 'Os percentuais pelo cálculo próprio', 'Pelo ' + esc(d.rgf || 'RGF') + ' e pelo ' + esc(d.rreo || 'RREO') + '. O cálculo é refeito a partir das linhas do demonstrativo; o declarado pelo Município fica ao lado.',
      '<div class="grade g3">' + d.medidas.map(function (m) { return medidor(m, fun); }).join('') + '</div>', { eyebrow: 'Orçamento' });
    h += painel('vias', 'As duas vias', 'O mesmo número em dois demonstrativos oficiais. Quando divergem, o selo fica azul e vira ficha.',
      d.vias.length ? '<div class="rola"><table class="t cartoes"><thead><tr><th>Conferência</th><th class="num">Primeira via</th><th class="num">Segunda via</th><th>Selo</th></tr></thead><tbody>' +
        d.vias.map(function (v) {
          return '<tr><td data-r="Conferência">' + esc(v.titulo) + '</td><td class="num" data-r="Primeira via">' + (v.vias[0] ? num(v.vias[0].valor) : '') + '<br><span class="nota">' + esc(v.vias[0] ? v.vias[0].rotulo : '') +
            '</span></td><td class="num" data-r="Segunda via">' + (v.vias[1] ? num(v.vias[1].valor) : '') + '<br><span class="nota">' + esc(v.vias[1] ? v.vias[1].rotulo : '') + '</span></td><td data-r="Selo">' + seloVias(v) + '</td></tr>';
        }).join('') + '</tbody></table></div>' : '<p class="sub">Sem conferência em duas vias neste período.</p>');
    if (d.pasta && d.pasta.length) {
      h += painel('pasta', 'Os pisos da pasta fiscalizada', 'Percentuais próprios da Assistência Social, do parecer mensal.',
        '<div class="grade g3">' + d.pasta.map(function (m) {
          return m.percentual ? medidor({ titulo: m.titulo, percentual: m.percentual, limite: m.limite, situacao: m.situacao, selo: m.selo, tipo: 'piso', funcao: m.funcao }, fun) :
            '<div class="medidor">' + '<h3>' + esc(m.titulo) + '</h3>' + vazio('Demonstrativo não publicado', 'Piso de ' + L.pct(m.limite) + '. O Município não publicou o demonstrativo que permite a conta neste mês.', true) + origem(m.fonte_ausente, 'ver a origem') + '</div>';
        }).join('') + '</div>');
    }
    if (d.notas && d.notas.length) h += '<p class="nota">' + d.notas.map(esc).join(' ') + '</p>';
    h += blocoFichas(D.fichas, 'As fichas dos pisos e tetos');
    return h;
  };
  function medidor(m, fun) {
    var p = m.percentual ? m.percentual.v : null, lim = m.limite || 0;
    var teto = m.tipo === 'teto' || (m.tipo !== 'piso' && /PESSOAL|DIVIDA|OPERACOES|CAMARA|SALDO/.test(m.id || ''));
    var escala = Math.max(lim * 1.35, p || 0, m.alerta || 0) || 100;
    var ruim = m.situacao === 'descumpre' || m.situacao === 'nao_cumpre', alerta = m.situacao === 'alerta' || m.situacao === 'acompanha';
    var sit = { cumpre: ['ok', 'cumpre'], descumpre: ['critica', 'descumpre'], nao_cumpre: ['critica', 'não cumpre'], alerta: ['alerta', 'no alerta'], acompanha: ['alerta', 'acompanhar'], sem_dado: ['roxo', 'sem dado'] }[m.situacao] || ['azul', m.situacao];
    var marcas = '<span class="lim" style="left:' + (lim / escala * 100).toFixed(1) + '%"><span>' + (teto ? 'teto ' : 'piso ') + NF1.format(lim) + '%</span></span>';
    if (m.alerta) marcas += '<span class="lim al" style="left:' + (m.alerta / escala * 100).toFixed(1) + '%"><span>alerta ' + NF1.format(m.alerta) + '</span></span>';
    if (m.prudencial) marcas += '<span class="lim al" style="left:' + (m.prudencial / escala * 100).toFixed(1) + '%;top:-2px"></span>';
    return '<div class="medidor' + (ruim ? ' ruim' : alerta ? ' alerta' : '') + (fun && m.funcao === fun ? ' foco' : '') + '"><h3>' + esc(m.titulo) + '</h3>' +
      '<span class="grande">' + num(m.percentual, 'pct') + '</span><div class="regua-m" aria-hidden="true"><span class="enche" style="width:' + Math.min(100, (p || 0) / escala * 100).toFixed(1) + '%"></span>' + marcas + '</div>' +
      '<p>' + selo(sit[0], sit[1]) + ' ' + (m.selo ? selo(m.selo) : '') + '</p>' +
      (m.declarado ? '<p class="sub">Declarado pelo Município: ' + num(m.declarado, 'pct') + (m.divergencia ? ', diferença de ' + NF2.format(m.divergencia) + ' p.p.' : '') + '</p>' : '') +
      (m.norma ? '<p class="nota">' + esc(m.norma) + '</p>' : '') +
      (m.memoria ? '<details><summary class="nota">Memória de cálculo</summary><p class="sub">' + esc(m.memoria) + '</p></details>' : '') + '</div>';
  }

  // --- Pessoal ------------------------------------------------------------------------------
  T.pessoal = function () {
    var serie = D.serie.filter(function (x) { return x.ate <= S.c; });
    var ult = serie[serie.length - 1];
    var h = '';
    if (ult) {
      var folga = { v: D.limite - ult.percentual.v, f: ult.percentual.f };
      h += painel('teto', 'A despesa com pessoal do Executivo', 'Pelo ' + esc(ult.rotulo) + ', contra o limite de ' + NF1.format(D.limite) + '% da receita corrente líquida (' + esc(D.norma) + ').',
        '<div class="grade gk">' + kpi('Despesa com pessoal', num(ult.percentual, 'pct'), 'cálculo próprio sobre a RCL', ult.percentual.v >= (D.prudencial || 99) ? 'critico' : ult.percentual.v >= (D.alerta || 99) ? 'ruim' : 'bom') +
        kpi('Declarado no RGF', num(ult.declarado, 'pct')) + kpi('Folga até o limite', num(folga, 'pp')) + '</div>' +
        grafico({
          titulo: 'Pessoal por quadrimestre', fmt: 'pct', min: 30, x: serie.map(function (x) { return x.rotulo.replace('RGF do ', '').replace(' quadrimestre de ', 'º q. '); }),
          series: [{ nome: 'Cálculo próprio', tipo: 'linha', cl: 'l1', cor: 'var(--royal)', vals: serie.map(function (x) { return x.percentual; }) },
          { nome: 'Declarado', tipo: 'linha', cl: 'l2', cor: 'var(--gold)', vals: serie.map(function (x) { return x.declarado; }) }],
          linhas: [{ v: D.limite, rot: 'limite ' + NF1.format(D.limite) + '%', cl: 'lim' }].concat(D.prudencial ? [{ v: D.prudencial, rot: 'prudencial ' + NF1.format(D.prudencial) + '%', cl: 'alr' }] : []).concat(D.alerta ? [{ v: D.alerta, rot: 'alerta ' + NF1.format(D.alerta) + '%', cl: 'alr' }] : [])
        }) + '<details><summary class="nota">Memória de cálculo</summary><p class="sub">' + esc(ult.memoria) + '</p></details>', { eyebrow: 'Liquidação e pagamento' });
    } else h += vazio('Sem RGF até este período', 'O primeiro RGF no banco é posterior a ' + L.mes(S.c) + '.');
    var fun = funcaoDoRecorte();
    var meses = Object.keys(D.mensal).filter(function (m) { return m.slice(0, 4) === S.c.slice(0, 4) && m <= S.c; }).sort();
    h += painel('folha', 'A folha mês a mês', 'Liquidado em pessoal e encargos (grupo 31) no mês, ' + (fun ? 'na função ' + esc(nomeFuncao(fun)) : 'em todas as funções') + ', pela matriz contábil.',
      meses.length ? grafico({
        titulo: 'Folha mensal', x: meses.map(L.mesCurto), agora: meses.indexOf(S.c),
        series: [{ nome: fun ? nomeFuncao(fun) : 'Todas as funções', cl: 'b1', cor: 'var(--royal)', vals: meses.map(function (m) {
          var pf = D.mensal[m].por_funcao, f = D.mensal[m].fonte;
          if (fun) return pf[fun] || null;
          return { v: Object.keys(pf).reduce(function (t, k) { return t + pf[k].v; }, 0), f: f };
        }) }]
      }) : vazio('Sem matriz no ano', 'A matriz do ano ainda não está no banco.'));
    var nm = D.nomeacoes;
    if (nm) {
      var ms = Object.keys(nm.meses).filter(function (m) { return m <= S.c; }).sort().slice(-12), atos = {};
      ms.forEach(function (m) { Object.keys(nm.meses[m]).forEach(function (a) { atos[a] = 1; }); });
      atos = Object.keys(atos).sort();
      h += painel('atos', 'Atos de pessoal da pasta no Diário Oficial', 'Contagem dos atos publicados nos últimos 12 meses com ato, por tipo. Só contagens: nenhum nome, matrícula ou CPF aparece nas telas.',
        ms.length ? '<div class="rola"><table class="t"><thead><tr><th>Mês</th>' + atos.map(function (a) { return '<th class="num">' + esc(a) + '</th>'; }).join('') + '</tr></thead><tbody>' +
          ms.map(function (m) { return '<tr><td>' + esc(L.mesCurto(m)) + '</td>' + atos.map(function (a) { return '<td class="num">' + (nm.meses[m][a] ? num(nm.meses[m][a], 'int') : '') + '</td>'; }).join('') + '</tr>'; }).join('') +
          '</tbody></table></div>' : '<p class="sub">Nenhum ato até este período.</p>', { lamina: false });
    }
    h += blocoFichas(D.fichas, 'O que a lei manda pagar e não foi pago', 'As fichas de pessoal no recorte.', 'fichas');
    return h;
  };

  // --- Preço e entrega ----------------------------------------------------------------------
  var buscaContrato = '', estadoContrato = '', paginaContrato = 0;
  T.precos = function () {
    var jan = L.janela(S.c, D.janela);
    var cs = D.contratos.filter(function (x) { return x[1] >= jan[0] && x[1] <= jan[1] && (!S.s || x[2] === S.s); });
    var cont = { preco: {}, entrega: {}, prest: {} };
    cs.forEach(function (x) { cont.preco[x[7]] = (cont.preco[x[7]] || 0) + 1; cont.entrega[x[9]] = (cont.entrega[x[9]] || 0) + 1; cont.prest[x[10]] = (cont.prest[x[10]] || 0) + 1; });
    var h = painel('triangulo', 'O triângulo: preço, entrega e prestação', cs.length + ' contrato(s) de ' + esc(L.mes(jan[0])) + ' a ' + esc(L.mes(jan[1])) + (S.s ? ' de ' + esc(nomeSec(S.s)) : ' no Município') +
      '. Um contrato só fecha quando os três vértices estão conferidos: o preço bate com o país, a entrega tem nota fiscal e a conta foi prestada.',
      '<div class="grade g2"><div class="triangulo">' + triangulo(cont, cs.length) + '</div><div class="grade gk" style="align-content:start">' +
      kpi('Preço com indício', L.int(cont.preco.indicio || 0), 'contratos com item acima da mediana nacional', cont.preco.indicio ? 'ruim' : 'bom') +
      kpi('Preço conferido sem indício', L.int(cont.preco.conferido || 0), 'itens comparados com o catálogo') +
      kpi('Entrega sem nota publicada', L.int(cont.entrega.ausente || 0), 'órgão sem nenhuma nota fiscal no PNCP', cont.entrega.ausente ? 'falta' : '') +
      kpi('Prestação de contas', (C.entradas || []).indexOf('execucao') >= 0 ? L.int(cont.prest.conferido || 0) + ' conferida(s)' : 'aguardando', 'liquidação do empenho do contrato') + '</div></div>', { eyebrow: 'Contratação' });
    var achados = D.achados.filter(function (a) { return a[3] >= jan[0] && a[3] <= jan[1] && (!S.s || a[1] === S.s); });
    var precos = achados.filter(function (a) { return a[0] === 'preco'; });
    h += painel('preco', 'Preço acima do país', precos.length + ' item(ns) com preço unitário acima da mediana nacional para o mesmo item e unidade, depois de descartar os de unidade diferente.',
      precos.length ? '<div class="rola"><table class="t cartoes"><thead><tr><th>Item e órgão</th><th class="num">Pago</th><th class="num">Mediana do país</th><th>Mês</th></tr></thead><tbody>' +
        precos.slice(0, 60).map(function (a) {
          return '<tr><td data-r="Item">' + esc(a[4]) + '<br><span class="nota">' + esc(nomeSec(a[1])) + '</span></td><td class="num" data-r="Pago">' + num(a[5], 'brl') + '</td><td class="num" data-r="Mediana">' + num(a[6], 'brl') + '</td><td data-r="Mês">' + esc(L.mesCurto(a[3])) + '</td></tr>';
        }).join('') + '</tbody></table></div>' + (precos.length > 60 ? '<p class="nota">Mostrando 60 de ' + precos.length + '; todos estão em <a href="' + link('indicios', { tema: 'precos' }) + '">Indícios</a>.</p>' : '')
        : '<p>' + selo('ok', 'sem indício') + ' Nenhum preço acima do país no recorte.</p>');
    var nf = achados.filter(function (a) { return a[0] === 'nf_ausente'; });
    var nfTodas = D.achados.filter(function (a) { return a[0] === 'nf_ausente' && (!S.s || a[1] === S.s) && a[7] <= S.c; });
    var porOrgao = {}; nfTodas.forEach(function (a) { porOrgao[a[1]] = a; });
    h += painel('notas', 'Notas fiscais nunca publicadas', 'A Lei 14.133/2021 manda publicar no PNCP as notas fiscais de cada contrato. Os órgãos abaixo não publicaram nenhuma no período lido.',
      Object.keys(porOrgao).length ? '<div class="grade g2">' + Object.keys(porOrgao).map(function (o) {
        var a = porOrgao[o];
        return '<div class="vazio roxo"><span class="ic" aria-hidden="true">!</span><div><h3>' + esc(nomeSec(o)) + '</h3><p>' + esc(a[4]) + '</p><p class="nota">Desde ' + esc(L.mes(a[7])) + '. ' + origem(a[5] && a[5].f, 'a leitura do PNCP') + '</p></div></div>';
      }).join('') + '</div>' : '<p class="sub">' + (nf.length ? '' : selo('cinza', 'sem leitura') + ' Nenhum órgão do recorte foi lido sem nota.') + '</p>');
    h += painel('contratos', 'Os contratos, um a um', 'Cada contrato com o estado dos três vértices. O valor abre a leitura do PNCP.',
      '<div class="filtros" style="margin-bottom:10px"><label><span class="sr">Buscar contrato</span><input type="search" id="busca-contrato" placeholder="Buscar fornecedor ou objeto" value="' + esc(buscaContrato) + '"></label>' +
      '<label><span class="sr">Estado</span><select id="estado-contrato"><option value="">Todos os estados</option><option value="indicio">Preço com indício</option><option value="ausente">Entrega sem nota</option><option value="conferido">Preço conferido</option></select></label></div><div id="lista-contratos"></div>', { lamina: false });
    h += blocoFichas(D.fichas, 'As fichas de preço e de notas');
    depois.push(function () {
      var b = document.getElementById('busca-contrato'), e = document.getElementById('estado-contrato');
      e.value = estadoContrato;
      var desenha = function () {
        var t = buscaContrato.toLowerCase();
        var f = cs.filter(function (x) { return (!t || (x[3] + ' ' + x[5]).toLowerCase().indexOf(t) >= 0) && (!estadoContrato || x[7] === estadoContrato || x[9] === estadoContrato); });
        var pp = 25, tot = Math.ceil(f.length / pp) || 1; paginaContrato = Math.min(paginaContrato, tot - 1);
        var est = { indicio: 'indício', conferido: 'conferido', sem_comparacao: 'sem comparação', ausente: 'nota não publicada', sem_leitura: 'sem leitura', aguardando: 'aguardando a execução' };
        document.getElementById('lista-contratos').innerHTML = '<div class="rola"><table class="t cartoes"><thead><tr><th>Fornecedor e objeto</th><th class="num">Valor</th><th>Preço</th><th>Entrega</th><th>Prestação</th></tr></thead><tbody>' +
          f.slice(paginaContrato * pp, paginaContrato * pp + pp).map(function (x) {
            return '<tr><td data-r="Contrato"><b>' + esc(x[3]) + '</b><br><span class="sub">' + esc(x[5]) + '</span><br><span class="nota">' + esc(nomeSec(x[2])) + ', ' + esc(L.mesCurto(x[1])) + ', <span class="mono">' + esc(x[0]) + '</span></span></td>' +
              '<td class="num" data-r="Valor">' + num(x[6]) + '</td><td data-r="Preço"><span class="estado ' + x[7] + '">' + est[x[7]] + (x[8] ? ' (' + x[8] + ')' : '') + '</span></td><td data-r="Entrega"><span class="estado ' + x[9] + '">' + est[x[9]] +
              '</span></td><td data-r="Prestação"><span class="estado ' + x[10] + '">' + est[x[10]] + '</span></td></tr>';
          }).join('') + '</tbody></table></div><div class="paginacao"><button class="bt" data-pg="-1"' + (paginaContrato ? '' : ' disabled') + '>Anterior</button><span>' + (paginaContrato + 1) + ' de ' + tot + ' (' + f.length + ' contratos)</span><button class="bt" data-pg="1"' + (paginaContrato < tot - 1 ? '' : ' disabled') + '>Próxima</button></div>';
        document.querySelectorAll('[data-pg]').forEach(function (bt) { bt.onclick = function () { paginaContrato += +bt.dataset.pg; desenha(); }; });
      };
      b.oninput = function () { buscaContrato = b.value; paginaContrato = 0; desenha(); };
      e.onchange = function () { estadoContrato = e.value; paginaContrato = 0; desenha(); };
      desenha();
    });
    return h;
  };
  function triangulo(cont, total) {
    function cor(st) { return st === 'ruim' ? 'var(--critico)' : st === 'falta' ? 'var(--ausencia)' : st === 'ok' ? 'var(--ok)' : 'var(--neutro)'; }
    var pr = cont.preco.indicio ? 'ruim' : cont.preco.conferido ? 'ok' : 'espera';
    var en = cont.entrega.ausente ? 'falta' : cont.entrega.conferido ? 'ok' : 'espera';
    var ps = cont.prest.ausente ? 'falta' : cont.prest.conferido ? 'ok' : 'espera';
    var v = [[220, 40, 'Preço', pr, (cont.preco.indicio || 0) + ' com indício'], [60, 300, 'Entrega', en, (cont.entrega.ausente || 0) + ' sem nota'], [380, 300, 'Prestação', ps, ps === 'espera' ? 'aguardando a execução' : (cont.prest.ausente || 0) + ' sem prestação']];
    var out = '<svg viewBox="0 0 440 360" role="img" aria-label="Triângulo preço, entrega e prestação de ' + total + ' contratos">' +
      '<polygon points="220,40 60,300 380,300" fill="var(--agua)" stroke="var(--line)" stroke-width="3"/>' +
      '<text x="220" y="215" text-anchor="middle" style="font:700 34px var(--f-mono)">' + total + '</text><text x="220" y="238" text-anchor="middle" class="vt">contratos no recorte</text>';
    v.forEach(function (p) {
      out += '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="22" fill="' + cor(p[3]) + '"' + (p[3] === 'espera' ? ' fill-opacity=".25" stroke="var(--neutro)" stroke-dasharray="4 3" stroke-width="2"' : '') + '/>' +
        '<text x="' + p[0] + '" y="' + (p[1] + (p[1] < 100 ? -30 : 44)) + '" text-anchor="middle">' + p[2] + '</text><text class="vt" x="' + p[0] + '" y="' + (p[1] + (p[1] < 100 ? -14 : 60)) + '" text-anchor="middle">' + esc(p[4]) + '</text>';
    });
    return out + '</svg>';
  }

  // --- Contratos e empresas -----------------------------------------------------------------
  T.empresas = function () {
    var jan = L.janela(S.c, 12);
    var forn = D.fornecedores.map(function (f) {
      var cs = f.contratos.filter(function (x) { return x[1] >= jan[0] && x[1] <= jan[1] && (!S.s || x[2] === S.s); });
      return { f: f, cs: cs, v: cs.reduce(function (t, x) { return t + x[3].v; }, 0) };
    }).filter(function (x) { return x.cs.length; }).sort(function (a, b) { return b.v - a.v; });
    var h = painel('fornecedores', 'Quem recebeu', forn.length + ' fornecedor(es) com contrato assinado de ' + esc(L.mes(jan[0])) + ' a ' + esc(L.mes(jan[1])) + (S.s ? ' em ' + esc(nomeSec(S.s)) : '') + '. Pessoas físicas aparecem sem documento.',
      '<div class="rola"><table class="t cartoes"><thead><tr><th>Fornecedor</th><th class="num">Contratos</th><th class="num">Valor</th><th>Receita Federal</th></tr></thead><tbody>' +
      forn.slice(0, 80).map(function (x) {
        var r = x.f.receita, alertas = r ? (r.alertas || []).slice(0, 3).map(function (a) {
          return '<br>' + selo(a.gravidade === 'critica' ? 'critica' : 'indicio', a.titulo || a.tipo || 'alerta') + (a.texto ? ' <span class="nota">' + esc(a.texto) + '</span>' : '');
        }).join('') + ((r.alertas || []).length > 3 ? '<br><span class="nota">e mais ' + ((r.alertas || []).length - 3) + ' alerta(s)</span>' : '') : '';
        return '<tr><td data-r="Fornecedor"><b>' + esc(x.f.nome) + '</b><br><span class="nota mono">' + esc(x.f.ni) + '</span></td><td class="num" data-r="Contratos">' + x.cs.length + '</td><td class="num" data-r="Valor">' +
          num({ v: x.v, f: x.cs[0][3].f }) + '</td><td data-r="Receita">' + (r && r.cadastro === false ? selo('cinza', 'cadastro não coletado') + ' ' + origem(r.fonte, 'por quê') + alertas : r ? (r.abertura ? 'Aberta em ' + esc(L.data(r.abertura)) + '. ' : '') + esc(r.situacao || '') + ' ' + alertas + (r.socios && r.socios.length ? '<br><span class="nota">Sócios e administradores: ' +
            r.socios.map(function (s) { return esc(s.nome) + (s.qualificacao ? ' (' + esc(s.qualificacao) + ')' : ''); }).join(', ') + '</span>' : '') + ' ' + origem(r.fonte, 'cartão do CNPJ') : selo('cinza', 'aguardando')) + '</td></tr>';
      }).join('') + '</tbody></table></div>' + (forn.length > 80 ? '<p class="nota">Os 80 maiores de ' + forn.length + '.</p>' : ''), { eyebrow: 'Contratação' });
    var cob = D.cobertura;
    if (cob) {
      var faltam = Object.keys(cob.sancoes_nao_conferidas || {});
      h += painel('cobertura', 'O que a conferência das empresas já cobre', 'Ausência de dado nunca é atestado de empresa limpa: o que não foi conferido aparece em cinza, como falha do próprio sistema.',
        '<div class="grade g3">' + kpi('CNPJs contratados', L.int(cob.cnpjs || 0), 'pessoas jurídicas com contrato no PNCP') +
        kpi('Com o cadastro da Receita', L.int(cob.com_cadastro || 0) + ' de ' + L.int(cob.cnpjs || 0), cob.com_cadastro ? 'cartão do CNPJ no banco' : selo('cinza', 'coleta ainda não feita'), cob.com_cadastro ? '' : 'ruim') +
        kpi('Cadastros de sanção conferidos', L.int(4 - faltam.length) + ' de 4', faltam.length ? faltam.map(function (k) { return selo('cinza', k + ' não conferido'); }).join(' ') : 'CEIS, CNEP, CEPIM e TCU', faltam.length ? 'ruim' : 'bom') + '</div>' +
        (faltam.length ? '<ul class="lista">' + faltam.map(function (k) { return '<li>' + selo('cinza', k) + ' ' + esc(cob.sancoes_nao_conferidas[k]) + '</li>'; }).join('') + '</ul>' : '') +
        (cob.lacunas || []).map(function (l) { return '<p class="nota">' + esc(l) + '.</p>'; }).join('') +
        (cob.alertas_gerais || []).map(function (a) { return '<p>' + selo('cinza', a.titulo) + ' <span class="nota">' + esc(a.texto) + '</span></p>'; }).join(''));
    }
    var cem = coleta('empresas');
    if (!D.receita && cem) {
      h += painel('receita', 'A empresa por trás do contrato', '', naoFeita(cem, 'empresas na Receita Federal', 'Quando a coleta trouxer o cartão do CNPJ, o quadro de sócios e as sanções, cada fornecedor ganha a idade da empresa, quem a administra e os alertas. Nenhum CPF aparece.'));
    } else if (!D.receita) {
      h += painel('receita', 'A empresa por trás do contrato', '', vazio('Aguardando a coleta das empresas na Receita Federal',
        'Quando a frente das empresas entregar o cartão do CNPJ, o quadro de sócios e administradores e as sanções (CEIS e CNEP), cada fornecedor acima ganha a idade da empresa, quem a administra, se podia contratar com o Município e os alertas de empresa recente e sem experiência. Nenhum CPF aparece.'));
    }
    var conc = D.concentracao.filter(function (x) { return x.mes <= S.c && x.mes >= jan[0] && (!S.s || x.orgao === S.s); });
    h += painel('concentracao', 'Poucos levam quase tudo', 'Órgãos em que poucos credores levam a maior parte do contratado no ano.',
      conc.length ? '<div class="grade g2">' + conc.map(function (x) {
        return '<div class="kpi ruim"><span class="rot">' + esc(nomeSec(x.orgao)) + ', ' + esc(x.ano) + '</span><span class="val">' + esc(x.levam) + ' de ' + esc(x.credores) + ' credores</span><span class="det">levam ' + esc(x.corte) + '% de ' + num(x.total) + '</span></div>';
      }).join('') + '</div>' : '<p>' + selo('ok', 'sem concentração') + ' Nenhuma concentração acima do corte no recorte.</p>');
    h += blocoFichas(D.fichas, 'As fichas dos contratos', 'Dispensas no teto, fracionamento, emergenciais, aditivos e concentração.');
    return h;
  };

  // --- Contas -------------------------------------------------------------------------------
  T.contas = function () {
    var ano = +S.c.slice(0, 4);
    var ent = D.entregas.filter(function (e) { return e.exercicio >= ano - 1 && e.exercicio <= ano && e.mes <= S.c; });
    var atrasadas = ent.filter(function (e) { return !e.no_prazo; });
    var h = painel('entregas', 'As entregas ao Tesouro', 'Cada demonstrativo de ' + (ano - 1) + ' e ' + ano + ' com o prazo e a data da entrega no SICONFI.',
      '<div class="grade gk" style="margin-bottom:12px">' + kpi('Entregas no período', L.int(ent.length)) + kpi('Fora do prazo', L.int(atrasadas.length), 'pelo extrato do SICONFI', atrasadas.length ? 'ruim' : 'bom') + '</div>' +
      '<div class="rola"><table class="t cartoes"><thead><tr><th>Demonstrativo</th><th>Prazo</th><th>Entregue</th><th class="num">Atraso</th></tr></thead><tbody>' +
      ent.slice().reverse().map(function (e) {
        return '<tr><td data-r="Demonstrativo">' + esc(e.rotulo) + '</td><td data-r="Prazo">' + esc(L.data(e.prazo)) + '</td><td data-r="Entregue">' + esc(L.data(e.entregue)) + '</td><td class="num" data-r="Atraso">' +
          (e.no_prazo ? selo('ok', 'no prazo') : num(e.atraso, 'dias')) + '</td></tr>';
      }).join('') + '</tbody></table></div>', { eyebrow: 'Prestação de contas' });
    h += painel('anuais', 'As contas anuais', 'Prazos da ' + esc(D.norma) + '. A conferência é possível quando o banco tem os demonstrativos do exercício.',
      '<div class="rola"><table class="t cartoes"><thead><tr><th>Exercício</th><th>Entrega ao TCM</th><th>Parecer prévio até</th><th>Julgamento até</th><th>Conferência</th><th>Situação</th></tr></thead><tbody>' +
      D.anuais.filter(function (a) { return a.exercicio < ano; }).reverse().map(function (a) {
        return '<tr><td data-r="Exercício"><b>' + a.exercicio + '</b></td><td data-r="Entrega">' + esc(L.data(a.prazo_entrega)) + '</td><td data-r="Parecer">' + esc(L.data(a.parecer_ate)) + '</td><td data-r="Julgamento">' + esc(L.data(a.julgamento_ate)) +
          '</td><td data-r="Conferência">' + (a.conferencia === 'possível' ? selo('verde', 'possível') : selo('cinza', 'sem demonstrativos no banco')) + '</td><td data-r="Situação">' + selo('cinza', 'aguardando o TCM') + ' ' + origem(a.fonte, 'por quê') + '</td></tr>';
      }).join('') + '</tbody></table></div>');
    h += blocoFichas(D.fichas, 'As fichas de contas e prestações');
    return h;
  };

  // --- Indícios -----------------------------------------------------------------------------
  var FI = {
    familias: (U.get('fam') || '').split(',').filter(Boolean), gravidades: (U.get('g') || '').split(',').filter(Boolean),
    temas: (U.get('tema') || '').split(',').filter(Boolean), texto: U.get('q') || '', estacao: U.get('est') || '',
    etapas: (U.get('etapa') || '').split(',').filter(Boolean), condicoes: (U.get('cd') || '').split(',').filter(Boolean),
    de: U.get('de') || '', ate: U.get('ate') || '', hash: U.get('hash') || '', mostrar: 30
  };
  var TIPO_HASH = {
    achado: 'hash do achado', apoio: 'hash das provas do achado', prova: 'uma prova do achado',
    resposta: 'hash da resposta (sha256)', registro: 'hash do registro da coleta'
  };
  function resultadosHash(q) {
    if (!q) return '';
    var p = L.hexDe(q);
    if (p.length < 4) return '<p class="nota">Digite pelo menos 4 caracteres do hash (algarismos e as letras de a a f).</p>';
    var achados = L.buscarHash(p, D.fichas, D.hashes, 20);
    var tit = {}; C.paginas.forEach(function (pg) { tit[pg.id] = pg.titulo; });
    if (!achados.length) {
      return '<p class="sem-hash">' + icHash('sem') + 'Nenhum hash começando com <code class="hash">' + esc(p) + '</code> nas telas. ' +
        'Para procurar em todos os registros do banco: <code>python -m onisciente rastreio --hash ' + esc(p) + '</code>.</p>';
    }
    return '<p class="sub">' + achados.length + ' resultado(s) para <code class="hash">' + esc(p) + '</code>.</p><ul class="res-hash">' + achados.map(function (x) {
      var cab = icHash(x.v ? 'ok' : '') + '<code class="hash" title="' + esc(TIPO_HASH[x.t] + ': ' + x.h) + '"><mark>' + esc(x.h.slice(0, p.length)) + '</mark>' +
        esc(x.h.slice(p.length, Math.max(12, p.length))) + '</code><button type="button" class="copiar" data-copiar="' + esc(x.h) + '" aria-label="Copiar por inteiro: ' + esc(TIPO_HASH[x.t] || 'hash') + '">copiar</button> ' +
        '<span class="tipo">' + esc(TIPO_HASH[x.t] || x.t) + '</span>';
      if (x.ficha) {
        var u = new URLSearchParams(); u.set('c', S.c); u.set('s', ''); u.set('q', x.ficha); if (x.de) u.set('de', x.de); if (x.ate) u.set('ate', x.ate);
        return '<li>' + cab + '<br><a href="indicios.html?' + u.toString() + '#ficha-' + esc(x.ficha).replace(/[^A-Za-z0-9_-]/g, '_') + '">' +
          '<b>' + esc(x.ficha) + '</b> ' + esc(x.r) + '</a></li>';
      }
      return '<li>' + cab + (x.v ? ' <span class="confere">confere com o selo da rodada</span>' : '') + '<br>' + esc(x.r) +
        ' · <a href="' + link(x.p) + '">ver na tela ' + esc(tit[x.p] || x.p) + '</a>' +
        (x.u ? ' · <a href="' + esc(x.u) + '" target="_blank" rel="noopener">abrir o original</a>' : '') + '</li>';
    }).join('') + '</ul>';
  }
  function etapaPorId(id) { return (C.etapas || []).filter(function (e) { return e.id === id; })[0]; }
  // O cabeçalho da etapa escolhida: o que ela confere e as telas onde ela aparece em detalhe.
  function cabecalhoEtapa() {
    var e = etapaPorId(FI.etapas[0]); if (!e || FI.etapas.length > 1) return '';
    var i = (C.etapas || []).indexOf(e), telas = [];
    e.temas.forEach(function (t) { var pg = TEMAS[t] && TEMAS[t].pagina; if (pg && telas.indexOf(pg) < 0) telas.push(pg); });
    var tit = {}; C.paginas.forEach(function (p) { tit[p.id] = p.titulo; });
    return '<section class="painel etapa-cab" aria-label="Etapa escolhida">' + ic(e.id, 'etapa-ic') + '<div><p class="eyebrow">Etapa ' + (i + 1) + ' de ' + C.etapas.length + '</p><h2>' + esc(e.nome) + '</h2>' +
      '<p class="sub">' + esc(e.confere) + '. Em detalhe: ' + telas.map(function (pg) { return '<a href="' + link(pg) + '">' + esc(tit[pg] || pg) + '</a>'; }).join(' · ') +
      ' · <a href="' + link('indicios') + '">todas as etapas</a></p></div></section>';
  }
  T.indicios = function () {
    var fams = Object.keys(D.familias);
    var periodos = C.competencias.slice().reverse();
    var opt = function (sel) { return '<option value="">Competência do recorte</option>' + periodos.map(function (c) { return '<option value="' + c + '"' + (c === sel ? ' selected' : '') + '>' + esc(L.mes(c)) + '</option>'; }).join(''); };
    var rot = D.rotulos || {};
    var h = cabecalhoEtapa() + '<section class="painel" aria-label="Filtros dos indícios"><div class="filtros">' +
      '<fieldset><legend>Etapa</legend>' + (C.etapas || []).map(function (e) { return '<button type="button" class="chip" data-etapa="' + e.id + '" aria-pressed="' + (FI.etapas.indexOf(e.id) >= 0) + '">' + ic(e.id) + esc(e.nome) + '</button>'; }).join('') + '</fieldset>' +
      '<fieldset><legend>Condição</legend>' + [['alerta', 'Alerta'], ['sem_dado', 'Sem dado']].map(function (x) { return '<button type="button" class="chip" data-cond="' + x[0] + '" aria-pressed="' + (FI.condicoes.indexOf(x[0]) >= 0) + '">' + icCond(x[0]) + x[1] + '</button>'; }).join('') + '</fieldset>' +
      '<fieldset><legend>Família</legend>' + fams.map(function (f) { return '<button type="button" class="chip" data-fam="' + f + '" aria-pressed="' + (FI.familias.indexOf(f) >= 0) + '" title="' + esc(D.familias[f]) + '">' + esc(rot[f] || f) + '</button>'; }).join('') + '</fieldset>' +
      '<fieldset><legend>Gravidade</legend>' + ['critica', 'alta', 'media'].map(function (g2) { return '<button type="button" class="chip" data-grav="' + g2 + '" aria-pressed="' + (FI.gravidades.indexOf(g2) >= 0) + '">' + GRAV[g2] + '</button>'; }).join('') + '</fieldset>' +
      '<fieldset><legend>Tema</legend><select id="f-tema"><option value="">Todos os temas</option>' + Object.keys(TEMAS).map(function (t) { return '<option value="' + t + '"' + (FI.temas[0] === t ? ' selected' : '') + '>' + esc(TEMAS[t].titulo) + '</option>'; }).join('') + '</select></fieldset>' +
      '<fieldset><legend>Período</legend><select id="f-de" aria-label="De">' + opt(FI.de) + '</select><select id="f-ate" aria-label="Até">' + opt(FI.ate) + '</select></fieldset>' +
      '<fieldset><legend>Texto</legend><input type="search" id="f-texto" placeholder="Código, título ou norma" value="' + esc(FI.texto) + '"></fieldset>' +
      (FI.estacao ? '<fieldset><legend>Estação</legend><button type="button" class="chip" data-limpa-est aria-pressed="true">Estação ' + esc(FI.estacao) + ' ×</button></fieldset>' : '') +
      '</div></section>' +
      painel('busca-hash', 'Procurar por hash', 'Cole o hash, ou o começo dele (4 caracteres ou mais), de um achado, das provas de um achado, da resposta de uma fonte (sha256) ou do registro de uma coleta, como aparece no parecer, nas fichas e no balão de origem de cada número.',
        '<form class="busca-hash" role="search" onsubmit="return false"><label>' + icHash() + '<span class="sr">Hash</span><input type="search" id="f-hash" autocomplete="off" spellcheck="false" placeholder="ex.: 3fa2c1d0" value="' + esc(FI.hash) + '"></label></form>' +
        '<div id="res-hash" aria-live="polite">' + resultadosHash(FI.hash) + '</div>', { lamina: false }) +
      '<div id="lista-fichas"></div>';
    depois.push(function () {
      function sync() {
        var u = new URLSearchParams(); u.set('c', S.c); if (S.s) u.set('s', S.s);
        if (FI.familias.length) u.set('fam', FI.familias.join(',')); if (FI.gravidades.length) u.set('g', FI.gravidades.join(','));
        if (FI.temas.length) u.set('tema', FI.temas.join(',')); if (FI.texto) u.set('q', FI.texto); if (FI.estacao) u.set('est', FI.estacao);
        if (FI.etapas.length) u.set('etapa', FI.etapas.join(',')); if (FI.condicoes.length) u.set('cd', FI.condicoes.join(','));
        if (FI.de) u.set('de', FI.de); if (FI.ate) u.set('ate', FI.ate); if (FI.hash) u.set('hash', FI.hash);
        history.replaceState(null, '', '?' + u.toString());
      }
      function lista() {
        var f = L.filtrar(D.fichas, { c: S.c, s: S.s, de: FI.de || (FI.ate ? '0000-00' : ''), ate: FI.ate || (FI.de ? S.c : ''), familias: FI.familias, gravidades: FI.gravidades, temas: FI.temas, etapas: FI.etapas, condicoes: FI.condicoes, texto: FI.texto, estacao: FI.estacao, estacoesDaFamilia: D.estacoes_da_familia });
        var ord = { critica: 0, alta: 1, media: 2 }, ordT = Object.keys(TEMAS);
        // Com etapa, secretaria ou tema escolhidos a lista sai inteira, agrupada por tema: a ficha fica a um clique.
        var inteira = !!(FI.etapas.length || FI.temas.length || S.s);
        f.sort(function (a, b) {
          return (inteira ? ordT.indexOf(a.tema) - ordT.indexOf(b.tema) : 0) || (ord[a.gravidade] - ord[b.gravidade]) || (L.periodoDa(b)[1] > L.periodoDa(a)[1] ? 1 : -1);
        });
        var corpo = '', tAnt = null, vis = inteira ? f : f.slice(0, FI.mostrar);
        vis.forEach(function (fi) {
          if (inteira && fi.tema !== tAnt) {
            corpo += (tAnt === null ? '' : '</div>') + '<h3 class="grupo-lista">' + esc(TEMAS[fi.tema] ? TEMAS[fi.tema].titulo : fi.tema) + '</h3><div class="fichas">';
            tAnt = fi.tema;
          }
          corpo += ficha(fi);
        });
        corpo = inteira ? corpo + (vis.length ? '</div>' : '') : '<div class="fichas">' + corpo + '</div>';
        var periodo = FI.de || FI.ate ? 'de ' + L.mes(FI.de || C.competencias[0]) + ' a ' + L.mes(FI.ate || S.c) : 'em ' + L.mes(S.c);
        document.getElementById('lista-fichas').innerHTML = '<p class="sub" aria-live="polite" style="margin-bottom:10px"><b>' + f.length + '</b> ficha(s) ' + esc(periodo) + (S.s ? ', ' + esc(nomeSec(S.s)) : '') + '.</p>' +
          (f.length ? corpo + (!inteira && f.length > FI.mostrar ? '<p style="margin-top:12px"><button type="button" class="bt" id="mais">Mostrar mais ' + Math.min(30, f.length - FI.mostrar) + '</button></p>' : '')
            : vazio('Nenhuma ficha com estes filtros', 'Tire um filtro ou mude o período.'));
        var m = document.getElementById('mais'); if (m) m.onclick = function () { FI.mostrar += 30; lista(); };
        marcarLaminas();
      }
      document.querySelectorAll('[data-fam]').forEach(function (b) { b.onclick = function () { tog(FI.familias, b.dataset.fam); b.setAttribute('aria-pressed', FI.familias.indexOf(b.dataset.fam) >= 0); FI.mostrar = 30; sync(); lista(); }; });
      document.querySelectorAll('[data-etapa]').forEach(function (b) { b.onclick = function () { tog(FI.etapas, b.dataset.etapa); FI.mostrar = 30; sync(); desenhar(); }; });
      document.querySelectorAll('[data-cond]').forEach(function (b) { b.onclick = function () { tog(FI.condicoes, b.dataset.cond); b.setAttribute('aria-pressed', FI.condicoes.indexOf(b.dataset.cond) >= 0); FI.mostrar = 30; sync(); lista(); }; });
      document.querySelectorAll('[data-grav]').forEach(function (b) { b.onclick = function () { tog(FI.gravidades, b.dataset.grav); b.setAttribute('aria-pressed', FI.gravidades.indexOf(b.dataset.grav) >= 0); FI.mostrar = 30; sync(); lista(); }; });
      document.getElementById('f-tema').onchange = function () { FI.temas = this.value ? [this.value] : []; sync(); lista(); };
      document.getElementById('f-de').onchange = function () { FI.de = this.value; sync(); lista(); };
      document.getElementById('f-ate').onchange = function () { FI.ate = this.value; sync(); lista(); };
      document.getElementById('f-texto').oninput = function () { FI.texto = this.value; sync(); lista(); };
      document.getElementById('f-hash').oninput = function () { FI.hash = this.value.trim(); sync(); document.getElementById('res-hash').innerHTML = resultadosHash(FI.hash); };
      var le = document.querySelector('[data-limpa-est]'); if (le) le.onclick = function () { FI.estacao = ''; sync(); desenhar(); };
      lista();
    });
    return h;
  };
  function tog(lista, v) { var i = lista.indexOf(v); if (i >= 0) lista.splice(i, 1); else lista.push(v); }

  var AUD = { cumpre: ['verde', 'atendido'], falha: ['roxo', 'não atendido'], sem_dado: ['cinza', 'não verificável'] };
  function seloAud(x) { var a = AUD[x] || AUD.sem_dado; return selo(a[0], a[1]); }
  var NOME_LEITURA = { oficial: 'Leitura oficial', restritiva: 'Leitura restritiva' };
  var NOME_MODO = { comprovada: 'comprovada', teto: 'no teto' };
  function telaSelo(sl) {
    var dec = sl.declarado || {}, h = '';
    var decVal = esc(dec.nivel || '') + (dec.nota ? ' · ' + num(dec.nota, 'int') : (dec.nota_texto ? ' · ' + esc(dec.nota_texto) : ''));
    var leit = sl.leituras || [];
    var oficial = leit.filter(function (x) { return x.leitura === 'oficial' && x.modo === 'comprovada'; })[0];
    h += painel('selo', 'O selo declarado e o selo refeito', esc(sl.programa || '') + '. O Onisciente refaz a avaliação critério por critério, como auditor independente, em duas leituras: a oficial (a da cartilha) e a restritiva (a que exige a prova completa). Cada uma aparece comprovada (só o que as provas lidas mostram) e no teto (o máximo possível com o que falta provar).',
      '<div class="grade g2">' + kpi('Declarado', decVal, 'ciclo ' + esc(dec.ciclo || '') + (dec.nota ? '' : ', sem a nota exata publicada') + ' ' + origem(dec.fonte, 'ver a notícia')) +
      (oficial ? kpi('Refeito pelo Onisciente', esc(oficial.nivel || '') + ' · ' + num(oficial.indice, 'pct'), 'leitura oficial, só com as provas lidas', oficial.selo ? 'bom' : 'critico')
        : kpi('Refeito pelo Onisciente', esc((sl.auditado || {}).nivel || 'sem cálculo') + ((sl.auditado || {}).nota ? ' · ' + num(sl.auditado.nota, 'int') : ''), 'com as provas abaixo',
          sl.auditado && sl.auditado.nota && dec.nota && sl.auditado.nota.v < dec.nota.v ? 'critico' : 'bom')) + '</div>' +
      (sl.veredito && sl.veredito.frase ? '<p class="destaque" style="margin:12px 0">' + esc(sl.veredito.frase) + '</p>' : '') +
      (leit.length ? '<div class="rola"><table class="t cartoes"><thead><tr><th>Leitura</th><th>Modo</th><th class="num">Índice</th><th>Nível</th><th>Essenciais em falta</th></tr></thead><tbody>' +
        leit.map(function (x) {
          return '<tr><td data-r="Leitura"><b>' + esc(NOME_LEITURA[x.leitura] || x.leitura) + '</b></td><td data-r="Modo">' + esc(NOME_MODO[x.modo] || x.modo) + '</td><td class="num" data-r="Índice">' + num(x.indice, 'pct') +
            '</td><td data-r="Nível">' + selo(x.selo ? 'ok' : 'indicio', x.nivel || '') + '</td><td data-r="Essenciais em falta">' + (x.essenciais_em_falta.length ? esc(x.essenciais_em_falta.join(', ')) : 'nenhum') + '</td></tr>';
        }).join('') + '</tbody></table></div>' : '') +
      (dec.ciclo_seguinte ? '<p class="nota">' + esc(dec.ciclo_seguinte) + '</p>' : '') +
      (sl.radar && !sl.radar.lido && sl.radar.motivo ? '<p class="nota">' + selo('cinza', 'Radar não lido') + ' ' + esc(sl.radar.motivo) + '.</p>' : ''), { eyebrow: 'Prestação de contas' });
    (sl.orgaos || []).forEach(function (o) {
      if (S.s && o.cnpj && o.cnpj !== S.s) return;
      h += painel('selo-' + esc(o.sigla.toLowerCase()), o.orgao, esc(o.nivel) + '. ' + esc(o.texto),
        '<div class="rola"><table class="t cartoes"><thead><tr><th>Obrigação</th><th>Situação</th><th class="num">Dinheiro em jogo</th><th>O que se viu</th></tr></thead><tbody>' +
        o.obrigacoes.map(function (x) {
          return '<tr><td data-r="Obrigação"><b>' + esc(x.id) + '</b> ' + esc(x.texto) + '<br><span class="nota">' + esc(x.base) + (x.pntp ? '; PNTP ' + esc(x.pntp) : '') + '</span></td><td data-r="Situação">' +
            (x.alerta ? selo('roxo', x.estado || 'em falta') : selo('ok', x.estado || 'cumprida')) + '</td><td class="num" data-r="Em jogo">' + (x.valor ? num(x.valor) : '') +
            '</td><td data-r="O que se viu">' + x.provas.slice(0, 3).map(function (pv) { return '<span class="nota">' + esc(pv) + '</span>'; }).join('<br>') + '</td></tr>';
        }).join('') + '</tbody></table></div>', { eyebrow: 'Fundo e Conselho' });
    });
    var crit = sl.criterios || [];
    var cont = { cumpre: 0, falha: 0, sem_dado: 0 };
    crit.forEach(function (c) { cont[c.auditado] = (cont[c.auditado] || 0) + 1; });
    h += painel('criterios', 'Critério por critério', crit.length + ' critérios. Na leitura oficial: ' + cont.cumpre + ' atendido(s), ' + cont.falha + ' não atendido(s), ' + cont.sem_dado + ' não verificável(is). Não verificável é prova que o sistema ainda não leu (cinza), nunca culpa do Município.',
      '<div class="rola"><table class="t cartoes"><thead><tr><th>Critério</th><th>Peso</th><th>Oficial</th><th>Restritiva</th><th>Prova</th></tr></thead><tbody>' +
      crit.map(function (c) {
        return '<tr><td data-r="Critério"><b>' + esc(c.id) + '</b> ' + esc(c.criterio) + (c.nota ? '<br><span class="nota">' + esc(c.nota) + '</span>' : '') + '</td><td data-r="Peso">' + esc(c.peso || '') + '</td><td data-r="Oficial">' + seloAud(c.auditado) +
          '</td><td data-r="Restritiva">' + seloAud(c.auditado_restritiva || c.auditado) + '</td><td data-r="Prova">' + origem(c.fonte, 'abrir') + '</td></tr>';
      }).join('') + '</tbody></table></div>');
    if ((sl.pendencias || []).length) h += painel('pendencias', 'O que ainda falta na própria auditoria', '', sl.pendencias.map(function (pd) { return '<p class="nota">' + esc(pd) + '</p>'; }).join(''), { lamina: false });
    return h;
  }

  // --- Transparência ------------------------------------------------------------------------
  T.transparencia = function () {
    var h = '';
    var cs = coleta('selo_transparencia');
    if (D.selo) h += telaSelo(D.selo);
    else if (cs) h += painel('selo', 'O selo de transparência, auditado', '', naoFeita(cs, 'auditoria do selo de transparência', 'Quando a auditoria do selo for gerada, esta seção mostra o selo declarado ao lado do selo refeito, critério por critério.'), { eyebrow: 'Prestação de contas' });
    else {
      h += painel('selo', 'O selo de transparência, auditado', '', vazio('Aguardando a coleta do selo de transparência',
        'O Município apresenta um selo de transparência. Quando a frente do selo entregar a metodologia replicada e as provas de cada critério, esta seção mostra o selo declarado ao lado do selo refeito pelo Onisciente, critério por critério, e a nota de cada secretaria. Enquanto isso, o que a lei manda publicar e não está publicado aparece logo abaixo.'), { eyebrow: 'Prestação de contas' });
    }
    var aus = D.ausencias.filter(function (a) { return a.cs.indexOf(S.c) >= 0 && (!S.s || a.secretarias.indexOf(S.s) >= 0); });
    var mun = D.municipio.filter(function (a) { return a.mes <= S.c; });
    h += painel('ausencias', 'O que a lei manda publicar e não está publicado', (aus.length + mun.length) + ' ausência(s) no recorte. Cada uma impede uma conferência e vira item de ofício.',
      (aus.length || mun.length ? '<div class="rola"><table class="t cartoes"><thead><tr><th>O que falta</th><th>Onde deveria estar</th><th>Conferência impedida</th><th>Fundamento</th></tr></thead><tbody>' +
        aus.map(function (a) {
          return '<tr><td data-r="O que falta">' + selo('roxo') + ' <b>' + esc(a.o_que_falta) + '</b>' + (a.periodo ? '<br><span class="nota">' + esc(a.periodo) + '</span>' : '') + '</td><td data-r="Onde">' + esc(a.onde_deveria_estar) + '</td><td data-r="Conferência">' + esc(a.conferencia_impedida) + '</td><td data-r="Fundamento">' + esc(a.fundamento) + '</td></tr>';
        }).join('') + mun.map(function (a) {
          return '<tr><td data-r="O que falta">' + selo('roxo') + ' <b>' + esc(a.o_que_falta) + '</b><br><span class="nota">prazo ' + esc(L.data(a.prazo)) + '</span></td><td data-r="Onde">' + esc(a.onde) + '</td><td data-r="Conferência">' + origem(a.fonte, 'ver') + '</td><td data-r="Fundamento">' + esc(a.fundamento) + '</td></tr>';
        }).join('') + '</tbody></table></div>' : '<p>' + selo('ok', 'nada faltando') + ' Nenhuma ausência registrada neste recorte.</p>'));
    var ofs = D.oficios[S.c] || [];
    h += painel('oficios', 'Os ofícios prontos', 'Pedido de acesso à informação pronto para protocolo, um por órgão, com os itens que faltam.',
      ofs.length ? ofs.map(function (o, i) {
        return '<h3 style="font-size:16px;margin:10px 0 6px">' + esc(o.destinatario) + ' · ' + o.itens + ' item(ns) <button type="button" class="bt" data-copiar="of-' + i + '">Copiar o texto</button></h3><pre class="oficio" id="of-' + i + '">' + esc(o.texto) + '</pre>';
      }).join('') : '<p class="sub">Nenhum ofício gerado para ' + esc(L.mes(S.c)) + '.</p>');
    h += painel('escada', 'Se não responderem', 'A escada contra a não resposta, degrau por degrau.',
      '<div class="escada">' + D.escada.map(function (d) {
        return '<div class="degrau"><p class="eyebrow">Degrau ' + d.n + '</p><h3>' + esc(d.nome) + '</h3><p>' + esc(d.fundamento) + '</p><p>' + (d.decidir ? 'Resposta em ' + d.decidir + ' dias. ' : '') + (d.agir ? 'Recurso em ' + d.agir + ' dias. ' : '') + esc(d.obs || '') + '</p></div>';
      }).join('') + '</div>');
    var falhas = D.falhas.filter(function (x) { return !x.mes || x.mes.slice(0, 4) === S.c.slice(0, 4); });
    h += painel('falhas', 'O que o próprio sistema não conseguiu ler', 'Falha do Onisciente, nunca imputada ao Município: ' + falhas.length + ' leitura(s) falharam no ano. Cada uma é refeita na próxima coleta.',
      falhas.length ? '<details><summary>Ver as leituras que falharam</summary><div class="rola"><table class="t"><thead><tr><th>Fonte</th><th>O que</th><th>Erro</th></tr></thead><tbody>' + falhas.slice(0, 100).map(function (x) {
        return '<tr><td>' + selo('vermelho') + ' ' + esc(x.motor) + '</td><td>' + esc(x.alvo) + ' ' + esc(x.mes) + '</td><td class="nota">' + esc(x.erro) + '</td></tr>';
      }).join('') + '</tbody></table></div></details>' : '<p>' + selo('ok', 'sem falhas') + ' Todas as leituras do ano deram certo.</p>', { lamina: false });
    h += blocoFichas(D.fichas, 'As fichas de transparência, leis e sistema');
    depois.push(function () {
      document.querySelectorAll('[data-copiar]').forEach(function (b) {
        b.onclick = function () {
          var t = document.getElementById(b.dataset.copiar).textContent;
          (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(function () { b.textContent = 'Copiado'; }, function () { b.textContent = 'Selecione e copie'; });
        };
      });
    });
    return h;
  };

  // --- Previsto e realizado-----------------------------------------------------------------
  T.tempo = function () {
    var fun = funcaoDoRecorte();
    var anos = D.anos;
    var h = '';
    var x = anos.map(function (a) { return String(a.ano); });
    var proj = {}; (fun ? (D.projecao_funcao[fun] || []) : D.projecao).forEach(function (p) { proj[p.ano] = p; });
    var serieDot = anos.map(function (a) { return fun ? (a.funcoes && a.funcoes[fun] ? a.funcoes[fun].dotacao : null) : a.dotacao || null; });
    var serieReal = anos.map(function (a) { return fun ? (a.funcoes && a.funcoes[fun] ? a.funcoes[fun].liquidado : null) : a.pago || null; });
    var serieProj = anos.map(function (a) { return proj[a.ano] && proj[a.ano].projetado && proj[a.ano].projetado.v !== null ? proj[a.ano].projetado : null; });
    h += painel('linha', 'Previsto e realizado, de ' + D.primeiro + ' a ' + D.ultimo_ppa, (fun ? 'Função ' + esc(nomeFuncao(fun)) + ': dotação atualizada e liquidado' : 'Município: dotação atualizada e despesa paga') +
      ' por exercício, pelo RREO; os anos futuros e o ano corrente trazem a projeção pela ' + esc(D.regua) + '.',
      grafico({
        titulo: 'Previsto e realizado', x: x, agora: x.indexOf(S.c.slice(0, 4)),
        series: [{ nome: 'Previsto (dotação atualizada)', cl: 'b1', cor: 'var(--royal)', vals: serieDot },
        { nome: fun ? 'Realizado (liquidado)' : 'Realizado (pago)', cl: 'b2', cor: 'var(--gold)', vals: serieReal },
        { nome: 'Projetado', cl: 'b3', cor: 'var(--vinc)', vals: serieProj }]
      }) + (D.falta ? '<p style="margin-top:10px">' + selo('alerta', 'projeção limitada') + ' ' + esc(D.falta) + '</p>' : ''), { eyebrow: 'Orçamento' });
    h += painel('anos', 'Ano a ano', 'Os exercícios sem RREO no banco aparecem como lacuna da coleta, em cinza.',
      '<div class="rola"><table class="t cartoes"><thead><tr><th>Ano</th><th>Situação</th><th class="num">Receita prevista</th><th class="num">Receita realizada</th><th class="num">Dotação</th><th class="num">Empenhado</th><th class="num">Pago</th></tr></thead><tbody>' +
      anos.map(function (a) {
        var sit = { fechado: selo('verde', 'fechado'), parcial: selo('azul', 'até o ' + a.bimestre + 'º bimestre'), sem_dado: selo('cinza', 'fora do banco'), futuro: selo('cinza', 'futuro') }[a.tipo];
        return '<tr' + (String(a.ano) === S.c.slice(0, 4) ? ' class="marcada"' : '') + '><td data-r="Ano"><b>' + a.ano + '</b></td><td data-r="Situação">' + sit + ' ' + origem(a.fonte, 'origem') + '</td>' +
          ['receita_prevista', 'receita_realizada', 'dotacao', 'empenhado', 'pago'].map(function (k) { return '<td class="num" data-r="' + k.replace('_', ' ') + '">' + (a[k] ? num(a[k]) : '') + '</td>'; }).join('') + '</tr>';
      }).join('') + '</tbody></table></div>');
    h += blocoFichas(D.fichas, 'As fichas do orçamento e da receita', 'Previsão, dotação e o ritmo da arrecadação.');
    return h;
  };

  // ===========================================================================================
  // Moldura: recorte, régua, caminho, apresentação
  // ===========================================================================================
  function montarSeletores() {
    var sa = document.getElementById('sel-alvo'), sp = document.getElementById('sel-periodo'), ss = document.getElementById('sel-secretaria');
    sa.innerHTML = (C.alvos.length ? C.alvos : [C.alvo]).map(function (a) { return '<option value="' + esc(a.id) + '">' + esc(a.nome) + '</option>'; }).join('');
    sa.onchange = function () { var a = C.alvos.filter(function (x) { return x.id === sa.value; })[0]; if (a && a.url) location.href = a.url; };
    sp.innerHTML = C.competencias.slice().reverse().map(function (c) {
      return '<option value="' + c + '"' + (c === S.c ? ' selected' : '') + '>' + esc(L.mes(c)) + (C.pareceres.indexOf(c) >= 0 ? ' · parecer' : '') + '</option>';
    }).join('');
    var pasta = C.secretarias.filter(function (s) { return s.pasta; }), outras = C.secretarias.filter(function (s) { return !s.pasta; });
    function op(s) { return '<option value="' + s.id + '"' + (s.id === S.s ? ' selected' : '') + '>' + esc(s.nome) + '</option>'; }
    ss.innerHTML = '<option value="">Município inteiro</option>' + (pasta.length ? '<optgroup label="Pasta fiscalizada">' + pasta.map(op).join('') + '</optgroup>' : '') +
      '<optgroup label="Demais órgãos">' + outras.map(op).join('') + '</optgroup>';
    sp.onchange = function () { mudar({ c: sp.value }); };
    ss.onchange = function () { mudar({ s: ss.value }); };
    var br = document.getElementById('bt-recorte'), rec = document.getElementById('recorte');
    if (window.matchMedia('(max-width: 760px)').matches) {
      br.hidden = false;
      br.onclick = function () { var ab = rec.dataset.aberto !== 'true'; rec.dataset.aberto = ab; br.setAttribute('aria-expanded', ab); };
    }
  }
  function mudar(novo) {
    if (novo.c !== undefined) S.c = novo.c;
    if (novo.s !== undefined) S.s = novo.s;
    gravarStorage('onisciente.recorte', JSON.stringify(S));
    var u = new URLSearchParams(location.search); u.set('c', S.c); if (S.s) u.set('s', S.s); else u.delete('s');
    history.replaceState(null, '', '?' + u.toString() + location.hash);
    document.getElementById('sel-periodo').value = S.c; document.getElementById('sel-secretaria').value = S.s;
    desenhar();
  }
  function atualizarMoldura() {
    var cont = L.contar(IND, S.c, S.s);
    document.querySelectorAll('[data-cont]').forEach(function (el) {
      var r = L.contarPagina(cont, TEMAS, el.dataset.cont);
      el.innerHTML = r.n ? '<i' + (r.critica ? ' class="c"' : '') + ' aria-hidden="true"></i>' + r.n + '<span class="sr"> indício(s)</span>' : (el.dataset.cont === 'leis' ? '' : '<i class="z" aria-hidden="true"></i>0');
    });
    document.querySelectorAll('a[data-pagina]').forEach(function (a) { a.href = link(a.dataset.pagina); });
    var resumo = L.mes(S.c) + ' · ' + (S.s ? nomeSec(S.s) : 'Município inteiro');
    document.getElementById('onde').textContent = 'Recorte: ' + resumo + '. ' + C.alvo.nome + '.';
    document.getElementById('resumo-recorte').textContent = resumo;
    document.getElementById('gerado').textContent = 'Gerado em ' + L.data(C.gerado_em) + ' a partir do banco histórico, versão ' + C.versao + '.';
    var i = ORDEM.indexOf(PID), ant = ORDEM[i - 1], prox = ORDEM[i + 1];
    var tit = {}; C.paginas.forEach(function (p) { tit[p.id] = p.titulo; });
    document.getElementById('caminho').innerHTML = (ant ? '<a href="' + link(ant) + '"><small>Tela anterior</small><b>' + esc(tit[ant]) + '</b></a>' : '<span></span>') +
      (prox ? '<a class="prox" href="' + link(prox) + '"><small>Seguindo o dinheiro</small><b>' + esc(tit[prox]) + '</b></a>'
        : '<a class="prox" href="' + link('index') + '"><small>Seguindo o dinheiro</small><b>De volta às etapas</b></a>');
  }
  function desenhar() {
    depois = [];
    var tela = document.getElementById('tela');
    try { tela.innerHTML = faixa() + (T[PID] || function () { return ''; })(); }
    catch (e) { tela.innerHTML = vazio('Esta tela não pôde ser desenhada', 'Erro: ' + e.message, false); if (window.console) console.error(e); }
    depois.forEach(function (f) { f(); });
    atualizarMoldura();
    marcarLaminas();
  }

  // --- modo apresentação --------------------------------------------------------------------
  var lam = [], li = 0, apresentando = false;
  function marcarLaminas() { lam = Array.prototype.slice.call(document.querySelectorAll('#tela .lamina')); if (apresentando) irPara(Math.min(li, lam.length - 1)); }
  function irPara(i) {
    if (!lam.length) return;
    lam.forEach(function (l) { l.classList.remove('agora'); });
    li = Math.max(0, Math.min(i, lam.length - 1));
    lam[li].classList.add('agora');
    document.getElementById('palco-cont').textContent = (li + 1) + ' de ' + lam.length;
    var tit = C.paginas.filter(function (p) { return p.id === PID; })[0];
    document.getElementById('palco-tela').textContent = tit.titulo + ' · ' + L.mes(S.c) + (S.s ? ' · ' + nomeSec(S.s) : '') + '. Passe o mouse nos números para ver a origem.';
    if (PID === 'origem' && lam[li].id === 'sankey') desenharSankey();
  }
  function apresentar(liga, inicio) {
    apresentando = liga; document.body.classList.toggle('apresentando', liga);
    document.getElementById('bt-apresentar').setAttribute('aria-pressed', liga);
    if (liga) { marcarLaminas(); irPara(inicio === -1 ? lam.length - 1 : (inicio || 0)); if (document.documentElement.requestFullscreen && !document.fullscreenElement) document.documentElement.requestFullscreen().catch(function () { }); }
    else { lam.forEach(function (l) { l.classList.remove('agora'); }); if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(function () { }); }
    var u = new URLSearchParams(location.search); if (liga) u.set('apresentar', '1'); else { u.delete('apresentar'); u.delete('l'); } history.replaceState(null, '', '?' + u.toString());
  }
  function passo(d) {
    if (li + d >= lam.length) { var i = ORDEM.indexOf(PID); if (ORDEM[i + 1]) location.href = link(ORDEM[i + 1], { apresentar: 1, l: 0 }); return; }
    if (li + d < 0) { var j = ORDEM.indexOf(PID); if (j > 0) location.href = link(ORDEM[j - 1], { apresentar: 1, l: -1 }); return; }
    irPara(li + d);
  }
  document.addEventListener('keydown', function (e) {
    if (e.target.closest && e.target.closest('input,select,textarea')) return;
    if (apresentando) {
      if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') { e.preventDefault(); passo(1); }
      else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); passo(-1); }
      else if (e.key === 'Escape') apresentar(false);
    } else if ((e.key === 'p' || e.key === 'P') && !e.ctrlKey && !e.metaKey && !e.altKey) apresentar(true);
  });
  document.addEventListener('fullscreenchange', function () { if (!document.fullscreenElement && apresentando) apresentar(false); });

  // --- partida ------------------------------------------------------------------------------
  montarSeletores();
  document.getElementById('bt-apresentar').onclick = function () { apresentar(!apresentando); };
  document.getElementById('palco-sair').onclick = function () { apresentar(false); };
  document.getElementById('bt-tema').onclick = function () {
    var r = document.documentElement, escuro = r.dataset.theme ? r.dataset.theme === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
    r.dataset.theme = escuro ? 'light' : 'dark'; gravarStorage('onisciente.tema', r.dataset.theme);
  };
  var topo = document.querySelector('.topo');
  function altura() { document.documentElement.style.setProperty('--alto-topo', topo.offsetHeight + 'px'); }
  altura(); window.addEventListener('resize', altura);
  desenhar();
  if (U.get('apresentar') === '1') apresentar(true, +(U.get('l') || 0));
  if (location.hash) { var alvo = document.getElementById(location.hash.slice(1)); if (alvo) setTimeout(function () { alvo.scrollIntoView(); if (alvo.tagName === 'DETAILS') alvo.open = true; }, 30); }
})();
