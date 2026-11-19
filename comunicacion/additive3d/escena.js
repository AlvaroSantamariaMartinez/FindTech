// La escena 3D que va detrás de las diapositivas. Nada es de un paciente:
//   - el cerebro es real: lo hizo MRAnalyzer con la resonancia pública «MRHead» de 3D Slicer, y sus secciones las separó
//     la red SynthSeg;
//   - el torso sale del TAC de tórax público «CTChest» de 3D Slicer, segmentado con TotalSegmentator
//     (herramientas/torso.py).
// Lo que se ve:
//   - Portada: el cerebro, girando.
//   - Simulación: los cortes del TAC se comprimen y de ese bloque sale el torso, estructura a estructura; después pasa
//     a malla, se cierra el molde, se cuela la silicona y aparece el gemelo digital con lo que lleva dentro.
//   - Realidad mixta: unas gafas escanean el torso, el gemelo digital encaja encima y se encienden sus vasos.
//   - Cierre: un avión de pasajeros da vueltas al coxis de la pelvis y, al final, el cerebro como holograma.
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
const pivote = new THREE.Group();          // el torso de la simulación (lo que gira)
escena.add(pivote);
const pivoteFinal = new THREE.Group();     // el cerebro del cierre (gira con él)
escena.add(pivoteFinal);
const pCerebro = new THREE.Group();        // el de la portada
escena.add(pCerebro);
let cerebro = null, pieza = null, alambre = null, gemelo = null, final = null;
const secciones = [];                      // { malla, capa, centro (su altura media), color }
const dentroFinal = [];
const planoBarrido = new THREE.Plane(new THREE.Vector3(0, -1, 0), 10);    // (se ve lo que queda por debajo)
const planoColada = new THREE.Plane(new THREE.Vector3(0, -1, 0), 10);
// la ventana del torso: quita lo que queda por delante de z = constante (la piel, el esternón y la parte de delante de las
// costillas) para que se vean los pulmones, los órganos y el hueco del tórax
const planoCorte = new THREE.Plane(new THREE.Vector3(0, 0, -1), 10);
const ABIERTOS = ['costillas', 'esternon', 'cintura'];
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
const a = { corte: 1.2, pila: 0, sep: 1, cerebro: 0, alambre: 0, molde: 0, cierre: 0, tornillos: 0, pieza: 0, gemelo: 0, final: 0, sombra: 0, x: 1.0, barrido: 0 };
let vistas = -1;
const SUBE_EN = 5.2;        // segundos que tarda el barrido en recorrer el cerebro
const ABRE_EN = 7.0;        // cuándo se aclara lo de fuera para enseñar lo de dentro

export function irA(m) { if (m !== modo) { modo = m; tModo = 0; } if (m !== 'sim') ponEtapa(-1); }
export function ponEtapa(n) {
  etapa = n; tEtapa = 0; vistas = -1;
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
  pivoteFinal.position.copy(pivote.position);
  pivoteFinal.rotation.y = pivote.rotation.y;

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

  // las estructuras: salen por debajo del barrido (la piel, medio transparente, para que se vea lo de dentro); después lo
  // de fuera se queda casi transparente y se ven el corazón, los vasos y la tráquea
  planoBarrido.constant = sim && etapa === 1 ? Math.min(nivel, arriba + 1) : 10;
  const abierto = sim && etapa === 1 && tEtapa > ABRE_EN;
  let n = 0;
  for (const p of secciones) {
    let obj = 0, color = p.color;
    if (sim && etapa === 1) { obj = p.capa === 0 ? (abierto ? 0.06 : 0.3) : abierto && p.capa < 2 ? 0.13 : 1; if (p.centro < nivel) n++; }
    else if (sim && etapa >= 2 && etapa <= 4) obj = p.capa === 0 ? 0 : 1;          // (dentro de la pieza abierta)
    else if (sim && etapa === 5) { obj = p.capa === 2 ? 1 : p.capa === 1 ? 0.3 : 0; color = p.capa === 2 ? MORADO : 0xb79cf0; }
    const m = p.malla.material;
    m.opacity = s(m.opacity, obj, obj > 0 ? 6 : 3, dt);
    m.color.lerp(colorTmp.set(color), 1 - Math.exp(-3 * dt));
    m.depthWrite = m.opacity > 0.9;
    p.malla.visible = m.opacity > 0.01;
  }
  if (sim && etapa === 1 && n !== vistas) { vistas = n; alContar(n, secciones.length); }

  // la ventana: se abre al pasar a modelo 3D y se cierra en el gemelo
  a.corte = s(a.corte, sim && etapa >= 2 && etapa <= 4 ? 0.12 : 1.2, 2, dt);
  planoCorte.constant = a.corte;
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

  mixtaFotograma(dt, ancho);
  avionFotograma(dt, t);
  renderer.render(escena, camara);
  requestAnimationFrame(fotograma);
}


// ---------------------------------------------------------------- realidad mixta (diapositiva «mixta»)
// Unas gafas escanean un cerebro real; su gemelo digital (la malla del mismo cerebro) llega, encaja encima y se
// dibujan, brillando, las venas que MRAnalyzer traza por sus surcos. Fases: 0 escaneo, 1 gemelo, 2 venas.
const mx = { grupo: new THREE.Group(), real: null, puntos: null, gemelo: null, red: null, venas: null, op: 0, fase: -1,
  gafas: new THREE.Group(), haz: null, anillo: null, onda: null, mats: [] };
