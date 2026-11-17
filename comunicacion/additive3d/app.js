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
// Cuánto dura cada etapa cuando avanza sola (la última se queda).
const DURA = [3.4, 9.5, 5.2, 4.6, 6.6];
const etapas = [...document.querySelectorAll('#etapas li')];
let reloj = null;
function etapa(n, sola) {
  clearTimeout(reloj);
  ponEtapa(n);
  etapas.forEach((li, i) => { li.classList.toggle('activa', i === n); li.classList.toggle('hecha', i < n); });
  document.body.classList.toggle('sim-en-marcha', n >= 0);
  document.body.classList.toggle('sim-contando', n >= 1);
  if (sola && n >= 0 && n < DURA.length) reloj = setTimeout(() => etapa(n + 1, true), DURA[n] * 1000);
}
window.__etapa = n => etapa(n, false);       // (para las capturas)
escucharCuenta((n, total) => {
  const c = document.getElementById('sim-cuenta');
  c.querySelector('b').textContent = n;
  c.querySelector('span').textContent = total;
});
etapas.forEach((li, i) => li.addEventListener('click', () => etapa(i, false)));
document.getElementById('reproducir').addEventListener('click', () => Reveal.next());
document.addEventListener('keydown', ev => {
  if (Reveal.getCurrentSlide().id !== 'simulacion' || ev.ctrlKey || ev.altKey || ev.metaKey) return;
  if (ev.key >= '1' && ev.key <= '6') etapa(+ev.key - 1, false);
});

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
  if (sec.id === 'simulacion') etapa(sec.querySelector('.fragment.visible') ? 0 : -1, !!sec.querySelector('.fragment.visible'));
  else etapa(-1, false);
}
function alFragmento(ev, visible) {
  const sec = Reveal.getCurrentSlide();
  if (sec.id === 'simulacion') etapa(visible ? 0 : -1, visible);
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
