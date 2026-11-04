// Reveal + HUD: arranque, reloj, registro del motor, barra de progreso, títulos que se «descifran» y contadores.
import { irA } from './escena.js';

const exportar = location.search.includes('export');
if (location.search.includes('limpio')) document.body.classList.add('limpio');  // (solo la escena 3D: renders del dosier)
const ETIQUETAS = ['ARRANQUE', 'PROBLEMA', 'SOLUCIÓN', 'ARQUITECTURA', 'IA CONTROLADA', 'IMPRESIÓN 3D', 'RV / RA', 'INGENIERÍA', 'CONCLUSIÓN'];
// x de la retícula (en % del ancho) para seguir al holograma; null = oculta
const RETICULA = [72, null, 73, 80, 70, 74, 50, 24, 50];

const segs = document.getElementById('hud-segmentos');
ETIQUETAS.forEach(() => segs.appendChild(document.createElement('i')));

// registro del motor: líneas con el formato de motor.log
const LINEAS = [
  '[carga] voxel_mm = 1.0 · vóxel cúbico', '[cuerpo] máscara del cuerpo sin la mesa', 'TotalSegmentator (total) en la GPU…',
  '[anatomía] organos = 117 estructuras', '[anatomía] vasos = arterias y venas pulmonares', '[anatomía] esqueleto ≥ 200 UH',
  '[hallazgos] zonas de otra densidad', '[modelos] mallas finas · borde a media altura', 'Creando los modelos 3D: 34 de 90',
  'Decimación sin romper la malla', '[autoajuste] suavizado_iteraciones = 20', '[autoajuste] piezas = 3 · máx. 45 mm',
  'firma de la actualización: OK', 'pesos SHA-256 verificados', 'sala compartida: dentro como «Persona 2»',
  'en las gafas: 87 imágenes por segundo', 'MRSegmentator: segunda opinión', 'nnInteractive: crecer con IA',
];
const registro = document.getElementById('hud-registro');
let nLinea = 0;
function nuevaLinea() {
  const d = new Date();
  const hh = d.toTimeString().slice(0, 8);
  const p = document.createElement('div');
  p.textContent = `${hh}  ${LINEAS[nLinea++ % LINEAS.length]}`;
  registro.appendChild(p);
  while (registro.children.length > 16) registro.firstChild.remove();
}
for (let i = 0; i < 10; i++) nuevaLinea();
setInterval(nuevaLinea, 1400);
setInterval(() => { document.getElementById('hud-reloj').textContent = new Date().toTimeString().slice(0, 8) + ' · SESIÓN SEGURA'; }, 500);

// títulos que se descifran
const SIGNOS = '█▓▒░<>/\\|=+*#ABCDEFGHIJKLMNÑOPQRSTUVWXYZ0123456789';
function descifrar(el) {
  if (!el.dataset.final) el.dataset.final = el.textContent;
  const final = el.dataset.final;
  let paso = 0;
  const total = 26;
  clearInterval(el._t);
  el._t = setInterval(() => {
    paso++;
    el.textContent = [...final].map((c, i) => (c === ' ' || i < (paso / total) * final.length) ? c
      : SIGNOS[Math.floor(Math.random() * SIGNOS.length)]).join('');
    if (paso >= total) { clearInterval(el._t); el.textContent = final; }
  }, 32);
}
// contadores
function contar(el) {
  const fin = parseFloat(el.dataset.hasta), dec = parseInt(el.dataset.dec || '0'), suf = el.dataset.suf || '';
  const t0 = performance.now(), dur = 1600;
  const paso = (t) => {
    const k = Math.min(1, (t - t0) / dur), v = fin * (1 - Math.pow(1 - k, 3));
    el.textContent = v.toFixed(dec).replace('.', ',') + suf;
    if (k < 1) requestAnimationFrame(paso);
  };
  requestAnimationFrame(paso);
}

function alCambiar(ev) {
  const i = ev.indexh;
  irA(i);
  [...segs.children].forEach((s, k) => { s.className = k < i ? 'hecho' : k === i ? 'ahora' : ''; });
  document.getElementById('hud-seccion').textContent = `${String(i + 1).padStart(2, '0')} / ${String(ETIQUETAS.length).padStart(2, '0')}`;
  document.getElementById('hud-etiqueta').textContent = ETIQUETAS[i];
  const r = document.getElementById('hud-reticula');
  r.style.opacity = RETICULA[i] === null ? 0 : 0.55;
  if (RETICULA[i] !== null) r.style.left = RETICULA[i] + '%';
  ev.currentSlide.querySelectorAll('[data-descifrar]').forEach(descifrar);
  ev.currentSlide.querySelectorAll('[data-hasta]').forEach(contar);
  const f = document.getElementById('destello');
  f.classList.remove('activo'); void f.offsetWidth; f.classList.add('activo');
}

// secuencia de arranque
const BOOT = [
  `MRANALYZER ${document.documentElement.dataset.version} — NÚCLEO DE ANÁLISIS`, '', '> comprobando firma de los módulos ........ OK',
  '> PyTorch de TotalSegmentator ............. GPU', '> pesos de las redes (SHA-256) ............ OK',
  '> cargando holograma: 89 estructuras ...... OK', '> modo: LOCAL · los datos no salen del equipo', '', 'INICIANDO INTERFAZ_',
];
async function arrancar() {
  const caja = document.getElementById('arranque'), txt = document.getElementById('arranque-texto');
  if (exportar) { caja.classList.add('fuera'); return; }
  let previo = '';
  for (const l of BOOT) {
    for (let k = 0; k <= l.length; k += 2) { txt.textContent = previo + l.slice(0, k); await new Promise(r => setTimeout(r, 9)); }
    previo += l + '\n';
    txt.textContent = previo;
    await new Promise(r => setTimeout(r, 110));
  }
  await new Promise(r => setTimeout(r, 450));
  caja.classList.add('fuera');
}

Reveal.initialize({
  width: 1920, height: 1080, margin: 0, minScale: 0.2, maxScale: 2,
  controls: true, controlsTutorial: false, progress: false, slideNumber: false, hash: true,
  transition: 'fade', transitionSpeed: 'slow', backgroundTransition: 'none', center: false,
  plugins: [RevealNotes],
}).then(() => {
  Reveal.on('slidechanged', alCambiar);
  alCambiar({ indexh: Reveal.getIndices().h, currentSlide: Reveal.getCurrentSlide() });
  arrancar();
});
