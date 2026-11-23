/* =========================================================================
 * BioImpresora – interfaz: paneles de parámetros, escena 3D y panel de IA
 * ========================================================================= */
(function () {
  'use strict';
  var $ = function (s) { return document.querySelector(s); };
  var el = function (tag, attrs, html) { var e = document.createElement(tag); if (attrs) for (var k in attrs) { if (k === 'class') e.className = attrs[k]; else e.setAttribute(k, attrs[k]); } if (html !== undefined) e.innerHTML = html; return e; };
  var clon = function (o) { return JSON.parse(JSON.stringify(o)); };
  function getP(o, p) { return p.split('.').reduce(function (a, k) { return a == null ? a : a[k]; }, o); }
  function setP(o, p, v) { var ks = p.split('.'), last = ks.pop(); ks.reduce(function (a, k) { return a[k]; }, o)[last] = v; }
  function fusionar(base, extra) { for (var k in extra) { if (extra[k] && typeof extra[k] === 'object' && !Array.isArray(extra[k]) && base[k] && typeof base[k] === 'object') fusionar(base[k], extra[k]); else base[k] = extra[k]; } return base; }
  function fmtT(s) { s = Math.max(0, s); var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), ss = Math.floor(s % 60); return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(ss).padStart(2, '0'); }
  function descargar(nombre, contenido, tipo) { var a = el('a', { href: URL.createObjectURL(new Blob([contenido], { type: tipo || 'text/plain' })), download: nombre }); document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500); }

  // ------------------------------------------------------------------ estado
  var CLAVE_LS = 'bioimpresora.cfg.v1';
  var cfg = CORE.defaults();
  try { var g = localStorage.getItem(CLAVE_LS); if (g) fusionar(cfg, JSON.parse(g)); } catch (e) { /* sin almacenamiento */ }
  var modelo = { tipo: 'implicita', id: 'corazon' }; // fuente actual
  var stl = null; // {nombre, crudo, crudoB, tam, ejeY, tris, trisB, clave}
  var sim = null, simId = 0, tSim = 0, reproduciendo = false;
  var ia = { hist: [], mejor: null, claves: [], estado: 'inactivo', sens: null, op: { episodios: 150, ensamble: 5, ocultas: '32,32', kappa: 2, resEntreno: 28, lr: 0.003, autoVer: true } };
  function guardarLS() { try { localStorage.setItem(CLAVE_LS, JSON.stringify(cfg)); } catch (e) { /* ignorar */ } }

  // ------------------------------------------------------------------ workers
  var srcWorker = $('#core-src').textContent + '\n' + $('#worker-src').textContent;
  function crearWorker() {
    try { return new Worker(URL.createObjectURL(new Blob([srcWorker], { type: 'text/javascript' }))); }
    catch (e) { // sin Web Workers (p. ej. políticas de file://): ejecutar en el hilo principal
      var w = { onmessage: null }, falso = { postMessage: function (d) { setTimeout(function () { w.onmessage && w.onmessage({ data: d }); }, 0); } };
      new Function('self', $('#worker-src').textContent)(falso);
      w.postMessage = function (d) { setTimeout(function () { falso.onmessage({ data: d }); }, 0); };
      w.terminate = function () {};
      return w;
    }
  }
  var wSim = crearWorker(), wIA = crearWorker();

  function descFuente() {
    if (modelo.tipo === 'implicita') return { tipo: 'implicita', id: modelo.id };
    return { tipo: 'malla', clave: stl.clave, nombre: stl.nombre, tris: stl.tris, trisB: stl.trisB };
  }

  // ------------------------------------------------------------------ esquema de paneles
  function N(path, label, unit, min, max, step, extra) { return Object.assign({ t: 'n', path: path, label: label, unit: unit, min: min, max: max, step: step }, extra || {}); }
  function S(path, label, ops) { return { t: 's', path: path, label: label, ops: ops }; }
  function C(path, label) { return { t: 'c', path: path, label: label }; }
  function T(path, label) { return { t: 'x', path: path, label: label }; }
  function H(txt) { return { t: 'h', txt: txt }; }
  function A(txt) { return { t: 'a', txt: txt }; }

  function camposExtrusor(k, nom) {
    return [H(nom), N('maquina.' + k + '.diam', 'Diámetro de boquilla', 'mm', 0.1, 1.0, 0.01), N('maquina.' + k + '.largo', 'Longitud de boquilla', 'mm', 2, 25, 0.5),
      N('maquina.' + k + '.temp', 'Temperatura del cartucho', '°C', 4, 40, 0.5), N('maquina.' + k + '.v_viaje', 'Velocidad de viaje', 'mm/s', 5, 150, 1),
      N('maquina.' + k + '.acel', 'Aceleración', 'mm/s²', 50, 3000, 10), N('maquina.' + k + '.radio', 'Radio de exclusión (antichoque)', 'mm', 0.5, 10, 0.1)];
  }
  function camposTinta(k, nom) {
    return [H(nom), T(k + '.nombre', 'Nombre'),
      N(k + '.tau0', 'Esfuerzo umbral τ0', 'Pa', 0, 1000, 1), N(k + '.K', 'Consistencia K', 'Pa·sⁿ', 1, 400, 1), N(k + '.n', 'Índice de flujo n', '', 0.15, 1, 0.01),
      N(k + '.densidad', 'Densidad', 'g/mL', 0.95, 1.2, 0.005), N(k + '.alpha_gel', 'Conversión de gelificación α_gel', '', 0.05, 0.8, 0.01),
      N(k + '.k_cura', 'Constante de curado k', 's⁻¹·(mW/cm²)^-½', 0.005, 0.5, 0.001), N(k + '.mu', 'Atenuación óptica base μ', '1/mm', 0, 3, 0.01),
      N(k + '.mu_pi', 'Atenuación por % de primer', '1/(mm·%)', 0, 5, 0.05), N(k + '.i_inh', 'Umbral inhibición O₂', 'mW/cm²', 0, 20, 0.1),
      N(k + '.t_ext', 'Tiempo de extensión (slumping)', 's', 0.5, 200, 0.5), N(k + '.ext_max', 'Ensanchamiento máximo', '×', 0, 2, 0.01),
      C(k + '.celulas', 'Contiene células'), N(k + '.dens_cel', 'Densidad celular', 'M cél/mL', 0, 50, 0.5),
      N(k + '.tau_crit', 'Cizalla crítica celular', 'Pa', 100, 10000, 50), N(k + '.dosis_letal', 'Dosis UV letal (1/e)', 'mJ/cm²', 20, 3000, 10)];
  }

  var PANELES = [
    { id: 'modelo', nombre: 'Modelo', campos: null },
    { id: 'maquina', nombre: 'Máquina', campos: [].concat(
      camposExtrusor('e1', 'Extrusor E1 · material A'), camposExtrusor('e2', 'Extrusor E2 · material B'),
      [H('Brazo UV'), S('maquina.uv.lambda', 'Longitud de onda', [[365, '365 nm'], [385, '385 nm'], [405, '405 nm']]),
        N('maquina.uv.spot', 'Diámetro del spot', 'mm', 0.5, 15, 0.1), N('maquina.uv.i_max', 'Intensidad máxima', 'mW/cm²', 5, 300, 1),
        N('maquina.uv.sep', 'Separación entre pasadas', 'mm', 0.2, 15, 0.1), N('maquina.uv.v_viaje', 'Velocidad de viaje', 'mm/s', 5, 150, 1),
        N('maquina.uv.radio', 'Radio de exclusión', 'mm', 0.5, 10, 0.1),
        H('Brazo auxiliar (AUX)'), A('Sin uso: permanece estacionado fuera de la zona de impresión. Reservado para cámara, tercer material o pinza.'),
        T('maquina.aux.rol', 'Rol / nota'),
        H('General'), N('maquina.t_cambio_capa', 'Tiempo de cambio de capa', 's', 0, 10, 0.1)]) },
    { id: 'tintas', nombre: 'Biotintas', campos: [].concat(
      [H('Primer (fotoiniciador)'), S('primer.tipo', 'Tipo de fotoiniciador', [['LAP', 'LAP'], ['I2959', 'Irgacure 2959'], ['Ru/SPS', 'Ru/SPS']]),
        A('La eficiencia depende de la longitud de onda del brazo UV (p. ej. I2959 casi no cura a 405 nm). La concentración se ajusta en Proceso.')],
      camposTinta('tintaA', 'Material A · biopolímero estructural (E1)'), camposTinta('tintaB', 'Material B · biotinta celular (E2)')) },
    { id: 'bano', nombre: 'Hidrogel', campos: [
      H('Hidrogel de soporte (baño)'), A('Medio en el que se imprime (p. ej. microgel de gelatina FRESH, Carbopol, agarosa fluida).'),
      C('bano.activo', 'Imprimir dentro de baño de hidrogel'), T('bano.nombre', 'Nombre'),
      N('bano.tau0', 'Esfuerzo umbral del baño', 'Pa', 0, 500, 1), N('bano.K', 'Consistencia del baño', 'Pa·sⁿ', 0, 50, 0.1),
      N('bano.t_reparacion', 'Tiempo de autorreparación', 's', 0.01, 20, 0.01), N('bano.densidad', 'Densidad', 'g/mL', 0.95, 1.2, 0.005),
      N('bano.temperatura', 'Temperatura', '°C', 4, 40, 0.5), N('bano.mu_uv', 'Atenuación UV del baño', '1/mm', 0, 1, 0.005),
      N('bano.nivel', 'Nivel del baño (altura)', 'mm', 1, 60, 0.5), N('bano.oxigeno', 'Oxígeno disuelto (relativo)', '×', 0, 2, 0.05)] },
    { id: 'proceso', nombre: 'Proceso', campos: null },
    { id: 'puntaje', nombre: 'Puntaje', campos: [
      H('Pesos del sistema de puntaje'), A('El puntaje (0–100) es la media ponderada de cada criterio. La IA intenta maximizarlo.'),
      N('puntaje.w_fid', 'Fidelidad de forma', 'peso', 0, 100, 1), N('puntaje.w_viab', 'Viabilidad celular', 'peso', 0, 100, 1),
      N('puntaje.w_cura', 'Curado completo', 'peso', 0, 100, 1), N('puntaje.w_tiempo', 'Rapidez', 'peso', 0, 100, 1),
      N('puntaje.w_riesgo', 'Seguridad (sin obstrucción)', 'peso', 0, 100, 1), N('puntaje.w_material', 'Eficiencia de material', 'peso', 0, 100, 1),
      H('Referencias y restricciones'), N('puntaje.t_ref_min', 'Tiempo de referencia', 'min', 1, 600, 1),
      N('puntaje.viab_min', 'Viabilidad mínima (penaliza)', '', 0, 1, 0.01)] },
    { id: 'ia', nombre: 'IA', campos: null }
  ];

  function controlCampo(f, onChange) {
    var fila = el('div', { class: 'campo' });
    fila.appendChild(el('label', null, f.label + (f.unit ? ' <span class="u">' + f.unit + '</span>' : '')));
    var ctl = el('div', { class: 'ctl' }); fila.appendChild(ctl);
    var v = getP(cfg, f.path);
    if (f.t === 'n') {
      var r = el('input', { type: 'range', min: f.min, max: f.max, step: f.step }), n = el('input', { type: 'number', min: f.min, max: f.max, step: f.step });
      r.value = v; n.value = v;
      r.oninput = function () { n.value = r.value; setP(cfg, f.path, +r.value); onChange(f.path); };
      n.onchange = function () { var x = +n.value; if (!isFinite(x)) return; r.value = x; setP(cfg, f.path, x); onChange(f.path); };
      ctl.appendChild(r); ctl.appendChild(n);
    } else if (f.t === 's') {
      var s = el('select'); f.ops.forEach(function (o) { var op = el('option', { value: o[0] }, o[1]); if (String(o[0]) === String(v)) op.selected = true; s.appendChild(op); });
      s.onchange = function () { var x = s.value; setP(cfg, f.path, isNaN(+x) ? x : +x); onChange(f.path); };
      ctl.appendChild(s);
    } else if (f.t === 'c') {
      var c = el('input', { type: 'checkbox' }); c.checked = !!v; c.onchange = function () { setP(cfg, f.path, c.checked); onChange(f.path); }; ctl.appendChild(c);
    } else if (f.t === 'x') {
      var tx = el('input', { type: 'text' }); tx.value = v; tx.onchange = function () { setP(cfg, f.path, tx.value); onChange(f.path); }; ctl.appendChild(tx);
    }
    return fila;
  }

  function construirPaneles() {
    var nav = $('#pestanas'), cont = $('#paneles'), activa = (nav.querySelector('.activa') || {}).dataset;
    activa = activa ? activa.id : 'modelo';
    nav.innerHTML = ''; cont.innerHTML = '';
    PANELES.forEach(function (p) {
      var b = el('button', { 'data-id': p.id }, p.nombre); if (p.id === activa) b.classList.add('activa');
      b.onclick = function () { nav.querySelectorAll('button').forEach(function (x) { x.classList.toggle('activa', x === b); }); cont.querySelectorAll('.panel').forEach(function (x) { x.classList.toggle('activo', x.id === 'panel-' + p.id); }); };
      nav.appendChild(b);
      var pan = el('div', { class: 'panel' + (p.id === activa ? ' activo' : ''), id: 'panel-' + p.id });
      if (p.campos) p.campos.forEach(function (f) {
        if (f.t === 'h') pan.appendChild(el('h3', null, f.txt));
        else if (f.t === 'a') pan.appendChild(el('p', { class: 'ayuda' }, f.txt));
        else pan.appendChild(controlCampo(f, alCambiar));
      });
      cont.appendChild(pan);
    });
    panelModelo($('#panel-modelo')); panelProceso($('#panel-proceso')); panelIA($('#panel-ia'));
  }

  // ---------------------------------------------------------------- panel Modelo
  function panelModelo(pan) {
    pan.appendChild(el('h3', null, 'Órgano a imprimir'));
    var sel = el('select', { id: 'sel-organo' });
    Object.keys(CORE.ORGANOS).forEach(function (k) { sel.appendChild(el('option', { value: k }, CORE.ORGANOS[k].nombre)); });
    if (stl) sel.appendChild(el('option', { value: '__stl' }, 'STL: ' + stl.nombre));
    sel.value = modelo.tipo === 'implicita' ? modelo.id : '__stl';
    sel.onchange = function () { if (sel.value === '__stl') modelo = { tipo: 'malla' }; else modelo = { tipo: 'implicita', id: sel.value }; actualizarInfoModelo(); construirFantasma(); pedirSim(true); };
    var f = el('div', { class: 'campo' }); f.appendChild(el('label', null, 'Modelo')); var c = el('div', { class: 'ctl' }); c.appendChild(sel); f.appendChild(c); pan.appendChild(f);

    pan.appendChild(el('h3', null, 'Cargar STL'));
    var zona = el('label', { class: 'soltar' }, '⬆ Haz clic o arrastra un archivo .stl (binario o ASCII)<input type="file" accept=".stl" hidden id="in-stl">');
    pan.appendChild(zona);
    zona.querySelector('input').onchange = function (e) { if (e.target.files[0]) leerSTL(e.target.files[0], false); };
    var tam = el('div', { class: 'campo' }); tam.appendChild(el('label', null, 'Tamaño (dimensión mayor) <span class="u">mm</span>'));
    var ct = el('div', { class: 'ctl' }), nt = el('input', { type: 'number', min: 2, max: 60, step: 0.5, id: 'stl-tam' }); nt.value = stl ? stl.tam : 12; ct.appendChild(nt); tam.appendChild(ct); pan.appendChild(tam);
    var eje = el('div', { class: 'campo' }); eje.appendChild(el('label', null, 'Eje vertical del archivo'));
    var ce = el('div', { class: 'ctl' }), se = el('select', { id: 'stl-eje' }); se.innerHTML = '<option value="z">Z arriba</option><option value="y">Y arriba</option>'; se.value = stl && stl.ejeY ? 'y' : 'z'; ce.appendChild(se); eje.appendChild(ce); pan.appendChild(eje);
    nt.onchange = se.onchange = function () { if (stl) { stl.tam = +nt.value; stl.ejeY = se.value === 'y'; prepararSTL(); } };
    var zonaB = el('label', { class: 'soltar' }, '＋ STL opcional que marca la región de material B<input type="file" accept=".stl" hidden>');
    zonaB.querySelector('input').onchange = function (e) { if (e.target.files[0]) leerSTL(e.target.files[0], true); };
    pan.appendChild(zonaB);

    pan.appendChild(el('h3', null, 'Asignación de materiales'));
    pan.appendChild(controlCampo(S('asignacion.modo', 'Distribución', [['carcasa', 'Carcasa A + núcleo celular B'], ['todoA', 'Todo material A'], ['todoB', 'Todo material B'], ['mallaB', 'STL B define la región B']]), alCambiar));
    pan.appendChild(controlCampo(N('asignacion.grosor', 'Grosor de la carcasa', 'mm', 0.2, 5, 0.05), alCambiar));
    pan.appendChild(el('p', { class: 'ayuda', id: 'nota-asig' }));
    pan.appendChild(el('h3', null, 'Resolución'));
    pan.appendChild(controlCampo(N('maquina.res_max', 'Vóxeles máx. por eje (vista 3D)', '', 16, 128, 1), alCambiar));
    pan.appendChild(el('p', { class: 'ayuda' }, 'Un vóxel = un filamento si el modelo es pequeño. En modelos grandes cada vóxel agrupa varios filamentos (los tiempos se escalan).'));
    pan.appendChild(el('div', { class: 'info', id: 'info-modelo' }, '—'));
    actualizarInfoModelo();
  }
  function actualizarInfoModelo() {
    var nota = $('#nota-asig'); if (!nota) return;
    var etiq = modelo.tipo === 'implicita' && CORE.ORGANOS[modelo.id].etiqueta;
    nota.textContent = etiq ? 'Este órgano predefinido ya tiene sus materiales definidos (la asignación no se aplica).' : '';
    var info = $('#info-modelo');
    if (sim) { var m = sim.metricas, gg = sim.geo; info.textContent = 'Rejilla ' + gg.nx + '×' + gg.ny + '×' + gg.nz + '  (vóxel ' + gg.res.toFixed(3) + ' mm)\nVóxeles impresos: ' + m.voxeles + '\nVolumen: ' + m.volumen_mm3.toFixed(1) + ' mm³' + (stl && modelo.tipo === 'malla' ? '\nTriángulos STL: ' + (stl.tris.length / 9) : ''); }
  }
  function leerSTL(file, esB) {
    var fr = new FileReader();
    fr.onload = function () {
      try {
        var tris = CORE.parseSTL(fr.result);
        if (esB) { if (!stl) { alert('Carga primero el STL principal.'); return; } stl.crudoB = tris; cfg.asignacion.modo = 'mallaB'; }
        else stl = { nombre: file.name.replace(/\.stl$/i, ''), crudo: tris, crudoB: null, tam: stl ? stl.tam : 12, ejeY: false };
        modelo = { tipo: 'malla' };
        prepararSTL(); construirPaneles();
      } catch (err) { alert('Error leyendo STL: ' + err.message); }
    };
    fr.readAsArrayBuffer(file);
  }
  function prepararSTL() {
    var a = CORE.normalizarMalla(stl.crudo, stl.tam, stl.ejeY);
    stl.tris = a.tris; stl.trisB = stl.crudoB ? CORE.normalizarMalla(stl.crudoB, stl.tam, stl.ejeY, a.bbox).tris : null;
    stl.clave = stl.nombre + ':' + stl.tam + ':' + stl.ejeY + ':' + Date.now();
    construirFantasma(); pedirSim(true);
  }

  // ---------------------------------------------------------------- panel Proceso
  function panelProceso(pan) {
    pan.appendChild(el('h3', null, 'Modo de trabajo'));
    pan.appendChild(controlCampo(S('proceso.modo_uv', 'Curado UV', [['por_capa', 'Barrido por capa'], ['seguimiento', 'Seguimiento de la boquilla']]), alCambiar));
    pan.appendChild(controlCampo(S('proceso.estrategia', 'Extrusores', [['secuencial', 'Secuencial (E1 → E2)'], ['paralelo', 'Paralelo con antichoque']]), alCambiar));
    pan.appendChild(controlCampo(C('optimizar_modo', 'La IA puede cambiar el modo'), alCambiar));
    pan.appendChild(el('p', { class: 'ayuda' }, 'En seguimiento el UV sólo puede acompañar a un extrusor: se fuerza el modo secuencial.'));
    pan.appendChild(el('h3', null, 'Parámetros y espacio de búsqueda de la IA'));
    pan.appendChild(el('p', { class: 'ayuda' }, 'Marca «IA» para que la red optimice ese parámetro dentro del rango [mín, máx].'));
    CORE.PARAMS_PROCESO.forEach(function (p) {
      var caja = el('div', { class: 'campo-proc' });
      caja.appendChild(controlCampo(N('proceso.' + p[0], p[1], p[2], cfg.rangos[p[0]][0], cfg.rangos[p[0]][1], p[0] === 'altura_capa' ? 0.01 : (p[4] - p[3]) / 500), alCambiar));
      var rg = el('div', { class: 'rango' }), ch = el('input', { type: 'checkbox' }), lo = el('input', { type: 'number', step: 'any' }), hi = el('input', { type: 'number', step: 'any' });
      ch.checked = !!cfg.optimizar[p[0]]; lo.value = cfg.rangos[p[0]][0]; hi.value = cfg.rangos[p[0]][1];
      ch.onchange = function () { cfg.optimizar[p[0]] = ch.checked; guardarLS(); };
      lo.onchange = hi.onchange = function () { var a = +lo.value, b = +hi.value; if (a < b) { cfg.rangos[p[0]] = [a, b]; guardarLS(); var r = caja.querySelector('input[type=range]'); r.min = a; r.max = b; } };
      var l1 = el('label'); l1.appendChild(ch); l1.appendChild(document.createTextNode(' IA'));
      rg.appendChild(l1); rg.appendChild(document.createTextNode('mín')); rg.appendChild(lo); rg.appendChild(document.createTextNode('máx')); rg.appendChild(hi);
      caja.appendChild(rg); pan.appendChild(caja);
    });
    var fb = el('div', { class: 'fila-botones' }), br = el('button', null, 'Restaurar valores por defecto');
    br.onclick = function () { var d = CORE.defaults(); cfg.proceso = d.proceso; cfg.rangos = d.rangos; cfg.optimizar = d.optimizar; construirPaneles(); alCambiar('proceso'); };
    fb.appendChild(br); pan.appendChild(fb);
  }

  // ---------------------------------------------------------------- panel IA
  function panelIA(pan) {
    pan.appendChild(el('h3', null, 'Aprendizaje profundo por puntajes'));
    pan.appendChild(el('p', { class: 'ayuda' }, 'Cada episodio la IA propone cómo imprimir, lo simula y recibe un puntaje. Un ensamble de redes neuronales aprende a predecir el puntaje y elige la siguiente prueba equilibrando explorar (incertidumbre) y explotar (predicción).'));
    function campoIA(clave, label, min, max, step) {
      var f = el('div', { class: 'campo' }); f.appendChild(el('label', null, label)); var c = el('div', { class: 'ctl' }), n = el('input', { type: step ? 'number' : 'text', min: min, max: max, step: step });
      n.value = ia.op[clave]; n.onchange = function () { ia.op[clave] = step ? +n.value : n.value; }; c.appendChild(n); f.appendChild(c); return f;
    }
    pan.appendChild(campoIA('episodios', 'Episodios', 5, 5000, 1));
    pan.appendChild(campoIA('ensamble', 'Redes en el ensamble', 2, 12, 1));
    pan.appendChild(campoIA('ocultas', 'Capas ocultas (neuronas)'));
    pan.appendChild(campoIA('kappa', 'Exploración κ', 0, 6, 0.1));
    pan.appendChild(campoIA('lr', 'Tasa de aprendizaje', 0.0001, 0.05, 0.0005));
    pan.appendChild(campoIA('resEntreno', 'Resolución de entrenamiento (vóxeles/eje)', 12, 64, 1));
    var au = el('label', { class: 'rango' }), ca = el('input', { type: 'checkbox' }); ca.checked = ia.op.autoVer; ca.onchange = function () { ia.op.autoVer = ca.checked; };
    au.appendChild(ca); au.appendChild(document.createTextNode(' Mostrar en 3D cada nuevo récord')); pan.appendChild(au);
    var fb = el('div', { class: 'fila-botones' });
    var bI = el('button', { class: 'prim', id: 'ia-iniciar' }, '▶ Iniciar aprendizaje'), bP = el('button', { id: 'ia-pausa' }, '⏸ Pausar'), bC = el('button', { id: 'ia-cont' }, '⏵ Continuar +50');
    bI.onclick = iniciarIA; bP.onclick = function () { wIA.postMessage({ cmd: 'pausa' }); }; bC.onclick = function () { wIA.postMessage({ cmd: 'continuar', extra: 50 }); ia.estado = 'aprendiendo'; refrescarIA(); };
    fb.appendChild(bI); fb.appendChild(bP); fb.appendChild(bC); pan.appendChild(fb);
    var fb2 = el('div', { class: 'fila-botones' });
    var bA = el('button', { id: 'ia-aplicar' }, '✔ Aplicar mejores parámetros'), bX = el('button', null, '⬇ Episodios CSV');
    bA.onclick = function () { if (ia.mejor) aplicarProceso(ia.mejor.proceso); };
    bX.onclick = exportarCSV; fb2.appendChild(bA); fb2.appendChild(bX); pan.appendChild(fb2);
    pan.appendChild(el('h3', null, 'Error de predicción de la red'));
    pan.appendChild(el('canvas', { id: 'graf-error', class: 'graf', width: 340, height: 110 }));
    pan.appendChild(el('h3', null, 'Mejores formas de imprimir encontradas'));
    pan.appendChild(el('div', { id: 'ia-top' }, '<p class="ayuda">Aún no hay episodios.</p>'));
    pan.appendChild(el('h3', null, 'Lo que la red ha aprendido: importancia de cada parámetro'));
    pan.appendChild(el('div', { id: 'ia-sens', class: 'sens' }, '<span class="ayuda">Disponible tras unos episodios.</span>'));
    pan.appendChild(el('h3', null, 'Registro'));
    pan.appendChild(el('div', { id: 'ia-log', class: 'registro' }));
    refrescarIA();
  }

  function iniciarIA() {
    if (modelo.tipo === 'malla' && !stl) return;
    ia.hist = []; ia.mejor = null; ia.sens = null; $('#ia-log').innerHTML = '';
    var ocultas = String(ia.op.ocultas).split(',').map(function (x) { return Math.max(2, parseInt(x, 10) || 16); });
    wIA.postMessage({ cmd: 'aprender', cfg: clon(cfg), fuente: descFuente(), op: { episodios: ia.op.episodios, ensamble: ia.op.ensamble, ocultas: ocultas, kappa: ia.op.kappa, resEntreno: ia.op.resEntreno, lr: ia.op.lr, semilla: (Date.now() % 100000) + 1 } });
    ia.estado = 'aprendiendo'; refrescarIA();
  }

  wIA.onmessage = function (e) {
    var m = e.data;
    if (m.tipo === 'inicio') { ia.claves = m.claves; }
    else if (m.tipo === 'ep') {
      var r = m.reg; ia.hist.push(r); if (m.sens) ia.sens = m.sens;
      if (r.record) {
        ia.mejor = r;
        if (ia.op.autoVer) aplicarProceso(r.proceso, true);
      }
      var log = $('#ia-log');
      if (log) {
        var linea = el('div', r.record ? { class: 'rec' } : null, '#' + (r.ep + 1) + ' ' + r.puntaje.toFixed(1) + ' pts' + (r.pred ? ' (pred ' + r.pred.mu.toFixed(1) + '±' + r.pred.sd.toFixed(1) + ')' : '') + ' · ' + r.razon + (r.record ? ' ★ récord' : ''));
        log.prepend(linea); while (log.childNodes.length > 200) log.lastChild.remove();
      }
      refrescarIA();
    } else if (m.tipo === 'fin') { ia.estado = 'terminado'; refrescarIA(); }
    else if (m.tipo === 'pausado') { ia.estado = 'en pausa'; refrescarIA(); }
    else if (m.tipo === 'error') { ia.estado = 'error'; refrescarIA(); console.error(m.msg); alert('Error en la IA: ' + m.msg.split('\n')[0]); }
  };

  function aplicarProceso(proc, silencioso) {
    cfg.proceso = clon(proc); guardarLS();
    if (!silencioso) construirPaneles(); else refrescarValoresProceso();
    pedirSim(true);
  }
  function refrescarValoresProceso() {
    var pan = $('#panel-proceso'); if (!pan) return;
    pan.querySelectorAll('.campo-proc').forEach(function (caja, i) {
      var k = CORE.PARAMS_PROCESO[i][0], v = cfg.proceso[k];
      var r = caja.querySelector('input[type=range]'), n = caja.querySelector('input[type=number]'); r.value = v; n.value = +v.toFixed(4);
    });
    var sels = pan.querySelectorAll('select'); if (sels[0]) sels[0].value = cfg.proceso.modo_uv; if (sels[1]) sels[1].value = cfg.proceso.estrategia;
  }

  var COLOR_COMBO = { 'por_capa|secuencial': '#4fd1c5', 'por_capa|paralelo': '#f2a93b', 'seguimiento|secuencial': '#c084fc' };
  function refrescarIA() {
    var n = ia.hist.length, best = ia.mejor;
    $('#ia-estado-mini').textContent = ia.estado + (n ? ' · ' + n + ' ep.' : '');
    $('#ia-resumen').textContent = best ? 'Mejor: ' + best.puntaje.toFixed(1) + ' pts (ep. ' + (best.ep + 1) + ') · ' + CORE.COMBO_TXT[best.comboTxt] : 'Pulsa «Iniciar aprendizaje» en la pestaña IA.';
    dibujarGrafIA($('#graf-ia'));
    var ge = $('#graf-error'); if (ge) dibujarGrafError(ge);
    var top = $('#ia-top');
    if (top && n) {
      var orden = ia.hist.slice().sort(function (a, b) { return b.puntaje - a.puntaje; }).slice(0, 6);
      var h = '<table class="tabla-ia"><tr><th>ep</th><th>pts</th><th>modo</th><th>IoU</th><th>viab</th><th>tiempo</th></tr>';
      orden.forEach(function (r, i) { h += '<tr class="click" data-i="' + ia.hist.indexOf(r) + '"><td>' + (r.ep + 1) + '</td><td><b>' + r.puntaje.toFixed(1) + '</b></td><td><span style="color:' + COLOR_COMBO[r.comboTxt] + '">●</span> ' + r.comboTxt.split('|')[0].replace('_', ' ') + '</td><td>' + r.metricas.fidelidad.toFixed(2) + '</td><td>' + r.metricas.viabilidad.toFixed(2) + '</td><td>' + fmtT(r.metricas.tiempo_s) + '</td></tr>'; });
      top.innerHTML = h + '</table><p class="ayuda">Clic en una fila para verla en 3D y aplicar sus parámetros.</p>';
      top.querySelectorAll('tr.click').forEach(function (tr) { tr.onclick = function () { aplicarProceso(ia.hist[+tr.dataset.i].proceso); }; });
    }
    var sens = $('#ia-sens');
    if (sens && ia.sens && ia.sens.length) {
      var nombres = {}; CORE.PARAMS_PROCESO.forEach(function (p) { nombres[p[0]] = p[1]; });
      sens.innerHTML = ia.sens.slice().sort(function (a, b) { return b.valor - a.valor; }).map(function (s) { return '<span>' + nombres[s.clave] + '</span><div class="pista"><i style="width:' + (100 * s.valor).toFixed(0) + '%"></i></div>'; }).join('');
    }
    var bI = $('#ia-iniciar'); if (bI) bI.textContent = n ? '↺ Reiniciar aprendizaje' : '▶ Iniciar aprendizaje';
  }

  function dibujarGrafIA(cv) {
    var c = cv.getContext('2d'), W = cv.width, Hh = cv.height, pad = { l: 34, r: 8, t: 8, b: 20 };
    c.clearRect(0, 0, W, Hh);
    var hs = ia.hist, n = hs.length;
    c.font = '10px system-ui'; c.fillStyle = '#8b98a8';
    if (!n) { c.fillText('Puntaje por episodio aparecerá aquí', pad.l + 10, Hh / 2); return; }
    var ys = hs.map(function (r) { return r.puntaje; }), lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
    lo = Math.max(0, Math.floor((lo - 2) / 5) * 5); hi = Math.min(100, Math.ceil((hi + 2) / 5) * 5); if (hi - lo < 10) lo = Math.max(0, hi - 10);
    var X = function (i) { return pad.l + (W - pad.l - pad.r) * (n === 1 ? 0.5 : i / (n - 1)); }, Y = function (v) { return Hh - pad.b - (Hh - pad.t - pad.b) * (v - lo) / (hi - lo); };
    c.strokeStyle = '#2a3441'; c.lineWidth = 1;
    for (var g = 0; g <= 4; g++) { var v = lo + (hi - lo) * g / 4, y = Y(v); c.beginPath(); c.moveTo(pad.l, y); c.lineTo(W - pad.r, y); c.stroke(); c.fillText(v.toFixed(0), 4, y + 3); }
    c.fillText('episodio ' + n, W - pad.r - 60, Hh - 5);
    hs.forEach(function (r, i) { if (!r.pred) return; c.strokeStyle = 'rgba(139,152,168,.35)'; c.beginPath(); c.moveTo(X(i), Y(Math.max(lo, Math.min(hi, r.pred.mu - r.pred.sd)))); c.lineTo(X(i), Y(Math.max(lo, Math.min(hi, r.pred.mu + r.pred.sd)))); c.stroke(); });
    hs.forEach(function (r, i) { c.fillStyle = COLOR_COMBO[r.comboTxt] || '#fff'; c.beginPath(); c.arc(X(i), Y(r.puntaje), r.record ? 3.5 : 2.2, 0, 7); c.fill(); });
    c.strokeStyle = '#3fb950'; c.lineWidth = 2; c.beginPath(); var mx = -1;
    hs.forEach(function (r, i) { mx = Math.max(mx, r.puntaje); if (i === 0) c.moveTo(X(i), Y(mx)); else c.lineTo(X(i), Y(mx)); }); c.stroke();
    var leg = [['por_capa|secuencial', 'UV capa·sec'], ['por_capa|paralelo', 'UV capa·par'], ['seguimiento|secuencial', 'UV seguim.']], lx = pad.l + 6;
    leg.forEach(function (l) { c.fillStyle = COLOR_COMBO[l[0]]; c.fillRect(lx, pad.t + 2, 8, 8); c.fillStyle = '#8b98a8'; c.fillText(l[1], lx + 11, pad.t + 10); lx += 78; });
    c.fillStyle = '#3fb950'; c.fillRect(lx, pad.t + 5, 10, 2); c.fillStyle = '#8b98a8'; c.fillText('mejor', lx + 13, pad.t + 10);
  }
  function dibujarGrafError(cv) {
    var c = cv.getContext('2d'), W = cv.width, Hh = cv.height, pad = 24; c.clearRect(0, 0, W, Hh);
    var pts = ia.hist.filter(function (r) { return r.pred; }).map(function (r) { return Math.abs(r.pred.mu - r.puntaje); });
    c.font = '10px system-ui'; c.fillStyle = '#8b98a8';
    if (pts.length < 2) { c.fillText('|predicción − real| (media móvil)', 10, Hh / 2); return; }
    var mm = [], k = 8; for (var i = 0; i < pts.length; i++) { var s = 0, q = 0; for (var j = Math.max(0, i - k + 1); j <= i; j++) { s += pts[j]; q++; } mm.push(s / q); }
    var hi = Math.max.apply(null, mm) * 1.1 || 1;
    c.strokeStyle = '#2a3441'; c.beginPath(); c.moveTo(pad, Hh - 14); c.lineTo(W - 4, Hh - 14); c.stroke();
    c.fillText(hi.toFixed(1) + ' pts', 2, 12); c.fillText('error medio de predicción', pad + 4, Hh - 2);
    c.strokeStyle = '#7c5cff'; c.lineWidth = 2; c.beginPath();
    mm.forEach(function (v, i) { var x = pad + (W - pad - 6) * i / (mm.length - 1), y = Hh - 14 - (Hh - 30) * v / hi; if (i) c.lineTo(x, y); else c.moveTo(x, y); }); c.stroke();
  }
  function exportarCSV() {
    if (!ia.hist.length) return;
    var cols = ['ep', 'puntaje', 'modo'].concat(CORE.PARAMS_PROCESO.map(function (p) { return p[0]; })).concat(['fidelidad', 'viabilidad', 'curado', 'tiempo_s', 'riesgo_obstruccion', 'eficiencia_material', 'pred_mu', 'pred_sd']);
    var filas = [cols.join(',')];
    ia.hist.forEach(function (r) { filas.push([r.ep + 1, r.puntaje.toFixed(3), r.comboTxt].concat(CORE.PARAMS_PROCESO.map(function (p) { return (+r.proceso[p[0]]).toFixed(4); })).concat([r.metricas.fidelidad, r.metricas.viabilidad, r.metricas.curado, r.metricas.tiempo_s, r.metricas.riesgo_obstruccion, r.metricas.eficiencia_material].map(function (v) { return (+v).toFixed(4); })).concat([r.pred ? r.pred.mu.toFixed(2) : '', r.pred ? r.pred.sd.toFixed(2) : '']).join(',')); });
    descargar('episodios_ia.csv', filas.join('\n'), 'text/csv');
  }

  // ---------------------------------------------------------------- cambios y simulación
  var tempo = null;
  function alCambiar(path) {
    guardarLS();
    if (path.indexOf('puntaje') === 0) { if (sim) { sim.puntaje = CORE.puntuar(sim.metricas, cfg.puntaje); mostrarPuntaje(); } return; }
    if (path.indexOf('maquina.aux.rol') === 0 || path.indexOf('.nombre') > 0) return;
    if (path === 'optimizar_modo') return;
    clearTimeout(tempo); tempo = setTimeout(function () { pedirSim(false); }, 350);
  }
  var gcodePendiente = false;
  function pedirSim(reproducir, gcode) {
    if (modelo.tipo === 'malla' && !stl) return;
    simId++; $('#cargando').hidden = false;
    wSim.postMessage({ cmd: 'simular', id: simId, cfg: clon(cfg), fuente: descFuente(), gcode: !!gcode, reproducir: reproducir });
    if (gcode) gcodePendiente = true;
    pedirSim.reproducir = reproducir;
  }
  wSim.onmessage = function (e) {
    var m = e.data;
    if (m.tipo === 'error') { $('#cargando').hidden = true; console.error(m.msg); alert('Error de simulación: ' + m.msg.split('\n')[0]); return; }
    if (m.gcode && m.r.gcode) { descargar((modelo.tipo === 'malla' ? stl.nombre : modelo.id) + '.gcode', m.r.gcode); gcodePendiente = false; }
    if (m.id !== simId) return;
    $('#cargando').hidden = true;
    var tAnt = sim ? tSim / sim.T : 1;
    sim = m.r; construirVoxeles(); mostrarPuntaje(); actualizarInfoModelo();
    if (pedirSim.reproducir) { tSim = 0; reproduciendo = true; } else { tSim = reproduciendo ? tAnt * sim.T : sim.T; }
    $('#btn-play').textContent = reproduciendo ? '⏸' : '▶';
    actualizarTiempo(true);
  };

  // ---------------------------------------------------------------- panel de puntaje
  var NOMBRE_PARTE = { fidelidad: 'Fidelidad', viabilidad: 'Viabilidad', curado: 'Curado', tiempo: 'Rapidez', riesgo: 'Seguridad', material: 'Material' };
  function mostrarPuntaje() {
    if (!sim) return;
    var p = sim.puntaje, m = sim.metricas;
    $('#pt-total').textContent = p.total.toFixed(1);
    $('#pt-estado').textContent = (modelo.tipo === 'malla' ? stl.nombre : CORE.ORGANOS[modelo.id].nombre);
    var pesos = { fidelidad: cfg.puntaje.w_fid, viabilidad: cfg.puntaje.w_viab, curado: cfg.puntaje.w_cura, tiempo: cfg.puntaje.w_tiempo, riesgo: cfg.puntaje.w_riesgo, material: cfg.puntaje.w_material };
    $('#pt-barras').innerHTML = Object.keys(p.partes).map(function (k) {
      var v = p.partes[k]; return '<div class="barra-pt" title="peso ' + pesos[k] + ' · aporta ' + p.aportes[k].toFixed(1) + ' pts"><span>' + NOMBRE_PARTE[k] + '</span><div class="pista"><i style="width:' + (100 * Math.max(0, Math.min(1, v))).toFixed(0) + '%;background:' + (v > 0.8 ? 'var(--ok)' : v > 0.55 ? 'var(--aviso)' : 'var(--mal)') + '"></i></div><span>' + (100 * v).toFixed(0) + '%</span></div>';
    }).join('');
    $('#pt-pen').innerHTML = Object.keys(p.penalizaciones).map(function (k) { return '⚠ ' + k.replace('_', ' ') + ' ' + p.penalizaciones[k]; }).join('<br>');
    var filas = [['Tiempo de impresión', fmtT(m.tiempo_s)], ['Capas', m.capas], ['Error de altura', (100 * m.error_altura).toFixed(1) + ' %'], ['Conversión media α', m.conversion.toFixed(2)],
      ['Dosis UV media', m.dosis_media.toFixed(0) + ' mJ/cm²'], ['Extrusión A / B', m.relacion_A.toFixed(2) + ' / ' + m.relacion_B.toFixed(2)], ['Superv. cizalla', (100 * m.sup_cizalla).toFixed(0) + ' %'],
      ['Riesgo obstrucción', (100 * m.riesgo_obstruccion).toFixed(1) + ' %'], ['Espera antichoque', m.espera_antichoque_s.toFixed(0) + ' s'], ['Colisiones', m.colisiones], ['Modo', CORE.COMBO_TXT[sim_combo()]]];
    $('#pt-metricas').innerHTML = filas.map(function (f) { return '<tr><td>' + f[0] + '</td><td>' + f[1] + '</td></tr>'; }).join('');
  }
  function sim_combo() { return cfg.proceso.modo_uv + '|' + (sim && sim.estrategia || cfg.proceso.estrategia); }

  // ================================================================ ESCENA 3D
  var cont3d = $('#lienzo3d'), renderer, scene, camara, voxMesh = null, fantasma = null, grupoBano, brazos = {}, plano = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 1e3);
  var ord = null; // datos de vóxeles ordenados por tiempo de deposición
  var orb = { theta: 0.8, phi: 1.05, r: 40, objetivo: new THREE.Vector3(0, 5, 0) };
  function S2T(x, y, z) { return new THREE.Vector3(x, z, -y); }

  function iniciar3D() {
    try { renderer = new THREE.WebGLRenderer({ antialias: true }); } catch (e) { cont3d.innerHTML = '<p style="padding:20px">WebGL no disponible en este navegador.</p>'; return false; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)); renderer.localClippingEnabled = true;
    renderer.setClearColor(0x0d1117); cont3d.appendChild(renderer.domElement);
    scene = new THREE.Scene();
    camara = new THREE.PerspectiveCamera(40, 1, 0.1, 2000);
    scene.add(new THREE.HemisphereLight(0xdde8ff, 0x202530, 1.0));
    var dl = new THREE.DirectionalLight(0xffffff, 1.1); dl.position.set(30, 60, 40); scene.add(dl);
    var dl2 = new THREE.DirectionalLight(0x88aaff, 0.4); dl2.position.set(-40, 20, -30); scene.add(dl2);
    var cama = new THREE.Mesh(new THREE.BoxGeometry(80, 1, 80), new THREE.MeshStandardMaterial({ color: 0x2b333d, roughness: 0.9 }));
    cama.position.y = -0.5; scene.add(cama);
    var rej = new THREE.GridHelper(80, 40, 0x3a4654, 0x262f3a); rej.position.y = 0.01; scene.add(rej);
    grupoBano = new THREE.Group(); scene.add(grupoBano);
    crearBrazos();
    controlesOrbita(renderer.domElement);
    window.addEventListener('resize', redimensionar); redimensionar();
    return true;
  }
  function redimensionar() { var w = cont3d.clientWidth, h = cont3d.clientHeight; if (!w || !h) return; renderer.setSize(w, h); camara.aspect = w / h; camara.updateProjectionMatrix(); }

  function etiqueta(txt, color) {
    var cv = document.createElement('canvas'); cv.width = 128; cv.height = 48; var c = cv.getContext('2d');
    c.fillStyle = 'rgba(13,17,23,.8)'; c.fillRect(0, 0, 128, 48); c.strokeStyle = color; c.lineWidth = 4; c.strokeRect(2, 2, 124, 44);
    c.fillStyle = '#fff'; c.font = 'bold 26px system-ui'; c.textAlign = 'center'; c.fillText(txt, 64, 33);
    var sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(cv), depthTest: false })); sp.scale.set(4, 1.5, 1); return sp;
  }
  function crearBrazos() {
    var def = { E1: 0xf2a93b, E2: 0xe5487f, UV: 0x8a5cff, AUX: 0x6b7480 };
    Object.keys(def).forEach(function (nm) {
      var g = new THREE.Group(), mat = new THREE.MeshStandardMaterial({ color: def[nm], metalness: 0.3, roughness: 0.5 });
      var varilla = new THREE.Mesh(new THREE.BoxGeometry(1.2, 40, 1.2), new THREE.MeshStandardMaterial({ color: 0x55606d, metalness: 0.6, roughness: 0.4 })); varilla.position.y = 26; g.add(varilla);
      var cuerpo = new THREE.Mesh(new THREE.CylinderGeometry(2, 2, 5, 20), mat); cuerpo.position.y = 4.5; g.add(cuerpo);
      var b = { g: g, mat: mat };
      if (nm === 'E1' || nm === 'E2') {
        var punta = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.15, 2, 12), new THREE.MeshStandardMaterial({ color: 0xc8d0d8, metalness: 0.8, roughness: 0.2 })); punta.position.y = 1; g.add(punta);
        var brillo = new THREE.Mesh(new THREE.SphereGeometry(0.35, 12, 8), new THREE.MeshBasicMaterial({ color: def[nm] })); brillo.position.y = 0; g.add(brillo); b.brillo = brillo;
      } else if (nm === 'UV') {
        var lente = new THREE.Mesh(new THREE.CylinderGeometry(1.2, 1.2, 0.6, 20), new THREE.MeshBasicMaterial({ color: 0xc4b5fd })); lente.position.y = 1.8; g.add(lente);
        var cono = new THREE.Mesh(new THREE.ConeGeometry(1, 1, 24, 1, true), new THREE.MeshBasicMaterial({ color: 0x9f7aea, transparent: true, opacity: 0.28, depthWrite: false, side: THREE.DoubleSide }));
        g.add(cono); b.cono = cono;
        var spot = new THREE.Mesh(new THREE.CircleGeometry(1, 32), new THREE.MeshBasicMaterial({ color: 0xb794f4, transparent: true, opacity: 0.55, depthWrite: false }));
        spot.rotation.x = -Math.PI / 2; scene.add(spot); b.spot = spot;
      }
      var et = etiqueta(nm, '#' + def[nm].toString(16).padStart(6, '0')); et.position.y = 9.5; g.add(et);
      scene.add(g); brazos[nm] = b;
    });
  }

  function controlesOrbita(dom) {
    var arr = null, ult = null, toques = {};
    dom.addEventListener('contextmenu', function (e) { e.preventDefault(); });
    dom.addEventListener('pointerdown', function (e) { dom.setPointerCapture(e.pointerId); toques[e.pointerId] = [e.clientX, e.clientY]; arr = (e.button === 2 || e.shiftKey) ? 'pan' : 'rot'; ult = [e.clientX, e.clientY]; });
    dom.addEventListener('pointermove', function (e) {
      if (!arr) return;
      var ids = Object.keys(toques);
      if (ids.length === 2 && toques[e.pointerId]) { // pellizco
        var o = ids[0] == e.pointerId ? toques[ids[1]] : toques[ids[0]], d0 = Math.hypot(toques[e.pointerId][0] - o[0], toques[e.pointerId][1] - o[1]), d1 = Math.hypot(e.clientX - o[0], e.clientY - o[1]);
        orb.r = Math.max(3, Math.min(400, orb.r * d0 / (d1 || 1))); toques[e.pointerId] = [e.clientX, e.clientY]; return;
      }
      var dx = e.clientX - ult[0], dy = e.clientY - ult[1]; ult = [e.clientX, e.clientY];
      if (arr === 'rot') { orb.theta -= dx * 0.008; orb.phi = Math.max(0.05, Math.min(Math.PI - 0.05, orb.phi - dy * 0.008)); }
      else { var f = orb.r * 0.0015, dir = new THREE.Vector3(); camara.getWorldDirection(dir); var der = new THREE.Vector3().crossVectors(dir, camara.up).normalize(), arriba = new THREE.Vector3().crossVectors(der, dir).normalize(); orb.objetivo.addScaledVector(der, -dx * f).addScaledVector(arriba, dy * f); }
    });
    var soltar = function (e) { delete toques[e.pointerId]; if (!Object.keys(toques).length) arr = null; };
    dom.addEventListener('pointerup', soltar); dom.addEventListener('pointercancel', soltar);
    dom.addEventListener('wheel', function (e) { e.preventDefault(); orb.r = Math.max(3, Math.min(400, orb.r * Math.exp(e.deltaY * 0.001))); }, { passive: false });
  }
  function actualizarCamara() {
    var o = orb.objetivo; camara.position.set(o.x + orb.r * Math.sin(orb.phi) * Math.sin(orb.theta), o.y + orb.r * Math.cos(orb.phi), o.z + orb.r * Math.sin(orb.phi) * Math.cos(orb.theta)); camara.lookAt(o);
  }

  function construirFantasma() {
    if (fantasma) { scene.remove(fantasma); fantasma.geometry.dispose(); fantasma = null; }
    if (modelo.tipo !== 'malla' || !stl) return;
    var t = stl.tris, pos = new Float32Array(t.length);
    for (var i = 0; i < t.length; i += 3) { pos[i] = t[i]; pos[i + 1] = t[i + 2]; pos[i + 2] = -t[i + 1]; }
    var geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(pos, 3)); geo.computeVertexNormals();
    fantasma = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0x9fb4c8, transparent: true, opacity: 0.12, depthWrite: false, side: THREE.DoubleSide, clippingPlanes: [plano] }));
    fantasma.visible = $('#ver-fantasma').checked; scene.add(fantasma);
  }

  function hash(i) { var x = Math.sin(i * 12.9898) * 43758.5453; return x - Math.floor(x); }
  var COL_A = new THREE.Color(0xf2a93b), COL_B = new THREE.Color(0xe5487f), BLANCO = new THREE.Color(0xffffff), tmpC = new THREE.Color();
  function construirVoxeles() {
    if (!scene) return;
    if (voxMesh) { scene.remove(voxMesh); voxMesh.geometry.dispose(); voxMesh.material.dispose(); voxMesh = null; }
    var g = sim.geo, nxy = g.nx * g.ny, idx = [];
    for (var i = 0; i < g.mat.length; i++) if (g.mat[i]) idx.push(i);
    idx.sort(function (a, b) { return sim.tdep[a] - sim.tdep[b]; });
    var n = idx.length;
    ord = { n: n, idx: idx, t: new Float64Array(n), tg: new Float64Array(n), capa: new Int32Array(n), m: new Int8Array(n), x: new Float32Array(n) };
    voxMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0.05, clippingPlanes: [plano] }), Math.max(n, 1));
    var mtx = new THREE.Matrix4(), q = new THREE.Quaternion(), wNom = Math.min(cfg.maquina.e1.diam, cfg.maquina.e2.diam);
    for (var s = 0; s < n; s++) {
      var id = idx[s], k = Math.floor(id / nxy), c = id % nxy, j = Math.floor(c / g.nx), ii = c % g.nx, m = g.mat[id], cp = sim.capas[k];
      ord.t[s] = sim.tdep[id]; ord.tg[s] = sim.tgel[id]; ord.capa[s] = k; ord.m[s] = m; ord.x[s] = g.xs[ii];
      var sig = cp.sigma[m], jx = (hash(id) - 0.5) * 2 * sig, jy = (hash(id + 7.7) - 0.5) * 2 * sig;
      var f = Math.max(0.35, Math.min(1.3, cp.ancho[m])) * (g.res > wNom * 1.05 ? 1 : 1);
      mtx.compose(S2T(g.xs[ii] + jx, g.ys[j] + jy, cp.zb + cp.h / 2), q, new THREE.Vector3(g.res * f, cp.h * 0.97, g.res * f));
      voxMesh.setMatrixAt(s, mtx); voxMesh.setColorAt(s, COL_A);
    }
    voxMesh.instanceMatrix.needsUpdate = true;
    scene.add(voxMesh);
    // baño de hidrogel
    while (grupoBano.children.length) { var ch = grupoBano.children.pop(); ch.geometry.dispose(); ch.material.dispose(); }
    var ancho = g.nx * g.res + 14, fondo = g.ny * g.res + 14, alto = cfg.bano.nivel;
    if (cfg.bano.activo) {
      var caja = new THREE.Mesh(new THREE.BoxGeometry(ancho, alto, fondo), new THREE.MeshStandardMaterial({ color: 0x5ab8e8, transparent: true, opacity: 0.10, depthWrite: false, roughness: 0.1 }));
      caja.position.y = alto / 2; grupoBano.add(caja);
      var bordes = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(ancho, alto, fondo)), new THREE.LineBasicMaterial({ color: 0x5ab8e8, transparent: true, opacity: 0.5 }));
      bordes.position.y = alto / 2; grupoBano.add(bordes);
    }
    grupoBano.visible = $('#ver-bano').checked;
    // encuadre
    var altoPieza = sim.capas.length ? sim.capas[sim.capas.length - 1].zb + sim.capas[sim.capas.length - 1].h : 5;
    var tam = Math.max(g.nx * g.res, g.ny * g.res, altoPieza);
    if (!construirVoxeles.encuadrado || construirVoxeles.tam !== Math.round(tam)) { orb.objetivo.set(0, altoPieza * 0.45, 0); orb.r = Math.max(tam * 3.4 + 20, 62); construirVoxeles.encuadrado = true; construirVoxeles.tam = Math.round(tam); }
    var cx = $('#corte-x'); cx.dataset.min = g.xs[0] - g.res; cx.dataset.max = g.xs[g.nx - 1] + g.res;
    aplicarCorte(); colorearEstatico(); actualizarLeyenda();
  }

  function mapaColor(v, tipo) { // v en [0,1]
    v = Math.max(0, Math.min(1, v));
    if (tipo === 'viab') return tmpC.setHSL(0.33 * v, 0.85, 0.5);
    var st = [[0.27, 0.0, 0.33], [0.23, 0.32, 0.55], [0.13, 0.57, 0.55], [0.37, 0.79, 0.38], [0.99, 0.91, 0.14]];
    var x = v * 4, i = Math.min(3, Math.floor(x)), f = x - i, a = st[i], b = st[i + 1];
    return tmpC.setRGB(a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2]));
  }
  var ultimoColor = 0;
  function colorearEstatico() {
    if (!voxMesh) return;
    var modo = $('#modo-color').value; if (modo === 'material') { colorearMaterial(true); return; }
    var dmax = 0; if (modo === 'dosis') for (var s = 0; s < ord.n; s++) dmax = Math.max(dmax, sim.dosis[ord.idx[s]]);
    for (s = 0; s < ord.n; s++) {
      var id = ord.idx[s], c;
      if (modo === 'conversion') c = mapaColor(sim.alpha[id]);
      else if (modo === 'dosis') c = mapaColor(sim.dosis[id] / (dmax || 1));
      else { var v = sim.viab[id]; c = v === v ? mapaColor(v, 'viab') : tmpC.set(0x3a4654); }
      voxMesh.setColorAt(s, c);
    }
    voxMesh.instanceColor.needsUpdate = true;
  }
  function colorearMaterial(forzar) {
    var ahora = performance.now(); if (!forzar && ahora - ultimoColor < 120) return; ultimoColor = ahora;
    var cnt = voxMesh.count, arr = voxMesh.instanceColor.array;
    for (var s = 0; s < cnt; s++) {
      var base = ord.m[s] === 1 ? COL_A : COL_B, gel = ord.tg[s] <= tSim;
      if (gel) { arr[3 * s] = base.r; arr[3 * s + 1] = base.g; arr[3 * s + 2] = base.b; }
      else { arr[3 * s] = base.r * 0.35 + 0.65; arr[3 * s + 1] = base.g * 0.35 + 0.65; arr[3 * s + 2] = base.b * 0.35 + 0.65; }
    }
    voxMesh.instanceColor.needsUpdate = true;
  }
  function actualizarLeyenda() {
    var modo = $('#modo-color').value, h = '';
    if (modo === 'material') h = '<div><span class="sw" style="background:#f2a93b"></span>A · ' + cfg.tintaA.nombre + '</div><div><span class="sw" style="background:#e5487f"></span>B · ' + cfg.tintaB.nombre + '</div><div><span class="sw" style="background:#f3e9e0"></span>sin gelificar (aún líquido)</div><div style="margin-top:4px;color:#8b98a8">Brazos: E1 ámbar · E2 rosa · UV violeta · AUX gris (sin uso)</div>';
    else if (modo === 'viabilidad') h = 'Viabilidad celular<div class="grad" style="background:linear-gradient(90deg,hsl(0,85%,50%),hsl(60,85%,50%),hsl(120,85%,50%))"></div><div style="display:flex;justify-content:space-between"><span>0%</span><span>100%</span></div>';
    else h = (modo === 'dosis' ? 'Dosis UV acumulada' : 'Conversión de polimerización α') + '<div class="grad" style="background:linear-gradient(90deg,#450054,#3b528c,#21918c,#5ec962,#fde725)"></div><div style="display:flex;justify-content:space-between"><span>baja</span><span>alta</span></div>';
    $('#leyenda').innerHTML = h;
  }
  function aplicarCorte() {
    var cx = $('#corte-x'), lo = +cx.dataset.min || -50, hi = +cx.dataset.max || 50, v = +cx.value / 100;
    plano.constant = v >= 0.999 ? 1e3 : lo + v * (hi - lo);
  }

  // ---------------------------------------------------------------- animación
  function posBrazo(tr, t) {
    var T = tr.t, n = T.length; if (t <= T[0]) return [tr.x[0], tr.y[0], 0]; if (t >= T[n - 1]) return [tr.x[n - 1], tr.y[n - 1], 0];
    var lo = 0, hi = n - 1; while (hi - lo > 1) { var m = (lo + hi) >> 1; if (T[m] <= t) lo = m; else hi = m; }
    var f = (t - T[lo]) / ((T[hi] - T[lo]) || 1); return [tr.x[lo] + f * (tr.x[hi] - tr.x[lo]), tr.y[lo] + f * (tr.y[hi] - tr.y[lo]), tr.on[hi]];
  }
  function capaEn(t) { var c = sim.capaT, lo = 0, hi = c.length - 1; if (t >= c[hi]) return c.length - 2; while (hi - lo > 1) { var m = (lo + hi) >> 1; if (c[m] <= t) lo = m; else hi = m; } return Math.min(lo, sim.capas.length - 1); }
  function actualizarTiempo(forzarColor) {
    if (!sim || !voxMesh) return;
    var lo = 0, hi = ord.n; while (lo < hi) { var m = (lo + hi) >> 1; if (ord.t[m] <= tSim) lo = m + 1; else hi = m; }
    var lim = +$('#corte-capa').value / 100, capaMax = Math.round(lim * (sim.capas.length - 1)), cnt = lo;
    if (lim < 0.999) { var a = 0, b = cnt; while (a < b) { var mm = (a + b) >> 1; if (ord.capa[mm] <= capaMax) a = mm + 1; else b = mm; } cnt = a; }
    voxMesh.count = cnt;
    if ($('#modo-color').value === 'material') colorearMaterial(forzarColor);
    var k = Math.max(0, capaEn(tSim)), cp = sim.capas[k], zTip = cp ? cp.zb + cp.h : 0;
    $('#t-texto').textContent = fmtT(tSim) + ' / ' + fmtT(sim.T);
    $('#capa-texto').textContent = 'capa ' + (k + 1) + '/' + sim.capas.length;
    if (!$('#tiempo').matches(':active')) $('#tiempo').value = Math.round(1000 * tSim / (sim.T || 1));
    var ver = $('#ver-brazos').checked;
    ['E1', 'E2', 'UV', 'AUX'].forEach(function (nm) {
      var b = brazos[nm], tr = sim.trays && sim.trays[nm]; b.g.visible = ver; if (!tr) return;
      var p = posBrazo(tr, tSim), z = zTip + (nm === 'UV' ? 7 : 0.3);
      if (nm === 'AUX') z = 4;
      b.g.position.copy(S2T(p[0], p[1], z));
      if (b.brillo) b.brillo.visible = !!p[2];
      if (b.cono) {
        var on = !!p[2] && ver; b.cono.visible = on; b.spot.visible = on;
        if (on) { var r = cfg.maquina.uv.spot / 2, hh = z - zTip; b.cono.scale.set(r, hh, r); b.cono.position.y = hh / 2 - 0.0; b.cono.position.y = -hh / 2 + 1.6; b.cono.rotation.x = 0; b.spot.scale.set(r, r, 1); b.spot.position.copy(S2T(p[0], p[1], zTip + 0.05)); }
      }
    });
  }

  var tPrev = performance.now();
  function bucleRender(ahora) {
    var dt = Math.min(0.1, (ahora - tPrev) / 1000); tPrev = ahora;
    if (sim && reproduciendo) {
      tSim += dt * +$('#velocidad').value;
      if (tSim >= sim.T) { tSim = sim.T; reproduciendo = false; $('#btn-play').textContent = '▶'; actualizarTiempo(true); }
      else actualizarTiempo(false);
    }
    actualizarCamara(); renderer.render(scene, camara);
    requestAnimationFrame(bucleRender);
  }

  // ---------------------------------------------------------------- eventos de la barra
  function enlazar() {
    $('#btn-play').onclick = function () { if (!sim) return; if (tSim >= sim.T) tSim = 0; reproduciendo = !reproduciendo; this.textContent = reproduciendo ? '⏸' : '▶'; };
    $('#btn-reiniciar').onclick = function () { if (!sim) return; tSim = 0; reproduciendo = true; $('#btn-play').textContent = '⏸'; actualizarTiempo(true); };
    $('#tiempo').oninput = function () { if (!sim) return; tSim = sim.T * this.value / 1000; actualizarTiempo(true); };
    $('#corte-capa').oninput = function () { actualizarTiempo(true); };
    $('#corte-x').oninput = aplicarCorte;
    $('#modo-color').onchange = function () { colorearEstatico(); actualizarLeyenda(); actualizarTiempo(true); };
    $('#ver-bano').onchange = function () { grupoBano.visible = this.checked; };
    $('#ver-brazos').onchange = function () { actualizarTiempo(true); };
    $('#ver-fantasma').onchange = function () { if (fantasma) fantasma.visible = this.checked; };
    $('#btn-simular').onclick = function () { pedirSim(true); };
    $('#btn-gcode').onclick = function () { pedirSim(false, true); };
    $('#btn-guardar').onclick = function () { descargar('bioimpresora_config.json', JSON.stringify({ version: 1, cfg: cfg, modelo: modelo.tipo === 'implicita' ? modelo.id : null }, null, 2), 'application/json'); };
    $('#in-config').onchange = function (e) {
      var f = e.target.files[0]; if (!f) return; var fr = new FileReader();
      fr.onload = function () { try { var d = JSON.parse(fr.result); cfg = fusionar(CORE.defaults(), d.cfg || d); if (d.modelo && CORE.ORGANOS[d.modelo]) modelo = { tipo: 'implicita', id: d.modelo }; guardarLS(); construirPaneles(); pedirSim(true); } catch (err) { alert('Configuración no válida: ' + err.message); } };
      fr.readAsText(f); e.target.value = '';
    };
    $('#btn-ayuda').onclick = function () { $('#modal-ayuda').hidden = false; };
    $('#cerrar-ayuda').onclick = function () { $('#modal-ayuda').hidden = true; };
    $('#modal-ayuda').onclick = function (e) { if (e.target === this) this.hidden = true; };
    // arrastrar y soltar STL sobre el visor
    var visor = document.querySelector('.visor'), cap = $('#arrastrar');
    visor.addEventListener('dragover', function (e) { e.preventDefault(); cap.hidden = false; });
    visor.addEventListener('dragleave', function (e) { if (e.target === cap) cap.hidden = true; });
    visor.addEventListener('drop', function (e) { e.preventDefault(); cap.hidden = true; var f = e.dataTransfer.files[0]; if (f && /\.stl$/i.test(f.name)) leerSTL(f, false); else if (f) alert('Arrastra un archivo .stl'); });
  }

  // ---------------------------------------------------------------- arranque
  construirPaneles(); enlazar();
  if (iniciar3D()) requestAnimationFrame(bucleRender);
  pedirSim(true);
  window.BIO = { brazos: brazos, cfg: function () { return cfg; }, ia: ia, sim: function () { return sim; }, leerSTL: leerSTL, iniciarIA: iniciarIA };
})();
