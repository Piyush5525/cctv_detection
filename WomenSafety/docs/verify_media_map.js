/**
 * Browser verification of the evidence media and the dispatch map layer, plus the 1920x1080 screenshots.
 * Usage: node docs/verify_media_map.js [baseUrl]   (a SCRATCH API with the showcase loaded; default http://127.0.0.1:8010)
 * Checks (prints PASS/FAIL lines): service markers sit at the plan coordinates in [lng, lat]; one route per required type
 * starting at the incident and ending at the service; fire = fire station + hospital only, crash = hospital + police only;
 * routes clear when the selection changes or closes; the <video> element is not reloaded by polling; media error state shows
 * a reason and a Retry; offline tiles keep the dispatch layer working.
 */
const path = require('path');
const { chromium } = require(path.join(__dirname, '..', 'frontend', 'node_modules', 'playwright'));
const BASE = process.argv[2] || 'http://127.0.0.1:8010';
const OUT = path.join(__dirname, 'screenshots');
let failures = 0;
const check = (ok, label, extra = '') => { if (!ok) failures++; console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${extra ? '  ' + extra : ''}`); };

async function newPage(browser, setup) {
  const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
  if (setup) await setup(page);
  await page.goto(`${BASE}/map`, { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForSelector('.camera-marker', { timeout: 30000 });
  await page.waitForTimeout(3500);
  return page;
}

async function select(page, category, minDuration = 0) {
  const n = (await page.$$('.camera-marker')).length;
  for (let i = 0; i < n; i++) {
    await page.evaluate(() => window.scrollTo(0, 0));
    const m = (await page.$$('.camera-marker'))[i];
    await m.click({ force: true });
    await page.waitForTimeout(1800);
    const cat = await page.$eval('.detail-category', (e) => e.innerText).catch(() => '');
    if (!cat.includes(category)) continue;
    const dur = await page.evaluate(async () => { const v = document.querySelector('.detail-panel video'); if (!v) return 0; await new Promise((r) => { if (v.readyState >= 1) r(); else { v.addEventListener('loadedmetadata', r, { once: true }); setTimeout(r, 4000); } }); return v.duration || 0; });
    if (dur >= minDuration) return true;
  }
  return false;
}

// What the map is actually drawing + the plan the API holds for the selected incident
async function mapState(page) {
  return page.evaluate(async () => {
    const map = window.__dispatchMap;
    const data = (id) => map?.getSource(id)?._data?.features || [];
    const clip = document.querySelector('.detail-panel video')?.getAttribute('src') || '';
    const iid = clip.split('/').slice(-2)[0];
    const inc = iid ? await (await fetch('/api/v1/incidents/' + iid)).json() : null;
    return { services: data('dispatch-services').map((f) => ({ type: f.properties.type, rank: f.properties.rank, c: f.geometry.coordinates })),
             routes: data('dispatch-routes').map((f) => ({ type: f.properties.type, est: f.properties.estimated, c: f.geometry.coordinates })),
             plan: inc?.dispatch_plan || null, here: inc ? [inc.longitude, inc.latitude] : null,
             bounds: map ? map.getBounds().toArray() : null, pin: document.querySelectorAll('.incident-pin').length, chips: [...document.querySelectorAll('.eta-chip')].map((e) => e.innerText) };
  });
}

const kmBetween = (a, b) => { const r = (d) => d * Math.PI / 180, h = Math.sin(r(b[1] - a[1]) / 2) ** 2 + Math.cos(r(a[1])) * Math.cos(r(b[1])) * Math.sin(r(b[0] - a[0]) / 2) ** 2; return 12742 * Math.asin(Math.sqrt(h)); };

function verifyMap(label, s, requiredTypes) {
  const prim = s.plan.assignments.filter((a) => a.status === 'available');
  const types = [...new Set(s.services.map((x) => x.type))].sort();
  check(JSON.stringify(types) === JSON.stringify([...requiredTypes].sort()), `${label}: markers only for ${requiredTypes.join(' + ')}`, `drawn=${types.join(',')}`);
  check(JSON.stringify(s.routes.map((r) => r.type).sort()) === JSON.stringify([...requiredTypes].sort()), `${label}: one route per required type`, `routes=${s.routes.map((r) => r.type).join(',')}`);
  let exact = true;
  for (const a of prim) {
    const want = [a.service.gps_coordinates.longitude, a.service.gps_coordinates.latitude];
    const m = s.services.find((x) => x.type === a.service_category && x.rank === 'primary');
    if (!m || m.c[0] !== want[0] || m.c[1] !== want[1]) exact = false;
  }
  check(exact, `${label}: every service marker is exactly at its plan position, [lng, lat]`);
  const startOk = s.routes.every((r) => kmBetween(r.c[0], s.here) < 0.3);
  check(startOk, `${label}: every route starts at the incident location (within 300 m of the road snap)`);
  const endOk = s.routes.every((r) => { const a = prim.find((x) => x.service_category === r.type); return kmBetween(r.c.at(-1), [a.service.gps_coordinates.longitude, a.service.gps_coordinates.latitude]) < 0.3; });
  check(endOk, `${label}: every route ends at its service (within 300 m of the road snap)`);
  const inView = [...s.services.map((x) => x.c), s.here].every(([lng, lat]) => lng >= s.bounds[0][0] - 1e-6 && lng <= s.bounds[1][0] + 1e-6 && lat >= s.bounds[0][1] - 1e-6 && lat <= s.bounds[1][1] + 1e-6);
  check(inView, `${label}: map fitted to the incident plus its services`, inView ? '' : JSON.stringify({ bounds: s.bounds, pts: [...s.services.map((x) => x.c), s.here] }));
  check(s.pin === 1, `${label}: a distinct incident pin is shown`);
  const cardKm = prim.map((a) => a.route.distance_km);
  check(s.chips.length === s.routes.length || s.routes.some((r, i) => cardKm[i] < 0.3), `${label}: ETA chips match routes`, s.chips.join(' | '));
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await newPage(browser);

  for (const [cat, req, tag] of [['Road Accident', ['hospital', 'police'], 'crash'], ['Fire', ['fire_station', 'hospital'], 'fire']]) {
    check(await select(page, cat, 10), `selected a ${tag} incident with a real clip (10 s or more)`);
    await page.waitForTimeout(1500);   // let the fit animation finish
    const s = await mapState(page);
    verifyMap(tag, s, req);
    // media: slideshow hover, detail photo, annotated toggle, video seek+play
    const marker = (await page.$$('.camera-marker'))[0];
    await page.screenshot({ path: path.join(OUT, `media_${tag}_1_map_and_detail.png`) });
    await page.click('.media-toggle button:nth-child(2)'); await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(OUT, `media_${tag}_2_annotated.png`) });
    const annotatedShown = await page.$eval('.detail-panel .media-frame img', (e) => e.src.includes('annotated_frame.jpg') && e.naturalWidth > 0);
    check(annotatedShown, `${tag}: annotated frame loads through the toggle`);
    await page.click('.media-toggle button:nth-child(1)'); await page.waitForTimeout(1000);
    const origShown = await page.$eval('.detail-panel .media-frame img', (e) => e.src.includes('best_frame.jpg') && e.naturalWidth > 0);
    check(origShown, `${tag}: original frame loads through the toggle`);
    const playing = await page.evaluate(async () => {
      const v = document.querySelector('.detail-panel video'); v.muted = true;
      await new Promise((r) => (v.readyState >= 1 ? r() : v.addEventListener('loadedmetadata', r, { once: true })));
      v.currentTime = Math.max(v.duration / 4, 0.5);
      await new Promise((r) => v.addEventListener('seeked', r, { once: true }));
      await v.play(); await new Promise((r) => setTimeout(r, 700));
      return { t: v.currentTime, dur: v.duration, paused: v.paused, seekedMid: v.currentTime >= v.duration / 4 - 0.1 };
    });
    check(playing.seekedMid && !playing.paused, `${tag}: video seeks (206) and plays mid-clip`, `t=${playing.t.toFixed(1)}/${playing.dur.toFixed(1)}s`);
    await page.screenshot({ path: path.join(OUT, `media_${tag}_3_video_playing.png`) });
    const shown = await page.$$eval('.detail-panel .media-frame', (els) => els.map((e) => { const r = e.getBoundingClientRect(); return +(r.width / r.height).toFixed(2); }));
    check(shown.every((x) => Math.abs(x - 1.78) < 0.03), `${tag}: media containers are 16:9`, shown.join(','));
    // polling must not reload the playing video
    const reload = await page.evaluate(() => new Promise((resolve) => { const v = document.querySelector('.detail-panel video'); v.__tag = 'same'; let n = 0; v.addEventListener('loadstart', () => n++); setTimeout(() => resolve({ same: document.querySelector('.detail-panel video')?.__tag === 'same', loadstarts: n, paused: v.paused }), 6500); }));
    check(reload.same && reload.loadstarts === 0 && !reload.paused, `${tag}: 2 s polling does not reload or stop the playing video`, JSON.stringify(reload));
  }

  // hover slideshow
  const first = (await page.$$('.camera-marker'))[0];
  await first.hover(); await page.waitForTimeout(1200);
  const slide = await page.$$eval('.hover-popup img', (els) => els.map((e) => { const r = e.getBoundingClientRect(); return { ratio: +(r.width / r.height).toFixed(2), fit: getComputedStyle(e).objectFit, lazy: e.loading, nat: `${e.naturalWidth}x${e.naturalHeight}` }; }));
  check(slide.length === 1 && Math.abs(slide[0].ratio - 1.78) < 0.03 && slide[0].fit === 'cover' && slide[0].lazy === 'lazy', 'slideshow thumbnail: fixed 16:9, object-fit cover, lazy', JSON.stringify(slide));
  await page.screenshot({ path: path.join(OUT, 'media_slideshow_hover.png') });
  await page.mouse.move(5, 5);

  // routes clear on selection change and on close
  await select(page, 'Fire', 10);
  let s = await mapState(page);
  const fireTypes = [...new Set(s.routes.map((r) => r.type))].sort();
  await select(page, 'Road Accident', 10);
  s = await mapState(page);
  check(JSON.stringify([...new Set(s.routes.map((r) => r.type))].sort()) === JSON.stringify(['hospital', 'police']) && !s.routes.some((r) => r.type === 'fire_station'),
        'switching fire -> crash leaves no stale fire-station route', `before=${fireTypes.join(',')}`);
  await page.click('.detail-close'); await page.waitForTimeout(1500);
  s = await mapState(page);
  check(s.routes.length === 0 && s.services.length === 0 && s.pin === 0, 'closing the panel clears routes, markers and the incident pin');

  // missing media -> clear error state with reason and Retry
  const errPage = await newPage(browser, async (p) => {
    await p.route('**/evidence/v2/**/clip.mp4*', (r) => r.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Evidence file not found"}' }));
    await p.route('**/evidence/v2/**/best_frame.jpg*', (r) => r.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Evidence file not found"}' }));
  });
  await select(errPage, 'Road Accident'); await errPage.waitForTimeout(1500);
  const errs = await errPage.$$eval('.media-error', (els) => els.map((e) => e.innerText.replace(/\n/g, ' | ')));
  check(errs.length === 2 && errs.every((t) => /not found/i.test(t) && /Retry/.test(t)), 'missing media: each frame shows the reason and a Retry button (never a blank box)', errs.join(' // '));
  await errPage.screenshot({ path: path.join(OUT, 'media_error_state.png') });
  await errPage.context().close();

  // tiles offline: Mapbox blocked, dispatch layer must still work
  const offPage = await newPage(browser, async (p) => { await p.route(/mapbox\.com/, (r) => r.abort()); });
  await offPage.waitForTimeout(9000);
  await select(offPage, 'Fire');
  const so = await mapState(offPage);
  check(so.services.length > 0 && so.routes.length === 2 && so.pin === 1, 'tiles offline: markers, routes and the incident pin still draw', `services=${so.services.length} routes=${so.routes.length}`);
  await offPage.screenshot({ path: path.join(OUT, 'media_tiles_offline.png') });

  await browser.close();
  console.log(failures ? `\n${failures} CHECK(S) FAILED` : '\nALL CHECKS PASSED');
  process.exit(failures ? 1 : 0);
})();
