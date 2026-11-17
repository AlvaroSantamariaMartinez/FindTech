// La escena 3D que va detrás de las diapositivas. Son modelos reales hechos con MRAnalyzer a partir de muestras públicas
// de 3D Slicer (tórax: TAC «CTChest»; cerebro: resonancia «MRHead»), nunca de pacientes.
//   - Portada: el cerebro, girando.
//   - Simulación: los cortes del TAC se comprimen y de ellos sale el modelo, estructura a estructura; después el corazón
//     pasa a malla, se cierra el molde, se cuela la silicona y aparece el gemelo digital.
//   - Cierre: el corazón como holograma.
import * as THREE from '../presentacion/vendor/three.module.min.js';

const EMBEBIDOS = window.__embebidos || {};      // (en la copia de un solo archivo, todo va dentro del HTML)
const exportar = location.search.includes('export');
const ruta = r => EMBEBIDOS[r] || r;
async function bytes(r) {
  if (!EMBEBIDOS[r]) return (await fetch(r)).arrayBuffer();
  const b = atob(EMBEBIDOS[r].split(',')[1]);
  const u = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
  return u.buffer;
}

const lienzo = document.getElementById('escena3d');
const renderer = new THREE.WebGLRenderer({ canvas: lienzo, antialias: true, alpha: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0x000000, 0);
renderer.localClippingEnabled = true;
const escena = new THREE.Scene();
const camara = new THREE.PerspectiveCamera(38, 16 / 9, 0.05, 60);
camara.position.set(0, 0.3, 5);
const mirarA = new THREE.Vector3();
function ajustar() {
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  camara.aspect = window.innerWidth / window.innerHeight;
  camara.updateProjectionMatrix();
}
window.addEventListener('resize', ajustar);
ajustar();

escena.add(new THREE.HemisphereLight(0xffffff, 0xb9c8c0, 1.15));
const sol = new THREE.DirectionalLight(0xffffff, 1.9);
sol.position.set(-2.5, 4, 3.5);
const contra = new THREE.DirectionalLight(0x9a6cff, 0.9);
contra.position.set(3, 1.5, -3);
escena.add(sol, contra);

const MORADO = 0x6422b8, TINTA = 0x063f3b, ARCILLA = 0xf3f1ec;

// ---------------------------------------------------------------- modelos (posiciones e índices en 16 bits)
async function paquete(nombre) {
  const man = JSON.parse(new TextDecoder().decode(await bytes(`modelos/${nombre}.json`)));
  const bin = await bytes(`modelos/${nombre}.bin`);
  return man.map(p => {
    const q = new Uint16Array(bin, p.pos[0], p.pos[1] * 3);
    const pos = new Float32Array(q.length);
    for (let i = 0; i < q.length; i++) pos[i] = p.min[i % 3] + q[i] / 65535 * p.tam[i % 3];
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setIndex(new THREE.BufferAttribute(new Uint16Array(bin, p.idx[0], p.idx[1]), 1));
    g.computeVertexNormals();
    g.computeBoundingBox();
    return { clave: p.clave, grupo: p.grupo, geo: g };
  });
}

function arcilla(color, opacidad = 1) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0, transparent: true, opacity: opacidad });
}
// El holograma: se ve el canto y unas bandas que suben. «suma» para fondo oscuro; sin ella, para fondo claro.
const tiempo = { value: 0 };
function holograma(color, suma) {
  return new THREE.ShaderMaterial({
    uniforms: { uTiempo: tiempo, uColor: { value: new THREE.Color(color) }, uOp: { value: 0 } },
    vertexShader: `varying vec3 vN; varying vec3 vV; varying vec3 vW;
      void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; vN = normalize(mat3(modelMatrix) * normal);
        vV = normalize(cameraPosition - w.xyz); gl_Position = projectionMatrix * viewMatrix * w; }`,
    fragmentShader: `uniform vec3 uColor; uniform float uOp; uniform float uTiempo; varying vec3 vN; varying vec3 vV; varying vec3 vW;
      void main() { float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 2.0);
        float bandas = 0.75 + 0.25 * sin(vW.y * 90.0 - uTiempo * 4.0);
        float barrido = smoothstep(0.06, 0.0, abs(fract(vW.y * 0.45 - uTiempo * 0.22) - 0.5));
        gl_FragColor = vec4(uColor * (0.55 + 0.9 * f) + vec3(barrido * 0.5), clamp((0.10 + 0.9 * f) * bandas + barrido * 0.5, 0.0, 1.0) * uOp); }`,
    transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: suma ? THREE.AdditiveBlending : THREE.NormalBlending,
  });
}

