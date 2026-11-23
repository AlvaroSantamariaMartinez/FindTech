/* =========================================================================
 * BioImpresora – núcleo de simulación + aprendizaje profundo (JS puro)
 * Compartido entre la interfaz y los Web Workers. Sin dependencias.
 * Unidades: mm, s, kPa, Pa, mW/cm², mJ/cm², °C, g/mL.
 * ========================================================================= */
var CORE = (function () {
  'use strict';

  // ---------------------------------------------------------------- config
  var COMBOS = ['por_capa|secuencial', 'por_capa|paralelo', 'seguimiento|secuencial'];
  var COMBO_TXT = { 'por_capa|secuencial': 'UV por capa · secuencial', 'por_capa|paralelo': 'UV por capa · paralelo', 'seguimiento|secuencial': 'UV seguimiento · secuencial' };

  var PARAMS_PROCESO = [
    // clave, etiqueta, unidad, min, max, defecto, escala log
    ['presion_e1', 'Presión E1', 'kPa', 30, 250, 110, true],
    ['presion_e2', 'Presión E2', 'kPa', 20, 200, 85, true],
    ['velocidad', 'Velocidad de impresión', 'mm/s', 2, 25, 8, true],
    ['altura_capa', 'Altura de capa', 'mm', 0.15, 0.5, 0.3, false],
    ['intensidad_uv', 'Intensidad UV', 'mW/cm²', 3, 100, 20, true],
    ['velocidad_uv', 'Velocidad barrido UV', 'mm/s', 0.5, 15, 3, true],
    ['retardo_uv', 'Retardo UV (seguimiento)', 's', 0.1, 6, 1, true],
    ['fotoiniciador', 'Fotoiniciador (primer)', '% p/v', 0.05, 1.5, 0.5, true]
  ];

  function defaults() {
    var proc = {}, rangos = {}, optimizar = {};
    PARAMS_PROCESO.forEach(function (p) { proc[p[0]] = p[5]; rangos[p[0]] = [p[3], p[4]]; optimizar[p[0]] = true; });
    proc.modo_uv = 'por_capa';
    proc.estrategia = 'secuencial';
    return {
      maquina: {
        e1: { diam: 0.25, largo: 6, v_viaje: 40, acel: 600, radio: 1.5, temp: 22, reposo: [-28, 0] },
        e2: { diam: 0.25, largo: 6, v_viaje: 40, acel: 600, radio: 1.5, temp: 22, reposo: [28, 0] },
        uv: { lambda: 365, spot: 4, i_max: 100, sep: 3.2, v_viaje: 40, acel: 600, radio: 2.5, reposo: [0, 28] },
        aux: { activo: false, rol: 'Sin uso (reservado)', radio: 1.5, reposo: [0, -28] },
        t_cambio_capa: 0.5,
        res_max: 64
      },
      tintaA: {
        nombre: 'GelMA-PEGDA estructural', tau0: 150, K: 80, n: 0.4, densidad: 1.04,
        alpha_gel: 0.30, k_cura: 0.075, mu: 0.3, mu_pi: 1.2, i_inh: 3,
        t_ext: 30, ext_max: 0.6, celulas: false, dens_cel: 0, tau_crit: 1500, dosis_letal: 400
      },
      tintaB: {
        nombre: 'GelMA 7% + células', tau0: 40, K: 40, n: 0.5, densidad: 1.03,
        alpha_gel: 0.25, k_cura: 0.07, mu: 0.5, mu_pi: 1.2, i_inh: 3,
        t_ext: 8, ext_max: 0.6, celulas: true, dens_cel: 5, tau_crit: 1500, dosis_letal: 400
      },
      primer: { tipo: 'LAP' },
      bano: {
        activo: true, nombre: 'Microgel de gelatina (FRESH)', tau0: 40, K: 2, t_reparacion: 0.5,
        densidad: 1.01, temperatura: 22, mu_uv: 0.05, nivel: 20, oxigeno: 1.0
      },
      proceso: proc,
      rangos: rangos,
      optimizar: optimizar,
      optimizar_modo: true,
      asignacion: { modo: 'carcasa', grosor: 0.6 },
      puntaje: { w_fid: 40, w_viab: 25, w_cura: 10, w_tiempo: 10, w_riesgo: 5, w_material: 10, t_ref_min: 20, viab_min: 0.7 }
    };
  }

  // -------------------------------------------------------------- materiales
  var EFIC_PRIMER = { LAP: { 365: 1, 385: 0.9, 405: 0.6 }, I2959: { 365: 1, 385: 0.35, 405: 0.03 }, 'Ru/SPS': { 365: 0.3, 385: 0.5, 405: 0.9 } };
  var DANO_LAMBDA = { 365: 1, 385: 0.6, 405: 0.35 };

  function esfuerzoPared(P, R, L) { return P * 1e3 * R / (2 * L); }
  function caudal(t, P, R, L, Tc) {
    var tef = esfuerzoPared(P, R, L) - t.tau0;
    if (tef <= 0) return 0;
    var K = t.K * Math.exp(0.04 * (22 - Tc));
    var r = R * 1e-3;
    return Math.PI * t.n * r * r * r / (3 * t.n + 1) * Math.pow(tef / K, 1 / t.n) * 1e9; // mm³/s
  }
  function supCizalla(t, P, R, L) {
    if (!t.celulas) return 1;
    var tw = esfuerzoPared(P, R, L);
    return Math.exp(-0.15 * Math.pow(tw / t.tau_crit, 2));
  }
  function muTinta(t, pi) { return t.mu + t.mu_pi * pi + (t.celulas ? 0.04 * t.dens_cel : 0); }

  // ---------------------------------------------------------------- fuentes
  // Una "fuente" describe el órgano: implícita (función) o malla STL (triángulos).
  function hexDentro(x, y, R) { var ax = Math.abs(x), ay = Math.abs(y); return ay <= R * Math.sqrt(3) / 2 && Math.sqrt(3) * ax + ay <= Math.sqrt(3) * R; }
  var ORGANOS = {
    vaso: { nombre: 'Vaso sanguíneo', bbox: [-3.4, 3.4, -3.4, 3.4, 0, 5], etiqueta: function (x, y) {
      var r = Math.hypot(x, y); if (r >= 1.4 && r < 2.0) return 2; if (r >= 2.0 && r < 3.2) return 1; return 0; } },
    lobulo_hepatico: { nombre: 'Lóbulo hepático', bbox: [-3.8, 3.8, -3.4, 3.4, 0, 4], etiqueta: function (x, y) {
      var R = 3.6; if (!hexDentro(x, y, R)) return 0;
      var r = Math.hypot(x, y); if (r < 0.6) return 0;
      var ay = Math.abs(y), ax = Math.abs(x);
      var dBorde = Math.min(R * Math.sqrt(3) / 2 - ay, (Math.sqrt(3) * R - Math.sqrt(3) * ax - ay) / 2);
      var th = Math.atan2(y, x), dr = Infinity;
      for (var k = 0; k < 6; k++) { var ph = (30 + 60 * k) * Math.PI / 180; if (r * Math.cos(th - ph) > 0) dr = Math.min(dr, Math.abs(r * Math.sin(th - ph))); }
      return (dr < 0.3 || dBorde < 0.4) ? 1 : 2; } },
    parche_cardiaco: { nombre: 'Parche cardíaco', bbox: [-3.9, 3.9, -3.9, 3.9, 0, 2], etiqueta: function (x, y) {
      var p = 1.5, w = 0.5, L = 3.75; if (Math.abs(x) > L || Math.abs(y) > L) return 0;
      var fx = (x + L) % p, fy = (y + L) % p; if (fx < w || fy < w) return 1;
      var i = Math.floor((x + L) / p), j = Math.floor((y + L) / p); return (i + j) % 2 === 0 ? 2 : 0; } },
    corazon: { nombre: 'Corazón (mini)', bbox: [-6.9, 6.9, -4.5, 4.5, 0, 13.2], dentro: function (x, y, z) {
      var s = 6, X = x / s, Y = y / s, Z = (z - 6) / s;
      var a = X * X + 2.25 * Y * Y + Z * Z - 1; return a * a * a - X * X * Z * Z * Z - 0.1125 * Y * Y * Z * Z * Z <= 0; } },
    rinon: { nombre: 'Riñón (mini)', bbox: [-4.2, 4.2, -6.2, 6.2, 0, 5.6], dentro: function (x, y, z) {
      var Z = z - 2.8; var e = (x / 4) * (x / 4) + (y / 6) * (y / 6) + (Z / 2.8) * (Z / 2.8);
      var hilio = (x - 4.4) * (x - 4.4) + y * y + Z * Z * 0.6 < 2.4 * 2.4; return e <= 1 && !hilio; } }
  };

  function fuenteOrgano(nombre) { var o = ORGANOS[nombre]; return { tipo: 'implicita', id: nombre, nombre: o.nombre, bbox: o.bbox, etiqueta: o.etiqueta, dentro: o.dentro }; }

  function fuenteMalla(nombre, tris, trisB) {
    var b = [Infinity, -Infinity, Infinity, -Infinity, Infinity, -Infinity];
    for (var i = 0; i < tris.length; i += 3) {
      b[0] = Math.min(b[0], tris[i]); b[1] = Math.max(b[1], tris[i]);
      b[2] = Math.min(b[2], tris[i + 1]); b[3] = Math.max(b[3], tris[i + 1]);
      b[4] = Math.min(b[4], tris[i + 2]); b[5] = Math.max(b[5], tris[i + 2]);
    }
    return { tipo: 'malla', id: 'stl', nombre: nombre, bbox: b, tris: tris, trisB: trisB || null, _cache: {} };
  }

  // ---------------------------------------------------------------- STL
  function parseSTL(buf) {
    var dv = new DataView(buf), n = buf.byteLength >= 84 ? dv.getUint32(80, true) : 0;
    var tris;
    if (n > 0 && 84 + n * 50 === buf.byteLength) {
      tris = new Float32Array(n * 9);
      for (var t = 0; t < n; t++) for (var v = 0; v < 9; v++) tris[t * 9 + v] = dv.getFloat32(84 + t * 50 + 12 + v * 4, true);
    } else {
      var txt = new TextDecoder().decode(new Uint8Array(buf));
      var re = /vertex\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)/g, m, arr = [];
      while ((m = re.exec(txt))) arr.push(+m[1], +m[2], +m[3]);
      if (!arr.length) throw new Error('No se reconoce el STL (ni binario ni ASCII)');
      tris = new Float32Array(arr.length - (arr.length % 9));
      for (var k = 0; k < tris.length; k++) tris[k] = arr[k];
    }
    return tris;
  }

  // Normaliza: escala a "tam" mm (dimensión mayor), centra en XY y apoya en z=0.
  function normalizarMalla(tris, tam, ejeArribaY, refBbox) {
    var out = new Float32Array(tris.length), i;
    for (i = 0; i < tris.length; i += 3) {
      if (ejeArribaY) { out[i] = tris[i]; out[i + 1] = -tris[i + 2]; out[i + 2] = tris[i + 1]; }
      else { out[i] = tris[i]; out[i + 1] = tris[i + 1]; out[i + 2] = tris[i + 2]; }
    }
    var b = refBbox || fuenteMalla('', out).bbox;
    var d = Math.max(b[1] - b[0], b[3] - b[2], b[5] - b[4]) || 1, s = tam / d;
    var cx = (b[0] + b[1]) / 2, cy = (b[2] + b[3]) / 2;
    for (i = 0; i < out.length; i += 3) { out[i] = (out[i] - cx) * s; out[i + 1] = (out[i + 1] - cy) * s; out[i + 2] = (out[i + 2] - b[4]) * s; }
    return { tris: out, bbox: b };
  }

  // Cruces de rayos verticales con la malla para cada columna (x_i, y_j).
  function cruces(tris, xs, ys) {
    var nx = xs.length, ny = ys.length, col = new Array(nx * ny);
    for (var c = 0; c < col.length; c++) col[c] = [];
    var res = xs.length > 1 ? xs[1] - xs[0] : 1, x0 = xs[0], y0 = ys[0];
    var ex = 1.3e-4 * res, ey = 0.7e-4 * res; // desplazamiento para evitar aristas exactas
    for (var t = 0; t < tris.length; t += 9) {
      var ax = tris[t], ay = tris[t + 1], az = tris[t + 2], bx = tris[t + 3], by = tris[t + 4], bz = tris[t + 5], cx = tris[t + 6], cy = tris[t + 7], cz = tris[t + 8];
      var den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
      if (Math.abs(den) < 1e-14) continue;
      var i0 = Math.max(0, Math.ceil((Math.min(ax, bx, cx) - x0) / res - 1e-9)), i1 = Math.min(nx - 1, Math.floor((Math.max(ax, bx, cx) - x0) / res + 1e-9));
      var j0 = Math.max(0, Math.ceil((Math.min(ay, by, cy) - y0) / res - 1e-9)), j1 = Math.min(ny - 1, Math.floor((Math.max(ay, by, cy) - y0) / res + 1e-9));
      for (var j = j0; j <= j1; j++) {
        var py = ys[j] + ey;
        for (var i = i0; i <= i1; i++) {
          var px = xs[i] + ex;
          var l1 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / den;
          var l2 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / den;
          var l3 = 1 - l1 - l2;
          if (l1 >= 0 && l2 >= 0 && l3 >= 0) col[j * nx + i].push(l1 * az + l2 * bz + l3 * cz);
        }
      }
    }
    for (c = 0; c < col.length; c++) {
      var a = col[c]; if (!a.length) continue;
      a.sort(function (p, q) { return p - q; });
      var u = [a[0]]; for (var k = 1; k < a.length; k++) if (a[k] - u[u.length - 1] > 1e-6) u.push(a[k]);
      if (u.length % 2) u.pop();
      col[c] = u;
    }
    return col;
  }
  function dentroIntervalos(iv, z) { for (var k = 0; k + 1 < iv.length; k += 2) if (z >= iv[k] && z <= iv[k + 1]) return true; return false; }
  function distVertical(iv, z) { var d = Infinity; for (var k = 0; k < iv.length; k++) d = Math.min(d, Math.abs(z - iv[k])); return d; }

  // --------------------------------------------------- transformada de distancia
  function dt1d(f, n, d, v, z) {
    var k = 0; v[0] = 0; z[0] = -1e20; z[1] = 1e20;
    for (var q = 1; q < n; q++) {
      var s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
      while (s <= z[k]) { k--; s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]); }
      k++; v[k] = q; z[k] = s; z[k + 1] = 1e20;
    }
    k = 0;
    for (q = 0; q < n; q++) { while (z[k + 1] < q) k++; d[q] = (q - v[k]) * (q - v[k]) + f[v[k]]; }
  }
  // Distancia euclídea (en celdas) de cada celda a la celda "objetivo" más cercana.
  function edt(obj, nx, ny) {
    var N = Math.max(nx, ny), f = new Float64Array(N), d = new Float64Array(N), v = new Int32Array(N), z = new Float64Array(N + 1);
    var g = new Float64Array(nx * ny), i, j;
    for (i = 0; i < nx * ny; i++) g[i] = obj[i] ? 0 : 1e20;
    for (j = 0; j < ny; j++) { for (i = 0; i < nx; i++) f[i] = g[j * nx + i]; dt1d(f, nx, d, v, z); for (i = 0; i < nx; i++) g[j * nx + i] = d[i]; }
    for (i = 0; i < nx; i++) { for (j = 0; j < ny; j++) f[j] = g[j * nx + i]; dt1d(f, ny, d, v, z); for (j = 0; j < ny; j++) g[j * nx + i] = Math.sqrt(d[j]); }
    return g;
  }
  // Distancia con signo en mm (negativa dentro).
  function distSignada(mask, nx, ny, res) {
    var n = nx * ny, inv = new Uint8Array(n), i;
    for (i = 0; i < n; i++) inv[i] = mask[i] ? 0 : 1;
    var dOut = edt(mask, nx, ny), dIn = edt(inv, nx, ny), sd = new Float64Array(n);
    for (i = 0; i < n; i++) sd[i] = mask[i] ? -(Math.min(dIn[i], 1e3) * res - res / 2) : (Math.min(dOut[i], 1e3) * res - res / 2);
    return sd;
  }

  // ---------------------------------------------------------------- vóxeles
  function voxelizar(fuente, res, h, asig) {
    var b = fuente.bbox;
    var nx = Math.ceil((b[1] - b[0]) / res) + 2, ny = Math.ceil((b[3] - b[2]) / res) + 2;
    var nz = Math.max(1, Math.round((b[5] - b[4]) / h));
    var cx = (b[0] + b[1]) / 2, cy = (b[2] + b[3]) / 2;
    var xs = new Float64Array(nx), ys = new Float64Array(ny), i, j, k;
    for (i = 0; i < nx; i++) xs[i] = cx + (i + 0.5 - nx / 2) * res;
    for (j = 0; j < ny; j++) ys[j] = cy + (j + 0.5 - ny / 2) * res;
    var nxy = nx * ny, mat = new Int8Array(nxy * nz);
    var zc = function (k) { return b[4] + (k + 0.5) * h; };

    if (fuente.tipo === 'implicita' && fuente.etiqueta) {
      for (k = 0; k < nz; k++) for (j = 0; j < ny; j++) for (i = 0; i < nx; i++) mat[k * nxy + j * nx + i] = fuente.etiqueta(xs[i], ys[j], zc(k));
      return { nx: nx, ny: ny, nz: nz, res: res, h: h, xs: xs, ys: ys, mat: mat, z0: b[4] };
    }
    var dentro = new Uint8Array(nxy * nz), ivA = null, ivB = null;
    if (fuente.tipo === 'malla') {
      var clave = res.toFixed(5);
      if (!fuente._cache[clave]) fuente._cache[clave] = { A: cruces(fuente.tris, xs, ys), B: fuente.trisB ? cruces(fuente.trisB, xs, ys) : null };
      ivA = fuente._cache[clave].A; ivB = fuente._cache[clave].B;
      for (k = 0; k < nz; k++) for (var c = 0; c < nxy; c++) dentro[k * nxy + c] = dentroIntervalos(ivA[c], zc(k)) ? 1 : 0;
    } else {
      for (k = 0; k < nz; k++) for (j = 0; j < ny; j++) for (i = 0; i < nx; i++) dentro[k * nxy + j * nx + i] = fuente.dentro(xs[i], ys[j], zc(k)) ? 1 : 0;
    }
    var modo = asig.modo;
    if (modo === 'mallaB' && !ivB) modo = 'carcasa';
    for (k = 0; k < nz; k++) {
      var capa = dentro.subarray(k * nxy, (k + 1) * nxy);
      if (modo === 'todoA' || modo === 'todoB') { for (c = 0; c < nxy; c++) mat[k * nxy + c] = capa[c] ? (modo === 'todoA' ? 1 : 2) : 0; continue; }
      if (modo === 'mallaB') { for (c = 0; c < nxy; c++) mat[k * nxy + c] = capa[c] ? (dentroIntervalos(ivB[c], zc(k)) ? 2 : 1) : 0; continue; }
      // carcasa (A) + núcleo (B)
      var inv = new Uint8Array(nxy); for (c = 0; c < nxy; c++) inv[c] = capa[c] ? 0 : 1;
      var dl = edt(inv, nx, ny);
      for (c = 0; c < nxy; c++) {
        if (!capa[c]) continue;
        var lat = dl[c] * res - res / 2, ver;
        if (ivA) ver = distVertical(ivA[c], zc(k));
        else { // implícita: distancia vertical buscando hacia arriba/abajo
          ver = Infinity;
          for (var dk = 1; dk * h < asig.grosor + h; dk++) {
            if (k - dk < 0 || !dentro[(k - dk) * nxy + c] || k + dk >= nz || !dentro[(k + dk) * nxy + c]) { ver = (dk - 0.5) * h; break; }
          }
        }
        mat[k * nxy + c] = Math.min(lat, ver) < asig.grosor ? 1 : 2;
      }
    }
    return { nx: nx, ny: ny, nz: nz, res: res, h: h, xs: xs, ys: ys, mat: mat, z0: b[4] };
  }

  // ---------------------------------------------------------------- cinemática
  function tViaje(d, v, a) { if (d <= 0) return 0; var da = v * v / a; return d >= da ? d / v + v / a : 2 * Math.sqrt(d / a); }

  function Tray(t0, x, y) { this.t = [t0]; this.x = [x]; this.y = [y]; this.on = [0]; }
  Tray.prototype.fin = function () { return this.t[this.t.length - 1]; };
  Tray.prototype.px = function () { return this.x[this.x.length - 1]; };
  Tray.prototype.py = function () { return this.y[this.y.length - 1]; };
  Tray.prototype.mover = function (x, y, dur, on) { this.t.push(this.fin() + Math.max(dur, 0)); this.x.push(x); this.y.push(y); this.on.push(on ? 1 : 0); };
  Tray.prototype.viajar = function (x, y, v, a, f) { var d = Math.hypot(x - this.px(), y - this.py()); if (d > 0) this.mover(x, y, tViaje(d, v, a) * (f || 1), 0); };
  Tray.prototype.esperarHasta = function (t) { if (t > this.fin()) this.mover(this.px(), this.py(), t - this.fin(), 0); };
  Tray.prototype.desplazada = function (dt) { var r = new Tray(0, 0, 0); r.t = this.t.map(function (v) { return v + dt; }); r.x = this.x.slice(); r.y = this.y.slice(); r.on = this.on.slice(); return r; };
  Tray.prototype.anexar = function (o) { this.esperarHasta(o.t[0]); for (var i = 1; i < o.t.length; i++) { this.t.push(o.t[i]); this.x.push(o.x[i]); this.y.push(o.y[i]); this.on.push(o.on[i]); } };
  Tray.prototype.pos = function (t) { // búsqueda binaria + interpolación
    var T = this.t, n = T.length; if (t <= T[0]) return [this.x[0], this.y[0], 0]; if (t >= T[n - 1]) return [this.x[n - 1], this.y[n - 1], 0];
    var lo = 0, hi = n - 1; while (hi - lo > 1) { var m = (lo + hi) >> 1; if (T[m] <= t) lo = m; else hi = m; }
    var f = (t - T[lo]) / ((T[hi] - T[lo]) || 1); return [this.x[lo] + f * (this.x[hi] - this.x[lo]), this.y[lo] + f * (this.y[hi] - this.y[lo]), this.on[hi]];
  };

  function holguraMin(a, b, ra, rb, t0, t1) {
    if (t1 <= t0) return { h: Infinity, c: 0 };
    var dt = Math.max(0.1, (t1 - t0) / 1500), h = Infinity, c = 0;
    for (var t = t0; t <= t1; t += dt) { var p = a.pos(t), q = b.pos(t), d = Math.hypot(p[0] - q[0], p[1] - q[1]) - ra - rb; if (d < h) h = d; if (d < 0) c++; }
    return { h: h, c: c };
  }

  // ---------------------------------------------------------------- planificador
  function raster(geo, k, etiqueta, transp, invertir, v, kf, tray, cfg, tdep, gc) {
    var nx = geo.nx, ny = geo.ny, nxy = nx * ny, base = k * nxy, res = geo.res, dist = 0, ultimo = -Infinity;
    var nL = transp ? nx : ny, nA = transp ? ny : nx, sentido = 1;
    for (var li = 0; li < nL; li++) {
      var l = invertir ? nL - 1 - li : li, tramos = [], a = -1;
      for (var q = 0; q <= nA; q++) {
        var on = q < nA && geo.mat[base + (transp ? q * nx + l : l * nx + q)] === etiqueta;
        if (on && a < 0) a = q; if (!on && a >= 0) { tramos.push([a, q - 1]); a = -1; }
      }
      if (!tramos.length) continue;
      if (sentido < 0) tramos = tramos.reverse().map(function (s) { return [s[1], s[0]]; });
      for (var s = 0; s < tramos.length; s++) {
        var ia = tramos[s][0], ib = tramos[s][1];
        var ca = transp ? geo.ys[ia] : geo.xs[ia], cb = transp ? geo.ys[ib] : geo.xs[ib], cl = transp ? geo.xs[l] : geo.ys[l];
        var pa = transp ? [cl, ca] : [ca, cl], pb = transp ? [cl, cb] : [cb, cl];
        tray.viajar(pa[0], pa[1], cfg.v_viaje, cfg.acel, kf);
        var t0 = tray.fin(), lo = Math.min(ia, ib), hi = Math.max(ia, ib);
        for (var q2 = lo; q2 <= hi; q2++) {
          var cq = transp ? geo.ys[q2] : geo.xs[q2], idx = base + (transp ? q2 * nx + l : l * nx + q2);
          tdep[idx] = t0 + kf * Math.abs(cq - ca) / v; if (tdep[idx] > ultimo) ultimo = tdep[idx];
        }
        var largo = Math.abs(cb - ca) + res;
        tray.mover(pb[0], pb[1], kf * largo / v, 1); dist += largo * kf;
        if (gc) gc.push('G0 X' + pa[0].toFixed(3) + ' Y' + pa[1].toFixed(3), 'M701', 'G1 X' + pb[0].toFixed(3) + ' Y' + pb[1].toFixed(3) + ' F' + Math.round(v * 60), 'M702');
      }
      sentido = -sentido;
    }
    return { dist: dist, ultimo: ultimo };
  }

  function planificar(geo, cfg, opt) {
    opt = opt || {};
    var M = cfg.maquina, P = cfg.proceso, nxy = geo.nx * geo.ny, N = nxy * geo.nz;
    var estrategia = P.modo_uv === 'seguimiento' ? 'secuencial' : P.estrategia;
    var w = Math.min(M.e1.diam, M.e2.diam), kf = Math.max(1, geo.res / w);
    var tdep = new Float64Array(N).fill(NaN), pasadas = [], gc = opt.gcode ? [] : null;
    var trays = { E1: new Tray(0, M.e1.reposo[0], M.e1.reposo[1]), E2: new Tray(0, M.e2.reposo[0], M.e2.reposo[1]), UV: new Tray(0, M.uv.reposo[0], M.uv.reposo[1]), AUX: new Tray(0, M.aux.reposo[0], M.aux.reposo[1]) };
    var t = 0, espera = 0, choques = 0, holgura = Infinity, dist = { E1: 0, E2: 0 }, capaT = [], rSpot = M.uv.spot / 2;
    if (gc) gc.push('; G-code generado por BioImpresora (simulador)', '; capas=' + geo.nz + ' modo=' + P.modo_uv + '+' + estrategia,
      '; T0=E1 T1=E2 T2=UV T3=AUX (' + M.aux.rol + ')', '; M700 P<kPa> presion | M701/M702 valvula | M710 S<mW/cm2>/M711 UV', 'G21', 'G90');

    function extrusor(nom, cm, etiq, presion, k, t0, inv) {
      var tr = new Tray(t0, cm.reposo[0], cm.reposo[1]);
      if (gc) gc.push('; --- ' + nom + ' ---', nom === 'E1' ? 'T0' : 'T1', 'M700 P' + presion.toFixed(1));
      var r = raster(geo, k, etiq, k % 2 === 1, inv, P.velocidad, kf, tr, cm, tdep, gc);
      tr.viajar(cm.reposo[0], cm.reposo[1], cm.v_viaje, cm.acel);
      return { tr: tr, dist: r.dist, ultimo: r.ultimo };
    }

    for (var k = 0; k < geo.nz; k++) {
      capaT.push(t);
      if (gc) gc.push('; ===== CAPA ' + k + ' =====', 'G0 Z' + ((k + 1) * geo.h).toFixed(3));
      var r1, r2;
      if (estrategia === 'paralelo') {
        r1 = extrusor('E1', M.e1, 1, P.presion_e1, k, t, false);
        var r2b = extrusor('E2', M.e2, 2, P.presion_e2, k, t, true);
        var dur1 = r1.tr.fin() - t, paso = Math.max(0.5, dur1 / 60), ret = 0, hh = null;
        for (ret = 0; ret <= dur1 + paso; ret += paso) {
          var cand = r2b.tr.desplazada(ret); hh = holguraMin(r1.tr, cand, M.e1.radio, M.e2.radio, t, Math.max(r1.tr.fin(), cand.fin()));
          if (hh.c === 0) break;
        }
        ret = Math.min(ret, dur1 + paso);
        r2 = { tr: r2b.tr.desplazada(ret), dist: r2b.dist, ultimo: r2b.ultimo + ret };
        for (var q = k * nxy; q < (k + 1) * nxy; q++) if (geo.mat[q] === 2) tdep[q] += ret;
        espera += ret; choques += hh.c; holgura = Math.min(holgura, hh.h);
      } else {
        r1 = extrusor('E1', M.e1, 1, P.presion_e1, k, t, false);
        var inicio2 = r1.tr.fin();
        if (P.modo_uv === 'seguimiento' && r1.ultimo > -Infinity) inicio2 = Math.max(inicio2, r1.ultimo + P.retardo_uv + rSpot / P.velocidad);
        r2 = extrusor('E2', M.e2, 2, P.presion_e2, k, inicio2, false);
      }
      trays.E1.anexar(r1.tr); trays.E2.anexar(r2.tr);
      dist.E1 += r1.dist; dist.E2 += r2.dist;
      t = Math.max(r1.tr.fin(), r2.tr.fin());

      var tuv = new Float64Array(nxy).fill(NaN), texp;
      if (P.modo_uv === 'por_capa') {
        var tr = new Tray(t, M.uv.reposo[0], M.uv.reposo[1]);
        var j0 = 1e9, j1 = -1, i0 = 1e9, i1 = -1, j, i;
        for (j = 0; j < geo.ny; j++) for (i = 0; i < geo.nx; i++) if (geo.mat[k * nxy + j * geo.nx + i]) { j0 = Math.min(j0, j); j1 = Math.max(j1, j); i0 = Math.min(i0, i); i1 = Math.max(i1, i); }
        texp = Math.PI * rSpot * rSpot / (P.velocidad_uv * M.uv.sep);
        if (j1 >= 0) {
          if (gc) gc.push('; --- UV barrido ---', 'T2');
          var y0 = geo.ys[j0], y1 = geo.ys[j1], x0 = geo.xs[i0] - rSpot, x1 = geo.xs[i1] + rSpot;
          var nf = Math.max(1, Math.ceil((y1 - y0) / M.uv.sep) + 1), yf = [];
          for (var f = 0; f < nf; f++) yf.push((y0 + y1) / 2 + (f - (nf - 1) / 2) * M.uv.sep);
          for (f = 0; f < nf; f++) {
            var ini = f % 2 === 0 ? x0 : x1, fin = f % 2 === 0 ? x1 : x0;
            tr.viajar(ini, yf[f], M.uv.v_viaje, M.uv.acel);
            var tt0 = tr.fin(); tr.mover(fin, yf[f], Math.abs(x1 - x0) / P.velocidad_uv, 1);
            if (gc) gc.push('G0 X' + ini.toFixed(3) + ' Y' + yf[f].toFixed(3), 'M710 S' + P.intensidad_uv.toFixed(1), 'G1 X' + fin.toFixed(3) + ' Y' + yf[f].toFixed(3) + ' F' + Math.round(P.velocidad_uv * 60), 'M711');
            for (j = 0; j < geo.ny; j++) {
              var best = 0, bd = Infinity; for (var g = 0; g < nf; g++) { var dd = Math.abs(geo.ys[j] - yf[g]); if (dd < bd) { bd = dd; best = g; } }
              if (best !== f || bd > Math.max(M.uv.sep / 2, rSpot) + 1e-9) continue;
              for (i = 0; i < geo.nx; i++) if (geo.xs[i] >= x0 - 1e-9 && geo.xs[i] <= x1 + 1e-9) tuv[j * geo.nx + i] = tt0 + Math.abs(geo.xs[i] - ini) / P.velocidad_uv;
            }
          }
        }
        tr.viajar(M.uv.reposo[0], M.uv.reposo[1], M.uv.v_viaje, M.uv.acel);
        trays.UV.anexar(tr); t = tr.fin();
      } else {
        texp = Math.PI * rSpot * rSpot / (P.velocidad * w);
        var finUV = t;
        for (var c = 0; c < nxy; c++) { var td = tdep[k * nxy + c]; if (td === td) { tuv[c] = td + P.retardo_uv; if (tuv[c] > finUV) finUV = tuv[c]; } }
        if (opt.tray) { // el brazo UV copia la trayectoria del extrusor con retardo
          [r1.tr, r2.tr].forEach(function (src) { var d = src.desplazada(P.retardo_uv); for (var m = 1; m < d.t.length; m++) { if (d.t[m] > trays.UV.fin()) { trays.UV.esperarHasta(d.t[m - 1]); trays.UV.mover(d.x[m], d.y[m], d.t[m] - trays.UV.fin(), d.on[m]); } } trays.UV.viajar(M.uv.reposo[0], M.uv.reposo[1], M.uv.v_viaje, M.uv.acel); });
        }
        if (gc) gc.push('; UV en seguimiento: retardo ' + P.retardo_uv.toFixed(2) + ' s, ' + P.intensidad_uv.toFixed(1) + ' mW/cm2');
        t = Math.max(t, finUV + rSpot / P.velocidad);
      }
      pasadas.push({ L: k, tuv: tuv, texp: texp });
      t += M.t_cambio_capa;
      for (var nm in trays) trays[nm].esperarHasta(t);
    }
    capaT.push(t);
    if (gc) gc.push('; fin', 'M711', 'M702', 'G0 Z30');
    return { tdep: tdep, pasadas: pasadas, T: t, espera: espera, choques: choques, holgura: holgura, dist: dist, trays: opt.tray ? trays : null, capaT: capaT, gcode: gc, kf: kf, estrategia: estrategia };
  }

  // ---------------------------------------------------------------- simulador
  function mediana(arr) { if (!arr.length) return Infinity; arr.sort(function (a, b) { return a - b; }); return arr[arr.length >> 1]; }

  function simular(fuente, cfg, opt) {
    opt = opt || {};
    var M = cfg.maquina, P = cfg.proceso, B = cfg.bano, tintas = [null, cfg.tintaA, cfg.tintaB];
    var w = Math.min(M.e1.diam, M.e2.diam), b = fuente.bbox;
    var dimMax = Math.max(b[1] - b[0], b[3] - b[2]);
    var res = Math.max(w, dimMax / (opt.resMax || M.res_max));
    var geo = voxelizar(fuente, res, P.altura_capa, cfg.asignacion);
    var plan = planificar(geo, cfg, { tray: opt.tray, gcode: opt.gcode });
    var nx = geo.nx, ny = geo.ny, nz = geo.nz, nxy = nx * ny, N = nxy * nz, h = geo.h, i, k, c;

    var lam = M.uv.lambda, efic = (EFIC_PRIMER[cfg.primer.tipo] || EFIC_PRIMER.LAP)[lam] || 1, dano = DANO_LAMBDA[lam] || 1;
    var pi = P.fotoiniciador, I0 = Math.min(P.intensidad_uv, M.uv.i_max);
    var o2 = B.activo ? B.oxigeno : 1.5;
    var kc = [0], mu = [0], iinh = [0], ag = [2];
    for (var m = 1; m <= 2; m++) { var tm = tintas[m]; kc.push(tm.k_cura * Math.sqrt(Math.max(pi, 1e-6) / 0.5) * Math.sqrt(efic)); mu.push(muTinta(tm, pi)); iinh.push(tm.i_inh * o2); ag.push(tm.alpha_gel); }

    var alpha = new Float64Array(N), dosis = new Float64Array(N), tgel = new Float64Array(N).fill(Infinity);
    // ------------------------------------------------ curado por pasadas UV
    for (var pIdx = 0; pIdx < plan.pasadas.length; pIdx++) {
      var pas = plan.pasadas[pIdx], L = pas.L, te = pas.texp;
      var cubierta = B.activo ? Math.max(0, B.nivel - (L + 1) * h) : 0;
      var Itop = I0 * Math.exp(-B.mu_uv * cubierta);
      for (c = 0; c < nxy; c++) {
        var tu = pas.tuv[c]; if (tu !== tu) continue;
        var od = 0;
        for (k = L; k >= 0; k--) {
          var idx = k * nxy + c, e = geo.mat[idx]; if (!e) continue;
          var I = Itop * Math.exp(-(od + 0.5 * mu[e] * h)); od += mu[e] * h;
          var kef = kc[e] * Math.sqrt(Math.max(I - iinh[e], 0)), a0 = alpha[idx];
          var a1 = 1 - (1 - a0) * Math.exp(-kef * te);
          if (a0 < ag[e] && a1 >= ag[e]) tgel[idx] = tu + Math.log((1 - a0) / (1 - ag[e])) / kef;
          alpha[idx] = a1; dosis[idx] += I * te;
          if (I < 0.02 * Itop && I < iinh[e]) break;
        }
      }
    }

    // ------------------------------------------------ forma resultante
    var relacion = [0, 0, 0], tc = [0, M.e1, M.e2], pres = [0, P.presion_e1, P.presion_e2];
    for (m = 1; m <= 2; m++) relacion[m] = caudal(tintas[m], pres[m], tc[m].diam / 2, tc[m].largo, tc[m].temp) / (P.velocidad * tc[m].diam * h);
    var soporte = B.activo ? 1 / (1 + B.tau0 / 20) * (1 / (1 + Math.max(0, 25 - B.temperatura) / 10)) : 1;
    var capas = [], ocup2d = new Float64Array(N), hReal = new Float64Array(nz);
    var largoMedio = 0, nTramos = 0;
    for (k = 0; k < nz; k++) {
      var alt = 0, peso = 0, info = { ancho: [0, 1, 1], sigma: [0, 0, 0], fgel: [0, 1, 1], ext: [0, 0, 0] };
      for (m = 1; m <= 2; m++) {
        var mask = new Uint8Array(nxy), cnt = 0, esperas = [], ngel = 0;
        for (c = 0; c < nxy; c++) if (geo.mat[k * nxy + c] === m) { mask[c] = 1; cnt++; var idx2 = k * nxy + c; esperas.push(tgel[idx2] - plan.tdep[idx2]); if (alpha[idx2] >= ag[m]) ngel++; }
        if (!cnt) continue;
        var tm2 = tintas[m], r = relacion[m];
        var tg = mediana(esperas); tg = isFinite(tg) ? Math.max(tg, 0) : 1e9;
        var s = tm2.ext_max * (1 - Math.exp(-tg / tm2.t_ext)) * soporte;
        var fgel = ngel / cnt;
        var colapso = fgel >= 0.5 ? 1 : (B.activo ? 1 - 0.4 * soporte : 0.6);
        var ancho = Math.pow(r, 0.7) * (1 + s), altoR = Math.pow(r, 0.3) / (1 + s) * colapso;
        // error de posición: arrastre en el baño, grietas sin reparar, flotabilidad
        var wm = tc[m].diam, sig2 = Math.pow(0.03 * wm, 2);
        if (B.activo) {
          var drag = B.tau0 + B.K * Math.sqrt(P.velocidad / wm);
          sig2 += Math.pow(wm * 0.25 * drag / (drag + tm2.tau0 + 30), 2);
          var tFila = Math.max(0.05, (geo.nx * geo.res * 0.6) / P.velocidad);
          sig2 += Math.pow(wm * 0.3 * (1 - Math.exp(-B.t_reparacion / tFila)), 2);
          sig2 += Math.pow(wm * Math.min(1, 50 * Math.abs(tm2.densidad - B.densidad) * Math.min(tg, 60) / (B.tau0 + 5)), 2);
        }
        var sigma = Math.sqrt(sig2);
        var delta = Math.max(ancho - 1, 0) * wm / 2, cob = Math.min(ancho, 1), blur = res + 2 * sigma;
        var sd = distSignada(mask, nx, ny, res);
        for (c = 0; c < nxy; c++) { var o = 0.5 + (delta - sd[c]) / blur; if (o > 0) ocup2d[k * nxy + c] += Math.min(o, 1) * cob; }
        alt += altoR * cnt; peso += cnt;
        info.ancho[m] = ancho; info.sigma[m] = sigma; info.fgel[m] = fgel; info.ext[m] = s;
      }
      hReal[k] = h * (peso ? alt / peso : 1);
      capas.push(info);
    }
    for (i = 0; i < N; i++) if (ocup2d[i] > 1) ocup2d[i] = 1;
    var zTop = new Float64Array(nz), acc = 0;
    for (k = 0; k < nz; k++) { acc += hReal[k]; zTop[k] = acc; capas[k].zb = acc - hReal[k]; capas[k].h = hReal[k]; }
    // IoU suave entre objetivo y pieza real (proyección vertical capa a capa)
    var nzE = Math.max(nz, Math.ceil(zTop[nz - 1] / h - 1e-9)) + 1, inter = 0, union = 0;
    var col = new Float64Array(nxy);
    for (var kk = 0; kk < nzE; kk++) {
      col.fill(0);
      var lo = kk * h, hi = lo + h;
      for (k = 0; k < nz; k++) {
        var s1 = Math.min(hi, zTop[k]) - Math.max(lo, zTop[k] - hReal[k]); if (s1 <= 0) continue;
        s1 /= h; for (c = 0; c < nxy; c++) col[c] += s1 * ocup2d[k * nxy + c];
      }
      for (c = 0; c < nxy; c++) { var A = Math.min(col[c], 1), T = kk < nz && geo.mat[kk * nxy + c] ? 1 : 0; inter += Math.min(A, T); union += Math.max(A, T); }
    }
    var iou = union > 0 ? inter / union : 1;

    // ------------------------------------------------ viabilidad celular
    var viab = new Float32Array(N).fill(NaN), sumV = 0, nV = 0;
    var vT = B.activo ? Math.exp(-Math.pow(Math.max(0, Math.abs(B.temperatura - 30) - 8) / 10, 2)) : 1;
    var sc = [1, supCizalla(cfg.tintaA, P.presion_e1, M.e1.diam / 2, M.e1.largo), supCizalla(cfg.tintaB, P.presion_e2, M.e2.diam / 2, M.e2.largo)];
    var nOcup = 0, nGel = 0, sumA = 0, sumD = 0;
    for (i = 0; i < N; i++) {
      var e2 = geo.mat[i]; if (!e2) continue;
      nOcup++; sumA += alpha[i]; sumD += dosis[i]; if (alpha[i] >= ag[e2]) nGel++;
      if (tintas[e2].celulas) { var vv = sc[e2] * Math.exp(-dosis[i] * dano / tintas[e2].dosis_letal) * vT; viab[i] = vv; sumV += vv; nV++; }
    }
    var fI = 1 - Math.exp(-I0 / 20), riesgo;
    if (P.modo_uv === 'seguimiento') { var dlag = P.velocidad * P.retardo_uv; riesgo = fI / (1 + Math.exp((dlag - (M.uv.spot / 2 + 0.5)) / 0.3)); }
    else riesgo = 0.02 * fI;
    var nA = 0, nB = 0; for (i = 0; i < N; i++) { if (geo.mat[i] === 1) nA++; else if (geo.mat[i] === 2) nB++; }
    var efMat = (nA * Math.exp(-Math.abs(Math.log(Math.max(relacion[1], 1e-3)))) + nB * Math.exp(-Math.abs(Math.log(Math.max(relacion[2], 1e-3))))) / Math.max(nA + nB, 1);

    var met = {
      fidelidad: iou, viabilidad: nV ? sumV / nV : 1, curado: nOcup ? nGel / nOcup : 0, conversion: nOcup ? sumA / nOcup : 0,
      error_altura: (zTop[nz - 1] - nz * h) / (nz * h), tiempo_s: plan.T, riesgo_obstruccion: riesgo, eficiencia_material: efMat,
      dosis_media: nOcup ? sumD / nOcup : 0, relacion_A: relacion[1], relacion_B: relacion[2], sup_cizalla: sc[2],
      espera_antichoque_s: plan.espera, colisiones: plan.choques, volumen_mm3: nOcup * res * res * h, capas: nz, voxeles: nOcup
    };
    var pt = puntuar(met, cfg.puntaje);
    var out = { metricas: met, puntaje: pt };
    if (opt.detalle) {
      out.geo = { nx: nx, ny: ny, nz: nz, res: res, h: h, xs: Array.from(geo.xs), ys: Array.from(geo.ys), mat: geo.mat };
      out.tdep = plan.tdep; out.tgel = tgel; out.alpha = alpha; out.dosis = dosis; out.viab = viab; out.capas = capas;
      out.capaT = plan.capaT; out.T = plan.T; out.estrategia = plan.estrategia;
      if (plan.trays) { out.trays = {}; for (var nm in plan.trays) out.trays[nm] = { t: plan.trays[nm].t, x: plan.trays[nm].x, y: plan.trays[nm].y, on: plan.trays[nm].on }; }
      if (plan.gcode) out.gcode = plan.gcode.join('\n');
    }
    return out;
  }

  // ---------------------------------------------------------------- puntaje
  function puntuar(m, w) {
    var partes = {
      fidelidad: m.fidelidad, viabilidad: m.viabilidad, curado: m.curado,
      tiempo: Math.exp(-m.tiempo_s / (60 * w.t_ref_min)), riesgo: 1 - m.riesgo_obstruccion, material: m.eficiencia_material
    };
    var pesos = { fidelidad: w.w_fid, viabilidad: w.w_viab, curado: w.w_cura, tiempo: w.w_tiempo, riesgo: w.w_riesgo, material: w.w_material };
    var tot = 0, sw = 0, aport = {};
    for (var key in partes) { tot += pesos[key] * partes[key]; sw += pesos[key]; }
    for (key in partes) aport[key] = sw > 0 ? 100 * pesos[key] * partes[key] / sw : 0;
    var total = sw > 0 ? 100 * tot / sw : 0, pen = {};
    if (m.viabilidad < w.viab_min) pen.viabilidad_baja = -Math.round(200 * (w.viab_min - m.viabilidad) * 10) / 10;
    if (m.colisiones > 0) pen.colision = -30;
    for (key in pen) total += pen[key];
    return { total: Math.max(0, total), partes: partes, aportes: aport, penalizaciones: pen };
  }

  // ---------------------------------------------------------------- red neuronal
  function rng(seed) { var s = seed >>> 0 || 1; return function () { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; }; }
  function gauss(r) { var u = r() || 1e-9, v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }

  // Perceptrón multicapa (SiLU) con Adam y gradiente respecto a la entrada.
  function MLP(sizes, seed) {
    this.sizes = sizes; this.W = []; this.b = []; var r = rng(seed || 7);
    for (var l = 0; l < sizes.length - 1; l++) {
      var a = sizes[l], bb = sizes[l + 1], W = new Float64Array(a * bb), sc = Math.sqrt(2 / a);
      for (var i = 0; i < W.length; i++) W[i] = gauss(r) * sc;
      this.W.push(W); this.b.push(new Float64Array(bb));
    }
    this.m = this.W.concat(this.b).map(function (p) { return new Float64Array(p.length); });
    this.v = this.W.concat(this.b).map(function (p) { return new Float64Array(p.length); });
    this.paso = 0;
  }
  MLP.prototype.adelante = function (x) {
    var acts = [x], pre = [];
    for (var l = 0; l < this.W.length; l++) {
      var a = acts[l], nI = this.sizes[l], nO = this.sizes[l + 1], W = this.W[l], z = new Float64Array(nO);
      for (var o = 0; o < nO; o++) { var s = this.b[l][o]; for (var i = 0; i < nI; i++) s += a[i] * W[i * nO + o]; z[o] = s; }
      pre.push(z);
      if (l < this.W.length - 1) { var y = new Float64Array(nO); for (o = 0; o < nO; o++) y[o] = z[o] / (1 + Math.exp(-z[o])); acts.push(y); } else acts.push(z);
    }
    return { y: acts[acts.length - 1], acts: acts, pre: pre };
  };
  MLP.prototype.atras = function (f, dy, gW, gb) {
    var g = dy;
    for (var l = this.W.length - 1; l >= 0; l--) {
      var nI = this.sizes[l], nO = this.sizes[l + 1], a = f.acts[l], W = this.W[l];
      if (gW) for (var i = 0; i < nI; i++) for (var o = 0; o < nO; o++) gW[l][i * nO + o] += a[i] * g[o];
      if (gb) for (o = 0; o < nO; o++) gb[l][o] += g[o];
      var gp = new Float64Array(nI);
      for (i = 0; i < nI; i++) { var s = 0; for (o = 0; o < nO; o++) s += W[i * nO + o] * g[o]; gp[i] = s; }
      if (l > 0) { var z = f.pre[l - 1]; for (i = 0; i < nI; i++) { var sg = 1 / (1 + Math.exp(-z[i])); gp[i] *= sg * (1 + z[i] * (1 - sg)); } }
      g = gp;
    }
    return g;
  };
  MLP.prototype.predecir = function (x) { return this.adelante(x).y[0]; };
  MLP.prototype.gradEntrada = function (x) { var f = this.adelante(x); return this.atras(f, new Float64Array([1])); };
  MLP.prototype.entrenar = function (X, Y, idx, pasos, lote, lr, l2, r) {
    var gW = this.W.map(function (W) { return new Float64Array(W.length); }), gb = this.b.map(function (b) { return new Float64Array(b.length); });
    var P = this.W.concat(this.b), perdida = 0;
    for (var st = 0; st < pasos; st++) {
      gW.forEach(function (g) { g.fill(0); }); gb.forEach(function (g) { g.fill(0); });
      var nb = Math.min(lote, idx.length); perdida = 0;
      for (var q = 0; q < nb; q++) {
        var n = idx[Math.floor(r() * idx.length)], f = this.adelante(X[n]), e = f.y[0] - Y[n];
        perdida += e * e; this.atras(f, new Float64Array([2 * e / nb]), gW, gb);
      }
      var G = gW.concat(gb); this.paso++;
      var b1 = 0.9, b2 = 0.999, c1 = 1 - Math.pow(b1, this.paso), c2 = 1 - Math.pow(b2, this.paso);
      for (var p = 0; p < P.length; p++) {
        var Pp = P[p], Gp = G[p], m = this.m[p], v = this.v[p], esW = p < this.W.length;
        for (var i = 0; i < Pp.length; i++) {
          var gg = Gp[i] + (esW ? l2 * Pp[i] : 0);
          m[i] = b1 * m[i] + (1 - b1) * gg; v[i] = b2 * v[i] + (1 - b2) * gg * gg;
          Pp[i] -= lr * (m[i] / c1) / (Math.sqrt(v[i] / c2) + 1e-8);
        }
      }
      perdida /= nb;
    }
    return perdida;
  };

  // ------------------------------------------- aprendiz (optimización bayesiana
  // con un ensamble de redes profundas: media = predicción, dispersión = incertidumbre)
  function Aprendiz(cfg, opciones) {
    this.cfg = JSON.parse(JSON.stringify(cfg));
    this.op = opciones;
    this.claves = PARAMS_PROCESO.map(function (p) { return p[0]; }).filter(function (k) { return cfg.optimizar[k]; });
    this.combos = cfg.optimizar_modo ? COMBOS.slice() : [cfg.proceso.modo_uv + '|' + (cfg.proceso.modo_uv === 'seguimiento' ? 'secuencial' : cfg.proceso.estrategia)];
    this.dIn = this.claves.length + (this.combos.length > 1 ? this.combos.length : 0);
    this.X = []; this.Y = []; this.hist = []; this.mejor = null; this.r = rng(opciones.semilla || 12345);
    var capas = [this.dIn].concat(opciones.ocultas || [32, 32]).concat([1]);
    this.red = []; for (var e = 0; e < (opciones.ensamble || 5); e++) this.red.push(new MLP(capas, 1000 + 17 * e));
  }
  Aprendiz.prototype.aValor = function (clave, u) {
    var rg = this.cfg.rangos[clave], lo = rg[0], hi = rg[1], log = PARAMS_PROCESO.filter(function (p) { return p[0] === clave; })[0][6] && lo > 0 && hi / lo > 3;
    return log ? Math.exp(Math.log(lo) + u * (Math.log(hi) - Math.log(lo))) : lo + u * (hi - lo);
  };
  Aprendiz.prototype.uActual = function () {
    var self = this;
    return this.claves.map(function (k) {
      var rg = self.cfg.rangos[k], lo = rg[0], hi = rg[1], v = Math.min(hi, Math.max(lo, self.cfg.proceso[k]));
      var log = PARAMS_PROCESO.filter(function (p) { return p[0] === k; })[0][6] && lo > 0 && hi / lo > 3;
      return hi > lo ? (log ? (Math.log(v) - Math.log(lo)) / (Math.log(hi) - Math.log(lo)) : (v - lo) / (hi - lo)) : 0.5;
    });
  };
  Aprendiz.prototype.codificar = function (u, combo) {
    var x = new Float64Array(this.dIn); for (var i = 0; i < u.length; i++) x[i] = u[i] * 2 - 1;
    if (this.combos.length > 1) x[u.length + combo] = 1;
    return x;
  };
  Aprendiz.prototype.parametros = function (u, combo) {
    var P = JSON.parse(JSON.stringify(this.cfg.proceso)), self = this;
    this.claves.forEach(function (k, i) { P[k] = self.aValor(k, u[i]); });
    var cb = this.combos[combo].split('|'); P.modo_uv = cb[0]; P.estrategia = cb[1];
    return P;
  };
  Aprendiz.prototype.predecir = function (x) {
    var s = 0, s2 = 0, n = this.red.length;
    for (var e = 0; e < n; e++) { var y = this.red[e].predecir(x); s += y; s2 += y * y; }
    var mu = s / n; return { mu: mu * this.ys + this.ym, sd: Math.sqrt(Math.max(s2 / n - mu * mu, 0)) * this.ys };
  };
  Aprendiz.prototype.entrenarRed = function (pasos) {
    var n = this.Y.length; this.ym = 0; for (var i = 0; i < n; i++) this.ym += this.Y[i]; this.ym /= n;
    var v = 0; for (i = 0; i < n; i++) v += (this.Y[i] - this.ym) * (this.Y[i] - this.ym); this.ys = Math.sqrt(v / n) + 1;
    var Yn = this.Y.map(function (y) { return (y - this.ym) / this.ys; }, this), perd = 0;
    for (var e = 0; e < this.red.length; e++) {
      var idx = []; for (i = 0; i < n; i++) idx.push(Math.floor(this.r() * n)); // bootstrap
      perd += this.red[e].entrenar(this.X, Yn, idx, pasos, 32, this.op.lr || 3e-3, 1e-4, this.r);
    }
    return perd / this.red.length;
  };
  Aprendiz.prototype.proponer = function (ep, total) {
    var d = this.claves.length, nC = this.combos.length, self = this;
    var nInit = Math.max(6, Math.min(16, 2 * d));
    if (this.X.length === 0) return { u: this.uActual(), combo: Math.max(0, this.combos.indexOf(this.cfg.proceso.modo_uv + '|' + (this.cfg.proceso.modo_uv === 'seguimiento' ? 'secuencial' : this.cfg.proceso.estrategia))), razon: 'parámetros actuales' };
    if (this.X.length < nInit || this.r() < (this.op.epsilon || 0.05)) {
      var u = []; for (var i = 0; i < d; i++) u.push(this.r()); return { u: u, combo: Math.floor(this.r() * nC), razon: this.X.length < nInit ? 'exploración inicial' : 'exploración aleatoria' };
    }
    var kappa = (this.op.kappa || 2) * (1 - 0.7 * ep / Math.max(total, 1)), mejor = null;
    var top = this.hist.slice().sort(function (a, b) { return b.puntaje - a.puntaje; }).slice(0, 8);
    var top5 = top.slice(0, 5);
    for (var c = 0; c < 1000; c++) {
      var uu, cb;
      if (c < 400 || !top.length) { uu = []; for (i = 0; i < d; i++) uu.push(this.r()); cb = Math.floor(this.r() * nC); }
      else {
        var base = top5[Math.floor(this.r() * top5.length)], sg = 0.02 + 0.10 * this.r();
        uu = base.u.map(function (x) { return Math.min(1, Math.max(0, x + sg * gauss(self.r))); });
        cb = this.r() < 0.15 ? Math.floor(this.r() * nC) : base.combo;
      }
      var p = this.predecir(this.codificar(uu, cb)), ucb = p.mu + kappa * p.sd;
      if (!mejor || ucb > mejor.ucb) mejor = { u: uu, combo: cb, ucb: ucb, mu: p.mu, sd: p.sd };
    }
    // refinamiento por gradiente a través de la red (diseño inverso local)
    for (var it = 0; it < 25; it++) {
      var x = this.codificar(mejor.u, mejor.combo), g = new Float64Array(this.dIn);
      for (var e = 0; e < this.red.length; e++) { var ge = this.red[e].gradEntrada(x); for (i = 0; i < d; i++) g[i] += ge[i]; }
      var nu = mejor.u.map(function (v, i2) { return Math.min(1, Math.max(0, v + 0.01 * Math.sign(g[i2]))); });
      var pn = this.predecir(this.codificar(nu, mejor.combo)), un = pn.mu + kappa * pn.sd;
      if (un > mejor.ucb) { mejor.u = nu; mejor.ucb = un; mejor.mu = pn.mu; mejor.sd = pn.sd; } else break;
    }
    mejor.razon = 'red neuronal (UCB κ=' + kappa.toFixed(2) + ')';
    return mejor;
  };
  Aprendiz.prototype.sensibilidad = function () {
    var d = this.claves.length, s = new Float64Array(d), n = Math.min(this.X.length, 60);
    if (!this.ys) return [];
    for (var q = 0; q < n; q++) {
      var x = this.X[this.X.length - 1 - q];
      for (var e = 0; e < this.red.length; e++) { var g = this.red[e].gradEntrada(x); for (var i = 0; i < d; i++) s[i] += Math.abs(g[i]); }
    }
    var mx = 0; for (i = 0; i < d; i++) mx = Math.max(mx, s[i]);
    var self = this; return this.claves.map(function (k, i2) { return { clave: k, valor: mx > 0 ? s[i2] / mx : 0 }; });
  };
  // Un episodio: proponer → simular → puntuar → aprender.
  Aprendiz.prototype.episodio = function (fuente, ep, total) {
    var prop = this.proponer(ep, total), pred = null;
    if (this.ys && prop.mu === undefined) { var pp = this.predecir(this.codificar(prop.u, prop.combo)); prop.mu = pp.mu; prop.sd = pp.sd; }
    if (prop.mu !== undefined) pred = { mu: prop.mu, sd: prop.sd };
    var cfg = JSON.parse(JSON.stringify(this.cfg)); cfg.proceso = this.parametros(prop.u, prop.combo);
    var t0 = Date.now(), r = simular(fuente, cfg, { resMax: this.op.resEntreno || 28 });
    var y = r.puntaje.total;
    this.X.push(this.codificar(prop.u, prop.combo)); this.Y.push(y);
    var perd = this.entrenarRed(this.X.length < 12 ? 150 : (this.op.pasos || 60));
    var reg = { ep: ep, u: prop.u, combo: prop.combo, comboTxt: this.combos[prop.combo], proceso: cfg.proceso, puntaje: y, desglose: r.puntaje, metricas: r.metricas, pred: pred, razon: prop.razon, perdida: perd, ms: Date.now() - t0 };
    this.hist.push(reg);
    var nuevo = !this.mejor || y > this.mejor.puntaje; if (nuevo) this.mejor = reg; reg.record = nuevo;
    return reg;
  };

  return {
    COMBOS: COMBOS, COMBO_TXT: COMBO_TXT, PARAMS_PROCESO: PARAMS_PROCESO, ORGANOS: ORGANOS, EFIC_PRIMER: EFIC_PRIMER,
    defaults: defaults, fuenteOrgano: fuenteOrgano, fuenteMalla: fuenteMalla, parseSTL: parseSTL, normalizarMalla: normalizarMalla,
    voxelizar: voxelizar, planificar: planificar, simular: simular, puntuar: puntuar, caudal: caudal, MLP: MLP, Aprendiz: Aprendiz, edt: edt
  };
})();
if (typeof module !== 'undefined') module.exports = CORE;
