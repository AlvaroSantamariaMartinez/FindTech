// TopoNet Studio — interfaz web
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';

const $ = (id) => document.getElementById(id);
const state = {
  meshInfo: null,
  origGeom: null,         // BufferGeometry del STL original
  regions: [],            // apoyos y cargas
  models: [],             // catálogo de plugins
  materials: {},
  pickMode: null,         // 'fixed' | 'load' | null
  job: null,
  panels: new Map(),      // key -> Panel
  refVertexVM: null,      // tensión de la pieza maciza en los vértices del STL
  voxelMesh: null,
  polling: null,
};

// ------------------------------------------------------------------ utilidades
function toast(msg, isError = false, ms = 4000) {
  const t = $('toast');
  t.textContent = msg; t.className = 'toast' + (isError ? ' error' : ''); t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}
function status(msg) { $('globalStatus').textContent = msg; }
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { const j = await r.json(); detail = j.detail || JSON.stringify(j); } catch { /* */ }
    throw new Error(detail);
  }
  return r.headers.get('content-type')?.includes('json') ? r.json() : r.arrayBuffer();
}
function b64(b64str, Type) {
  const bin = atob(b64str); const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return new Type(u8.buffer);
}
const fmt = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v)) ? '—'
  : Math.abs(v) >= 1e4 ? v.toExponential(2) : Number(v).toFixed(d);

// Mapa de color "turbo" (aprox. polinómica)
function turbo(t) {
  t = Math.min(1, Math.max(0, t));
  const r = 34.61 + t * (1172.33 - t * (10793.56 - t * (33300.12 - t * (38394.49 - t * 14825.05))));
  const g = 23.31 + t * (557.33 + t * (1225.33 - t * (3574.96 - t * (1073.77 + t * 707.56))));
  const b = 27.2 + t * (3211.1 - t * (15327.97 - t * (27814 - t * (22569.18 - t * 6838.66))));
  return [Math.min(1, Math.max(0, r / 255)), Math.min(1, Math.max(0, g / 255)), Math.min(1, Math.max(0, b / 255))];
}

// ------------------------------------------------------------------ visor 3D
const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 1e6);
camera.up.set(0, 0, 1);
const sharedTarget = new THREE.Vector3();
const isDark = matchMedia('(prefers-color-scheme: dark)').matches;
const COLORS = { solid: isDark ? 0x9fb4d9 : 0x5b7bb5, orig: isDark ? 0xb0b8c4 : 0x8a94a3, fixed: 0x2fb344, load: 0xf2711c };

class Panel {
  constructor(key, title, { pickable = false } = {}) {
    this.key = key;
    this.el = document.createElement('div');
    this.el.className = 'panel';
    this.el.innerHTML = `
      <div class="ptitle"><span class="name"></span><span class="msg"></span></div>
      <div class="progress"><div></div></div>
      <div class="canvas"></div>
      <div class="pfoot"></div>`;
    this.el.querySelector('.name').textContent = title;
    $('viewports').appendChild(this.el);
    this.container = this.el.querySelector('.canvas');
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.container.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.4));
    this.light = new THREE.DirectionalLight(0xffffff, 1.6);
    this.scene.add(this.light);
    this.controls = new OrbitControls(camera, this.renderer.domElement);
    this.controls.target = sharedTarget;  // todas las vistas comparten cámara y objetivo
    this.controls.enableDamping = false;
    this.markers = new THREE.Group();
    this.scene.add(this.markers);
    this.object = null;     // malla principal
    this.ghost = null;      // silueta del original
    this.scalars = null;    // {von_mises:{data,min,max,p99}, ...}
    this.result = null;
    if (pickable) this.enablePicking();
    state.panels.set(key, this);
  }
  setMessage(msg, isError = false) {
    this.el.querySelector('.msg').textContent = msg || '';
    this.el.classList.toggle('error', isError);
  }
  setProgress(p) { this.el.querySelector('.progress div').style.width = `${Math.round(100 * p)}%`; }
  setObject(obj) {
    if (this.object) { this.scene.remove(this.object); this.object.geometry.dispose(); }
    this.object = obj; if (obj) this.scene.add(obj);
  }
  setGhost(geom) {
    if (this.ghost) this.scene.remove(this.ghost);
    if (!geom) { this.ghost = null; return; }
    this.ghost = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({
      color: COLORS.orig, transparent: true, opacity: 0.08, depthWrite: false }));
    this.ghost.visible = $('ghostToggle').checked;
    this.scene.add(this.ghost);
  }
  enablePicking() {
    const ray = new THREE.Raycaster();
    let down = null;
    this.renderer.domElement.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
    this.renderer.domElement.addEventListener('pointerup', (e) => {
      if (!state.pickMode || !down || !this.object) return;
      if (Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;  // fue un arrastre
      const r = this.renderer.domElement.getBoundingClientRect();
      const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, camera);
      const hit = ray.intersectObject(this.object, false)[0];
      if (!hit) return;
      addRegion(state.pickMode, { center: hit.point.toArray(), normal: hit.face?.normal?.toArray() });
      setPickMode(null);
    });
  }
  render() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h) return;
    const c = this.renderer.domElement;
    if (c.width !== Math.floor(w * this.renderer.getPixelRatio()) || c.height !== Math.floor(h * this.renderer.getPixelRatio())) {
      this.renderer.setSize(w, h, false);
    }
    camera.aspect = w / h; camera.updateProjectionMatrix();
    this.light.position.copy(camera.position);
    this.renderer.render(this.scene, camera);
  }
  dispose() {
    // libera el contexto WebGL: los navegadores limitan cuántos puede haber vivos
    this.renderer.dispose(); this.renderer.forceContextLoss();
    this.controls.dispose(); this.el.remove(); state.panels.delete(this.key);
  }
}

