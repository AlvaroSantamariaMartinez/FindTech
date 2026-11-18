// Los efectos de sonido. Se hacen en el navegador (Web Audio): no hay archivos de audio.
// El navegador no deja sonar nada hasta la primera tecla o clic; al presentar, la primera tecla ya lo arranca.
// La tecla M (o el altavoz del pie) quita y pone el sonido, y se recuerda.
// Cada diapositiva suena por su propio «bus»: al cambiar de diapositiva o de etapa se apaga, con lo que tenía pendiente.
export const sonido = (() => {
  const AC = window.AudioContext || window.webkitAudioContext;
  // (sin sonido en las capturas ni en las miniaturas de la vista del orador)
  const mudo = !AC || /export|receiver/.test(location.search);
  const VOLUMEN = 0.9;
  let ac = null, salida = null, bus = null, ruido = null, motor = null;
  let activo = true;
  try { activo = localStorage.getItem('a3d-sonido') !== 'no'; } catch (e) { /* sin almacenamiento: con sonido */ }

  function arrancar() {
    if (mudo) return;
    if (!ac) {
      ac = new AC();
      const comp = ac.createDynamicsCompressor();
      comp.threshold.value = -14; comp.ratio.value = 4;
      salida = ac.createGain();
      salida.gain.value = activo ? VOLUMEN : 0;
      salida.connect(comp).connect(ac.destination);
      const n = ac.sampleRate * 2, b = ac.createBuffer(1, n, ac.sampleRate), d = b.getChannelData(0);
      for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
      ruido = b;
      nuevoBus();
    }
    if (ac.state === 'suspended') ac.resume();
  }
  document.addEventListener('keydown', arrancar, true);
  document.addEventListener('pointerdown', arrancar, true);
  const listo = () => ac && ac.state === 'running';

  function nuevoBus() {
    if (bus) {
      const viejo = bus;
      viejo.gain.setTargetAtTime(0, ac.currentTime, 0.08);
      setTimeout(() => viejo.disconnect(), 600);
    }
    bus = ac.createGain();
    bus.connect(salida);
  }

  // ---- piezas
  // Un tono con su envolvente: sube en «ataque» y cae hasta el final. f2: el tono al acabar.
  function tono({ f, f2 = f, tipo = 'sine', t = 0, dur = 0.2, vol = 0.05, ataque = 0.005, corte = 0, destino = bus }) {
    const t0 = ac.currentTime + t, o = ac.createOscillator(), g = ac.createGain();
    o.type = tipo;
    o.frequency.setValueAtTime(f, t0);
    if (f2 !== f) o.frequency.exponentialRampToValueAtTime(f2, t0 + dur);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol, t0 + ataque);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    let ultimo = o;
    if (corte) { const fl = ac.createBiquadFilter(); fl.type = 'lowpass'; fl.frequency.value = corte; o.connect(fl); ultimo = fl; }
    ultimo.connect(g).connect(destino);
    o.start(t0); o.stop(t0 + dur + 0.05);
  }
  // Ruido filtrado: el filtro va de f a f2 durante el sonido. «forma»: cuándo llega al máximo (0–1 de la duración).
  function soplo({ t = 0, dur = 0.5, vol = 0.08, tipo = 'bandpass', f = 800, f2 = f, q = 0.8, forma = 0.4, destino = bus }) {
    const t0 = ac.currentTime + t, s = ac.createBufferSource(), fl = ac.createBiquadFilter(), g = ac.createGain();
    s.buffer = ruido; s.loop = true;
    fl.type = tipo; fl.Q.value = q;
    fl.frequency.setValueAtTime(f, t0);
    fl.frequency.exponentialRampToValueAtTime(f2, t0 + dur);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol, t0 + Math.max(0.01, dur * forma));
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    s.connect(fl).connect(g).connect(destino);
    s.start(t0, Math.random() * 1.5); s.stop(t0 + dur + 0.05);
  }
  const clic = (t, f, vol = 0.05) => tono({ f, t, dur: 0.045, vol, tipo: 'triangle' });
  const golpe = (t, vol = 0.22) => {          // (un golpe sordo, como algo que encaja)
    tono({ f: 140, f2: 48, t, dur: 0.32, vol });
    soplo({ t, dur: 0.07, vol: vol * 0.6, tipo: 'bandpass', f: 1800, f2: 900, q: 1.2, forma: 0.05 });
  };
  const brillo = (t, n, desde, hasta, vol = 0.02) => {
    for (let i = 0; i < n; i++) tono({ f: 2200 + Math.random() * 2600, t: desde + Math.random() * (hasta - desde), dur: 0.25, vol, ataque: 0.01 });
  };
  const acorde = (t, notas, dur, vol, tipo = 'sine', ataque = 0.6) => notas.forEach(f => tono({ f, t, dur, vol, tipo, ataque, corte: 2400 }));

  // ---- lo que suena en cada momento
  const ETAPAS = [
    // 0 · imagen: los cortes de la resonancia aparecen uno tras otro
    () => { for (let i = 0; i < 14; i++) clic(0.05 + i * 0.05, 1300 + i * 70, 0.035); },
    // 1 · segmentación: los cortes se comprimen en un bloque, golpe, y el barrido sube sacando las secciones
    () => {
      soplo({ dur: 0.95, vol: 0.09, tipo: 'lowpass', f: 3200, f2: 260, q: 0.6, forma: 0.6 });
      golpe(0.9, 0.2);
      const t0 = ac.currentTime + 1.2, o = ac.createOscillator(), fl = ac.createBiquadFilter(), g = ac.createGain();
      o.type = 'triangle';
      o.frequency.setValueAtTime(170, t0); o.frequency.linearRampToValueAtTime(340, t0 + 5.2);
      fl.type = 'lowpass'; fl.frequency.value = 900;
      g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(0.04, t0 + 0.4);
      g.gain.setValueAtTime(0.04, t0 + 4.8); g.gain.exponentialRampToValueAtTime(0.0001, t0 + 5.4);
      o.connect(fl).connect(g).connect(bus); o.start(t0); o.stop(t0 + 5.5);
      acorde(7.0, [523.3, 659.3, 784], 2.2, 0.025);
    },
    // 2 · modelo 3D: aparece la malla
    () => { [660, 880, 1320].forEach((f, i) => tono({ f, t: 0.6 + i * 0.09, dur: 0.16, vol: 0.045 })); soplo({ t: 0.55, dur: 0.4, vol: 0.03, tipo: 'highpass', f: 4000, f2: 6000 }); },
    // 3 · molde: las dos mitades se cierran, encajan y entran los tornillos
    () => {
      soplo({ t: 0.3, dur: 2.2, vol: 0.05, tipo: 'lowpass', f: 220, f2: 900, q: 0.7, forma: 0.85 });
      golpe(2.45, 0.13);
      for (let k = 0; k < 4; k++) for (let j = 0; j < 5; j++) clic(2.7 + k * 0.17 + j * 0.012, 2600 + 300 * j, 0.025);
    },
    // 4 · fabricación: la silicona entra y burbujea, cura, y el molde se abre
    () => {
      soplo({ t: 0.4, dur: 2.9, vol: 0.05, tipo: 'bandpass', f: 380, f2: 620, q: 2.5, forma: 0.3 });
      for (let i = 0; i < 18; i++) {
        const f = 260 + Math.random() * 420;
        tono({ f, f2: f * 1.7, t: 0.5 + Math.random() * 2.7, dur: 0.08, vol: 0.05, ataque: 0.004 });
      }
      tono({ f: 300, f2: 460, t: 3.0, dur: 1.5, vol: 0.025, ataque: 0.5 });
      tono({ f: 210, f2: 80, t: 3.7, dur: 0.16, vol: 0.1 });
      soplo({ t: 3.6, dur: 1.6, vol: 0.045, tipo: 'lowpass', f: 900, f2: 200, forma: 0.2 });
    },
    // 5 · gemelo digital: un acorde suave de holograma y destellos
    () => { acorde(0.1, [261.6, 329.6, 392, 493.9], 4.5, 0.022, 'triangle', 1.0); brillo(0, 10, 0.5, 3.5, 0.016); },
  ];

  // las notas de la red neuronal: bajan al comprimir y suben al ampliar
  const NOTAS_RED = [784, 659.3, 587.3, 523.3, 440, 523.3, 587.3, 659.3, 784];

  // el avión: ruido de reactor y el silbido de las turbinas, por un panorama estéreo
  function hacerMotor() {
    const m = { gain: ac.createGain(), pan: ac.createStereoPanner ? ac.createStereoPanner() : null, filtro: ac.createBiquadFilter(), oscs: [], z: 0 };
    m.gain.gain.value = 0;
    m.filtro.type = 'lowpass'; m.filtro.frequency.value = 800; m.filtro.Q.value = 0.5;
    const s = ac.createBufferSource(); s.buffer = ruido; s.loop = true;
    const gr = ac.createGain(); gr.gain.value = 0.9;
    s.connect(gr).connect(m.filtro);
    for (const [f, tipo, v] of [[96, 'sawtooth', 0.12], [97.3, 'sawtooth', 0.12], [1850, 'sine', 0.035]]) {
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = tipo; o.frequency.value = f; g.gain.value = v;
      o.connect(g).connect(m.filtro);
      o.start(); m.oscs.push(o);
    }
    s.start();
    m.filtro.connect(m.gain);
    if (m.pan) m.gain.connect(m.pan).connect(salida); else m.gain.connect(salida);
    return m;
  }

  // ---- el interruptor
  const boton = document.getElementById('sonido');
  function pintar() {
    if (!boton) return;
    boton.classList.toggle('apagado', !activo);
    boton.setAttribute('aria-pressed', String(!activo));
    boton.setAttribute('aria-label', activo ? 'Quitar el sonido (M)' : 'Poner el sonido (M)');
    boton.title = boton.getAttribute('aria-label');
  }
  function alternar() {
    activo = !activo;
    try { localStorage.setItem('a3d-sonido', activo ? 'si' : 'no'); } catch (e) { /* sin almacenamiento */ }
    if (ac) salida.gain.setTargetAtTime(activo ? VOLUMEN : 0, ac.currentTime, 0.05);
    pintar();
  }
  if (mudo) { if (boton) boton.hidden = true; }
  else {
    pintar();
    boton?.addEventListener('click', ev => { ev.stopPropagation(); arrancar(); alternar(); });
    document.addEventListener('keydown', ev => {
      if ((ev.key === 'm' || ev.key === 'M') && !ev.ctrlKey && !ev.altKey && !ev.metaKey) alternar();
    });
  }

  return {
    // al cambiar de diapositiva: se corta lo que sonaba y pasa un soplo suave
    pase() {
      if (!listo()) return;
      nuevoBus();
      soplo({ dur: 0.5, vol: 0.12, f: 320, f2: 1900, q: 0.7, forma: 0.35, destino: salida });
    },
    etapa(n) { if (!listo() || n < 0 || !ETAPAS[n]) return; nuevoBus(); ETAPAS[n](); },
    seccion(n) { if (listo()) clic(0, 560 + n * 38, 0.03); },
    neurona(k) {
      if (!listo()) return;
      tono({ f: NOTAS_RED[k], dur: 0.45, vol: 0.04, ataque: 0.01 });
      clic(0, 2400, 0.02);
      if (k === 8) brillo(0.05, 6, 0, 0.8, 0.015);
    },
    fase(n) {
      if (!listo()) return;
      if (n === 0) {          // las gafas escanean: un zumbido que barre, como el haz
        clic(0, 1320, 0.04);
        const t0 = ac.currentTime, fl = ac.createBiquadFilter(), g = ac.createGain(), lfo = ac.createOscillator(), lg = ac.createGain();
        fl.type = 'lowpass'; fl.frequency.value = 800; fl.Q.value = 6;
        lfo.frequency.value = 0.9; lg.gain.value = 500;
        lfo.connect(lg).connect(fl.frequency);
        g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(0.035, t0 + 0.3);
        g.gain.setValueAtTime(0.035, t0 + 3.2); g.gain.exponentialRampToValueAtTime(0.0001, t0 + 3.6);
        fl.connect(g).connect(bus);
        for (const f of [110, 110.7]) { const o = ac.createOscillator(); o.type = 'sawtooth'; o.frequency.value = f; o.connect(fl); o.start(t0); o.stop(t0 + 3.7); }
        lfo.start(t0); lfo.stop(t0 + 3.7);
      } else if (n === 1) {   // llega el gemelo y encaja
        soplo({ dur: 2.2, vol: 0.06, f: 400, f2: 1600, q: 1, forma: 0.8 });
        golpe(2.2, 0.16);
        tono({ f: 880, t: 2.2, dur: 0.25, vol: 0.035 }); tono({ f: 1318.5, t: 2.26, dur: 0.3, vol: 0.03 });
      } else if (n === 2) {   // se encienden las venas
        tono({ f: 400, f2: 1600, dur: 4.2, vol: 0.022, ataque: 0.8, corte: 3000 });
        brillo(0.3, 14, 0.3, 4.2, 0.016);
        acorde(3.9, [587.3, 880, 1174.7], 2.0, 0.02);
      }
    },
    // el contador: un tic por número (como mucho uno cada 45 ms) y una campana al llegar
    tic(k) { if (listo()) clic(0, 900 + 700 * k, 0.035); },
    campana() { if (listo()) { tono({ f: 1318.5, dur: 0.7, vol: 0.045 }); tono({ f: 1975.5, t: 0.02, dur: 0.8, vol: 0.03 }); } },
    // el cierre: «Ayúdanos a mejorar la medicina»
    final() {
      if (!listo()) return;
      nuevoBus();
      soplo({ dur: 1.4, vol: 0.06, tipo: 'lowpass', f: 300, f2: 2400, forma: 0.9 });
      acorde(0.9, [65.4, 98, 130.8, 196, 261.6], 4.5, 0.035, 'sine', 1.2);
    },
    // el avión: x de −1 (izquierda) a 1, z de −1 (detrás del coxis) a 1 (delante); null cuando no se ve
    avion(x, z, dt) {
      if (!listo()) return;
      if (x === null) { if (motor) motor.gain.gain.setTargetAtTime(0, ac.currentTime, 0.15); return; }
      if (!motor) motor = hacerMotor();
      const t = ac.currentTime, delante = (z + 1) / 2;
      motor.gain.gain.setTargetAtTime(0.05 + 0.25 * delante * delante, t, 0.08);
      motor.filtro.frequency.setTargetAtTime(350 + 2200 * delante * delante, t, 0.08);   // (detrás, el hueso lo apaga)
      if (motor.pan) motor.pan.pan.setTargetAtTime(Math.max(-1, Math.min(1, x * 0.85)), t, 0.08);
      // efecto Doppler: más agudo cuando se acerca, más grave cuando se aleja
      const acerca = dt > 0 ? (z - motor.z) / dt : 0;
      motor.z = z;
      for (const o of motor.oscs) o.detune.setTargetAtTime(Math.max(-1, Math.min(1, acerca / 0.63)) * 70, t, 0.1);
    },
  };
})();
