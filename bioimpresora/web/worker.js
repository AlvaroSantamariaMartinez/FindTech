/* Worker: simulaciones para la vista 3D y bucle de aprendizaje de la IA.
 * Se ejecuta con `self` real (Web Worker) o con un `self` simulado (modo sin workers). */
var cacheFuente = { clave: null, f: null };
function obtenerFuente(d) {
  var clave = d.tipo === 'implicita' ? 'org:' + d.id : d.clave;
  if (cacheFuente.clave !== clave) {
    cacheFuente = { clave: clave, f: d.tipo === 'implicita' ? CORE.fuenteOrgano(d.id) : CORE.fuenteMalla(d.nombre, new Float32Array(d.tris), d.trisB ? new Float32Array(d.trisB) : null) };
  }
  return cacheFuente.f;
}

var ap = null, fuenteIA = null, corriendo = false, total = 0, ep = 0;

function resumen(r) {
  return { ep: r.ep, u: r.u, combo: r.combo, comboTxt: r.comboTxt, proceso: r.proceso, puntaje: r.puntaje, desglose: r.desglose, metricas: r.metricas, pred: r.pred, razon: r.razon, perdida: r.perdida, ms: r.ms, record: r.record };
}

function bucle() {
  if (!corriendo) return;
  if (ep >= total) { corriendo = false; self.postMessage({ tipo: 'fin', ep: ep }); return; }
  try {
    var r = ap.episodio(fuenteIA, ep, total);
    ep++;
    self.postMessage({ tipo: 'ep', reg: resumen(r), sens: (ep % 5 === 0 || ep === total) ? ap.sensibilidad() : null, claves: ap.claves });
  } catch (err) {
    corriendo = false; self.postMessage({ tipo: 'error', msg: String(err && err.stack || err) }); return;
  }
  setTimeout(bucle, 0);
}

self.onmessage = function (e) {
  var m = e.data;
  try {
    if (m.cmd === 'simular') {
      var f = obtenerFuente(m.fuente);
      var r = CORE.simular(f, m.cfg, { detalle: true, tray: true, gcode: !!m.gcode, resMax: m.resMax });
      var bufs = [r.tdep.buffer, r.tgel.buffer, r.alpha.buffer, r.dosis.buffer, r.viab.buffer];
      self.postMessage({ tipo: 'sim', id: m.id, gcode: !!m.gcode, r: r }, bufs);
    } else if (m.cmd === 'aprender') {
      ap = new CORE.Aprendiz(m.cfg, m.op);
      fuenteIA = m.fuente.tipo === 'implicita' ? CORE.fuenteOrgano(m.fuente.id) : CORE.fuenteMalla(m.fuente.nombre, new Float32Array(m.fuente.tris), m.fuente.trisB ? new Float32Array(m.fuente.trisB) : null);
      total = m.op.episodios; ep = 0; corriendo = true;
      self.postMessage({ tipo: 'inicio', claves: ap.claves, combos: ap.combos });
      setTimeout(bucle, 0);
    } else if (m.cmd === 'pausa') {
      corriendo = false; self.postMessage({ tipo: 'pausado', ep: ep });
    } else if (m.cmd === 'continuar') {
      if (ap && !corriendo) { total = Math.max(total, ep + (m.extra || 0)); corriendo = true; setTimeout(bucle, 0); }
    }
  } catch (err) {
    self.postMessage({ tipo: 'error', id: m.id, msg: String(err && err.stack || err) });
  }
};
