// Lo que mueve la presentación: reveal, los tonos del fondo, los títulos, los contadores, el pie y la simulación.
import { irA, ponEtapa, escucharCuenta } from './escena.js';

const exportar = location.search.includes('export');
const secciones = [...document.querySelectorAll('.reveal .slides > section')];

// Cada línea de un título sale de debajo de su propia máscara.
document.querySelectorAll('.titulo').forEach(t => {
  t.querySelectorAll('.l').forEach((l, n) => {
    const dentro = document.createElement('span');
    dentro.style.setProperty('--n', n);
    dentro.append(...l.childNodes);
    l.append(dentro);
  });
});
// La granja: 40 impresoras que se van encendiendo.
const rejilla = document.getElementById('rejilla-impresoras');
for (let k = 0; k < 40; k++) {
  const i = document.createElement('i');
  i.style.setProperty('--k', k);
  rejilla.append(i);
}

function contar(el) {
  const fin = parseFloat(el.dataset.hasta), miles = 'miles' in el.dataset;
  const t0 = performance.now(), dur = exportar ? 1 : 1700;
  const pinta = v => { el.textContent = miles ? Math.round(v).toLocaleString('es-ES', { useGrouping: 'always' }) : String(Math.round(v)); };
  const paso = t => {
    const k = Math.min(1, (t - t0) / dur);
    pinta(fin * (1 - Math.pow(1 - k, 3)));
    if (k < 1) requestAnimationFrame(paso);
  };
  pinta(0);
  setTimeout(() => requestAnimationFrame(paso), exportar ? 0 : 700);
}

// ------------------------------------------------------------------ simulación
// La simulación avanza con el botón de pasar diapositiva: cada etapa es un «fragmento» de reveal, así que el avance
// pasa a la siguiente y el retroceso vuelve a la anterior. Después de la última, el avance pasa de diapositiva.
const etapas = [...document.querySelectorAll('#etapas li')];
let etapaPuesta = -2;
function etapa(n) {
  if (n === etapaPuesta) return;
  etapaPuesta = n;
  ponEtapa(n);
  etapas.forEach((li, i) => { li.classList.toggle('activa', i === n); li.classList.toggle('hecha', i < n); });
  document.body.classList.toggle('sim-en-marcha', n >= 0);
  document.body.classList.toggle('sim-contando', n >= 1);
}
const etapaDeLaDiapositiva = sec => sec.querySelectorAll('.fragment.visible').length - 1;
window.__etapa = n => Reveal.navigateFragment(n);       // (para las capturas)
escucharCuenta((n, total) => {
  const c = document.getElementById('sim-cuenta');
  c.querySelector('b').textContent = n;
  c.querySelector('span').textContent = total;
});
etapas.forEach((li, i) => li.addEventListener('click', () => Reveal.navigateFragment(i)));
document.getElementById('reproducir').addEventListener('click', () => Reveal.next());
document.addEventListener('keydown', ev => {
  if (Reveal.getCurrentSlide().id !== 'simulacion' || ev.ctrlKey || ev.altKey || ev.metaKey) return;
  if (ev.key >= '1' && ev.key <= '6') Reveal.navigateFragment(+ev.key - 1);
});