function colorDe(clave, grupo) {
  if (clave === 'heart' || clave === 'atrial_appendage_left') return 0xd24a55;
  if (clave === 'lung_arteries' || clave === 'aorta' || clave.includes('artery') || clave === 'brachiocephalic_trunk') return 0xd8434f;
  if (clave === 'lung_veins' || clave.includes('vein') || clave.includes('vena_cava')) return 0x4a6fd8;
  if (clave.startsWith('lung_') && clave.includes('lobe')) return 0xf0a79f;
  if (clave === 'lung_airways' || clave === 'trachea') return 0x7fcbe3;
  if (clave === 'liver') return 0xa5563f;
  if (clave === 'spleen') return 0x8a4f77;
  if (clave.startsWith('kidney')) return 0xb5694c;
  if (clave === 'spinal_cord') return 0xf0cf63;
  if (clave === 'gallbladder') return 0x5aa36a;
  if (grupo === 'hueso') return 0xefe6d2;
  if (grupo === 'musculo') return 0xc9756b;
  if (grupo === 'vaso') return 0xd8434f;
  return 0xe3b089;
}
function opacidadDe(clave, grupo) {
  if (clave.startsWith('lung_') && clave.includes('lobe')) return 0.34;
  if (grupo === 'musculo') return 0.5;
  return 1;
}
const DEL_CORAZON = new Set(['heart', 'atrial_appendage_left', 'aorta', 'pulmonary_vein', 'superior_vena_cava', 'inferior_vena_cava',
  'brachiocephalic_trunk', 'brachiocephalic_vein_left', 'brachiocephalic_vein_right', 'subclavian_artery_left', 'subclavian_artery_right',
  'common_carotid_artery_left', 'common_carotid_artery_right']);

// ---------------------------------------------------------------- lo que hay en la escena
// pivote (donde se mira, y lo que gira) > contenido (la escala y el centro del modelo)
const pivote = new THREE.Group();
const contenido = new THREE.Group();
pivote.add(contenido);
escena.add(pivote);
const partes = [];          // el tórax: { clave, malla, base, y, corazon, color }
const relleno = [];         // la pieza de silicona (el corazón y sus vasos, otra vez)
const gemelo = [];          // su holograma
const final = [];           // el holograma del cierre
let mallaAlambre = null;

const pCerebro = new THREE.Group();
escena.add(pCerebro);
let cerebro = null;

// la sombra de contacto
const lienzoSombra = document.createElement('canvas');
lienzoSombra.width = lienzoSombra.height = 128;
{
  const c = lienzoSombra.getContext('2d');
  const g = c.createRadialGradient(64, 64, 4, 64, 64, 62);
  g.addColorStop(0, 'rgba(6,40,38,.42)');
  g.addColorStop(1, 'rgba(6,40,38,0)');
  c.fillStyle = g;
  c.fillRect(0, 0, 128, 128);
}
const sombra = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 3.2),
  new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(lienzoSombra), transparent: true, opacity: 0, depthWrite: false }));
sombra.rotation.x = -Math.PI / 2;
escena.add(sombra);