function animate() {
  requestAnimationFrame(animate);
  for (const p of state.panels.values()) p.render();
}

function fitCamera(geom) {
  geom.computeBoundingBox();
  const bb = geom.boundingBox, c = new THREE.Vector3(), s = new THREE.Vector3();
  bb.getCenter(c); bb.getSize(s);
  const d = s.length();
  sharedTarget.copy(c);
  // distancia para que la esfera envolvente quepa en el campo de visión (con margen)
  // usa el menor de los semiángulos vertical/horizontal (paneles casi cuadrados, aspecto ≥ 0.9)
  const halfV = THREE.MathUtils.degToRad(camera.fov / 2);
  const halfH = Math.atan(0.9 * Math.tan(halfV));
  const dist = (d / 2) / Math.sin(Math.min(halfV, halfH)) * 1.05;
  camera.position.copy(c).add(new THREE.Vector3(0.9, -1.3, 0.8).normalize().multiplyScalar(dist));
  camera.near = d / 1000; camera.far = d * 100; camera.updateProjectionMatrix();
  camera.lookAt(c);
  for (const p of state.panels.values()) p.controls.update();
}

function bboxDiag() {
  if (!state.meshInfo) return 100;
  const s = state.meshInfo.size_mm; return Math.hypot(s[0], s[1], s[2]);
}

// ------------------------------------------------------------------ coloreado
function colorMode() { return $('colorMode').value; }

function globalScale(field) {
  // escala común a todas las vistas: comparación honesta entre modelos
  let max = 0;
  for (const p of state.panels.values()) {
    const s = p.key === 'orig' ? p.origScalars?.[field] : p.scalars?.[field];
    if (s) max = Math.max(max, field === 'von_mises' ? s.p99 : s.max);
  }
  return max || 1;
}

function applyColors() {
  const mode = colorMode();
  const legend = $('legend');
  let max = 1;
  if (mode !== 'solid') {
    max = globalScale(mode);
    legend.hidden = false;
    $('legendMin').textContent = '0';
    $('legendMax').textContent = mode === 'von_mises' ? `${fmt(max, 1)} MPa` : `${fmt(max, 3)} mm`;
  } else legend.hidden = true;
  for (const p of state.panels.values()) {
    if (!p.object) continue;
    const geom = p.object.geometry;
    const src = p.key === 'orig' ? p.origScalars : p.scalars;
    const s = src?.[mode];
    if (mode === 'solid' || !s) {
      p.object.material.vertexColors = false;
      p.object.material.color.set(p.key === 'orig' ? COLORS.orig : COLORS.solid);
    } else {
      const n = geom.attributes.position.count;
      const col = new Float32Array(n * 3);
      const data = s.arr || (s.arr = b64(s.data, Float32Array));
      for (let i = 0; i < n; i++) {
        const c = turbo(data[i] / max);
        col[3 * i] = c[0]; col[3 * i + 1] = c[1]; col[3 * i + 2] = c[2];
      }
      geom.setAttribute('color', new THREE.BufferAttribute(col, 3));
      p.object.material.vertexColors = true;
      p.object.material.color.set(0xffffff);
    }
    p.object.material.needsUpdate = true;
  }
}

