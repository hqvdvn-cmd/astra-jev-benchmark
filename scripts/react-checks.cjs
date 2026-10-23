// External evaluator. This file is never copied into a model-editable workspace.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');

// Native dialog may tab into browser chrome: W3C WCAG technique H102.
// Background page controls must never receive focus while the dialog is open.
async function assertModalFocus(page) {
  const dialog = page.getByTestId('brief-dialog');
  await dialog.waitFor({ state: 'visible' });
  await page.waitForFunction(() => document.querySelector('[data-testid="brief-dialog"]')?.contains(document.activeElement));
  for (const key of [...Array(12).fill('Tab'), ...Array(12).fill('Shift+Tab')]) {
    await page.keyboard.press(key);
    await page.waitForTimeout(30);
    const state = await dialog.evaluate(el => ({
      inside: el.contains(document.activeElement),
      browserChrome: el.matches(':modal') && !document.hasFocus() && document.activeElement === document.body,
    }));
    assert(state.inside || state.browserChrome, 'Keyboard focus moved outside the modal into the background page');
  }
}

async function evaluate(workspace, output, playwrightModule, channel = 'chrome') {
  const { chromium } = require(playwrightModule);
  const root = path.resolve(workspace, 'dist');
  fs.mkdirSync(output, { recursive: true });
  const checks = { build: true }, details = {}, errors = [], external = [];
  const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.mp4': 'video/mp4', '.png': 'image/png' };
  const server = http.createServer((req, res) => {
    let filename;
    try { filename = path.resolve(root, '.' + decodeURIComponent(new URL(req.url, 'http://local').pathname)); }
    catch { res.writeHead(400).end(); return; }
    if (filename !== root && !filename.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
    if (filename === root) filename = path.join(root, 'index.html');
    if (req.url === '/favicon.ico') { res.writeHead(204).end(); return; }
    if (!fs.existsSync(filename) || !fs.statSync(filename).isFile()) { res.writeHead(404).end(); return; }
    const size = fs.statSync(filename).size;
    // Video seeking and autoplay need byte-range support.
    const range = req.headers.range?.match(/^bytes=(\d+)-(\d*)$/);
    const start = range ? Number(range[1]) : 0;
    const end = range && range[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
    if (start > end || start >= size) { res.writeHead(416).end(); return; }
    const headers = { 'Content-Type': mime[path.extname(filename)] || 'application/octet-stream', 'Content-Length': end - start + 1, 'Accept-Ranges': 'bytes' };
    if (range) headers['Content-Range'] = `bytes ${start}-${end}/${size}`;
    res.writeHead(range ? 206 : 200, headers);
    fs.createReadStream(filename, { start, end }).pipe(res);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  let browser;
  const contexts = [];
  const check = async (name, fn) => {
    try { await fn(); checks[name] = true; }
    catch (error) { checks[name] = false; details[name] = String(error.message).slice(0, 350); }
  };
  const visibleCards = async page => page.getByTestId('project-card').evaluateAll(items => items.filter(item => item.getBoundingClientRect().width && getComputedStyle(item).visibility !== 'hidden').map(item => ({ category: item.dataset.category, title: item.textContent })));
  try {
    browser = await chromium.launch({ headless: true, channel });
    const createPage = async (viewport, reducedMotion, record) => {
      const context = await browser.newContext({ viewport, reducedMotion, serviceWorkers: 'block', ...(record ? { recordVideo: { dir: path.join(output, 'recordings'), size: viewport } } : {}) });
      contexts.push(context);
      await context.routeWebSocket('**/*', socket => { external.push(socket.url()); socket.close(); });
      await context.route('**/*', route => {
        const url = route.request().url();
        if (url.startsWith(base + '/') || url.startsWith('data:') || url.startsWith('blob:')) return route.continue();
        external.push(url.split('?')[0]);
        return route.abort();
      });
      const page = await context.newPage();
      page.setDefaultTimeout(2500);
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(base, { waitUntil: 'load', timeout: 20000 });
      await page.waitForTimeout(1600);
      return page;
    };
    const desktop = await createPage({ width: 1440, height: 1000 }, 'no-preference', true);
    // Reveal content using the same scroll sweep for every candidate before full-page capture.
    const revealAll = async page => {
      const height = await page.evaluate(() => document.documentElement.scrollHeight);
      for (let y = 0; y < height; y += 650) {
        await page.evaluate(y => scrollTo({ top: y, behavior: 'instant' }), y);
        await page.waitForTimeout(300);
      }
      await page.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }));
      await page.waitForTimeout(700);
    };
    await revealAll(desktop);
    await desktop.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true });
    await check('main_and_headings', async () => { assert.equal(await desktop.locator('main').count(), 1); assert.equal(await desktop.locator('h1').count(), 1); });
    await check('all_six_projects', async () => {
      const cards = await visibleCards(desktop); assert.equal(cards.length, 6);
      for (const name of ['Afterlight', 'Tidal', 'Monogram', 'Form & Field', 'Signal', 'Atlas']) assert(cards.some(c => c.title.includes(name)));
    });
    await check('project_filters', async () => {
      for (const category of ['film', 'identity', 'interactive']) {
        await desktop.getByTestId('filter-' + category).click(); await desktop.waitForTimeout(600);
        const cards = await visibleCards(desktop); assert.equal(cards.length, 2); assert(cards.every(card => card.category === category));
      }
      await desktop.getByTestId('filter-all').click(); await desktop.waitForTimeout(600); assert.equal((await visibleCards(desktop)).length, 6);
    });
    await check('pricing_toggle', async () => {
      const number = async name => Number((await desktop.getByTestId('price-' + name).innerText()).match(/\d+(?:\.\d+)?/)[0]);
      await desktop.getByTestId('billing-monthly').click(); assert.equal(await number('studio'), 89); assert.equal(await number('team'), 199);
      await desktop.getByTestId('billing-yearly').click(); await desktop.waitForTimeout(500); assert.equal(await number('studio'), 71.2); assert.equal(await number('team'), 159.2);
      await desktop.getByTestId('billing-monthly').click(); await desktop.waitForTimeout(500); assert.equal(await number('studio'), 89); assert.equal(await number('team'), 199);
    });
    await check('faq_accordion', async () => {
      for (let index = 0; index < 3; index++) {
        const question = desktop.getByTestId('faq-' + index), answer = desktop.getByTestId('faq-answer-' + index);
        if (await question.getAttribute('aria-expanded') === 'true') await question.click();
        await question.click(); await desktop.waitForTimeout(400);
        assert.equal(await question.getAttribute('aria-expanded'), 'true'); assert(await answer.isVisible());
        await question.click(); await desktop.waitForTimeout(400); assert.equal(await question.getAttribute('aria-expanded'), 'false');
        assert(!(await answer.isVisible()));
      }
    });
    await check('modal_form', async () => {
      await desktop.getByTestId('open-brief').filter({ visible: true }).first().click();
      const dialog = desktop.getByTestId('brief-dialog'); await dialog.waitFor({ state: 'visible' });
      assert.equal(await dialog.getAttribute('role'), 'dialog'); assert.equal(await dialog.getAttribute('aria-modal'), 'true');
      assert((await dialog.getAttribute('aria-label')) || (await dialog.getAttribute('aria-labelledby')));
      await desktop.getByTestId('submit-brief').click();
      const error = desktop.getByTestId('brief-errors'); assert(await error.isVisible()); assert((await error.innerText()).trim());
      await desktop.getByTestId('brief-name').fill('Benchmark visitor'); await desktop.getByTestId('brief-email').fill('invalid'); await desktop.getByTestId('brief-message').fill('A fictional interactive studio project.');
      await desktop.getByTestId('submit-brief').click(); assert(await error.isVisible()); assert.equal(await desktop.getByTestId('brief-name').inputValue(), 'Benchmark visitor');
      await desktop.getByTestId('brief-email').fill('benchmark@example.com'); await desktop.getByTestId('submit-brief').click();
      await desktop.getByTestId('brief-success').waitFor({ state: 'visible' });
      assert((await desktop.getByTestId('brief-success').innerText()).includes('Demo request saved locally'));
      await desktop.screenshot({ path: path.join(output, 'form.png') });
      await desktop.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' });
    });
    await check('modal_keyboard_focus', async () => {
      await desktop.goto(base, { waitUntil: 'load' }); await desktop.waitForTimeout(1600);
      await desktop.getByTestId('open-brief').filter({ visible: true }).first().click();
      await assertModalFocus(desktop);
      await desktop.getByTestId('close-brief').click(); await desktop.getByTestId('brief-dialog').waitFor({ state: 'hidden' });
    });
    await check('video_and_pause_control', async () => {
      // A failed dialog check must not block this independent video check.
      await desktop.goto(base, { waitUntil: 'load' }); await desktop.waitForTimeout(1600);
      const video = desktop.getByTestId('hero-video');
      await video.scrollIntoViewIfNeeded(); await desktop.waitForTimeout(500);
      assert(await video.evaluate(v => v.tagName === 'VIDEO' && v.muted && v.loop && v.readyState >= 2));
      const before = await video.evaluate(v => v.paused); await desktop.getByTestId('video-toggle').click(); await desktop.waitForTimeout(250); assert.notEqual(await video.evaluate(v => v.paused), before);
    });
    // Capture a simple scroll journey for visual review in addition to functional actions.
    if (await desktop.getByTestId('brief-dialog').isVisible()) await desktop.keyboard.press('Escape');
    for (const id of ['work', 'services', 'pricing', 'faq']) {
      await check('section_' + id, async () => { await desktop.locator('#' + id).scrollIntoViewIfNeeded(); });
      await desktop.waitForTimeout(250);
    }
    const mobile = await createPage({ width: 390, height: 844 }, 'no-preference', true);
    await revealAll(mobile);
    await mobile.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true });
    await check('mobile_menu', async () => {
      const toggle = mobile.getByTestId('menu-toggle'); await toggle.click(); assert.equal(await toggle.getAttribute('aria-expanded'), 'true'); await mobile.getByTestId('mobile-menu').waitFor({ state: 'visible' });
      await toggle.click(); assert.equal(await toggle.getAttribute('aria-expanded'), 'false'); await mobile.getByTestId('mobile-menu').waitFor({ state: 'hidden' });
    });
    await check('no_horizontal_overflow', async () => {
      for (const width of [390, 320]) { await mobile.setViewportSize({ width, height: 844 }); await mobile.waitForTimeout(300); assert(await mobile.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)); }
    });
    const reduced = await createPage({ width: 1280, height: 900 }, 'reduce', false);
    await check('reduced_motion', async () => {
      assert(await reduced.getByTestId('hero-video').evaluate(v => v.paused));
      const running = await reduced.evaluate(() => document.getAnimations().filter(a => a.playState === 'running' && a.effect?.getTiming().iterations === Infinity).length);
      assert.equal(running, 0); assert(await reduced.locator('h1').isVisible());
    });
    await reduced.screenshot({ path: path.join(output, 'reduced-motion.png'), fullPage: true });
    checks.no_runtime_errors = errors.length === 0;
    checks.no_external_requests = external.length === 0;
    for (const [page, name] of [[desktop, 'desktop'], [mobile, 'mobile']]) {
      const video = page.video(); await page.context().close(); if (video) fs.copyFileSync(await video.path(), path.join(output, name + '.webm'));
    }
  } catch (error) { checks.browser_completed = false; details.browser_completed = String(error.message).slice(0, 400); }
  finally {
    for (const context of contexts) await context.close().catch(() => {});
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
  const result = { success: Object.values(checks).every(Boolean), checks, details, runtime_errors: errors, blocked_external_requests: external };
  fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify(result, null, 2));
  return result;
}

if (require.main === module) evaluate(...process.argv.slice(2)).then(r => { console.log(JSON.stringify(r)); process.exitCode = r.success ? 0 : 1; }).catch(e => { console.error(e.message); process.exitCode = 2; });
module.exports = { evaluate, assertModalFocus };
