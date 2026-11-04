// Chromium (Playwright) para comunicacion/generar.py.
//   node navegador.cjs renders <url_presentacion> <carpeta> nombre=diapositiva ...   (escena 3D sola, sin texto ni HUD)
//   node navegador.cjs capturas <url_presentacion> <carpeta> [0,1,2...]             (diapositivas completas, para revisarlas)
//   node navegador.cjs pdf <url_dosier> <archivo.pdf>
const { chromium } = require('playwright');

(async () => {
  const [modo, url, destino, ...resto] = process.argv.slice(2);
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errores = [];
  try {
    if (modo === 'pdf') {
      const p = await b.newPage();
      p.on('pageerror', e => errores.push(e.message));
      await p.goto(url, { waitUntil: 'networkidle' });
      await p.evaluate(() => document.fonts.ready);
      await p.pdf({ path: destino, format: 'A4', printBackground: true, preferCSSPageSize: true });
    } else {
      const p = await b.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
      p.on('pageerror', e => errores.push(e.message));
      await p.goto(url + (modo === 'renders' ? '?export&limpio' : '?export'), { waitUntil: 'load' });
      await p.waitForFunction(() => window.__escenaLista === true, null, { timeout: 180000 });
      const lista = modo === 'renders' ? resto.map(x => x.split('='))
        : (resto[0] || '0,1,2,3,4,5,6,7,8').split(',').map(i => [`d${String(+i + 1).padStart(2, '0')}`, i]);
      for (const [nombre, i] of lista) {
        await p.evaluate(i => Reveal.slide(i), +i);
        await p.waitForTimeout(9000);  // (sin GPU, la escena tarda en llegar a su sitio)
        await p.screenshot({ path: `${destino}/${nombre}.png` });
        console.log('  ', nombre);
      }
    }
  } finally {
    await b.close();
  }
  if (errores.length) { console.error('Errores de la página:\n' + errores.join('\n')); process.exit(1); }
})();