// ------------------------------------------------------------------ marcadores
function buildMarkers(group) {
  group.clear();
  const d = bboxDiag();
  for (const r of state.regions) {
    const color = r.kind === 'fixed' ? COLORS.fixed : COLORS.load;
    if (r.shape === 'sphere') {
      const m = new THREE.Mesh(new THREE.SphereGeometry(r.radius, 24, 16),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.35, depthWrite: false }));
      m.position.fromArray(r.center); group.add(overlay(m));
      const dot = new THREE.Mesh(new THREE.SphereGeometry(d * 0.008, 12, 8), new THREE.MeshBasicMaterial({ color }));
      dot.position.fromArray(r.center); group.add(overlay(dot));
    } else {
      const [lo, hi] = state.meshInfo.bounds;
      const ax = 'xyz'.indexOf(r.face[0]);
      const pos = (r.face.endsWith('min') ? lo : hi).slice();
      const center = lo.map((v, i) => (v + hi[i]) / 2); center[ax] = pos[ax];
      const size = hi.map((v, i) => v - lo[i]); size[ax] = d * 0.004;
      const m = new THREE.Mesh(new THREE.BoxGeometry(...size),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.35, depthWrite: false }));
      m.position.fromArray(center); group.add(overlay(m));
      r._anchor = center;
    }
    if (r.kind === 'load') {
      const f = new THREE.Vector3().fromArray(r.force);
      const L = f.length();
      if (L > 0) {
        const dir = f.clone().normalize();
        const len = d * 0.18;
        const origin = new THREE.Vector3().fromArray(r.shape === 'sphere' ? r.center : r._anchor).sub(dir.clone().multiplyScalar(len));
        group.add(overlay(new THREE.ArrowHelper(dir, origin, len, color, len * 0.25, len * 0.12)));
      }
    }
  }
}
// los marcadores se dibujan siempre por encima de la pieza para que se vean
function overlay(obj) {
  obj.traverse((o) => { if (o.material) { o.material.depthTest = false; o.material.transparent = true; } o.renderOrder = 10; });
  return obj;
}
function refreshMarkers() {
  for (const p of state.panels.values()) { buildMarkers(p.markers); p.markers.visible = $('markersToggle').checked; }
}

// ------------------------------------------------------------------ regiones (UI)
function addRegion(kind, { center = [0, 0, 0], normal = null, shape = 'sphere', face = 'xmin' } = {}) {
  const d = bboxDiag();
  const r = { kind, shape, face, center, radius: +(d * 0.06).toFixed(1), dofs: [true, true, true], keep_solid: true,
              force: [0, 0, -100] };
  if (kind === 'load' && normal && shape === 'sphere') {
    // por defecto: empuja hacia dentro de la superficie
    const n = new THREE.Vector3().fromArray(normal).normalize().multiplyScalar(-100);
    r.force = n.toArray().map((v) => +v.toFixed(1));
  }
  state.regions.push(r);
  renderRegions();
}

