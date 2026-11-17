// La escena 3D que va detrás de las diapositivas. Es un cerebro real: lo hizo MRAnalyzer con la resonancia pública
// «MRHead» de 3D Slicer, y sus 27 secciones las separó la red SynthSeg. No es un paciente.
//   - Portada: el cerebro, girando.
//   - Simulación: los cortes de la resonancia se comprimen y de ese bloque sale el cerebro, sección a sección; después
//     pasa a malla, se cierra el molde, se cuela la silicona y aparece el gemelo digital con lo que lleva dentro.
//   - Cierre: el cerebro como holograma.
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

const MORADO = 0x6422b8, ARCILLA = 0xf3f1ec, ESCALA = 0.92;

// ---------------------------------------------------------------- el paquete de mallas (posiciones e índices en 16 bits)
async function paquete(nombre) {
  const datos = JSON.parse(new TextDecoder().decode(await bytes(`modelos/${nombre}.json`)));
  const bin = await bytes(`modelos/${nombre}.bin`);
  datos.mallas = datos.mallas.map(p => {
    const q = new Uint16Array(bin, p.pos[0], p.pos[1] * 3);
    const pos = new Float32Array(q.length);
    for (let i = 0; i < q.length; i++) pos[i] = p.min[i % 3] + q[i] / 65535 * p.tam[i % 3];
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setIndex(new THREE.BufferAttribute(new Uint16Array(bin, p.idx[0], p.idx[1]), 1));
    g.computeVertexNormals();
    return { ...p, geo: g };
  });
  return datos;
}

function arcilla(color, opacidad = 1) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0, transparent: true, opacity: opacidad });
}
// El holograma: se ve el canto y unas bandas que suben. «suma» para fondo oscuro; sin ella, para fondo claro.
const tiempo = { value: 0 };
function holograma(color, suma) {
  return new THREE.ShaderMaterial({
    uniforms: { uTiempo: tiempo, uColor: { value: new THREE.Color(color) }, uOp: { value: 0 }, uBanda: { value: suma ? 0.16 : 0.5 } },
    vertexShader: `varying vec3 vN; varying vec3 vV; varying vec3 vW;
      void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; vN = normalize(mat3(modelMatrix) * normal);
        vV = normalize(cameraPosition - w.xyz); gl_Position = projectionMatrix * viewMatrix * w; }`,
    fragmentShader: `uniform vec3 uColor; uniform float uOp; uniform float uTiempo; uniform float uBanda; varying vec3 vN; varying vec3 vV; varying vec3 vW;
      void main() { float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 2.0);
        float bandas = 0.75 + 0.25 * sin(vW.y * 90.0 - uTiempo * 4.0);
        float barrido = smoothstep(0.06, 0.0, abs(fract(vW.y * 0.45 - uTiempo * 0.22) - 0.5));
        gl_FragColor = vec4(uColor * (0.55 + 0.9 * f) + vec3(barrido * uBanda), clamp((0.10 + 0.9 * f) * bandas + barrido * uBanda, 0.0, 1.0) * uOp); }`,
    transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: suma ? THREE.AdditiveBlending : THREE.NormalBlending,
  });
}

// ---------------------------------------------------------------- lo que hay en la escena
const pivote = new THREE.Group();          // el cerebro de la simulación y del cierre (lo que gira)
escena.add(pivote);
const pCerebro = new THREE.Group();        // el de la portada
escena.add(pCerebro);
let cerebro = null, pieza = null, alambre = null, gemelo = null, final = null;
const secciones = [];                      // { malla, capa, centro (su altura media), color }
const dentroFinal = [];
const planoBarrido = new THREE.Plane(new THREE.Vector3(0, -1, 0), 10);    // (se ve lo que queda por debajo)
const planoColada = new THREE.Plane(new THREE.Vector3(0, -1, 0), 10);
const forma = { alto: 1.44 * ESCALA, lado: 2.3, altoCortes: 1.3 };

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

// los cortes de la resonancia (un cuadrado de lado 1: se le da el tamaño al cargar el cerebro)
const pila = new THREE.Group();
escena.add(pila);
const cortes = [];
const cargador = new THREE.TextureLoader();
// (en la malla, x va de la nuca a la frente y z de izquierda a derecha: el corte se tumba y se gira para coincidir)
const tumbado = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(
  new THREE.Vector3(0, 0, 1), new THREE.Vector3(-1, 0, 0), new THREE.Vector3(0, -1, 0)));
