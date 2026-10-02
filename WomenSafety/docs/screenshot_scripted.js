/**
 * 1920x1080 screenshots of SCRIPTED demo incidents: map marker + popup with the badge, the detail panel with the photo and the
 * clip playing, the scripted note, and the Demo panel (toggles + tooltips).
 * Usage: node docs/screenshot_scripted.js [baseUrl]   (a scratch API holding scripted incidents; default http://127.0.0.1:8010)
 */
const path = require('path');
const { chromium } = require(path.join(__dirname, '..', 'frontend', 'node_modules', 'playwright'));
const BASE = process.argv[2] || 'http://127.0.0.1:8010';
const OUT = path.join(__dirname, 'screenshots');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(`${BASE}/map`, { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForSelector('.camera-marker');
  await page.waitForTimeout(3500);
  const n = (await page.$$('.camera-marker')).length;
  const seen = new Set();
  for (let i = 0; i < n; i++) {
    await page.evaluate(() => window.scrollTo(0, 0));
    const m = (await page.$$('.camera-marker'))[i];
    await m.hover(); await page.waitForTimeout(1200);
    const popup = await page.$eval('.hover-popup', (e) => e.innerText.replace(/\n+/g, ' | ')).catch(() => '');
    const cat = (popup.match(/Violence|Fall|Snatching|Snatch/) || [''])[0].toLowerCase().replace('snatch', 'snatching').replace('snatchingining', 'snatching');
    if (!cat || seen.has(cat)) continue;
    seen.add(cat);
    console.log(`${cat}: popup -> ${popup}`);
    await page.screenshot({ path: path.join(OUT, `scripted_${cat}_1_marker_popup.png`) });
    await m.click({ force: true }); await page.waitForTimeout(3000);
    const state = await page.evaluate(async () => {
      const v = document.querySelector('.detail-panel video'); v.muted = true;
      await new Promise((r) => { if (v.readyState >= 1) r(); else { v.addEventListener('loadedmetadata', r, { once: true }); setTimeout(r, 5000); } });
      v.currentTime = Math.max(v.duration / 2, 0.5);
      await new Promise((r) => { v.addEventListener('seeked', r, { once: true }); setTimeout(r, 3000); });
      await v.play(); await new Promise((r) => setTimeout(r, 900));
      return { t: +v.currentTime.toFixed(1), dur: +v.duration.toFixed(1), paused: v.paused,
               badges: [...document.querySelectorAll('.detail-badges .honesty-badge')].map((e) => e.innerText),
               meta: [...document.querySelectorAll('.meta-item')].map((e) => e.innerText.replace(/\n/g, ': ')),
               panel: document.querySelector('.scripted-panel')?.innerText.replace(/\n+/g, ' | ').slice(0, 260) };
    });
    console.log(`${cat}: detail ->`, JSON.stringify(state));
    await page.screenshot({ path: path.join(OUT, `scripted_${cat}_2_detail_playing.png`) });
    await page.evaluate(() => { const d = document.querySelector('.detail-panel'); d.scrollTop = d.scrollHeight; });
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(OUT, `scripted_${cat}_3_detail_note.png`) });
    await page.click('.detail-close'); await page.waitForTimeout(800);
  }
  // Demo panel: category picker (tooltips), scripted auto-call toggle, dry run
  await page.keyboard.press('Control+Shift+D'); await page.waitForTimeout(1500);
  const opts = await page.$$eval('.demo-select[aria-label="Trigger category"] option', (els) => els.map((e) => `${e.innerText.trim()} [title: ${(e.getAttribute('title') || '').slice(0, 60)}]`));
  console.log('picker:', JSON.stringify(opts));
  await page.screenshot({ path: path.join(OUT, 'scripted_demo_panel.png') });
  console.log('page errors:', errors.length);
  await browser.close();
})();