// los cortes del TAC
const pila = new THREE.Group();
escena.add(pila);
const cortes = [];
const cargador = new THREE.TextureLoader();
for (let i = 0; i < 14; i++) {
  const tex = cargador.load(ruta(`img/corte_${String(i).padStart(2, '0')}.webp`));
  tex.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(1.7, 1.7),
    new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
  m.rotation.x = -Math.PI / 2;
  const marco = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(1.7, 1.7)),
    new THREE.LineBasicMaterial({ color: MORADO, transparent: true, opacity: 0 }));
  m.add(marco);
  m.userData.marco = marco;
  pila.add(m);
  cortes.push(m);
}
// el plano que barre el modelo mientras se segmenta
const barrido = new THREE.Mesh(new THREE.PlaneGeometry(3.1, 3.1), new THREE.ShaderMaterial({
  uniforms: { uTiempo: tiempo, uOp: { value: 0 } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  fragmentShader: `uniform float uOp; uniform float uTiempo; varying vec2 vUv;
    void main(){ float r = length(vUv - 0.5); float aro = smoothstep(0.014, 0.0, abs(r - 0.47));
      float lineas = step(0.97, fract((vUv.x + vUv.y) * 34.0 + uTiempo));
      gl_FragColor = vec4(0.39, 0.13, 0.72, (smoothstep(0.5, 0.0, r) * (0.10 + 0.25 * lineas) + aro) * uOp); }`,
  transparent: true, depthWrite: false, side: THREE.DoubleSide,
}));
barrido.rotation.x = -Math.PI / 2;
escena.add(barrido);

// el molde: dos mitades de vidrio morado con sus tornillos
const molde = new THREE.Group();
escena.add(molde);
const mitades = [];
const tornillos = new THREE.Group();
molde.add(tornillos);
function hacerMolde(w, h, d) {
  const vidrio = new THREE.MeshStandardMaterial({ color: 0x7c4ad6, roughness: 0.25, transparent: true, opacity: 0, depthWrite: false });
  const borde = new THREE.LineBasicMaterial({ color: MORADO, transparent: true, opacity: 0 });
  for (const lado of [-1, 1]) {
    const caja = new THREE.BoxGeometry(w / 2, h, d);
    const m = new THREE.Mesh(caja, vidrio);
    m.add(new THREE.LineSegments(new THREE.EdgesGeometry(caja), borde));
    m.userData.lado = lado;
    molde.add(m);
    mitades.push(m);
  }
  const metal = new THREE.MeshStandardMaterial({ color: 0x8b9199, roughness: 0.4, metalness: 0.3, transparent: true, opacity: 0 });
  for (const sy of [-1, 1]) for (const sz of [-1, 1]) {
    const t = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, w * 1.03, 12), metal);
    t.rotation.z = Math.PI / 2;
    t.position.set(0, sy * (h / 2 - 0.09), sz * (d / 2 - 0.09));
    tornillos.add(t);
  }
  molde.userData = { w, h, d, vidrio, borde, metal };
}
// los aros del gemelo digital
const aros = new THREE.Group();
escena.add(aros);
for (const [r, arco, v] of [[0.92, Math.PI * 1.4, 0.5], [1.03, Math.PI * 0.5, -0.9], [0.8, Math.PI * 0.25, 1.4]]) {
  const a = new THREE.Mesh(new THREE.RingGeometry(r, r + 0.018, 96, 1, 0, arco),
    new THREE.MeshBasicMaterial({ color: MORADO, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
  a.rotation.x = -Math.PI / 2;
  a.userData.v = v;
  aros.add(a);
}

// ---------------------------------------------------------------- estado
// modo: 'cerebro' | 'nada' | 'sim' | 'final'. etapa (solo en 'sim'): −1 en espera, 0 imagen, 1 segmentación, 2 modelo 3D,
// 3 molde, 4 fabricación, 5 gemelo digital.
let modo = 'cerebro', etapa = -1, tEtapa = 0, tModo = 0;
let alContar = () => {};
const caja = { centro: new THREE.Vector3(), escala: 1, centroCorazon: new THREE.Vector3(), escalaCorazon: 1, alto: 1 };
const a = { foco: 0, pila: 0, sep: 1, cerebro: 0, alambre: 0, molde: 0, cierre: 0, tornillos: 0, pieza: 0, gemelo: 0, final: 0, sombra: 0, x: 1.0, barrido: 0 };
const planoColada = new THREE.Plane(new THREE.Vector3(0, -1, 0), 10);
let vistas = 0;

export function irA(m) { if (m !== modo) { modo = m; tModo = 0; } if (m !== 'sim') ponEtapa(-1); }
export function ponEtapa(n) { etapa = n; tEtapa = 0; if (n < 1) { vistas = 0; alContar(0, partes.length); } if (n >= 2) alContar(partes.length, partes.length); }
export function escucharCuenta(f) { alContar = f; }

const reloj = new THREE.Clock();
const s = (v, obj, k, dt) => v + (obj - v) * (1 - Math.exp(-k * dt));
const suave = x => { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x); };
const camObj = new THREE.Vector3(), miraObj = new THREE.Vector3(), tmp = new THREE.Vector3();
const colorTmp = new THREE.Color();

function fotograma() {
  const dt = Math.min(reloj.getDelta(), exportar ? 1.5 : 0.05);
  const t = reloj.elapsedTime;
  tiempo.value = t;
  tEtapa += dt;
  tModo += dt;
  const sim = modo === 'sim';

  // la cámara y dónde se pone el modelo (a la derecha del texto; en el cierre, también)
  if (sim && etapa <= 0) camObj.set(0, 1.9, 5.1); else if (sim && etapa === 1) camObj.set(0, 0.5, 5.1); else camObj.set(0, 0.28, 4.8);
  miraObj.set(0, sim && etapa <= 1 ? 0.02 : 0, 0);
  camara.position.x = s(camara.position.x, camObj.x, 2, dt);
  camara.position.y = s(camara.position.y, camObj.y, 2, dt);
  camara.position.z = s(camara.position.z, camObj.z, 2, dt);
  mirarA.lerp(miraObj, 1 - Math.exp(-2.2 * dt));
  camara.lookAt(mirarA);
  const ancho = Math.tan(THREE.MathUtils.degToRad(19)) * 5 * camara.aspect;      // (media anchura visible a 5 de distancia)
  a.x = s(a.x, (modo === 'final' ? 0.44 : 0.40) * ancho, 3, dt);

  // ---- portada: el cerebro
  a.cerebro = s(a.cerebro, modo === 'cerebro' ? 1 : 0, 3, dt);
  pCerebro.position.set(a.x * 1.3, 0.05 + Math.sin(t * 0.8) * 0.03, 0);
  pCerebro.rotation.y += 0.22 * dt;
  if (cerebro) {
    cerebro.material.opacity = a.cerebro;
    cerebro.visible = a.cerebro > 0.01;
    const e = 0.86 + 0.14 * suave(Math.min(1, tModo / 1.6));
    if (modo === 'cerebro') pCerebro.scale.setScalar(e);
  }

  // ---- simulación
  const objFoco = sim && etapa >= 2 || modo === 'final' ? 1 : 0;
  a.foco = s(a.foco, objFoco, 2.2, dt);
  const k = suave(a.foco);
  const esc = caja.escala + (caja.escalaCorazon - caja.escala) * k;
  tmp.copy(caja.centro).lerp(caja.centroCorazon, k);
  contenido.scale.setScalar(esc);
  contenido.position.copy(tmp).multiplyScalar(-esc);
  pivote.position.set(a.x, 0, 0);
  pivote.rotation.y += (sim && etapa === 1 ? 0.16 : sim && (etapa === 3 || etapa === 4) ? 0.1 : 0.2) * dt;

  // los cortes: separados en «imagen», y se comprimen al segmentar
  a.pila = s(a.pila, sim && etapa <= 1 ? 1 : 0, 3, dt);
  a.sep = s(a.sep, sim && etapa >= 1 ? 0.0 : 1, sim && etapa >= 1 ? 0.9 : 3, dt);
  const nivel = -caja.alto / 2 - 0.1 + Math.max(0, tEtapa - 1.2) * (caja.alto + 0.3) / 5.6;      // (por dónde va el barrido)
  // (ya comprimidos, suben con el barrido: de ese bloque de cortes va saliendo el modelo, y al llegar arriba se apagan)
  const yPila = sim && etapa === 1 ? Math.min(nivel, caja.alto / 2 + 0.1) * (1 - a.sep) : 0;
  const quita = sim && etapa === 1 ? 1 - suave((nivel - (caja.alto / 2 - 0.2)) / 0.3) : sim && etapa >= 2 ? 0 : 1;
  cortes.forEach((c, i) => {
    c.position.set(a.x, yPila + (i - 6.5) * (0.012 + 0.15 * a.sep), 0);
    c.rotation.z = pivote.rotation.y;
    const op = a.pila * quita * suave((tModo - i * 0.05) / 0.8);
    c.material.opacity = (0.55 + 0.38 * a.sep) * op;
    c.userData.marco.material.opacity = 0.7 * op;
    c.visible = op > 0.01;
  });
  a.barrido = s(a.barrido, sim && etapa === 1 && tEtapa > 1.0 && nivel < caja.alto / 2 + 0.1 ? 1 : 0, 5, dt);
  barrido.material.uniforms.uOp.value = a.barrido;
  barrido.position.set(a.x, Math.min(nivel, caja.alto / 2 + 0.1), 0);
  barrido.visible = a.barrido > 0.01;

  // el tórax, estructura a estructura
  let n = 0;
  for (const p of partes) {
    let obj = 0, color = p.color;
    if (sim && etapa === 1) obj = p.y < nivel ? p.base : 0;
    if (obj > 0) n++;
    const m = p.malla.material;
    m.opacity = s(m.opacity, obj, obj > 0 ? 6 : 4, dt);
    m.color.lerp(colorTmp.set(color), 1 - Math.exp(-3 * dt));
    m.depthWrite = m.opacity > 0.9;
    p.malla.visible = m.opacity > 0.01;
    // (al aparecer, cada estructura crece un poco)
    const e = 0.94 + 0.06 * Math.min(1, m.opacity / Math.max(0.05, p.base));
    p.malla.scale.setScalar(sim && etapa === 1 ? e : 1);
  }
  if (sim && etapa === 1 && n !== vistas) { vistas = n; alContar(n, partes.length); }

  // el modelo 3D: la malla, a la vista un momento
  a.alambre = s(a.alambre, sim && etapa === 2 && tEtapa > 0.6 && tEtapa < 3.6 ? 1 : 0, 4, dt);
  if (mallaAlambre) { mallaAlambre.material.opacity = 0.55 * a.alambre; mallaAlambre.visible = a.alambre > 0.01; }

  // el molde: se cierra en «molde» y se abre al acabar la colada
  const cerrado = sim && etapa === 3 ? suave((tEtapa - 0.3) / 2.2) : sim && etapa === 4 ? 1 - suave((tEtapa - 3.6) / 1.6) : 0;
  a.molde = s(a.molde, sim && (etapa === 3 || (etapa === 4 && tEtapa < 5)) ? 1 : 0, 4, dt);
  a.cierre = s(a.cierre, cerrado, 8, dt);
  a.tornillos = s(a.tornillos, cerrado > 0.97 ? 1 : 0, 6, dt);
  if (molde.userData.w) {
    const u = molde.userData;
    molde.position.set(a.x, 0, 0);
    molde.rotation.y = pivote.rotation.y;
    for (const m of mitades) m.position.x = m.userData.lado * (u.w / 4 + (1 - a.cierre) * 1.0);
    u.vidrio.opacity = 0.22 * a.molde;
    u.borde.opacity = 0.9 * a.molde;
    u.metal.opacity = a.tornillos * a.molde;
    tornillos.visible = u.metal.opacity > 0.02;
    molde.visible = a.molde > 0.01;
    // la colada: la silicona sube dentro del molde
    const sube = sim && etapa === 4 ? suave((tEtapa - 0.4) / 2.8) : 1;
    planoColada.constant = -u.h / 2 + sube * (u.h + 0.05);
  }
  a.pieza = s(a.pieza, sim && etapa >= 2 ? (etapa === 5 ? 0.82 : 1) : 0, 4, dt);
  const curada = sim && etapa === 4 ? suave((tEtapa - 3.0) / 1.5) : 1;
  for (const r of relleno) {
    r.material.opacity = a.pieza;
    colorTmp.set(sim && etapa === 5 && r.userData.vaso ? MORADO : sim && etapa >= 4 ? 0xf6f4ef : ARCILLA);
    if (sim && etapa === 4) r.material.color.set(0xc9b3f5).lerp(colorTmp, curada);
    else r.material.color.lerp(colorTmp, 1 - Math.exp(-3 * dt));
    r.material.depthWrite = a.pieza > 0.9;
    r.visible = a.pieza > 0.01;
  }
  // el gemelo digital
  a.gemelo = s(a.gemelo, sim && etapa === 5 ? 1 : 0, 2.5, dt);
  for (const g of gemelo) { g.material.uniforms.uOp.value = 0.85 * a.gemelo; g.visible = a.gemelo > 0.01; g.scale.setScalar(1.035 + 0.01 * Math.sin(t * 2)); }
  aros.position.set(a.x, -molde.userData.h / 2 - 0.05 || -1, 0);
  aros.children.forEach(o => { o.material.opacity = 0.8 * Math.max(a.gemelo, a.final * 0); o.rotation.z += o.userData.v * dt; o.visible = a.gemelo > 0.01; });

  // el cierre: el corazón, de holograma
  a.final = s(a.final, modo === 'final' ? 1 : 0, 2, dt);
  for (const f of final) { f.material.uniforms.uOp.value = 0.9 * a.final; f.visible = a.final > 0.01; }

  // la sombra, debajo de lo que haya
  const hay = Math.max(a.cerebro, sim && etapa >= 1 && etapa !== 5 ? 1 : 0) * (modo === 'final' ? 0 : 1);
  a.sombra = s(a.sombra, hay, 3, dt);
  sombra.material.opacity = 0.8 * a.sombra;
  sombra.position.set(modo === 'cerebro' ? a.x * 1.3 : a.x, modo === 'cerebro' ? -0.98 : sim && etapa >= 2 ? -1.02 : -caja.alto / 2 - 0.12, 0);
  sombra.scale.setScalar(modo === 'cerebro' ? 0.62 : sim && etapa >= 2 ? 0.7 : 0.85);
  sombra.visible = a.sombra > 0.01;

  renderer.render(escena, camara);
  requestAnimationFrame(fotograma);
}

// ---------------------------------------------------------------- arranque
export const lista = (async () => {
  requestAnimationFrame(fotograma);
  const [tx, cb] = await Promise.all([paquete('torax'), paquete('cerebro')]);

  // el cerebro, a 2,1 de alto
  {
    const g = cb[0].geo, b = g.boundingBox, tam = b.getSize(new THREE.Vector3()), c = b.getCenter(new THREE.Vector3());
    cerebro = new THREE.Mesh(g, arcilla(0xeba896, 0));
    const e = 1.9 / Math.max(tam.x, tam.y, tam.z);
    cerebro.scale.setScalar(e);
    cerebro.position.copy(c).multiplyScalar(-e);
    pCerebro.add(cerebro);
  }

  // el tórax, a 2,5 de alto, y dónde queda el corazón
  const todo = new THREE.Box3(), cor = new THREE.Box3();
  for (const p of tx) todo.union(p.geo.boundingBox);
  // La pieza es el corazón con el arranque de sus vasos: de cada vaso se quedan los triángulos que caen cerca de él.
  const bc = tx.find(p => p.clave === 'heart').geo.boundingBox, tc = bc.getSize(new THREE.Vector3());
  const cerca = new THREE.Box3(new THREE.Vector3(bc.min.x - 0.3 * tc.x, bc.min.y + 0.04 * tc.y, bc.min.z - 0.6 * tc.z),
    new THREE.Vector3(bc.max.x + 0.3 * tc.x, bc.max.y + 0.62 * tc.y, bc.max.z + 0.6 * tc.z));
  const recortes = new Map();
  for (const p of tx) {
    if (!DEL_CORAZON.has(p.clave)) continue;
    const pos = p.geo.getAttribute('position'), idx = p.geo.index.array, dentro = [], v = new THREE.Vector3();
    const entero = p.clave === 'heart' || p.clave === 'atrial_appendage_left';
    for (let i = 0; i < idx.length; i += 3) {
      v.set(0, 0, 0);
      for (let k = 0; k < 3; k++) { v.x += pos.getX(idx[i + k]) / 3; v.y += pos.getY(idx[i + k]) / 3; v.z += pos.getZ(idx[i + k]) / 3; }
      if (entero || cerca.containsPoint(v)) { dentro.push(idx[i], idx[i + 1], idx[i + 2]); cor.expandByPoint(v); }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', pos);                 // (las mismas posiciones: se mueven con las de la estructura entera)
    g.setIndex(new THREE.BufferAttribute(new Uint16Array(dentro), 1));
    g.computeVertexNormals();
    recortes.set(p.clave, g);
  }
  const tam = todo.getSize(new THREE.Vector3()), tamCor = cor.getSize(new THREE.Vector3());
  caja.escala = 2.3 / tam.y;
  caja.alto = 2.3;
  todo.getCenter(caja.centro);
  cor.getCenter(caja.centroCorazon);
  caja.escalaCorazon = 1.7 / Math.max(tamCor.x, tamCor.y, tamCor.z);
  for (const p of tx) {
    const corazon = DEL_CORAZON.has(p.clave);
    const color = colorDe(p.clave, p.grupo);
    const m = new THREE.Mesh(p.geo, arcilla(color, 0));
    m.visible = false;
    // (cada estructura crece desde su centro, no desde el del cuerpo)
    const c = p.geo.boundingBox.getCenter(new THREE.Vector3());
    p.geo.translate(-c.x, -c.y, -c.z);
    m.position.copy(c);
    contenido.add(m);
    partes.push({ clave: p.clave, malla: m, base: opacidadDe(p.clave, p.grupo), y: (c.y - caja.centro.y) * caja.escala, corazon, color });
    if (corazon) {
      const vaso = p.clave !== 'heart' && p.clave !== 'atrial_appendage_left';
      const corta = recortes.get(p.clave);
      const r = new THREE.Mesh(corta, arcilla(ARCILLA, 0));
      r.material.clippingPlanes = [planoColada];
      r.position.copy(c);
      r.userData.vaso = vaso;
      r.visible = false;
      contenido.add(r);
      relleno.push(r);
      const g = new THREE.Mesh(corta, holograma(0x7a3fe0, false));
      g.position.copy(c);
      g.visible = false;
      g.renderOrder = 3;
      contenido.add(g);
      gemelo.push(g);
      const f = new THREE.Mesh(corta, holograma(vaso ? 0xcdb5f5 : 0x9a6cff, true));
      f.position.copy(c);
      f.visible = false;
      contenido.add(f);
      final.push(f);
      if (p.clave === 'heart') {
        mallaAlambre = new THREE.LineSegments(new THREE.WireframeGeometry(p.geo), new THREE.LineBasicMaterial({ color: MORADO, transparent: true, opacity: 0 }));
        mallaAlambre.position.copy(c);
        mallaAlambre.scale.setScalar(1.004);
        mallaAlambre.visible = false;
        contenido.add(mallaAlambre);
      }
    }
  }
  hacerMolde(tamCor.x * caja.escalaCorazon + 0.3, tamCor.y * caja.escalaCorazon + 0.3, tamCor.z * caja.escalaCorazon + 0.3);
  window.__escenaLista = true;
})();