for (let i = 0; i < 14; i++) {
  const tex = cargador.load(ruta(`img/corte_${String(i).padStart(2, '0')}.webp`));
  tex.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(1, 1),
    new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
  const marco = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(1, 1)),
    new THREE.LineBasicMaterial({ color: MORADO, transparent: true, opacity: 0 }));
  m.add(marco);
  m.userData.marco = marco;
  pila.add(m);
  cortes.push(m);
}
// el plano que barre el modelo mientras se segmenta
const barrido = new THREE.Mesh(new THREE.PlaneGeometry(3.3, 3.3), new THREE.ShaderMaterial({
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
for (const [r, arco, v] of [[1.12, Math.PI * 1.4, 0.5], [1.24, Math.PI * 0.5, -0.9], [1.0, Math.PI * 0.25, 1.4]]) {
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
const a = { pila: 0, sep: 1, cerebro: 0, alambre: 0, molde: 0, cierre: 0, tornillos: 0, pieza: 0, gemelo: 0, final: 0, sombra: 0, x: 1.0, barrido: 0 };
let vistas = -1;
const SUBE_EN = 5.2;        // segundos que tarda el barrido en recorrer el cerebro
const ABRE_EN = 7.0;        // cuándo se aclara lo de fuera para enseñar lo de dentro

export function irA(m) { if (m !== modo) { modo = m; tModo = 0; } if (m !== 'sim') ponEtapa(-1); }
// Con «sola», la simulación pasa de etapa por su cuenta, con el reloj de la propia escena (lo que dura cada una).
const DURA = [3.4, 9.5, 5.2, 4.6, 6.6];
let sola = false, alEtapa = () => {};
export function escucharEtapa(f) { alEtapa = f; }
export function ponEtapa(n, auto = false) {
  etapa = n; tEtapa = 0; vistas = -1; sola = auto;
  if (n < 1) alContar(0, secciones.length);
  if (n >= 2) alContar(secciones.length, secciones.length);
}
export function escucharCuenta(f) { alContar = f; }

const reloj = new THREE.Clock();
const s = (v, obj, k, dt) => v + (obj - v) * (1 - Math.exp(-k * dt));
const suave = x => { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x); };
const camObj = new THREE.Vector3(), miraObj = new THREE.Vector3();
const colorTmp = new THREE.Color(), giroTmp = new THREE.Quaternion(), ejeY = new THREE.Vector3(0, 1, 0);

function fotograma() {
  const dt = Math.min(reloj.getDelta(), exportar ? 1.5 : 0.1);
  const t = reloj.elapsedTime;
  tiempo.value = t;
  tEtapa += dt;
  tModo += dt;
  const sim = modo === 'sim';
  if (sim && sola && etapa >= 0 && etapa < DURA.length && tEtapa > DURA[etapa]) { ponEtapa(etapa + 1, true); alEtapa(etapa); }

  // la cámara y dónde se pone el modelo (a la derecha del texto)
  if (sim && etapa <= 0) camObj.set(0, 1.9, 5.1); else if (sim && etapa === 1) camObj.set(0, 1.5, 4.9); else camObj.set(0, 0.28, 4.8);
  miraObj.set(0, 0, 0);
  camara.position.x = s(camara.position.x, camObj.x, 2, dt);
  camara.position.y = s(camara.position.y, camObj.y, 2, dt);
  camara.position.z = s(camara.position.z, camObj.z, 2, dt);
  mirarA.lerp(miraObj, 1 - Math.exp(-2.2 * dt));
  camara.lookAt(mirarA);
  const ancho = Math.tan(THREE.MathUtils.degToRad(19)) * 5 * camara.aspect;      // (media anchura visible a 5 de distancia)
  a.x = s(a.x, (modo === 'final' ? 0.46 : 0.40) * ancho, 3, dt);

  // ---- portada: el cerebro
  a.cerebro = s(a.cerebro, modo === 'cerebro' ? 1 : 0, 3, dt);
  pCerebro.position.set(a.x * 1.3, 0.05 + Math.sin(t * 0.8) * 0.03, 0);
  pCerebro.rotation.y += 0.22 * dt;
  if (cerebro) {
    cerebro.material.opacity = a.cerebro;
    cerebro.visible = a.cerebro > 0.01;
    if (modo === 'cerebro') pCerebro.scale.setScalar(0.86 + 0.14 * suave(Math.min(1, tModo / 1.6)));
  }

  // ---- simulación
  pivote.position.set(a.x, 0, 0);
  pivote.rotation.y += (sim && etapa === 1 ? 0.2 : sim && (etapa === 3 || etapa === 4) ? 0.1 : 0.22) * dt;

  // Los cortes: separados en «imagen». Al segmentar se comprimen en un bloque, que sube con el barrido: de él va saliendo
  // el modelo, y al llegar arriba se apaga.
  const abajo = -forma.alto / 2 - 0.08, arriba = forma.alto / 2 + 0.08;
  const nivel = abajo + Math.max(0, tEtapa - 1.2) * (arriba - abajo) / SUBE_EN;
  a.pila = s(a.pila, sim && etapa <= 1 ? 1 : 0, 3, dt);
  a.sep = s(a.sep, sim && etapa >= 1 ? 0.0 : 1, sim && etapa >= 1 ? 0.9 : 3, dt);
  const yPila = sim && etapa === 1 ? Math.min(nivel, arriba) * (1 - a.sep) : 0;
  const quita = sim && etapa === 1 ? 1 - suave((nivel - (arriba - 0.2)) / 0.3) : sim && etapa >= 2 ? 0 : 1;
  giroTmp.setFromAxisAngle(ejeY, pivote.rotation.y);
  cortes.forEach((c, i) => {
    c.position.set(a.x, yPila + (i - 6.5) * (0.012 + (forma.altoCortes * 1.25 / 13 - 0.012) * a.sep), 0);
    c.quaternion.copy(giroTmp).multiply(tumbado);
    c.scale.setScalar(forma.lado);
    const op = a.pila * quita * suave((tModo - i * 0.05) / 0.8);
    c.material.opacity = (0.55 + 0.38 * a.sep) * op;
    c.userData.marco.material.opacity = 0.7 * op;
    c.visible = op > 0.01;
  });
  a.barrido = s(a.barrido, sim && etapa === 1 && tEtapa > 1.0 && nivel < arriba ? 1 : 0, 5, dt);
  barrido.material.uniforms.uOp.value = a.barrido;
  barrido.position.set(a.x, sim && etapa === 1 ? Math.min(nivel, arriba) : arriba, 0);
  barrido.visible = a.barrido > 0.01;

  // las secciones: salen por debajo del barrido; después lo de fuera se queda casi transparente y se ven los núcleos y
  // los ventrículos
  planoBarrido.constant = sim && etapa === 1 ? Math.min(nivel, arriba + 1) : 10;
  const abierto = sim && etapa === 1 && tEtapa > ABRE_EN;
  let n = 0;
  for (const p of secciones) {
    let obj = 0, color = p.color;
    if (sim && etapa === 1) { obj = abierto && p.capa < 2 ? 0.13 : 1; if (p.centro < nivel) n++; }
    else if (sim && etapa === 5) { obj = p.capa === 2 ? 1 : 0; color = MORADO; }
    const m = p.malla.material;
    m.opacity = s(m.opacity, obj, obj > 0 ? 6 : 3, dt);
    m.color.lerp(colorTmp.set(color), 1 - Math.exp(-3 * dt));
    m.depthWrite = m.opacity > 0.9;
    p.malla.visible = m.opacity > 0.01;
  }
  if (sim && etapa === 1 && n !== vistas) { vistas = n; alContar(n, secciones.length); }

  // el modelo 3D: la malla, a la vista un momento
  a.alambre = s(a.alambre, sim && etapa === 2 && tEtapa > 0.6 && tEtapa < 3.6 ? 1 : 0, 4, dt);
  if (alambre) { alambre.material.opacity = 0.3 * a.alambre; alambre.visible = a.alambre > 0.01; }

  // el molde: se cierra en «molde» y se abre al acabar la colada
  const cerrado = sim && etapa === 3 ? suave((tEtapa - 0.3) / 2.2) : sim && etapa === 4 ? 1 - suave((tEtapa - 3.6) / 1.6) : 0;
  a.molde = s(a.molde, sim && (etapa === 3 || (etapa === 4 && tEtapa < 5)) ? 1 : 0, 4, dt);
  a.cierre = s(a.cierre, cerrado, 8, dt);
  a.tornillos = s(a.tornillos, cerrado > 0.97 ? 1 : 0, 6, dt);
  if (molde.userData.w) {
    const u = molde.userData;
    molde.position.set(a.x, 0, 0);
    molde.rotation.y = pivote.rotation.y;
    for (const m of mitades) m.position.x = m.userData.lado * (u.w / 4 + (1 - a.cierre) * 0.75);
    u.vidrio.opacity = 0.22 * a.molde;
    u.borde.opacity = 0.9 * a.molde;
    u.metal.opacity = a.tornillos * a.molde;
    tornillos.visible = u.metal.opacity > 0.02;
    molde.visible = a.molde > 0.01;
    // la colada: la silicona sube dentro del molde
    const sube = sim && etapa === 4 ? suave((tEtapa - 0.4) / 2.8) : 1;
    planoColada.constant = -u.h / 2 + sube * (u.h + 0.05);
    aros.position.set(a.x, -u.h / 2 + 0.02, 0);
  }
  // la pieza: el cerebro entero, de arcilla primero y de silicona después
  a.pieza = s(a.pieza, sim && etapa >= 2 ? (etapa === 5 ? 0.3 : 1) : 0, 4, dt);
  if (pieza) {
    const curada = sim && etapa === 4 ? suave((tEtapa - 3.0) / 1.5) : 1;
    pieza.material.opacity = a.pieza;
    colorTmp.set(sim && etapa >= 4 ? 0xf6f4ef : ARCILLA);
    if (sim && etapa === 4) pieza.material.color.set(0xc9b3f5).lerp(colorTmp, curada);
    else pieza.material.color.lerp(colorTmp, 1 - Math.exp(-3 * dt));
    pieza.material.depthWrite = a.pieza > 0.9;
    pieza.visible = a.pieza > 0.01;
  }
  // el gemelo digital
  a.gemelo = s(a.gemelo, sim && etapa === 5 ? 1 : 0, 2.5, dt);
  if (gemelo) { gemelo.material.uniforms.uOp.value = 0.8 * a.gemelo; gemelo.visible = a.gemelo > 0.01; gemelo.scale.setScalar(1.03 + 0.008 * Math.sin(t * 2)); }
  aros.children.forEach(o => { o.material.opacity = 0.8 * a.gemelo; o.rotation.z += o.userData.v * dt; o.visible = a.gemelo > 0.01; });

  // el cierre: el cerebro, de holograma, con lo de dentro encendido
  a.final = s(a.final, modo === 'final' ? 1 : 0, 2, dt);
  if (final) { final.material.uniforms.uOp.value = 0.85 * a.final; final.visible = a.final > 0.01; }
  for (const f of dentroFinal) { f.material.opacity = 0.28 * a.final; f.visible = a.final > 0.01; }

  // la sombra, debajo de lo que haya
  const hay = Math.max(a.cerebro, sim && etapa >= 1 && etapa !== 5 ? 1 : 0) * (modo === 'final' ? 0 : 1);
  a.sombra = s(a.sombra, hay, 3, dt);
  sombra.material.opacity = 0.8 * a.sombra;
  sombra.position.set(modo === 'cerebro' ? a.x * 1.3 : a.x, modo === 'cerebro' ? -0.86 : -forma.alto / 2 - 0.16, 0);
  sombra.scale.setScalar(modo === 'cerebro' ? 0.62 : 0.8);
  sombra.visible = a.sombra > 0.01;

  renderer.render(escena, camara);
  requestAnimationFrame(fotograma);
}

// ---------------------------------------------------------------- arranque
export const lista = (async () => {
  requestAnimationFrame(fotograma);
  const datos = await paquete('cerebro');
  forma.lado = datos.lado_cortes * ESCALA;
  forma.altoCortes = datos.alto_cortes * ESCALA;
  const entero = datos.mallas.find(p => p.clave === 'cerebro');
  forma.alto = entero.tam[1] * ESCALA;

  cerebro = new THREE.Mesh(entero.geo, arcilla(0xeba896, 0));
  cerebro.scale.setScalar(0.95);
  pCerebro.add(cerebro);

  pivote.scale.setScalar(ESCALA);
  for (const p of datos.mallas) {
    if (p.clave === 'cerebro') continue;
    const m = new THREE.Mesh(p.geo, new THREE.MeshStandardMaterial({ color: p.color, roughness: 0.62, transparent: true, opacity: 0,
      side: THREE.DoubleSide, clippingPlanes: [planoBarrido] }));
    m.visible = false;
    m.renderOrder = 2 - p.capa;      // (lo de dentro, antes: así se ve a través de lo que se está apagando)
    pivote.add(m);
    secciones.push({ malla: m, capa: p.capa, centro: (p.min[1] + p.tam[1] / 2) * ESCALA, color: p.color });
    if (p.capa === 2) {
      const f = new THREE.Mesh(p.geo, new THREE.MeshBasicMaterial({ color: 0xcdb5f5, transparent: true, opacity: 0, depthWrite: false,
        blending: THREE.AdditiveBlending }));
      f.visible = false;
      pivote.add(f);
      dentroFinal.push(f);
    }
  }
  pieza = new THREE.Mesh(entero.geo, arcilla(ARCILLA, 0));
  pieza.material.clippingPlanes = [planoColada];
  pieza.visible = false;
  pieza.renderOrder = 3;
  alambre = new THREE.LineSegments(new THREE.WireframeGeometry(entero.geo), new THREE.LineBasicMaterial({ color: MORADO, transparent: true, opacity: 0 }));
  alambre.scale.setScalar(1.003);
  alambre.visible = false;
  gemelo = new THREE.Mesh(entero.geo, holograma(0x7a3fe0, false));
  gemelo.visible = false;
  gemelo.renderOrder = 4;
  final = new THREE.Mesh(entero.geo, holograma(0x9a6cff, true));
  final.visible = false;
  pivote.add(pieza, alambre, gemelo, final);
  hacerMolde(entero.tam[0] * ESCALA + 0.24, entero.tam[1] * ESCALA + 0.24, entero.tam[2] * ESCALA + 0.24);
  window.__escenaLista = true;
})();
