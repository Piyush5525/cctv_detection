/**
 * Hackathon screenshot capture script.
 * Takes 1920x1080 screenshots of the dashboard for docs/screenshots/.
 *
 * Usage: node docs/take_screenshots.js
 * Requires: backend on :8000, frontend on :3001
 */
const { chromium } = require('playwright');
const path = require('path');

const BASE = 'http://localhost:3001';
const OUT = path.join(__dirname, 'screenshots');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });

  const page = await context.newPage();

  // Collect console errors
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', err => errors.push(err.message));

  // 1. Map overview
  console.log('1. Map overview...');
  await page.goto(`${BASE}/map`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(4000); // Let map tiles + markers render
  await page.screenshot({ path: path.join(OUT, '01_map_overview.png'), fullPage: false });
  console.log('   ✓ saved 01_map_overview.png');

  // 2. Hover slideshow — hover over the first camera marker
  console.log('2. Hover slideshow...');
  const markers = await page.$$('.camera-marker');
  if (markers.length > 0) {
    await markers[0].hover();
    await page.waitForTimeout(1500); // Let hover popup appear
    await page.screenshot({ path: path.join(OUT, '02_hover_slideshow.png'), fullPage: false });
    console.log('   ✓ saved 02_hover_slideshow.png');
  } else {
    console.log('   ⚠ no markers found, skipping hover');
  }

  // 3. Detail view — click the first camera marker
  console.log('3. Detail view...');
  if (markers.length > 0) {
    await markers[0].click();
    await page.waitForTimeout(2500); // Let detail panel load
    await page.screenshot({ path: path.join(OUT, '03_detail_view.png'), fullPage: false });
    console.log('   ✓ saved 03_detail_view.png');

    // Scroll the detail panel to show timeline and dispatch
    const detail = await page.$('.detail-panel');
    if (detail) {
      await detail.evaluate(el => el.scrollTop = el.scrollHeight);
      await page.waitForTimeout(500);
      await page.screenshot({ path: path.join(OUT, '04_detail_timeline_dispatch.png'), fullPage: false });
      console.log('   ✓ saved 04_detail_timeline_dispatch.png');
    }
  }

  // 4. Live cameras panel — scroll down
  console.log('4. Live cameras panel...');
  await page.evaluate(() => {
    const el = document.getElementById('live-cameras-panel');
    if (el) el.scrollIntoView({ behavior: 'instant' });
  });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(OUT, '05_live_cameras.png'), fullPage: false });
  console.log('   ✓ saved 05_live_cameras.png');

  // 5. Trigger a new incident for pulse screenshot
  console.log('5. New-incident pulse...');
  // Go back to map overview first
  await page.goto(`${BASE}/map`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(3000);
  // Trigger via API
  try {
    await page.evaluate(async () => {
      await fetch('/api/v1/demo/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ camera_id: 'CAM-SAMPLE-001', category: 'fire' }),
      });
    });
    await page.waitForTimeout(3000); // Wait for poll + pulse
  } catch (e) {
    console.log('   ⚠ trigger failed:', e.message);
  }
  await page.screenshot({ path: path.join(OUT, '06_new_incident_pulse.png'), fullPage: false });
  console.log('   ✓ saved 06_new_incident_pulse.png');

  // Report console errors
  console.log('\n--- Console errors ---');
  if (errors.length === 0) {
    console.log('None');
  } else {
    errors.forEach(e => console.log(' ✗', e));
  }

  // Check for failed network requests
  console.log('\n--- Failed network requests ---');
  const failedRequests = [];
  page.on('requestfailed', req => failedRequests.push(`${req.method()} ${req.url()} → ${req.failure().errorText}`));

  // Reload to capture any failures
  await page.goto(`${BASE}/map`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(3000);

  if (failedRequests.length === 0) {
    console.log('None');
  } else {
    failedRequests.forEach(r => console.log(' ✗', r));
  }

  await browser.close();
  console.log('\nDone.');
})();
