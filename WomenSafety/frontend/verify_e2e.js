/**
 * End-to-end verification + screenshot capture for the hackathon dashboard.
 * Run from frontend/: node verify_e2e.js
 * Requires: backend on :8000, frontend on :3001
 */
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE = 'http://localhost:3001';
const OUT = path.join(__dirname, '..', 'docs', 'screenshots');

// Ensure output dir
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  console.log('=== Hackathon Dashboard E2E Verification ===\n');

  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (e) {
    console.log('ERROR: Could not launch Chromium. Run: npx playwright install chromium');
    console.log(e.message);
    process.exit(1);
  }

  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });

  const page = await context.newPage();

  // Collect errors
  const consoleErrors = [];
  const failedRequests = [];
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', err => consoleErrors.push(`PAGE ERROR: ${err.message}`));
  page.on('requestfailed', req => {
    failedRequests.push(`${req.method()} ${req.url()} => ${req.failure()?.errorText || 'unknown'}`);
  });

  // ─── 1. Map overview ─────────────────────────────────────────────
  console.log('1. Loading map overview...');
  try {
    await page.goto(`${BASE}/map`, { waitUntil: 'networkidle', timeout: 30000 });
  } catch (e) {
    console.log(`   FAIL: Could not load ${BASE}/map — ${e.message}`);
    console.log('   Make sure both backend (:8000) and frontend (:3001) are running.');
    await browser.close();
    process.exit(1);
  }

  await page.waitForTimeout(5000); // Let map tiles + markers render

  // Check key elements
  const elChecks = [
    ['DEMO MODE badge', '.demo-mode-badge'],
    ['Page title h1', '.demo-title'],
    ['Overview button', '.overview-btn'],
    ['Map container', '.map-container'],
    ['Legend', '.map-legend'],
    ['Detail panel', '.detail-panel'],
  ];

  for (const [name, sel] of elChecks) {
    const el = await page.$(sel);
    console.log(`   ${el ? '✓' : '✗'} ${name}`);
  }

  const markers = await page.$$('.camera-marker');
  console.log(`   ${markers.length > 0 ? '✓' : '✗'} Camera markers: ${markers.length} found`);

  await page.screenshot({ path: path.join(OUT, '01_map_overview.png'), fullPage: false });
  console.log('   📸 Saved 01_map_overview.png\n');

  // ─── 2. Hover slideshow ───────────────────────────────────────────
  console.log('2. Hover popup...');
  if (markers.length > 0) {
    const box = await markers[0].boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.waitForTimeout(2000);

      const hoverPopup = await page.$('.hover-popup');
      console.log(`   ${hoverPopup ? '✓' : '✗'} Hover popup appeared`);

      await page.screenshot({ path: path.join(OUT, '02_hover_slideshow.png'), fullPage: false });
      console.log('   📸 Saved 02_hover_slideshow.png\n');
    }
  } else {
    console.log('   ⚠ No markers to hover\n');
  }

  // ─── 3. Detail view (click marker) ───────────────────────────────
  console.log('3. Detail view...');
  if (markers.length > 0) {
    await markers[0].click();
    await page.waitForTimeout(3000);

    const detailSel = [
      ['Category heading', '.detail-category'],
      ['Detection metadata', '.detail-meta-grid'],
      ['Status buttons', '.detail-actions'],
      ['Video player', '.detail-video'],
      ['Best frame img', '.detail-best-frame'],
      ['Honesty badge', '.honesty-badge'],
    ];

    for (const [name, sel] of detailSel) {
      const el = await page.$(sel);
      console.log(`   ${el ? '✓' : '✗'} ${name}`);
    }

    // Check text sections
    const headings = await page.$$eval('h3', hs => hs.map(h => h.textContent));
    console.log(`   ${headings.some(h => h.includes('Notification')) ? '✓' : '✗'} Notification Timeline heading`);
    console.log(`   ${headings.some(h => h.includes('Dispatch')) ? '✓' : '✗'} Dispatch Plan heading`);

    await page.screenshot({ path: path.join(OUT, '03_detail_view.png'), fullPage: false });
    console.log('   📸 Saved 03_detail_view.png');

    // Scroll detail panel down
    const detailPanel = await page.$('.detail-panel');
    if (detailPanel) {
      await detailPanel.evaluate(el => el.scrollTop = el.scrollHeight);
      await page.waitForTimeout(500);
      await page.screenshot({ path: path.join(OUT, '04_detail_timeline_dispatch.png'), fullPage: false });
      console.log('   📸 Saved 04_detail_timeline_dispatch.png\n');
    }
  }

  // ─── 4. Live cameras panel ────────────────────────────────────────
  console.log('4. Live cameras panel...');
  const livePanel = await page.$('#live-cameras-panel');
  console.log(`   ${livePanel ? '✓' : '✗'} Live cameras section exists`);

  if (livePanel) {
    await livePanel.scrollIntoViewIfNeeded();
    await page.waitForTimeout(1000);
  }
  await page.screenshot({ path: path.join(OUT, '05_live_cameras.png'), fullPage: false });
  console.log('   📸 Saved 05_live_cameras.png\n');

  // ─── 5. Trigger + pulse ───────────────────────────────────────────
  console.log('5. New-incident pulse...');
  await page.goto(`${BASE}/map`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(3000);

  try {
    const resp = await page.evaluate(async () => {
      const r = await fetch('/api/v1/demo/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ camera_id: 'CAM-SAMPLE-001', category: 'fire' }),
      });
      return { status: r.status, ok: r.ok };
    });
    console.log(`   ${resp.ok ? '✓' : '✗'} Demo trigger API: ${resp.status}`);
  } catch (e) {
    console.log(`   ✗ Demo trigger failed: ${e.message}`);
  }

  await page.waitForTimeout(4000);
  const pulsingMarkers = await page.$$('.camera-marker.pulse');
  console.log(`   ${pulsingMarkers.length > 0 ? '✓' : '○'} Pulsing markers: ${pulsingMarkers.length}`);

  await page.screenshot({ path: path.join(OUT, '06_new_incident_pulse.png'), fullPage: false });
  console.log('   📸 Saved 06_new_incident_pulse.png\n');

  // ─── Report ───────────────────────────────────────────────────────
  console.log('=== Console Errors ===');
  // Filter out noise
  const real = consoleErrors.filter(e =>
    !e.includes('net::') && !e.includes('favicon') && !e.includes('WebSocket')
  );
  if (real.length === 0) {
    console.log('None (clean) ✓');
  } else {
    real.forEach(e => console.log(` ✗ ${e}`));
  }
  if (consoleErrors.length > real.length) {
    console.log(` (${consoleErrors.length - real.length} network/WS messages suppressed)`);
  }

  console.log('\n=== Failed Network Requests ===');
  if (failedRequests.length === 0) {
    console.log('None ✓');
  } else {
    failedRequests.forEach(r => console.log(` ✗ ${r}`));
  }

  console.log('\n=== Screenshots ===');
  const files = fs.readdirSync(OUT).filter(f => f.endsWith('.png'));
  files.forEach(f => {
    const size = fs.statSync(path.join(OUT, f)).size;
    console.log(` ${f} (${Math.round(size / 1024)} KB)`);
  });

  console.log(`\nTotal: ${files.length} screenshots captured.`);
  await browser.close();
  console.log('Done.');
})();