function renderRegions() {
  const list = $('regionList');
  list.innerHTML = '';
  state.regions.forEach((r, i) => {
    const div = document.createElement('div');
    div.className = `region ${r.kind}`;
    const title = r.kind === 'fixed' ? 'Apoyo' : 'Carga';
    const where = r.shape === 'face' ? `cara ${r.face}` : 'esfera';
    let html = `<header><span>${title} ${i + 1} · ${where}</span><button class="del" title="Eliminar">×</button></header>`;
    if (r.shape === 'sphere') {
      html += `<div class="vec"><span>centro</span>${r.center.map((v, k) => `<input type="number" step="0.5" data-k="center" data-i="${k}" value="${(+v).toFixed(1)}">`).join('')}</div>
               <div class="vec"><span>radio</span><input type="number" step="0.5" min="0.1" data-k="radius" value="${r.radius}"><span></span><span></span></div>`;
    }
    if (r.kind === 'load') {
      html += `<div class="vec"><span>F [N]</span>${r.force.map((v, k) => `<input type="number" step="10" data-k="force" data-i="${k}" value="${v}">`).join('')}</div>`;
    } else {
      html += `<div class="opts">bloquear: ${['X', 'Y', 'Z'].map((a, k) => `<label><input type="checkbox" data-k="dofs" data-i="${k}" ${r.dofs[k] ? 'checked' : ''}> ${a}</label>`).join('')}</div>`;
    }
    html += `<div class="opts"><label title="La zona se mantiene maciza (recomendado)"><input type="checkbox" data-k="keep_solid" ${r.keep_solid ? 'checked' : ''}> zona no diseñable</label></div>`;
    div.innerHTML = html;
    div.querySelector('.del').onclick = () => { state.regions.splice(i, 1); renderRegions(); };
    div.querySelectorAll('input').forEach((inp) => {
      inp.addEventListener('change', () => {
        const k = inp.dataset.k, j = inp.dataset.i;
        if (inp.type === 'checkbox') { if (j !== undefined) r[k][+j] = inp.checked; else r[k] = inp.checked; }
        else if (j !== undefined) r[k][+j] = parseFloat(inp.value) || 0;
        else r[k] = parseFloat(inp.value) || 0;
        refreshMarkers();
      });
    });
    list.appendChild(div);
  });
  refreshMarkers();
}

function setPickMode(mode) {
  state.pickMode = mode;
  $('pickFixed').classList.toggle('active', mode === 'fixed');
  $('pickLoad').classList.toggle('active', mode === 'load');
  state.panels.get('orig')?.el.classList.toggle('picking', !!mode);
  if (mode) status(mode === 'fixed' ? 'Haz clic en la pieza para colocar un apoyo…' : 'Haz clic en la pieza para colocar una carga…');
  else status('Listo');
}

// ------------------------------------------------------------------ carga de la pieza
async function loadMesh(info) {
  state.meshInfo = info;
  state.regions = [];
  state.refVertexVM = null;
  const buf = await api(`/api/mesh/${info.mesh_id}/stl`);
  const geom = new STLLoader().parse(buf);
  geom.computeVertexNormals();
  state.origGeom = geom;
  // reinicia los visores
  for (const p of [...state.panels.values()]) p.dispose();
  $('comparison').innerHTML = '<p class="muted">Lanza una optimización para ver la comparación.</p>';
  const orig = new Panel('orig', 'Original', { pickable: true });
  orig.setObject(new THREE.Mesh(geom, new THREE.MeshStandardMaterial({ color: COLORS.orig, roughness: 0.6, metalness: 0.05 })));
  orig.el.querySelector('.pfoot').innerHTML = '<span class="muted">Arrastra para rotar · rueda para zoom · clic derecho para desplazar</span>';
  fitCamera(geom);
  const s = info.size_mm.map((v) => v.toFixed(1)).join(' × ');
  $('meshInfo').innerHTML = `<b>${info.name}</b><br>${s} mm · ${info.triangles.toLocaleString()} triángulos` +
    (info.volume_mm3 ? ` · ${(info.volume_mm3 / 1000).toFixed(1)} cm³` : '') +
    (info.watertight ? '' : '<br><span style="color:var(--bad)">La malla no es estanca: la voxelización puede fallar.</span>');
  renderRegions();
  updateVoxelInfo(false);
}

