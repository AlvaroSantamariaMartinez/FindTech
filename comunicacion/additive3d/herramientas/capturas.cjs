// Una imagen por diapositiva, para revisarlas (Chromium de Playwright, sin tarjeta gráfica).
//   node capturas.cjs URL CARPETA [lista]      lista: 0,1,…  y «7:3» es la diapositiva 7 en la etapa 3 de la simulación
//                                              («7:1:4» la saca a los 4 s de empezar esa etapa); «12:f» es la
//                                              diapositiva 12 con su segundo acto
const { chromium } = require('playwright');

(async () => {
  const [url, destino, lista] = process.argv.slice(2);
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const errores = [];
  try {
    const p = await b.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
    p.on('pageerror', e => errores.push(e.message));
    p.on('console', m => { if (m.type() === 'error') errores.push(m.text()); });
    await p.goto(url + (url.includes('?') ? '&' : '?') + 'export', { waitUntil: 'load' });
    await p.waitForFunction(() => window.__escenaLista === true, null, { timeout: 180000 });
    const n = await p.evaluate(() => document.querySelectorAll('.reveal .slides > section').length);
    const pasos = (lista || [...Array(n).keys()].join(',')).split(',');
    for (const paso of pasos) {
      const [i, extra, espera] = paso.split(':');
      await p.evaluate(i => Reveal.slide(i), +i);
      if (extra === 'f') await p.evaluate(() => Reveal.nextFragment());
      else if (extra !== undefined) await p.evaluate(e => window.__etapa(e), +extra);
      await p.waitForTimeout(espera ? +espera * 1000 : extra !== undefined && extra !== 'f' ? 7000 : 5000);
      const nombre = `d${String(+i + 1).padStart(2, '0')}${extra !== undefined ? '-' + extra : ''}${espera ? '-' + espera + 's' : ''}`;
      await p.screenshot({ path: `${destino}/${nombre}.png` });
      console.log('  ', nombre);
    }
  } finally {
    await b.close();
  }
  if (errores.length) { console.error('Errores de la página:\n' + errores.join('\n')); process.exit(1); }
})();
