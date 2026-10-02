/**
 * Diagnostic: for each camera marker, open the incident in headless Chrome (1920x1080) and record how its media loads.
 * Usage: node docs/diag_media.js [baseUrl]   (default http://127.0.0.1:8010, a scratch API)
 * Prints one JSON object per incident: request URLs (relative), status, content-type, size, Range result, element sizes,
 * video state, whether polling reloaded the <video>, console errors and failed requests. Never prints secrets.
 */
const path = require('path');
const { chromium } = require(path.join(__dirname, '..', 'frontend', 'node_modules', 'playwright'));
const BASE = process.argv[2] || 'http://127.0.0.1:8010';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const probe = await (await browser.newContext()).newPage();
  await probe.goto(`${BASE}/map`, { waitUntil: 'domcontentloaded' });
  const count = await (async () => { await probe.waitForSelector('.camera-marker', { timeout: 30000 }); return (await probe.$$('.camera-marker')).length; })();
  await probe.close();

  for (let idx = 0; idx < count; idx++) {
    const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
    const out = { marker: idx, requests: [], consoleErrors: [], failed: [] };
    page.on('console', (m) => { if (m.type() === 'error') out.consoleErrors.push(m.text().slice(0, 160)); });
    page.on('pageerror', (e) => out.consoleErrors.push('pageerror: ' + e.message.slice(0, 160)));
    page.on('requestfailed', (r) => out.failed.push(r.url().replace(BASE, '').slice(0, 120) + ' ' + (r.failure()?.errorText || '')));
    page.on('response', async (res) => {
      const u = res.url();
      if (!u.includes('/evidence/')) return;
      const h = res.headers();
      out.requests.push({ url: u.replace(BASE, ''), status: res.status(), type: h['content-type'], len: h['content-length'], ranges: h['accept-ranges'], range: h['content-range'] });
    });
    await page.goto(`${BASE}/map`, { waitUntil: 'networkidle', timeout: 45000 });
    await page.waitForTimeout(3500);
    const markers = await page.$$('.camera-marker');
    await markers[idx].hover();
    await page.waitForTimeout(1200);
    out.slideshow = await page.$$eval('.hover-popup img', (els) => els.map((e) => ({ src: e.getAttribute('src'), natural: `${e.naturalWidth}x${e.naturalHeight}`, shown: `${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`, fit: getComputedStyle(e).objectFit })));
    await markers[idx].click();
    await page.waitForTimeout(3000);
    out.category = await page.$eval('.detail-category', (e) => e.innerText).catch(() => null);
    out.detailImg = await page.$$eval('.detail-panel img', (els) => els.map((e) => ({ src: e.getAttribute('src'), natural: `${e.naturalWidth}x${e.naturalHeight}`, shown: `${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`, fit: getComputedStyle(e).objectFit })));
    // Range probes for the four files, from the page origin (same as the app)
    out.probe = await page.evaluate(async () => {
      const v = document.querySelector('.detail-panel video');
      const base = (v?.getAttribute('src') || '').replace(/clip\.mp4$/, '');
      const res = {};
      for (const name of ['thumbnail.jpg', 'best_frame.jpg', 'annotated_frame.jpg', 'clip.mp4']) {
        try {
          const r = await fetch(base + name, { headers: { Range: 'bytes=0-99' } });
          const full = await fetch(base + name, { method: 'HEAD' });
          res[name] = { range: r.status, contentRange: r.headers.get('content-range'), acceptRanges: r.headers.get('accept-ranges'), type: r.headers.get('content-type'), headStatus: full.status, headLen: full.headers.get('content-length') };
        } catch (e) { res[name] = { error: String(e).slice(0, 80) }; }
      }
      return res;
    });
    // polling check: tag the <video>, count loadstart over 7 s (the page polls every 2 s)
    out.pollCheck = await page.evaluate(() => new Promise((resolve) => {
      const v = document.querySelector('.detail-panel video');
      if (!v) return resolve({ video: false });
      v.__tag = 'same'; let loads = 0; v.addEventListener('loadstart', () => loads++);
      const startedAt = v.currentTime;
      setTimeout(() => resolve({ sameElement: document.querySelector('.detail-panel video')?.__tag === 'same', loadstartEvents: loads }), 7000);
    }));
    out.video = await page.evaluate(() => {
      const v = document.querySelector('.detail-panel video');
      return v ? { readyState: v.readyState, networkState: v.networkState, error: v.error ? v.error.code : null, size: `${v.videoWidth}x${v.videoHeight}`, duration: v.duration, shown: `${Math.round(v.getBoundingClientRect().width)}x${Math.round(v.getBoundingClientRect().height)}`, fit: getComputedStyle(v).objectFit, poster: v.getAttribute('poster') } : null;
    });
    out.panelOverflowX = await page.$eval('.detail-panel', (e) => e.scrollWidth > e.clientWidth).catch(() => null);
    out.requests = out.requests.filter((r, i, a) => a.findIndex((x) => x.url === r.url && x.status === r.status) === i);
    console.log(JSON.stringify(out));
    await page.context().close();
  }
  await browser.close();
})();