async function updateVoxelInfo(preview) {
  if (!state.meshInfo) return;
  try {
    const v = await api('/api/voxelize', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mesh_id: state.meshInfo.mesh_id, resolution: +$('resolution').value, preview }) });
    $('voxelInfo').innerHTML = `${v.grid.join('×')} · ${v.elements.toLocaleString()} elementos · vóxel ${v.pitch_mm.toFixed(2)} mm` +
      (v.too_big ? ' <span style="color:var(--bad)">(demasiado grande)</span>' : '');
    const orig = state.panels.get('orig');
    if (preview && v.mesh && !v.mesh.empty && orig) {
      if (state.voxelMesh) orig.scene.remove(state.voxelMesh);
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(b64(v.mesh.positions, Float32Array), 3));
      g.setIndex(new THREE.BufferAttribute(b64(v.mesh.indices, Uint32Array), 1));
      g.computeVertexNormals();
      state.voxelMesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0xf59f00, wireframe: false, transparent: true, opacity: 0.55, flatShading: true }));
      orig.scene.add(state.voxelMesh);
      $('voxelBtn').textContent = 'Ocultar vóxeles';
    }
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ modelos
function renderModels() {
  const list = $('modelList');
  list.innerHTML = '';
  for (const m of state.models) {
    const div = document.createElement('div');
    div.className = 'model' + (m.available ? '' : ' disabled');
    const defaultOn = m.available && (m.id === 'simp' || m.id === 'toponet');
    div.innerHTML = `
      <div class="head">
        <input type="checkbox" id="m_${m.id}" ${defaultOn ? 'checked' : ''} ${m.available ? '' : 'disabled'}>
        <div style="flex:1"><label for="m_${m.id}"></label><div class="muted small desc"></div></div>
        <span class="badge"></span>
      </div>
      ${m.available ? '' : '<div class="reason"></div>'}
      <details><summary>Parámetros</summary><div class="params"></div></details>`;
    div.querySelector('label').textContent = m.name;
    div.querySelector('.desc').textContent = m.description;
    div.querySelector('.badge').textContent = m.kind;
    if (!m.available) div.querySelector('.reason').textContent = m.unavailable_reason;
    const pdiv = div.querySelector('.params');
    for (const p of m.params) {
      const row = document.createElement('div');
      row.className = 'param';
      row.title = p.help || '';
      const lab = document.createElement('span'); lab.textContent = p.label;
      let input;
      if (p.type === 'choice') {
        input = document.createElement('select');
        for (const c of p.choices) { const o = document.createElement('option'); o.value = o.textContent = c; input.appendChild(o); }
        input.value = p.default;
      } else if (p.type === 'bool') {
        input = document.createElement('input'); input.type = 'checkbox'; input.checked = !!p.default;
      } else {
        input = document.createElement('input'); input.type = 'number';
        if (p.min !== null) input.min = p.min; if (p.max !== null) input.max = p.max;
        if (p.step !== null) input.step = p.step; input.value = p.default;
      }
      input.dataset.param = p.name; input.dataset.type = p.type;
      row.append(lab, input); pdiv.appendChild(row);
    }
    list.appendChild(div);
  }
}

function selectedModels() {
  const out = [];
  for (const m of state.models) {
    const cb = $(`m_${m.id}`);
    if (!cb || !cb.checked) continue;
    const params = {};
    cb.closest('.model').querySelectorAll('[data-param]').forEach((inp) => {
      params[inp.dataset.param] = inp.dataset.type === 'bool' ? inp.checked
        : inp.dataset.type === 'choice' ? inp.value : parseFloat(inp.value);
    });
    out.push({ id: m.id, params });
  }
  return out;
}

async function loadModels(reload = false) {
  const r = await api(reload ? '/api/models/reload' : '/api/models', { method: reload ? 'POST' : 'GET' });
  state.models = r.models;
  renderModels();
  if (r.errors?.length) toast('Errores al cargar plugins:\n' + r.errors.join('\n'), true, 8000);
}

// ------------------------------------------------------------------ material
function setMaterial(name) {
  const m = state.materials[name]; if (!m) return;
  $('matE').value = m.E; $('matNu').value = m.nu; $('matY').value = m.yield_strength; $('matRho').value = m.density;
}