// ------------------------------------------------------------------ la red neuronal (diapositiva «red»)
// Una red en forma de U, como las que segmentan: baja comprimiendo la imagen (cada vez menos detalle y más «qué es»),
// sube ampliándola y arriba devuelve una etiqueta por punto. El corte y sus etiquetas son reales.
const red = (() => {
  const lienzo = document.getElementById('red-lienzo'), c = lienzo.getContext('2d');
  const pasos = [...document.querySelectorAll('#red-pasos li')];
  const EMB = window.__embebidos || {};
  const carga = r => { const i = new Image(); i.src = EMB[r] || r; return i; };
  const entrada = carga('img/red_entrada.webp'), salida = carga('img/red_salida.png');
  const MORADO = '#6422b8', TINTA = '#063f3b';
  // cada nivel: centro, lado y cuántos píxeles de lado le quedan a la imagen ahí
  const N = [[168, 196, 290, 0], [432, 286, 172, 48], [602, 376, 122, 24], [738, 448, 84, 12], [852, 512, 58, 6],
    [966, 448, 84, 12], [1102, 376, 122, 24], [1272, 286, 172, 48], [1592, 196, 290, 0]];
  const mapas = [];
  let listo = false, activa = false, t0 = 0;
  function preparar() {
    if (listo || !entrada.complete || !salida.complete || !entrada.naturalWidth || !salida.naturalWidth) return listo;
    N.forEach(([, , , res], k) => {
      const m = document.createElement('canvas');
      m.width = m.height = res || 384;
      const x = m.getContext('2d');
      x.drawImage(entrada, 0, 0, m.width, m.height);
      if (k >= 5) {                      // (al subir, ya lleva las etiquetas: primero gruesas, luego finas)
        x.globalAlpha = 0.9;
        x.imageSmoothingEnabled = k < 8;
        x.drawImage(salida, 0, 0, m.width, m.height);
      }
      mapas.push(m);
    });
    return (listo = true);
  }
  function caja(x, y, l, r) { c.beginPath(); c.roundRect(x - l / 2, y - l / 2, l, l, r); }
  function dibujar(t) {
    c.setTransform(2, 0, 0, 2, 0, 0);
    c.clearRect(0, 0, 1760, 600);
    if (!preparar()) return;
    const CICLO = 11, p = exportar ? 0.8 : (t % CICLO) / CICLO;
    const onda = p * 1.45;                                   // (recorre los nueve niveles en algo más de la mitad del ciclo)
    const fundido = exportar ? 1 : Math.min(1, (1 - p) / 0.06);
    const act = N.map((_, k) => Math.min(1, Math.max(0, (onda - k / 8 * 0.86) / 0.07)) * fundido);
    pasos.forEach((li, i) => li.classList.toggle('activo', [act[0] > 0 && act[2] < 1, act[2] >= 1 && act[5] < 1, act[5] >= 1][i]));
    c.lineCap = 'round';
    c.font = '600 22px Inter, "Segoe UI", sans-serif';
    c.textAlign = 'center';

    // las conexiones que saltan de un lado al otro: llevan el detalle fino a la subida
    for (const [i, j] of [[0, 8], [1, 7], [2, 6], [3, 5]]) {
      const y = i === 0 ? N[0][1] - 96 : N[i][1], a = Math.min(act[i], act[j] > 0 ? 1 : 0.45);
      c.strokeStyle = MORADO; c.globalAlpha = 0.18 + 0.5 * a; c.lineWidth = 3;
      c.setLineDash([10, 12]); c.lineDashOffset = -t * 46;
      c.beginPath(); c.moveTo(N[i][0] + N[i][2] / 2 + 10, y); c.lineTo(N[j][0] - N[j][2] / 2 - 10, y); c.stroke();
      c.setLineDash([]);
    }
    c.globalAlpha = 0.75; c.fillStyle = MORADO;
    c.fillText('conserva el detalle', 880, N[0][1] - 108);

    // el camino de la señal, de nivel en nivel, con pulsos que lo recorren
    for (let k = 0; k < 8; k++) {
      const [x1, y1, l1] = N[k], [x2, y2, l2] = N[k + 1];
      const d = Math.hypot(x2 - x1, y2 - y1), ux = (x2 - x1) / d, uy = (y2 - y1) / d;
      const ax = x1 + ux * (l1 / 2 + 6), ay = y1 + uy * (l1 / 2 + 6), bx = x2 - ux * (l2 / 2 + 6), by = y2 - uy * (l2 / 2 + 6);
      c.globalAlpha = 0.25 + 0.75 * act[k]; c.strokeStyle = MORADO; c.lineWidth = 5;
      c.beginPath(); c.moveTo(ax, ay); c.lineTo(bx, by); c.stroke();
      if (act[k] > 0.5) for (let j = 0; j < 2; j++) {
        const f = (t * 0.9 + j / 2 + k * 0.13) % 1;
        c.globalAlpha = Math.sin(f * Math.PI) * act[k]; c.fillStyle = '#fff';
        c.shadowColor = MORADO; c.shadowBlur = 16;
        c.beginPath(); c.arc(ax + (bx - ax) * f, ay + (by - ay) * f, 6, 0, Math.PI * 2); c.fill();
        c.shadowBlur = 0;
      }
    }
    c.globalAlpha = 0.75; c.fillStyle = TINTA;
    c.fillText('comprime', 560, 500); c.fillText('amplía', 1150, 500);

    // los niveles: la imagen tal como la «ve» la red en cada uno
    N.forEach(([x, y, l, res], k) => {
      const a = k === 0 ? 1 : act[k], capas = k === 0 || k === 8 ? 0 : Math.min(k, 8 - k) + 1;
      for (let j = capas; j >= 1; j--) {                       // (cuanto más abajo, más canales: más láminas detrás)
        c.globalAlpha = 0.25 + 0.5 * a; c.fillStyle = '#fff'; c.strokeStyle = MORADO; c.lineWidth = 2;
        caja(x + j * 7, y - j * 7, l, 12); c.fill(); c.stroke();
      }
      c.globalAlpha = 1; c.fillStyle = '#eef0ee'; caja(x, y, l, k === 0 || k === 8 ? 22 : 12); c.fill();
      c.save(); c.clip();
      c.globalAlpha = k === 8 ? 1 : a;
      c.imageSmoothingEnabled = !(res && res < 64);
      if (k === 8) {                                           // (la salida: la imagen, y las etiquetas que van cayendo)
        c.drawImage(mapas[0], x - l / 2, y - l / 2, l, l);
        c.beginPath(); c.rect(x - l / 2, y - l / 2, l, l * act[8]); c.clip();
        c.drawImage(mapas[8], x - l / 2, y - l / 2, l, l);
      } else c.drawImage(mapas[k], x - l / 2, y - l / 2, l, l);
      if (k > 0 && k < 5) { c.globalAlpha = 0.1 * k * a; c.fillStyle = MORADO; c.fillRect(x - l / 2, y - l / 2, l, l); }
      c.restore();
      c.globalAlpha = 0.35 + 0.65 * a; c.strokeStyle = MORADO; c.lineWidth = k === 0 || k === 8 ? 5 : 3;
      if (a > 0 && a < 1) { c.shadowColor = MORADO; c.shadowBlur = 30; }
      caja(x, y, l, k === 0 || k === 8 ? 22 : 12); c.stroke();
      c.shadowBlur = 0;
    });
    // el filtro que recorre la imagen de entrada
    const [x0, y0, l0] = N[0], paso = (t * 1.6) % 25, fx = Math.floor(paso) % 5, fy = Math.floor(paso / 5), lado = l0 / 5;
    c.globalAlpha = 0.9; c.strokeStyle = '#fff'; c.lineWidth = 4; c.fillStyle = 'rgba(100,34,184,.35)';
    c.beginPath(); c.roundRect(x0 - l0 / 2 + fx * lado + 3, y0 - l0 / 2 + fy * lado + 3, lado - 6, lado - 6, 8); c.fill(); c.stroke();
    c.globalAlpha = 1; c.fillStyle = TINTA; c.font = '700 26px Inter, "Segoe UI", sans-serif';
    c.fillText('Resonancia', x0, y0 + l0 / 2 + 42);
    c.fillText('Segmentación', N[8][0], N[8][1] + N[8][2] / 2 + 42);
  }
  (function bucle(ms) {
    if (activa) dibujar((ms - t0) / 1000);
    requestAnimationFrame(bucle);
  })(0);
  return { al(estar) { activa = estar; t0 = performance.now(); if (estar) dibujar(0); } };
})();

