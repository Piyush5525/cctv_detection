/**
 * End-to-end check of ONE incident on a scratch API: open the map, select the incident, and verify the detail panel, media and the
 * dispatch map layer (markers at plan coordinates in [lng, lat], one route per required type from the incident location,
 * card distance = route distance, no stale/foreign services), then screenshot.
 * Usage: node docs/e2e_incident.js <label e.g. Fall> <required types comma list> <screenshot name> [baseUrl] [scripted:0|1]
 */
const path = require('path');
const { chromium } = require(path.join(__dirname, '..', 'frontend', 'node_modules', 'playwright'));
const [label, typesArg, shot, BASE = 'http://127.0.0.1:8010', scripted = '0'] = process.argv.slice(2);
const required = typesArg.split(',');
let failures = 0;
const check = (ok, text, extra = '') => { if (!ok) failures++; console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${text}${extra ? '  ' + extra : ''}`); };
const km = (a, b) => { const r = (d) => d * Math.PI / 180, h = Math.sin(r(b[1] - a[1]) / 2) ** 2 + Math.cos(r(a[1])) * Math.cos(r(b[1])) * Math.sin(r(b[0] - a[0]) / 2) ** 2; return 12742 * Math.asin(Math.sqrt(h)); };

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
  const failed = [];
  page.on('response', (r) => { if (r.url().includes('/evidence/') && r.status() >= 400) failed.push(`${r.status()} ${r.url().split('/').pop()}`); });
  await page.goto(`${BASE}/map`, { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForSelector('.camera-marker'); await page.waitForTimeout(3500);
  let found = false;
  for (const m of await page.$$('.camera-marker')) {
    await page.evaluate(() => window.scrollTo(0, 0));
    await m.click({ force: true }); await page.waitForTimeout(2200);
    const cat = await page.$eval('.detail-category', (e) => e.innerText).catch(() => '');
    if (cat.includes(label)) { found = true; break; }
  }
  check(found, `${label}: incident selectable on the map`);
  await page.waitForTimeout(2000);
  const s = await page.evaluate(async () => {
    const map = window.__dispatchMap, data = (id) => map?.getSource(id)?._data?.features || [];
    const src = document.querySelector('.detail-panel video')?.getAttribute('src') || '';
    const iid = src.split('/').slice(-2)[0];
    const inc = iid ? await (await fetch('/api/v1/incidents/' + iid)).json() : null;
    const v = document.querySelector('.detail-panel video');
    return { inc, services: data('dispatch-services').map((f) => ({ type: f.properties.type, rank: f.properties.rank, c: f.geometry.coordinates })),
             routes: data('dispatch-routes').map((f) => ({ type: f.properties.type, est: f.properties.estimated, c: f.geometry.coordinates })),
             badges: [...document.querySelectorAll('.detail-badges .honesty-badge')].map((e) => e.innerText),
             meta: [...document.querySelectorAll('.meta-item')].map((e) => e.innerText.replace(/\n/g, ': ')),
             cardRows: [...document.querySelectorAll('.dispatch-row')].map((e) => e.innerText.split('\n').slice(0, 3).join(' | ')),
             chips: [...document.querySelectorAll('.eta-chip')].map((e) => e.innerText), pins: document.querySelectorAll('.incident-pin').length,
             video: v ? { ready: v.readyState, err: v.error?.code ?? null, dur: v.duration } : null, errors: [...document.querySelectorAll('.media-error')].map((e) => e.innerText) };
  });
  const inc = s.inc;
  const here = [inc.longitude, inc.latitude];
  const plan = inc.dispatch_plan.assignments.filter((a) => a.status === 'available');
  check(JSON.stringify([...new Set(s.services.map((x) => x.type))].sort()) === JSON.stringify([...required].sort()), `${label}: markers only for ${required.join(' + ')}`, [...new Set(s.services.map((x) => x.type))].join(','));
  check(JSON.stringify(s.routes.map((r) => r.type).sort()) === JSON.stringify([...required].sort()), `${label}: one route per required type`);
  check(plan.every((a) => { const m = s.services.find((x) => x.type === a.service_category && x.rank === 'primary'); return m && m.c[0] === a.service.gps_coordinates.longitude && m.c[1] === a.service.gps_coordinates.latitude; }), `${label}: markers exactly at plan coordinates [lng, lat]`);
  check(s.routes.every((r) => km(r.c[0], here) < 0.3), `${label}: routes start at the incident location`);
  check(plan.every((a) => { const r = s.routes.find((x) => x.type === a.service_category); return r && km(r.c.at(-1), [a.service.gps_coordinates.longitude, a.service.gps_coordinates.latitude]) < 0.3; }), `${label}: routes end at their service`);
  check(s.pins === 1, `${label}: incident pin shown`);
  check(plan.every((a) => s.cardRows.some((row) => row.includes(a.service.title) && row.includes(`${a.route.distance_km} km`))), `${label}: card shows each service with the route distance`, s.cardRows.join(' // '));
  const straight = plan.filter((a) => a.route.route_source !== 'mapbox_driving');
  check(straight.every((a) => s.routes.find((r) => r.type === a.service_category).est === true), `${label}: straight-line routes are dashed/estimated`, `route sources: ${plan.map((a) => a.route.route_source).join(',')}`);
  check(s.video && s.video.err === null && s.video.dur > 0 && s.errors.length === 0 && failed.length === 0, `${label}: photo and clip load`, `dur=${s.video?.dur?.toFixed(1)}s ${failed.join(',')}`);
  if (scripted === '1') {
    check(s.badges.includes('SCRIPTED DEMO') && s.badges.includes('EXPERIMENTAL'), `${label}: SCRIPTED DEMO + EXPERIMENTAL badges`);
    check(s.meta.some((t) => /Not scored/.test(t)) && inc.detection.peak_confidence === null, `${label}: confidence shown as Not scored (null stored)`);
  } else {
    check(!s.badges.includes('SCRIPTED DEMO'), `${label}: not labelled scripted`);
  }
  console.log(`  plan: ${plan.map((a) => `${a.service_category}=${a.service.title} ${a.route.distance_km}km ${a.route.eta_minutes}min (${a.route.route_source})`).join(' | ')}`);
  await page.screenshot({ path: path.join(__dirname, 'screenshots', `${shot}.png`) });
  await browser.close();
  process.exit(failures ? 1 : 0);
})();
