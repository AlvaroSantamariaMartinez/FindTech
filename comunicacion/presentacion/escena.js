// Escena 3D continua detrás de las diapositivas: holograma de anatomía real generada por MRAnalyzer
// (tórax: TAC «CTChest» de muestra de 3D Slicer; cerebro: «MRHead» de 3D Slicer).
import * as THREE from './vendor/three.module.min.js';

const lienzo = document.getElementById('escena3d');
const renderer = new THREE.WebGLRenderer({ canvas: lienzo, antialias: true, alpha: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0x000000, 0);
const escena = new THREE.Scene();
escena.fog = new THREE.FogExp2(0x02060c, 0.12);
const camara = new THREE.PerspectiveCamera(38, 16 / 9, 0.01, 100);
camara.position.set(0, 0.3, 5);
const mirarA = new THREE.Vector3();

function ajustar() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h, false);
  camara.aspect = w / h;
  camara.updateProjectionMatrix();
}
window.addEventListener('resize', ajustar);
ajustar();

// ---------------------------------------------------------------- material holográfico
const uniformesComunes = { uTiempo: { value: 0 } };
function holo(color, opacidad = 0.6) {
  return new THREE.ShaderMaterial({
    uniforms: {
      ...uniformesComunes,
      uColor: { value: new THREE.Color(color) },
      uOpacidad: { value: opacidad },
      uCorte: { value: 10.0 },
      uSolido: { value: 0.0 },
    },
    vertexShader: `
      varying vec3 vN; varying vec3 vV; varying vec3 vW;
      void main() {
        vec4 w = modelMatrix * vec4(position, 1.0);
        vW = w.xyz;
        vN = normalize(mat3(modelMatrix) * normal);
        vV = normalize(cameraPosition - w.xyz);
        gl_Position = projectionMatrix * viewMatrix * w;
      }`,
    fragmentShader: `
      uniform vec3 uColor; uniform float uOpacidad; uniform float uCorte; uniform float uTiempo; uniform float uSolido;
      varying vec3 vN; varying vec3 vV; varying vec3 vW;
      void main() {
        if (vW.y > uCorte) discard;
        vec3 n = normalize(vN);
        float f = pow(1.0 - abs(dot(n, normalize(vV))), 2.2);
        float bandas = 0.82 + 0.18 * sin(vW.y * 140.0 - uTiempo * 5.0);
        float luz = 0.35 + 0.65 * max(dot(n, normalize(vec3(0.4, 0.8, 0.6))), 0.0);
        float borde = smoothstep(0.035, 0.0, abs(vW.y - uCorte));
        vec3 c = uColor * mix((0.18 + 1.35 * f) * bandas, luz * 1.15 + f * 0.6, uSolido);
        c += vec3(0.75, 1.0, 1.0) * borde * 2.2;
        float a = uOpacidad * mix(0.12 + 0.88 * f, 0.92, uSolido) + borde;
        gl_FragColor = vec4(c, clamp(a, 0.0, 1.0));
      }`,
    transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
  });
}

// ---------------------------------------------------------------- carga de mallas (binario propio)
async function cargarPaquete(nombre) {
  const [man, bin] = await Promise.all([
    fetch(`assets/${nombre}.json`).then(r => r.json()),
    // (.bin en la carpeta local; la copia publicada en línea lo sirve como .bin.wasm)
    fetch(`assets/${nombre}.bin`).then(r => r.ok ? r : fetch(`assets/${nombre}.bin.wasm`)).then(r => r.arrayBuffer()),
  ]);
  return man.map(p => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(bin, p.pos[0], p.pos[1] * 3), 3));
    g.setIndex(new THREE.BufferAttribute(new Uint32Array(bin, p.idx[0], p.idx[1]), 1));
    g.computeVertexNormals();
    g.computeBoundingBox();
    return { clave: p.clave, grupo: p.grupo, geo: g };
  });
}