escena.add(mx.grupo, mx.gafas);
let alFase = () => {};
export function escucharFase(f) { alFase = f; }
const MX = { escaneo: [1.3, 4.9], llega: [4.9, 7.1], venas: [7.4, 11.6] };
const TAM_MX = 0.78;      // (el torso, más pequeño que en la simulación: así no choca con las gafas)

function rectRedondo(forma, x, y, w, h, r) {
  forma.moveTo(x + r, y); forma.lineTo(x + w - r, y); forma.quadraticCurveTo(x + w, y, x + w, y + r);
  forma.lineTo(x + w, y + h - r); forma.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  forma.lineTo(x + r, y + h); forma.quadraticCurveTo(x, y + h, x, y + h - r);
  forma.lineTo(x, y + r); forma.quadraticCurveTo(x, y, x + r, y);
  return forma;
}
// Las gafas: unas Meta Quest 3, mirando hacia +z. Carcasa blanca con el frente en blanco y las tres «pastillas» negras
// verticales (las de los lados con dos cámaras cada una; la del medio, con el sensor de profundidad), las dos cámaras de
// las esquinas de abajo, la almohadilla oscura, los brazos laterales y la cinta de tela gris por detrás.
function hacerGafas() {
  const m = o => { const x = new THREE.MeshPhysicalMaterial({ transparent: true, opacity: 0, ...o }); mx.mats.push(x); return x; };
  const carcasa = m({ color: 0xf3f4f6, roughness: 0.38, clearcoat: 0.55, clearcoatRoughness: 0.3 });
  const negro = m({ color: 0x0b0c10, roughness: 0.1, metalness: 0.3, clearcoat: 1, clearcoatRoughness: 0.03 });
  const lente = m({ color: 0x4a5160, roughness: 0.03, metalness: 0.85, clearcoat: 1 });
  const almohadilla = m({ color: 0x2b2e34, roughness: 0.9 });
  const tela = m({ color: 0x8a8f96, roughness: 0.95 });
  const brazo = m({ color: 0xe4e6e9, roughness: 0.45 });
  const g = mx.gafas;
  // el cuerpo: ancho, poco alto y con los cantos muy redondeados; el frente, algo más estrecho (se afila hacia delante)
  const cuerpo = new THREE.ExtrudeGeometry(rectRedondo(new THREE.Shape(), -0.47, -0.17, 0.94, 0.34, 0.16),
    { depth: 0.2, bevelEnabled: true, bevelThickness: 0.07, bevelSize: 0.06, bevelSegments: 8, curveSegments: 24 });
  cuerpo.translate(0, 0, -0.1);
  g.add(new THREE.Mesh(cuerpo, carcasa));
  const z = 0.172;   // (la cara de delante)
  // las tres pastillas
  for (const [x, alto, ancho] of [[-0.25, 0.2, 0.085], [0, 0.16, 0.07], [0.25, 0.2, 0.085]]) {
    const p = new THREE.Mesh(new THREE.ShapeGeometry(rectRedondo(new THREE.Shape(), -ancho / 2, -alto / 2, ancho, alto, ancho / 2), 16), negro);
    p.position.set(x, 0.005, z);
    g.add(p);
    const camaras = x === 0 ? [[0, 0.03, 0.018], [0, -0.035, 0.01]] : [[0, 0.045, 0.024], [0, -0.045, 0.024]];
    for (const [cx, cy, r] of camaras) {
      const c = new THREE.Mesh(new THREE.CircleGeometry(r, 24), lente);
      c.position.set(x + cx, 0.005 + cy, z + 0.002);
      g.add(c);
    }
  }
  // las cámaras de las esquinas de abajo, mirando un poco hacia abajo y hacia fuera
  for (const lado of [-1, 1]) {
    const c = new THREE.Mesh(new THREE.CircleGeometry(0.02, 20), negro);
    c.position.set(lado * 0.4, -0.15, z - 0.03);
    c.rotation.set(0.5, lado * 0.45, 0);
    g.add(c);
  }
  const led = new THREE.Mesh(new THREE.PlaneGeometry(0.42, 0.01), new THREE.MeshBasicMaterial({ color: 0xb48cff, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
  mx.led = led;   // (sin luz a la vista: las Quest 3 no la llevan; se queda para no tocar el resto)
  // la almohadilla de la cara
  const cara = new THREE.ExtrudeGeometry(rectRedondo(new THREE.Shape(), -0.42, -0.14, 0.84, 0.28, 0.13), { depth: 0.1, bevelEnabled: true, bevelThickness: 0.02, bevelSize: 0.02, bevelSegments: 3, curveSegments: 16 });
  cara.translate(0, 0, -0.29);
  g.add(new THREE.Mesh(cara, almohadilla));
  // los brazos laterales (rígidos, del color de la carcasa) y la cinta de tela que da la vuelta por detrás
  for (const lado of [-1, 1]) {
    const b = new THREE.Mesh(new THREE.BoxGeometry(0.045, 0.1, 0.32), brazo);
    b.position.set(lado * 0.5, 0.0, -0.3);
    b.rotation.y = lado * -0.12;
    g.add(b);
  }
  const cinta = new THREE.TorusGeometry(0.5, 0.03, 8, 64, Math.PI);
  cinta.rotateX(-Math.PI / 2);
  cinta.scale(1.04, 2.0, 1.15);
  cinta.translate(0, 0, -0.44);
  g.add(new THREE.Mesh(cinta, tela));
  g.scale.setScalar(0.85);
}

function prepararMixta(geoCerebro, geoAlambre, vasos, dentro) {
  const real = new THREE.Mesh(geoCerebro, new THREE.MeshStandardMaterial({ color: 0xd9a097, roughness: 0.55,
    emissive: 0x7a3fe0, emissiveIntensity: 0, transparent: true }));
  mx.real = real;
  real.renderOrder = 3;
  // lo de dentro: costillas, columna, pulmones y órganos (los vasos grandes van aparte, encendidos)
  const VASOS = ['aorta', 'troncos', 'venas_pulmonares', 'cavas'];
  const HUESOS = ['costillas', 'esternon', 'columna', 'cintura'];
  mx.dentro = dentro.filter(p => !VASOS.includes(p.clave)).map(p => {
    const m = new THREE.Mesh(p.geo, new THREE.MeshStandardMaterial({ color: p.color, roughness: 0.6, transparent: true, opacity: 0,
      depthWrite: false, side: THREE.DoubleSide }));
    m.userData.base = HUESOS.includes(p.clave) ? 0.95 : p.clave.startsWith('pulmon') ? 0.3 : 0.85;
    m.renderOrder = p.clave.startsWith('pulmon') ? 2 : 1;
    m.visible = false;
    mx.grupo.add(m);
    return m;
  });
  geoCerebro.computeBoundingBox();
  mx.arriba = geoCerebro.boundingBox.max.y;
  mx.abajo = geoCerebro.boundingBox.min.y;
  mx.grupo.add(real);
  // los puntos del escaneo: los vértices del torso, encendidos donde pasa el barrido
  mx.puntos = new THREE.Points(geoCerebro, new THREE.ShaderMaterial({
    uniforms: { uFrente: { value: 2 }, uOp: { value: 0 }, uTiempo: tiempo },
    vertexShader: `uniform float uFrente; varying float vB; varying float vY;
      void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_Position = projectionMatrix * mv;
        vY = position.y; vB = exp(-pow((position.y - uFrente) / 0.06, 2.0)); gl_PointSize = (1.8 + 4.0 * vB) * (3.0 / -mv.z); }`,
    fragmentShader: `uniform float uFrente; uniform float uOp; varying float vB; varying float vY;
      void main(){ vec2 c = gl_PointCoord - 0.5; if (length(c) > 0.5) discard;
        float hecho = step(uFrente, vY) * 0.32;
        gl_FragColor = vec4(mix(vec3(0.62, 0.42, 1.0), vec3(1.0), vB), (hecho + vB) * uOp); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  mx.grupo.add(mx.puntos);
  // el anillo que acompaña al barrido
  mx.anillo = new THREE.Mesh(new THREE.RingGeometry(1.08, 1.1, 128), new THREE.MeshBasicMaterial({ color: 0xc9a8ff, transparent: true, opacity: 0,
    side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }));
  mx.anillo.rotation.x = -Math.PI / 2;
  escena.add(mx.anillo);
  // el gemelo digital: holograma y malla
  mx.gemelo = new THREE.Mesh(geoCerebro, holograma(0x9a6cff, true));
  mx.red = new THREE.LineSegments(geoAlambre, new THREE.LineBasicMaterial({ color: 0xb48cff, transparent: true, opacity: 0,
    blending: THREE.AdditiveBlending, depthWrite: false }));
  mx.gemeloG = new THREE.Group();
  mx.gemeloG.add(mx.gemelo, mx.red);
  escena.add(mx.gemeloG);
  // la onda del encaje
  mx.onda = new THREE.Mesh(new THREE.RingGeometry(0.98, 1.0, 128), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0,
    side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }));
  escena.add(mx.onda);
  // el haz de las gafas
  mx.haz = new THREE.Mesh(new THREE.ConeGeometry(1, 1, 64, 1, true), new THREE.ShaderMaterial({
    uniforms: { uOp: { value: 0 }, uTiempo: tiempo },
    vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: `uniform float uOp; uniform float uTiempo; varying vec2 vUv;
      void main(){ float lineas = 0.55 + 0.45 * step(0.5, fract(vUv.x * 40.0));
        float ondas = 0.6 + 0.4 * sin(vUv.y * 40.0 + uTiempo * 9.0);
        float a = (0.05 + 0.2 * (1.0 - vUv.y)) * lineas * ondas;
        gl_FragColor = vec4(0.7, 0.5, 1.0, a * uOp); }`,
    transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending }));
  escena.add(mx.haz);
  // los vasos: su superficie, con la distancia de cada vértice al corazón (0–1); se dibujan creciendo hasta uFrente
  const q = new Uint16Array(vasos.bin, vasos.datos.pos[0], vasos.datos.pos[1] * 3);
  const pos = new Float32Array(q.length);
  for (let i = 0; i < q.length; i++) pos[i] = vasos.datos.min[i % 3] + q[i] / 65535 * vasos.datos.tam[i % 3];
  const ql = new Uint16Array(vasos.bin, vasos.datos.largo[0], vasos.datos.largo[1]);
  const largo = new Float32Array(ql.length);
  for (let i = 0; i < ql.length; i++) largo[i] = ql[i] / 65535;
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('aLargo', new THREE.BufferAttribute(largo, 1));
  g.setIndex(new THREE.BufferAttribute(new Uint32Array(vasos.bin, vasos.datos.idx[0], vasos.datos.idx[1]), 1));
  g.computeVertexNormals();
  mx.venas = new THREE.Mesh(g, new THREE.ShaderMaterial({
    uniforms: { uFrente: { value: 0 }, uOp: { value: 0 }, uTiempo: tiempo },
    vertexShader: `attribute float aLargo; varying float vL; varying vec3 vN; varying vec3 vV;
      void main(){ vL = aLargo; vec4 w = modelMatrix * vec4(position, 1.0); vN = normalize(mat3(modelMatrix) * normal);
        vV = normalize(cameraPosition - w.xyz); gl_Position = projectionMatrix * viewMatrix * w; }`,
    fragmentShader: `uniform float uFrente; uniform float uOp; uniform float uTiempo; varying float vL; varying vec3 vN; varying vec3 vV;
      void main(){ if (vL > uFrente) discard;
        float punta = smoothstep(uFrente - 0.07, uFrente, vL);
        float pulso = 0.5 + 0.5 * sin(vL * 70.0 - uTiempo * 5.0);
        float f = abs(dot(normalize(vN), normalize(vV)));
        vec3 c = mix(vec3(0.66, 0.42, 1.0), vec3(1.0, 0.95, 1.0), max(punta, 0.25 * pulso));
        gl_FragColor = vec4(c * (0.55 + 0.75 * f) * (1.0 + 1.5 * punta), (0.75 + 0.25 * f) * uOp); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  mx.venas.renderOrder = 5;
  mx.grupo.add(mx.venas);
  // el halo: los mismos tubos, inflados hacia fuera y muy tenues
  mx.halo = new THREE.Mesh(g, new THREE.ShaderMaterial({
    uniforms: { uFrente: mx.venas.material.uniforms.uFrente, uOp: { value: 0 } },
    vertexShader: `attribute float aLargo; varying float vL; varying vec3 vN; varying vec3 vV;
      void main(){ vL = aLargo; vec4 w = modelMatrix * vec4(position + normal * 0.012, 1.0); vN = normalize(mat3(modelMatrix) * normal);
        vV = normalize(cameraPosition - w.xyz); gl_Position = projectionMatrix * viewMatrix * w; }`,
    fragmentShader: `uniform float uFrente; uniform float uOp; varying float vL; varying vec3 vN; varying vec3 vV;
      void main(){ if (vL > uFrente) discard; float f = abs(dot(normalize(vN), normalize(vV)));
        gl_FragColor = vec4(vec3(0.55, 0.3, 1.0) * pow(f, 2.0), uOp); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  mx.halo.renderOrder = 4;
  mx.grupo.add(mx.halo);
  hacerGafas();
}

const centroMx = new THREE.Vector3(), gafasMx = new THREE.Vector3(), tmpMx = new THREE.Vector3(), arribaMx = new THREE.Vector3(0, 1, 0);
const giroMx = new THREE.Quaternion();
function mixtaFotograma(dt, ancho) {
  if (!mx.real) return;
  const activa = modo === 'mixta', tm = activa ? tModo : 0;
  mx.op = s(mx.op, activa ? 1 : 0, activa ? 3 : 5, dt);
  const op = mx.op, ver = op > 0.01;
  for (const o of [mx.grupo, mx.gafas, mx.haz, mx.anillo, mx.gemeloG, mx.onda]) o.visible = ver;
  if (!ver) { mx.fase = -1; return; }
  const fase = tm < MX.escaneo[0] ? -1 : tm < MX.llega[0] ? 0 : tm < MX.venas[0] ? 1 : 2;
  if (activa && fase !== mx.fase) { mx.fase = fase; alFase(fase); }
  const e = MX.escaneo, l = MX.llega, v = MX.venas;
  centroMx.set(0.3 * ancho, -0.2, 0);
  mx.grupo.position.copy(centroMx);
  // (gira despacio: escanea de tres cuartos y llega casi de frente a los vasos)
  mx.grupo.rotation.y = -0.75 + 0.07 * tModo;
  // el torso real: cuando se encienden los vasos se vuelve de cristal, como con los rayos X de las gafas
  const venasK = suave((tm - v[0]) / 1.2);
  // (entra creciendo, que fundido se ve el interior de la malla)
  mx.grupo.scale.setScalar(TAM_MX * (0.7 + 0.3 * suave(tm / 1.0)));
  mx.real.material.color.setHex(0xd9a097).multiplyScalar(1 - 0.35 * venasK);
  mx.real.material.opacity = 1 - 0.8 * venasK;
  mx.real.material.depthWrite = venasK < 0.02;
  for (const m of mx.dentro) { m.material.opacity = op * venasK * m.userData.base; m.visible = m.material.opacity > 0.01; }
  // el escaneo: el barrido baja por el torso
  const k = (tm - e[0]) / (e[1] - e[0]);
  const frente = mx.arriba - (mx.arriba - mx.abajo + 0.05) * suave(k);
  mx.puntos.material.uniforms.uFrente.value = tm < e[0] ? 2 : frente;
  mx.puntos.material.uniforms.uOp.value = op * (tm < e[0] ? 0 : tm < e[1] + 0.3 ? 1 : Math.max(0.25, 1 - (tm - e[1] - 0.3) / 1.2));
  const barre = op * (tm > e[0] && tm < e[1] + 0.2 ? Math.min(1, (tm - e[0]) * 3) * Math.min(1, (e[1] + 0.2 - tm) * 4) : 0);
  mx.anillo.material.opacity = 0.9 * barre;
  mx.anillo.position.set(centroMx.x, centroMx.y + frente * TAM_MX, 0);
  mx.anillo.scale.setScalar(TAM_MX);
  // las gafas: entran por la izquierda y miran al torso
  const entra = suave(tm / 1.3);
  gafasMx.set(centroMx.x + 1.05, 0.95, -1.1).add(tmpMx.set(0.9 * (1 - entra), 0.35 * (1 - entra), 0));
  mx.gafas.position.copy(gafasMx);
  mx.gafas.lookAt(centroMx.x, centroMx.y + 0.1, 0);
  mx.gafas.position.y += Math.sin(tModo * 1.3) * 0.015;
  for (const m of mx.mats) m.opacity = op * entra;
  mx.led.material.opacity = op * entra * (0.35 + 0.65 * (tm > e[0] && tm < l[1] ? 0.5 + 0.5 * Math.sin(tModo * 10) : 0.2));
  // el haz, de las gafas al torso, mientras escanea
  const delante = tmpMx.set(0, 0, 0.2).applyQuaternion(mx.gafas.quaternion);
  const desde = gafasMx.clone().add(delante), hasta = centroMx.clone();
  const largoHaz = desde.distanceTo(hasta);
  mx.haz.position.copy(desde).lerp(hasta, 0.5);
  giroMx.setFromUnitVectors(arribaMx, desde.clone().sub(hasta).normalize());
  mx.haz.quaternion.copy(giroMx);
  mx.haz.scale.set(0.95, largoHaz, 0.95);
  mx.haz.material.uniforms.uOp.value = op * (tm > e[0] - 0.3 && tm < e[1] + 0.5 ? Math.min(1, (tm - e[0] + 0.3) * 2) * Math.min(1, (e[1] + 0.5 - tm) * 2) : 0);
  // el gemelo: aparece junto a las gafas y baja a encajar sobre el torso
  const kl = suave((tm - l[0]) / (l[1] - l[0]));
  const aparece = Math.min(1, Math.max(0, (tm - l[0]) / 0.5));
  // (llega por delante, desde arriba a la izquierda, para que se vea encajar)
  mx.gemeloG.position.copy(centroMx).add(tmpMx.set(-0.75, 0.8, 1.05).multiplyScalar(1 - kl));
  mx.gemeloG.rotation.y = mx.grupo.rotation.y + 0.9 * (1 - kl);
  mx.gemeloG.rotation.z = 0.25 * (1 - kl);
  mx.gemeloG.scale.setScalar(TAM_MX * (1.0 + 0.012 + 0.25 * (1 - kl)));
  const encajado = tm > l[1];
  mx.gemelo.material.uniforms.uOp.value = op * aparece * (encajado ? 0.42 - 0.12 * venasK : 0.9);
  mx.red.material.opacity = op * aparece * (encajado ? 0.1 * (1 - venasK) + 0.03 : 0.35);
  // el encaje: una onda que se abre y un destello en el torso
  const tOnda = tm - l[1];
  const onda = tOnda > 0 && tOnda < 1.1 ? tOnda / 1.1 : -1;
  mx.onda.visible = ver && onda >= 0;
  if (onda >= 0) {
    mx.onda.position.copy(centroMx);
    mx.onda.quaternion.copy(camara.quaternion);
    mx.onda.scale.setScalar(TAM_MX * (1.0 + 1.1 * onda));
    mx.onda.material.opacity = op * (1 - onda) * 0.9;
  }
  mx.real.material.emissiveIntensity = onda >= 0 ? 0.7 * (1 - onda) : 0;
  // los vasos, creciendo desde el corazón
  mx.venas.material.uniforms.uFrente.value = tm < v[0] ? 0 : 1.08 * suave((tm - v[0]) / (v[1] - v[0]));
  mx.venas.material.uniforms.uOp.value = op;
  mx.halo.material.uniforms.uOp.value = 0.8 * op;
}

// ---------------------------------------------------------------- el cierre: un avión de pasajeros en órbita alrededor del coxis
// Va en sus propios lienzos, centrados en el coxis de la foto de la pelvis. Por detrás del coxis lo tapa el hueso y solo
// se ve por los huecos de la pelvis.
// El avión mide 1 de largo, con el morro hacia +z, las alas a lo largo de x y el techo hacia +y.
function hacerAvion() {
  const g = new THREE.Group();
  const blanco = new THREE.MeshStandardMaterial({ color: 0xf6f7f9, roughness: 0.3, metalness: 0.15 });
  const gris = new THREE.MeshStandardMaterial({ color: 0xc9cfd7, roughness: 0.35, metalness: 0.45 });
  const morado = new THREE.MeshStandardMaterial({ color: MORADO, roughness: 0.35, metalness: 0.1 });
  const oscuro = new THREE.MeshStandardMaterial({ color: 0x1b2130, roughness: 0.12, metalness: 0.5 });
  // fuselaje: un perfil girado; la cola sube un poco, como en los aviones de verdad
  const perfil = [[0, -0.5], [0.016, -0.495], [0.032, -0.45], [0.047, -0.37], [0.058, -0.27], [0.062, -0.15], [0.062, 0.3],
    [0.059, 0.37], [0.052, 0.42], [0.04, 0.46], [0.024, 0.49], [0, 0.5]];
  const subeCola = y => (y < -0.15 ? (-0.15 - y) * 0.13 : 0);
  function trozo(desde, hasta, phi0, phiL, crece, mat) {
    const pts = perfil.filter(([, y]) => y >= desde && y <= hasta).map(([r, y]) => new THREE.Vector2(r * crece, y));
    const geo = new THREE.LatheGeometry(pts, 28, phi0, phiL);
    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) pos.setZ(i, pos.getZ(i) - subeCola(pos.getY(i)));
    geo.rotateX(Math.PI / 2);         // (el eje del perfil, y, pasa a z; y lo que era −z queda arriba)
    geo.computeVertexNormals();
    g.add(new THREE.Mesh(geo, mat));
  }
  trozo(-1, 1, 0, Math.PI * 2, 1, blanco);
  const lado = Math.PI / 2;           // (phi = π/2 es el costado +x, phi = π es el techo)
  for (const s of [1, -1]) {
    const c = s > 0 ? lado : 3 * lado;
    trozo(-0.33, 0.37, c + s * 0.3 - 0.035, 0.07, 1.006, oscuro);    // las ventanillas
    trozo(-0.4, 0.43, c + s * 0.06 - 0.06, 0.12, 1.006, morado);     // la franja
  }
  trozo(0.4, 0.46, Math.PI - 0.55, 1.1, 1.008, oscuro);              // la cabina
  // alas, estabilizadores y deriva: planchas finas con la planta del ala
  function plancha(puntos, grueso, mat) {
    const forma = new THREE.Shape(puntos.map(([a, b]) => new THREE.Vector2(a, b)));
    const geo = new THREE.ExtrudeGeometry(forma, { depth: grueso, bevelEnabled: false });
    geo.translate(0, 0, -grueso / 2);
    return new THREE.Mesh(geo, mat);
  }
  const semiala = [[0.04, 0.12], [0.5, -0.13], [0.5, -0.19], [0.04, -0.08]];
  const semicola = [[0.03, -0.35], [0.2, -0.46], [0.2, -0.5], [0.03, -0.45]];
  for (const s of [1, -1]) {
    const espejo = p => (s > 0 ? p : p.map(([a, b]) => [-a, b]).reverse());
    const ala = plancha(espejo(semiala), 0.014, gris);
    ala.geometry.rotateX(Math.PI / 2);            // (la planta, en el plano xz)
    ala.position.set(0, -0.03, 0);
    ala.rotation.z = s * 0.08;                    // (diedro)
    g.add(ala);
    const cola = plancha(espejo(semicola), 0.01, gris);
    cola.geometry.rotateX(Math.PI / 2);
    cola.position.set(0, 0.035, 0);
    cola.rotation.z = s * 0.1;
    g.add(cola);
    // winglet, morado
    const wl = plancha([[-0.13, 0], [-0.17, 0.07], [-0.2, 0.07], [-0.19, 0]], 0.008, morado);
    wl.geometry.rotateY(-Math.PI / 2);
    wl.position.set(s * 0.5, -0.03 + 0.5 * Math.sin(0.08), 0);     // (en la punta del ala, que sube con el diedro)
    g.add(wl);
    // motor bajo el ala, con su pilón y la toma oscura
    const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.036, 0.03, 0.17, 24).rotateX(Math.PI / 2), blanco);
    motor.position.set(s * 0.18, -0.075, 0.08);
    g.add(motor);
    const labio = new THREE.Mesh(new THREE.TorusGeometry(0.033, 0.006, 8, 24), gris);
    labio.position.set(s * 0.18, -0.075, 0.165);
    g.add(labio);
    const toma = new THREE.Mesh(new THREE.CircleGeometry(0.031, 24), oscuro);
    toma.position.set(s * 0.18, -0.075, 0.16);
    g.add(toma);
    const pilon = new THREE.Mesh(new THREE.BoxGeometry(0.01, 0.04, 0.09), gris);
    pilon.position.set(s * 0.18, -0.045, 0.05);
    g.add(pilon);
  }
  const deriva = plancha([[-0.3, 0.04], [-0.46, 0.27], [-0.52, 0.27], [-0.5, 0.03]], 0.012, morado);
  deriva.geometry.rotateY(-Math.PI / 2);          // (la planta, en el plano yz)
  g.add(deriva);
  // luces: roja a la izquierda, verde a la derecha y un destello blanco en la cola
  const luz = (color, x, y, z) => {
    const m = new THREE.Mesh(new THREE.SphereGeometry(0.014, 10, 8), new THREE.MeshBasicMaterial({ color }));
    m.position.set(x, y, z);
    g.add(m);
    return m;
  };
  luz(0xff3040, -0.505, 0.0, -0.17);
  luz(0x30ff7a, 0.505, 0.0, -0.17);
  g.userData.destello = luz(0xffffff, 0, 0.035, -0.505);
  return g;
}

// Un solo WebGL fuera de la página dibuja dos veces: lo que está por delante del coxis (z > 0) va al lienzo de encima de la
// foto y lo de detrás, al de debajo. Así el avión y la estela cruzan por detrás del hueso sin saltos.
const RADIO_ORBITA = 3.1, VUELTA_S = 10, ALABEO = 0.38, ESCALA_AVION = 1.2, PUNTOS_ESTELA = 64, LARGO_ESTELA = 2.2;
const lienzosAvion = [document.getElementById('avion'), document.getElementById('avion-detras')];
const av = lienzosAvion[0] && (() => {
  const r = new THREE.WebGLRenderer({ canvas: document.createElement('canvas'), antialias: true, alpha: true });
  r.setClearColor(0x000000, 0);
  const esc = new THREE.Scene();
  esc.add(new THREE.HemisphereLight(0xffffff, 0x9fb0a8, 1.4));
  const sol = new THREE.DirectionalLight(0xffffff, 2.4);
  sol.position.set(-3, 6, 5);
  const contra = new THREE.DirectionalLight(0x9a6cff, 0.8);
  contra.position.set(4, 1, -4);
  esc.add(sol, contra);
  // 100 px de la diapositiva por unidad en el centro de la órbita: los lienzos (800 × 400) ven 8 × 4
  const dist = 14, elev = 0.27;
  const cam = new THREE.PerspectiveCamera(2 * Math.atan(2 / dist) * 180 / Math.PI, 2, 1, 40);
  cam.position.set(0, dist * Math.sin(elev), dist * Math.cos(elev));
  cam.lookAt(0, 0, 0);
  const avion = hacerAvion();
  avion.scale.setScalar(ESCALA_AVION);
  esc.add(avion);
  // la estela: una cinta morada que sigue la órbita por detrás del avión y se apaga
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(PUNTOS_ESTELA * 2 * 3), 3));
  const col = new Float32Array(PUNTOS_ESTELA * 2 * 4);
  const lila = new THREE.Color(0x7a3fd0);
  for (let k = 0; k < PUNTOS_ESTELA; k++) {
    const f = k / (PUNTOS_ESTELA - 1), alfa = 0.5 * (1 - f) * (1 - f) * Math.min(1, k / 3);
    for (const j of [0, 1]) col.set([lila.r, lila.g, lila.b, alfa], (2 * k + j) * 4);
  }
  geo.setAttribute('color', new THREE.BufferAttribute(col, 4));
  const idx = [];
  for (let k = 0; k < PUNTOS_ESTELA - 1; k++) idx.push(2 * k, 2 * k + 1, 2 * k + 2, 2 * k + 1, 2 * k + 3, 2 * k + 2);
  geo.setIndex(idx);
  const estela = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false,
    side: THREE.DoubleSide }));
  estela.frustumCulled = false;
  esc.add(estela);
  const cortes = [new THREE.Plane(new THREE.Vector3(0, 0, 1), 0), new THREE.Plane(new THREE.Vector3(0, 0, -1), 0)];
  return { r, esc, cam, avion, estela, cortes, ctx: lienzosAvion.map(l => l.getContext('2d')), ang: 0, w: 0, h: 0 };
})();

// en la órbita, el punto del ángulo a (por delante va de izquierda a derecha, y sube y baja un poco) y su rumbo
const enOrbita = (a, v) => v.set(RADIO_ORBITA * Math.cos(a), 0.14 * Math.sin(2 * a), -RADIO_ORBITA * Math.sin(a));
const rumboOrbita = (a, v) => v.set(-Math.sin(a), 0.28 * Math.cos(2 * a) / RADIO_ORBITA, -Math.cos(a)).normalize();
const vAv = new THREE.Vector3(), vAv2 = new THREE.Vector3(), vAv3 = new THREE.Vector3();
let alAvion = () => {}, avionSonando = false;
export function escucharAvion(f) { alAvion = f; }    // (para el sonido: dónde va, o null cuando no se ve)

function avionFotograma(dt, t) {
  if (!av || !document.querySelector('#cierre.present:not(.acto2)')) {
    if (avionSonando) { avionSonando = false; alAvion(null); }
    return;
  }
  const caja = lienzosAvion[0].getBoundingClientRect();
  if (caja.width < 2) return;
  const dpr = Math.min(window.devicePixelRatio, 2);
  if (Math.abs(caja.width - av.w) > 0.5 || Math.abs(caja.height - av.h) > 0.5) {
    av.w = caja.width; av.h = caja.height;
    av.r.setPixelRatio(dpr);
    av.r.setSize(av.w, av.h, false);
    for (const l of lienzosAvion) { l.width = Math.round(av.w * dpr); l.height = Math.round(av.h * dpr); }
  }
  av.ang += dt * 2 * Math.PI / VUELTA_S;
  const a = av.ang;
  const pos = enOrbita(a, vAv), rumbo = rumboOrbita(a, vAv2);
  av.avion.position.copy(pos);
  // alabeado hacia dentro de la curva
  av.avion.up.set(-Math.cos(a) * Math.sin(ALABEO), Math.cos(ALABEO), Math.sin(a) * Math.sin(ALABEO));
  av.avion.lookAt(vAv3.copy(pos).add(rumbo));
  av.avion.userData.destello.visible = (t % 1.3) < 0.09;
  avionSonando = true;
  alAvion(pos.x / RADIO_ORBITA, pos.z / RADIO_ORBITA, dt);
  // la estela, desde la cola hacia atrás, de cara a la cámara y abriéndose un poco
  const p = av.estela.geometry.attributes.position;
  const cola = 0.42 * ESCALA_AVION / RADIO_ORBITA;
  for (let k = 0; k < PUNTOS_ESTELA; k++) {
    const ak = a - cola - k * LARGO_ESTELA / PUNTOS_ESTELA;
    enOrbita(ak, vAv);
    rumboOrbita(ak, vAv2);
    vAv3.subVectors(av.cam.position, vAv).cross(vAv2).normalize().multiplyScalar(0.025 + 0.05 * k / PUNTOS_ESTELA);
    p.setXYZ(2 * k, vAv.x + vAv3.x, vAv.y + vAv3.y - 0.03, vAv.z + vAv3.z);
    p.setXYZ(2 * k + 1, vAv.x - vAv3.x, vAv.y - vAv3.y - 0.03, vAv.z - vAv3.z);
  }
  p.needsUpdate = true;
  // delante y detrás del coxis, cada uno a su lienzo
  for (let i = 0; i < 2; i++) {
    av.r.clippingPlanes = [av.cortes[i]];
    av.r.render(av.esc, av.cam);
    const c = av.ctx[i];
    c.clearRect(0, 0, c.canvas.width, c.canvas.height);
    c.drawImage(av.r.domElement, 0, 0);
  }
}

// ---------------------------------------------------------------- arranque
export const lista = (async () => {
  requestAnimationFrame(fotograma);
  const [datosCerebro, datos] = await Promise.all([paquete('cerebro'), paquete('torso')]);
  // el cerebro: el de la portada y el holograma del cierre, con sus núcleos y ventrículos encendidos
  const enteroCerebro = datosCerebro.mallas.find(p => p.clave === 'cerebro');
  cerebro = new THREE.Mesh(enteroCerebro.geo, arcilla(0xeba896, 0));
  cerebro.scale.setScalar(0.95);
  pCerebro.add(cerebro);
  pivoteFinal.scale.setScalar(ESCALA);
  final = new THREE.Mesh(enteroCerebro.geo, holograma(0x9a6cff, true));
  final.visible = false;
  pivoteFinal.add(final);
  for (const p of datosCerebro.mallas) {
    if (p.capa !== 2) continue;
    const f = new THREE.Mesh(p.geo, new THREE.MeshBasicMaterial({ color: 0xcdb5f5, transparent: true, opacity: 0, depthWrite: false,
      blending: THREE.AdditiveBlending }));
    f.visible = false;
    pivoteFinal.add(f);
    dentroFinal.push(f);
  }

  // el torso: la simulación y la realidad mixta
  forma.lado = datos.lado_cortes * ESCALA;
  forma.altoCortes = Math.min(datos.alto_cortes * ESCALA, 1.15);     // (la pila, que quepa en la diapositiva)
  const entero = datos.mallas.find(p => p.clave === 'torso');
  forma.alto = entero.tam[1] * ESCALA;
  pivote.scale.setScalar(ESCALA);
  for (const p of datos.mallas) {
    if (p.clave === 'torso') continue;
    const m = new THREE.Mesh(p.geo, new THREE.MeshStandardMaterial({ color: p.color, roughness: 0.62, transparent: true, opacity: 0,
      side: THREE.DoubleSide, clippingPlanes: ABIERTOS.includes(p.clave) ? [planoBarrido, planoCorte] : [planoBarrido] }));
    m.visible = false;
    m.renderOrder = 2 - p.capa;      // (lo de dentro, antes: así se ve a través de lo que se está apagando)
    pivote.add(m);
    secciones.push({ malla: m, capa: p.capa, centro: (p.min[1] + p.tam[1] / 2) * ESCALA, color: p.color });
  }
  pieza = new THREE.Mesh(entero.geo, arcilla(ARCILLA, 0));
  pieza.material.clippingPlanes = [planoColada, planoCorte];
  pieza.material.side = THREE.DoubleSide;       // (abierta por delante: se ve el hueco por dentro de la piel)
  pieza.visible = false;
  pieza.renderOrder = 3;
  alambre = new THREE.LineSegments(new THREE.WireframeGeometry(entero.geo), new THREE.LineBasicMaterial({ color: MORADO, transparent: true, opacity: 0 }));
  alambre.scale.setScalar(1.003);
  alambre.material.clippingPlanes = [planoCorte];
  alambre.visible = false;
  gemelo = new THREE.Mesh(entero.geo, holograma(0x7a3fe0, false));
  gemelo.visible = false;
  gemelo.renderOrder = 4;
  pivote.add(pieza, alambre, gemelo);
  hacerMolde(entero.tam[0] * ESCALA + 0.24, entero.tam[1] * ESCALA + 0.24, entero.tam[2] * ESCALA + 0.24);
  const vasos = { datos: JSON.parse(new TextDecoder().decode(await bytes('modelos/vasos.json'))), bin: await bytes('modelos/vasos.bin') };
  prepararMixta(entero.geo, alambre.geometry, vasos, datos.mallas.filter(p => p.clave !== 'torso' && p.capa > 0));
  window.__escenaLista = true;
})();
