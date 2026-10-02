/**
 * 1920x1080 screenshots of the map + detail panel + dispatch card for ONE incident category (DISPATCH_RULES check).
 *
 * Usage: node docs/take_rules_screenshots.js <name> [baseUrl]
 *   writes docs/screenshots/rules_<name>_full.png and rules_<name>_card.png
 * The dashboard is served by the API itself (frontend/build), default http://127.0.0.1:8010 (a scratch instance).
 * Name fixtures with a "fixture_" prefix: they are UI rendering fixtures, not detections.
 */
const path = require('path');
const { chromium } = require(path.join(__dirname, '..', 'frontend', 'node_modules', 'playwright'));

const name = process.argv[2];
const BASE = process.argv[3] || 'http://127.0.0.1:8010';
const OUT = path.join(__dirname, 'screenshots');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(`${BASE}/map`, { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForTimeout(4000);
  const marker = await page.$('.camera-marker');
  if (!marker) { console.log('NO MARKER FOUND'); await browser.close(); process.exit(1); }
  await marker.click();
  await page.waitForTimeout(3000);
  await page.screenshot({ path: path.join(OUT, `rules_${name}_full.png`) });
  const detail = await page.$('.detail-panel');
  if (detail) await detail.evaluate((el) => { el.scrollTop = el.scrollHeight; });
  await page.waitForTimeout(600);
  const card = await page.$('.dispatch-list');
  if (card) await card.screenshot({ path: path.join(OUT, `rules_${name}_card.png`) });
  const rows = await page.$$eval('.dispatch-row', (els) => els.map((e) => e.innerText.split('\n').slice(0, 3).join(' | ')));
  console.log(`${name}: dispatch rows ->`, JSON.stringify(rows));
  const badges = await page.$$eval('.detail-badges .honesty-badge', (els) => els.map((e) => e.innerText));
  console.log(`${name}: badges ->`, JSON.stringify(badges), '| page errors:', errors.length);
  await browser.close();
})();