// ------------------------------------------------------------------ ejecución
async function run() {
  if (!state.meshInfo) return toast('Primero carga una pieza.', true);
  if (!state.regions.some((r) => r.kind === 'fixed')) return toast('Añade al menos un apoyo.', true);
  if (!state.regions.some((r) => r.kind === 'load')) return toast('Añade al menos una carga.', true);
  const models = selectedModels();
  if (!models.length) return toast('Elige al menos un modelo.', true);
  const body = {
    mesh_id: state.meshInfo.mesh_id,
    resolution: +$('resolution').value,
    volfrac: +$('volfrac').value / 100,
    safety_target: +$('safety').value,
    material: { name: $('materialSelect').value, E: +$('matE').value, nu: +$('matNu').value,
                yield_strength: +$('matY').value, density: +$('matRho').value },
    regions: state.regions.map(({ _anchor, ...r }) => r),
    models,
  };
  $('runBtn').disabled = true;
  try {
    const { job_id } = await api('/api/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    // elimina visores de resultados anteriores
    for (const p of [...state.panels.values()]) if (p.key !== 'orig') p.dispose();
    state.job = { id: job_id, data: null };
    const orig = state.panels.get('orig');
    orig.origScalars = null;
    clearInterval(state.polling);
    state.polling = setInterval(poll, 800);
    poll();
  } catch (e) { toast(e.message, true); $('runBtn').disabled = false; }
}

async function poll() {
  if (!state.job) return;
  let j;
  try { j = await api(`/api/jobs/${state.job.id}`); } catch (e) { return; }
  state.job.data = j;
  status(j.message || j.status);
  const orig = state.panels.get('orig');
  if (j.reference && orig && !orig.origScalars) {
    const vm = b64(j.reference.vertex_von_mises, Float32Array);
    orig.origScalars = { von_mises: await mapOrigScalars(vm, j.reference.metrics) };
    applyColors();
  }
  for (const [key, r] of Object.entries(j.runs)) {
    let p = state.panels.get(key);
    if (!p) {
      p = new Panel(key, r.name);
      p.setGhost(state.origGeom);
      buildMarkers(p.markers);
      p.markers.visible = $('markersToggle').checked;
      p.el.querySelector('.pfoot').innerHTML = `
        <label>Umbral <input type="range" min="0.1" max="0.9" step="0.05" value="0.5" class="thr"> <b class="thrv">0.50</b></label>
        <span class="spacer"></span>
        <a class="dl" href="#" download>Descargar STL</a>`;
      const thr = p.el.querySelector('.thr');
      let tmo;
      thr.addEventListener('input', () => {
        p.el.querySelector('.thrv').textContent = (+thr.value).toFixed(2);
        clearTimeout(tmo); tmo = setTimeout(() => loadResultMesh(p, +thr.value), 250);
      });
    }
    p.setProgress(r.progress || 0);
    p.setMessage(r.message, r.status === 'error');
    if (r.status === 'done' && !p.result) {
      p.result = r;
      await loadResultMesh(p, 0.5);
    }
  }
  renderComparison();
  if (j.status === 'done' || j.status === 'error') {
    clearInterval(state.polling);
    $('runBtn').disabled = false;
    if (j.status === 'error') toast(j.message, true, 8000);
    else status('Terminado');
  }
}

// Pieza original: el servidor envía la tensión en los vértices fusionados de su malla.
// STLLoader produce una geometría NO indexada (3 vértices por triángulo), así que
// asociamos cada vértice del visor con el del servidor por su posición exacta.
async function mapOrigScalars(vertVM, metrics) {
  const geom = state.origGeom;
  const n = geom.attributes.position.count;
  if (!state._origIndex) {
    state._origIndex = await buildOrigIndex();
  }
  const idx = state._origIndex;
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = vertVM[idx[i]] ?? 0;
  let max = 0; for (const v of out) max = Math.max(max, v);
  const sorted = Array.from(out).sort((a, b) => a - b);
  return { arr: out, min: 0, max, p99: sorted[Math.floor(0.99 * (sorted.length - 1))] || max };
}
async function buildOrigIndex() {
  const r = await api(`/api/mesh/${state.meshInfo.mesh_id}/vertices`);
  const verts = b64(r.positions, Float32Array);
  const key = (x, y, z) => `${x.toFixed(4)},${y.toFixed(4)},${z.toFixed(4)}`;
  const map = new Map();
  for (let i = 0; i < verts.length / 3; i++) map.set(key(verts[3 * i], verts[3 * i + 1], verts[3 * i + 2]), i);
  const pos = state.origGeom.attributes.position.array;
  const idx = new Int32Array(pos.length / 3);
  for (let i = 0; i < idx.length; i++) idx[i] = map.get(key(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2])) ?? 0;
  return idx;
}