const CIAN = 0x38e8ff, AMBAR = 0xffb547, ROJO = 0xff3b4e, AZUL = 0x3b7bff;
function colorDe(clave, grupo) {
  if (clave === 'lung_arteries' || clave.includes('artery') || clave === 'aorta' || clave === 'brachiocephalic_trunk') return ROJO;
  if (clave === 'lung_veins' || clave.includes('vein') || clave.includes('vena_cava')) return AZUL;
  if (clave === 'heart' || clave === 'atrial_appendage_left') return 0xff5a6e;
  if (clave.startsWith('lung_') && clave.includes('lobe')) return 0x2fd4ff;
  if (clave === 'lung_airways' || clave === 'trachea') return 0x9ff6ff;
  if (grupo === 'hueso') return 0xbfefff;
  if (grupo === 'organo') return AMBAR;
  if (grupo === 'organo_hueco') return 0xff9a3c;
  if (grupo === 'musculo') return 0xff7a59;
  return CIAN;
}
function opacidadBase(clave, grupo) {
  if (clave.startsWith('lung_') && clave.includes('lobe')) return 0.22;
  if (grupo === 'hueso') return 0.75;
  if (grupo === 'musculo') return 0.25;
  if (clave === 'lung_arteries' || clave === 'lung_veins') return 0.9;
  return 0.6;
}

const raiz = new THREE.Group();
escena.add(raiz);
const torax = new THREE.Group();
const cerebro = new THREE.Group();
const piezas = new THREE.Group();
raiz.add(torax, cerebro, piezas);
const partesTorax = [];
const partesPiezas = [];

// ---------------------------------------------------------------- decorado: rejilla, anillos, pila de cortes
const rejilla = new THREE.GridHelper(14, 56, 0x0f6b82, 0x0a3442);
rejilla.position.y = -1.25;
rejilla.material.transparent = true;
rejilla.material.opacity = 0.35;
escena.add(rejilla);

const anillos = new THREE.Group();
escena.add(anillos);
function anillo(r, grosor, color, arco = Math.PI * 2, op = 0.7) {
  const m = new THREE.Mesh(new THREE.RingGeometry(r, r + grosor, 128, 1, 0, arco),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: op, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }));
  m.rotation.x = -Math.PI / 2;
  return m;
}
const a1 = anillo(1.45, 0.012, CIAN), a2 = anillo(1.6, 0.04, CIAN, Math.PI * 1.3, 0.35), a3 = anillo(1.75, 0.006, AMBAR, Math.PI * 0.4, 0.9);
const a4 = anillo(1.2, 0.02, CIAN, Math.PI * 0.15, 0.9);
anillos.add(a1, a2, a3, a4);
anillos.position.y = -1.2;
// marcas de escala del anillo
const marcas = new THREE.Group();
for (let i = 0; i < 72; i++) {
  const largo = i % 6 === 0 ? 0.09 : 0.035;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(0.006, largo), new THREE.MeshBasicMaterial({ color: CIAN, transparent: true, opacity: 0.8, side: THREE.DoubleSide, blending: THREE.AdditiveBlending }));
  const ang = i / 72 * Math.PI * 2;
  m.position.set(Math.cos(ang) * 1.92, 0, Math.sin(ang) * 1.92);
  m.rotation.x = -Math.PI / 2;
  m.rotation.z = -ang + Math.PI / 2;
  marcas.add(m);
}
anillos.add(marcas);

// plano de escaneo (barre el modelo al reconstruirlo)
const planoEscaneo = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 3.2),
  new THREE.ShaderMaterial({
    uniforms: { ...uniformesComunes, uOp: { value: 0 } },
    vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
    fragmentShader: `uniform float uOp; uniform float uTiempo; varying vec2 vUv;
      void main(){ vec2 c = vUv - 0.5; float r = length(c);
        float g = smoothstep(0.5, 0.0, r) * (0.25 + 0.75 * step(0.985, fract((vUv.x + vUv.y) * 40.0 + uTiempo)));
        float aro = smoothstep(0.012, 0.0, abs(r - 0.48));
        gl_FragColor = vec4(vec3(0.3, 0.95, 1.0), (g * 0.35 + aro) * uOp); }`,
    transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
  }));
planoEscaneo.rotation.x = -Math.PI / 2;
escena.add(planoEscaneo);

const pila = new THREE.Group();
escena.add(pila);
const cortes = [];
const cargador = new THREE.TextureLoader();
for (let i = 0; i < 14; i++) {
  const tex = cargador.load(`assets/corte_${String(i).padStart(2, '0')}.png`);
  tex.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 1.5), new THREE.MeshBasicMaterial({
    map: tex, transparent: true, opacity: 0, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }));
  m.rotation.x = -Math.PI / 2;
  const marco = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(1.5, 1.5)),
    new THREE.LineBasicMaterial({ color: CIAN, transparent: true, opacity: 0, blending: THREE.AdditiveBlending }));
  m.add(marco);
  m.userData.marco = marco;
  pila.add(m);
  cortes.push(m);
}