// ------------------------------------------------------------------ al cambiar de diapositiva
function tono(t) {
  for (const c of ['blanco', 'salvia', 'oscuro']) document.body.classList.toggle('tono-' + c, c === t);
}
function alCambiar(ev) {
  const sec = ev.currentSlide, i = secciones.indexOf(sec);
  const acto2 = sec.id === 'cierre' && sec.querySelector('.fragment.visible');
  sec.classList.toggle('acto2', !!acto2);
  tono(acto2 ? 'oscuro' : sec.dataset.tono);
  irA(acto2 ? 'final' : sec.dataset.escena);
  document.body.classList.toggle('portada', i === 0);
  document.getElementById('pie-avance').style.width = (i / (secciones.length - 1) * 100) + '%';
  document.getElementById('pie-num').textContent = `${String(i + 1).padStart(2, '0')} / ${String(secciones.length).padStart(2, '0')}`;
  sec.querySelectorAll('[data-hasta]').forEach(contar);
  red.al(sec.id === 'red');
  etapa(sec.id === 'simulacion' ? etapaDeLaDiapositiva(sec) : -1);
}
function alFragmento(ev, visible) {
  const sec = Reveal.getCurrentSlide();
  if (sec.id === 'simulacion') etapa(etapaDeLaDiapositiva(sec));
  if (sec.id === 'cierre') {
    sec.classList.toggle('acto2', visible);
    tono(visible ? 'oscuro' : sec.dataset.tono);
    irA(visible ? 'final' : sec.dataset.escena);
  }
}

// Las fotos siguen un poco al ratón.
let mx = 0, my = 0, px = 0, py = 0;
window.addEventListener('pointermove', ev => { mx = ev.clientX / window.innerWidth * 2 - 1; my = ev.clientY / window.innerHeight * 2 - 1; });
(function sigue() {
  px += (mx - px) * 0.06; py += (my - py) * 0.06;
  document.documentElement.style.setProperty('--px', px.toFixed(3));
  document.documentElement.style.setProperty('--py', py.toFixed(3));
  requestAnimationFrame(sigue);
})();

Reveal.initialize({
  width: 1920, height: 1080, margin: 0, minScale: 0.1, maxScale: 3,
  controls: true, controlsTutorial: false, progress: false, slideNumber: false, hash: true,
  transition: 'fade', transitionSpeed: 'default', backgroundTransition: 'none', center: false,
  plugins: [RevealNotes],
}).then(() => {
  Reveal.on('slidechanged', alCambiar);
  Reveal.on('fragmentshown', ev => alFragmento(ev, true));
  Reveal.on('fragmenthidden', ev => alFragmento(ev, false));
  alCambiar({ currentSlide: Reveal.getCurrentSlide() });
});