async function loadResultMesh(panel, threshold) {
  const rid = panel.result.result_id;
  try {
    const r = await api(`/api/results/${rid}/mesh?threshold=${threshold}`);
    panel.result.metrics = r.metrics; panel.result.checks = r.checks;
    if (r.mesh.empty) { panel.setObject(null); panel.setMessage('Diseño vacío con este umbral', true); return; }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(b64(r.mesh.positions, Float32Array), 3));
    g.setIndex(new THREE.BufferAttribute(b64(r.mesh.indices, Uint32Array), 1));
    g.computeVertexNormals();
    panel.scalars = r.mesh.scalars;
    panel.setObject(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: COLORS.solid, roughness: 0.55, metalness: 0.05 })));
    const a = panel.el.querySelector('.dl');
    a.href = `/api/results/${rid}/stl?threshold=${threshold}`;
    applyColors();
    renderComparison();
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ tabla comparativa
const ROWS = [
  ['section', 'Rendimiento'],
  ['optimize_time_s', 'Tiempo de optimización (s)', 1, 'min'],
  ['section', 'Material'],
  ['volume_fraction', 'Volumen conservado (%)', 1, null, (v) => 100 * v],
  ['mass_g', 'Masa (g)', 1, 'min'],
  ['section', 'Rigidez'],
  ['compliance_Nmm', 'Flexibilidad F·u (N·mm)', 3, 'min'],
  ['stiffness_retained_pct', 'Rigidez conservada (%)', 1, 'max'],
  ['specific_stiffness_gain', 'Rigidez / masa (× original)', 2, 'max'],
  ['max_displacement_mm', 'Desplazamiento máx. (mm)', 4, 'min'],
  ['section', 'Resistencia'],
  ['p99_von_mises_MPa', 'σ von Mises p99 (MPa)', 1, 'min'],
  ['max_von_mises_MPa', 'σ von Mises máx. (MPa)', 1, 'min'],
  ['safety_factor', 'Factor de seguridad', 2, 'max'],
  ['section', 'Integridad'],
  ['load_carried_pct', 'Carga transmitida (%)', 1, 'max'],
  ['thin_member_pct', 'Miembros de 1 vóxel (%)', 1, 'min'],
];

function renderComparison() {
  const j = state.job?.data;
  if (!j || !j.reference) return;
  const cols = [{ name: 'Original (macizo)', metrics: j.reference.metrics, checks: j.reference.checks, ref: true }];
  for (const [key, r] of Object.entries(j.runs)) {
    const p = state.panels.get(key);
    cols.push({ name: r.name, metrics: p?.result?.metrics || r.metrics, checks: p?.result?.checks || r.checks, status: r.status });
  }
  let html = '<table><thead><tr><th>Métrica</th>' + cols.map((c) => `<th>${escapeHtml(c.name)}</th>`).join('') + '</tr></thead><tbody>';
  for (const row of ROWS) {
    if (row[0] === 'section') { html += `<tr class="section"><td colspan="${cols.length + 1}">${row[1]}</td></tr>`; continue; }
    const [k, label, dec, better, tf] = row;
    const vals = cols.map((c) => { const v = c.metrics?.[k]; return v === undefined || v === null ? null : (tf ? tf(v) : v); });
    let best = null;
    if (better) {
      const cand = vals.map((v, i) => (i > 0 && v !== null ? v : null)).filter((v) => v !== null);
      if (cand.length > 1) best = better === 'min' ? Math.min(...cand) : Math.max(...cand);
    }
    html += `<tr><td>${label}</td>` + vals.map((v, i) => `<td class="${i > 0 && v !== null && v === best ? 'best' : ''}">${fmt(v, dec)}</td>`).join('') + '</tr>';
  }
  html += `<tr><td>Comprobaciones</td>` + cols.map((c) => {
    if (!c.checks) return `<td>${c.status === 'error' ? '<span class="bad">error</span>' : '…'}</td>`;
    return '<td class="checks">' + c.checks.map((ch) => `<span class="${ch.ok ? 'ok' : 'bad'}" title="${escapeHtml(ch.name + ': ' + ch.detail)}">${ch.ok ? '✔' : '✘'}</span>`).join('') + '</td>';
  }).join('') + '</tr>';
  html += '</tbody></table><p class="muted small">Pasa el ratón por ✔/✘ para ver cada comprobación (camino de carga, islas, resistencia, FEM, espesor). ' +
    'El factor de seguridad usa el percentil 99 de la tensión para no dejarse engañar por las singularidades de los vóxeles en apoyos y cargas.</p>';
  $('comparison').innerHTML = html;
}
function escapeHtml(s) { return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

// ------------------------------------------------------------------ eventos
async function init() {
  animate();
  const [mats, examples] = await Promise.all([api('/api/materials'), api('/api/examples')]);
  state.materials = mats;
  for (const name of Object.keys(mats)) { const o = document.createElement('option'); o.value = o.textContent = name; $('materialSelect').appendChild(o); }
  $('materialSelect').value = 'PLA'; setMaterial('PLA');
  for (const e of examples) { const o = document.createElement('option'); o.value = e; o.textContent = e; $('exampleSelect').appendChild(o); }
  await loadModels();

  $('materialSelect').onchange = (e) => setMaterial(e.target.value);
  $('fileInput').onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    status('Subiendo…');
    try { await loadMesh(await api('/api/upload', { method: 'POST', body: fd })); state._origIndex = null; status('Listo'); }
    catch (err) { toast(err.message, true); status('Error'); }
  };
  $('exampleSelect').onchange = async (e) => {
    if (!e.target.value) return;
    try { state._origIndex = null; await loadMesh(await api(`/api/examples/${encodeURIComponent(e.target.value)}`, { method: 'POST' })); applyExamplePreset(e.target.value); }
    catch (err) { toast(err.message, true); }
  };
  $('resolution').oninput = () => { $('resVal').textContent = $('resolution').value; };
  $('resolution').onchange = () => { removeVoxelPreview(); updateVoxelInfo(false); };
  $('voxelBtn').onclick = () => { if (state.voxelMesh) removeVoxelPreview(); else updateVoxelInfo(true); };
  $('volfrac').oninput = () => { $('vfVal').textContent = `${$('volfrac').value} %`; };
  $('safety').oninput = () => { $('sfVal').textContent = (+$('safety').value).toFixed(1); };
  $('pickFixed').onclick = () => setPickMode(state.pickMode === 'fixed' ? null : 'fixed');
  $('pickLoad').onclick = () => setPickMode(state.pickMode === 'load' ? null : 'load');
  $('faceFixed').onclick = () => state.meshInfo && addRegion('fixed', { shape: 'face', face: $('faceSelect').value });
  $('faceLoad').onclick = () => state.meshInfo && addRegion('load', { shape: 'face', face: $('faceSelect').value });
  $('reloadModels').onclick = () => loadModels(true).then(() => toast('Modelos recargados'));
  $('runBtn').onclick = run;
  $('colorMode').onchange = applyColors;
  $('ghostToggle').onchange = () => { for (const p of state.panels.values()) if (p.ghost) p.ghost.visible = $('ghostToggle').checked; };
  $('markersToggle').onchange = refreshMarkers;
  addEventListener('keydown', (e) => { if (e.key === 'Escape') setPickMode(null); });
}