// ---------------------------------------------------------------- partículas que se ensamblan en el tórax
let particulas = null;
function crearParticulas(fuentes, n = 26000) {
  const pos = new Float32Array(n * 3), ini = new Float32Array(n * 3), azar = new Float32Array(n);
  const verts = [];
  for (const g of fuentes) verts.push(g.getAttribute('position'));
  const total = verts.reduce((s, a) => s + a.count, 0);
  for (let i = 0; i < n; i++) {
    let k = Math.floor(Math.random() * total), a = verts[0];
    for (const v of verts) { if (k < v.count) { a = v; break; } k -= v.count; }
    pos.set([a.getX(k), a.getY(k), a.getZ(k)], i * 3);
    const r = 3 + Math.random() * 5, t = Math.random() * Math.PI * 2, f = Math.acos(2 * Math.random() - 1);
    ini.set([r * Math.sin(f) * Math.cos(t), r * Math.cos(f), r * Math.sin(f) * Math.sin(t)], i * 3);
    azar[i] = Math.random();
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('aIni', new THREE.BufferAttribute(ini, 3));
  g.setAttribute('aAzar', new THREE.BufferAttribute(azar, 1));
  const m = new THREE.ShaderMaterial({
    uniforms: { ...uniformesComunes, uMezcla: { value: 0 }, uOp: { value: 1 } },
    vertexShader: `uniform float uMezcla; uniform float uTiempo; attribute vec3 aIni; attribute float aAzar; varying float vA;
      void main(){ float t = clamp(uMezcla * 1.4 - aAzar * 0.4, 0.0, 1.0); t = t * t * (3.0 - 2.0 * t);
        vec3 p = mix(aIni, position, t) + 0.006 * vec3(sin(uTiempo*2.0+aAzar*40.0), cos(uTiempo*1.7+aAzar*30.0), 0.0);
        vec4 mv = modelViewMatrix * vec4(p, 1.0); gl_Position = projectionMatrix * mv;
        gl_PointSize = (1.6 + 2.4 * aAzar) * (3.2 / -mv.z); vA = 0.35 + 0.65 * t; }`,
    fragmentShader: `uniform float uOp; varying float vA; void main(){ vec2 c = gl_PointCoord - 0.5; float d = length(c);
        if (d > 0.5) discard; gl_FragColor = vec4(0.45, 0.95, 1.0, (1.0 - d * 2.0) * vA * uOp); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  particulas = new THREE.Points(g, m);
  torax.add(particulas);
}

// ---------------------------------------------------------------- «espectadores» de la sala de RV
const espectadores = new THREE.Group();
escena.add(espectadores);
for (let i = 0; i < 6; i++) {
  const cono = new THREE.Mesh(new THREE.ConeGeometry(0.09, 0.22, 4, 1, true),
    new THREE.MeshBasicMaterial({ color: i % 2 ? CIAN : AMBAR, wireframe: true, transparent: true, opacity: 0, blending: THREE.AdditiveBlending }));
  const ang = i / 6 * Math.PI * 2;
  cono.position.set(Math.cos(ang) * 2.1, 0.15, Math.sin(ang) * 2.1);
  cono.lookAt(0, 0, 0);
  cono.rotateX(Math.PI / 2);
  const rayo = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(-Math.cos(ang) * 2.1, -0.1, -Math.sin(ang) * 2.1)]),
    new THREE.LineDashedMaterial({ color: CIAN, dashSize: 0.05, gapSize: 0.04, transparent: true, opacity: 0, blending: THREE.AdditiveBlending }));
  rayo.computeLineDistances();
  rayo.position.copy(cono.position);
  espectadores.add(cono, rayo);
}

// ---------------------------------------------------------------- estados por diapositiva
// cam: posición; mira: punto; torax/cerebro/piezas: opacidad 0–1; corte: altura del plano de corte (y);
// pila: separación de los cortes (0 = ocultos); vasos: 1 = solo vasos; explota: separación de las piezas; giro: rad/s
const ESTADOS = [
  { cam: [0, 0.25, 4.6], mira: [0, 0.05, 0], torax: 1, corte: 2, giro: 0.18, part: 1, x: 1.05 },             // portada
  { cam: [1.6, 1.9, 3.6], mira: [0, 0.1, 0], torax: 0, corte: 2, pila: 1, giro: 0.05, x: 0.9 },             // problema
  { cam: [0, 0.5, 4.3], mira: [0, 0.05, 0], torax: 1, corte: -1.2, corteA: 1.3, pila: 0.25, escaneo: 1, giro: 0.12, x: 0.95 }, // solución
  { cam: [0.2, 0.35, 4.9], mira: [0, 0.05, 0], torax: 0.9, corte: 2, giro: 0.25, x: 1.25 },                // arquitectura
  { cam: [0, 0.45, 3.3], mira: [0, 0.3, 0], torax: 1, corte: 2, vasos: 1, giro: 0.1, x: 0.95 },           // IA
  { cam: [0, 0.3, 3.9], mira: [0, 0.0, 0], cerebro: 0, piezas: 1, explota: 1, giro: 0.22, x: 0.95 },        // impresión
  { cam: [3.2, 2.6, 3.4], mira: [0, 0.0, 0], torax: 1, corte: 2, giro: 0.08, espect: 1, x: 0 },            // RV/RA
  { cam: [0, 0.2, 5.6], mira: [0, 0.05, 0], torax: 0.45, corte: 2, giro: 0.3, part: 0.6, x: -1.2 },        // ingeniería
  { cam: [0, 0.15, 6.4], mira: [0, -0.62, 0], torax: 1, corte: 2, giro: 0.35, part: 1, x: 0, final: 1 },    // cierre
];
let estado = ESTADOS[0];
let tEstado = 0;
const actual = { torax: 0, cerebro: 0, piezas: 0, pila: 0, vasos: 0, explota: 0, espect: 0, escaneo: 0, part: 0, x: 1.05, corte: -1.3 };
const camObjetivo = new THREE.Vector3(), miraObjetivo = new THREE.Vector3();

export function irA(i) {
  estado = ESTADOS[Math.max(0, Math.min(ESTADOS.length - 1, i))];
  tEstado = 0;
  if (estado.corteA !== undefined) actual.corte = estado.corte;  // (la reconstrucción empieza abajo)
  if (estado.explota) actual.explota = 0;
}

// ---------------------------------------------------------------- bucle
const reloj = new THREE.Clock();
let arranque = 0;
function suavizar(a, b, k, dt) { return a + (b - a) * (1 - Math.exp(-k * dt)); }

function fotograma() {
  const dt = Math.min(reloj.getDelta(), location.search.includes('export') ? 1.5 : 0.05);  // (al exportar, por tiempo real)
  const t = reloj.elapsedTime;
  tEstado += dt;
  arranque = Math.min(1, arranque + dt / 3.2);
  uniformesComunes.uTiempo.value = t;
  const e = estado;

  for (const k of ['torax', 'cerebro', 'piezas', 'pila', 'vasos', 'espect', 'escaneo', 'part', 'x'])
    actual[k] = suavizar(actual[k], e[k] ?? (k === 'x' ? 0 : 0), k === 'x' ? 2.2 : 3, dt);
  const corteObj = e.corteA !== undefined ? Math.min(e.corteA, e.corte + tEstado * 0.85) : e.corte;
  actual.corte = suavizar(actual.corte, corteObj, e.corteA !== undefined ? 8 : 3, dt);
  actual.explota = suavizar(actual.explota, e.explota ? 0.5 + 0.5 * Math.sin(tEstado * 1.1 - Math.PI / 2) : 0, 4, dt);

  camObjetivo.set(...e.cam);
  miraObjetivo.set(...e.mira);
  camara.position.lerp(camObjetivo, 1 - Math.exp(-1.8 * dt));
  mirarA.lerp(miraObjetivo, 1 - Math.exp(-2.2 * dt));
  camara.position.y += Math.sin(t * 0.5) * 0.0008;
  camara.lookAt(mirarA);

  raiz.position.x = actual.x;
  raiz.rotation.y += (e.giro ?? 0.1) * dt;
  anillos.position.x = actual.x;
  anillos.rotation.y = t * 0.15;
  a2.rotation.z = t * 0.4; a3.rotation.z = -t * 0.7; a4.rotation.z = t * 1.3;
  marcas.rotation.y = -t * 0.05;

  // tórax: cada parte, con su opacidad y modo (vasos solos en la diapositiva de IA)
  const entrada = estado === ESTADOS[0] ? arranque : 1;
  for (const p of partesTorax) {
    const esVaso = p.clave === 'lung_arteries' || p.clave === 'lung_veins' || p.clave === 'lung_airways';
    const foco = esVaso ? 1 : 1 - 0.93 * actual.vasos;
    const u = p.malla.material.uniforms;
    u.uOpacidad.value = p.base * actual.torax * foco * entrada;
    u.uSolido.value = esVaso ? actual.vasos * 0.85 : 0;
    u.uCorte.value = actual.corte;
    p.malla.visible = u.uOpacidad.value > 0.004;
  }
  if (particulas) {
    particulas.material.uniforms.uMezcla.value = estado === ESTADOS[0] ? arranque : 1;
    particulas.material.uniforms.uOp.value = actual.part * actual.torax * (estado === ESTADOS[0] ? 1.15 - arranque * 0.6 : 0.5);
    particulas.visible = particulas.material.uniforms.uOp.value > 0.01;
  }
  // cerebro y piezas de impresión
  for (const m of cerebro.children) { m.material.uniforms.uOpacidad.value = 0.8 * actual.cerebro; m.visible = actual.cerebro > 0.01; }
  partesPiezas.forEach((p, i) => {
    const u = p.malla.material.uniforms;
    u.uOpacidad.value = 0.85 * actual.piezas;
    u.uSolido.value = 0.25;
    p.malla.visible = actual.piezas > 0.01;
    p.malla.position.set(0, p.orden * actual.explota * 0.42, 0);
  });
  // pila de cortes del TAC
  cortes.forEach((c, i) => {
    const sep = actual.pila;
    c.position.y = (i - 6.5) * 0.17 * sep + 0.05;
    c.position.x = actual.x;
    c.rotation.z = Math.sin(t * 0.3 + i * 0.3) * 0.05 * sep;
    const visible = Math.min(1, sep * 1.2) * (estado === ESTADOS[2] ? Math.max(0, 1 - tEstado * 0.7) : 1);
    c.material.opacity = 0.55 * visible;
    c.userData.marco.material.opacity = 0.5 * visible;
    c.visible = visible > 0.01;
  });
  // plano de escaneo
  planoEscaneo.material.uniforms.uOp.value = actual.escaneo * (actual.corte < 1.25 ? 1 : Math.max(0, 1 - (tEstado - 3)));
  planoEscaneo.position.set(actual.x, actual.corte, 0);
  // espectadores
  espectadores.rotation.y = t * 0.12;
  espectadores.children.forEach(o => { o.material.opacity = 0.85 * actual.espect; o.visible = actual.espect > 0.01; });
  rejilla.material.opacity = 0.25 + 0.15 * actual.espect;

  renderer.render(escena, camara);
  requestAnimationFrame(fotograma);
}

// ---------------------------------------------------------------- arranque
(async () => {
  requestAnimationFrame(fotograma);
  const [tx, cb, pz] = await Promise.all([cargarPaquete('torax'), cargarPaquete('cerebro'), cargarPaquete('piezas')]);
  for (const p of tx) {
    const m = new THREE.Mesh(p.geo, holo(colorDe(p.clave, p.grupo), 0));
    m.renderOrder = p.grupo === 'hueso' ? 2 : 1;
    torax.add(m);
    partesTorax.push({ clave: p.clave, malla: m, base: opacidadBase(p.clave, p.grupo) });
  }
  crearParticulas(tx.filter(p => p.grupo === 'hueso' || p.clave.includes('lobe')).map(p => p.geo));
  for (const p of cb) cerebro.add(new THREE.Mesh(p.geo, holo(0xffc27a, 0)));
  const centro = new THREE.Vector3();
  const ys = pz.map(p => p.geo.boundingBox.getCenter(centro).y);
  const orden = [...ys].sort((a, b) => a - b);
  pz.forEach((p, i) => {
    const m = new THREE.Mesh(p.geo, holo(i === 1 ? 0xffd27a : AMBAR, 0));
    piezas.add(m);
    partesPiezas.push({ malla: m, orden: orden.indexOf(ys[i]) - 1 });  // (abajo −1, en medio 0, arriba +1)
  });
  document.body.classList.add('escena-lista');
  window.__escenaLista = true;
})();