function removeVoxelPreview() {
  const orig = state.panels.get('orig');
  if (state.voxelMesh && orig) orig.scene.remove(state.voxelMesh);
  state.voxelMesh = null; $('voxelBtn').textContent = 'Ver vóxeles';
}

// Condiciones de contorno sugeridas para los ejemplos incluidos
function applyExamplePreset(name) {
  const [lo, hi] = state.meshInfo.bounds;
  const c = lo.map((v, i) => (v + hi[i]) / 2);
  state.regions = [];
  if (name.startsWith('viga')) {
    addRegion('fixed', { shape: 'face', face: 'xmin' });
    addRegion('load', { center: [hi[0], c[1], lo[2]] });
    state.regions[1].force = [0, 0, -500]; state.regions[1].radius = 6;
  } else if (name.startsWith('puente')) {
    addRegion('fixed', { center: [lo[0], c[1], lo[2]] });
    addRegion('fixed', { center: [hi[0], c[1], lo[2]] });
    state.regions[1].dofs = [false, true, true];
    addRegion('load', { center: [c[0], c[1], hi[2]] });
    state.regions[2].force = [0, 0, -1000];
  } else if (name.startsWith('soporte')) {
    addRegion('fixed', { center: [25, 20, 0] }); state.regions[0].radius = 7;
    addRegion('fixed', { center: [65, 20, 0] }); state.regions[1].radius = 7;
    addRegion('load', { center: [0, 20, 58] }); state.regions[2].radius = 6; state.regions[2].force = [-200, 0, 0];
  } else if (name.startsWith('brida')) {
    for (const ang of [45, 135, 225, 315]) {
      const a = ang * Math.PI / 180;
      addRegion('fixed', { center: [38 * Math.cos(a), 38 * Math.sin(a), 0] }); state.regions.at(-1).radius = 6;
    }
    addRegion('load', { center: [0, 0, 12] }); state.regions.at(-1).radius = 15; state.regions.at(-1).force = [0, 0, -2000];
  }
  renderRegions();
  toast('Apoyos y cargas de ejemplo aplicados: edítalos a tu gusto.');
}

window.toponet = { state, camera, THREE };  // útil para depurar desde la consola
init().catch((e) => toast(e.message, true));
