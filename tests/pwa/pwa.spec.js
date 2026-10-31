// Kid-facing PWA against the mock backend. Run from the repo root with the
// machine-wide harness:  pw test tests/pwa      (HACKLAB_PYTHON=<python> to override .venv)
// Two uvicorn instances per worker: one with ANTHROPIC_API_KEY (Home), one
// without (Offline). PYTHONPATH pins `hacklab` to this checkout; `python -m
// uvicorn` avoids the venv's console-script launchers (their shebang breaks
// when the checkout folder is renamed).
const { test, expect, devices } = require('@playwright/test');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

const ROOT = path.resolve(__dirname, '..', '..');
const PYTHON = process.env.HACKLAB_PYTHON || path.join(ROOT, '.venv', 'bin', 'python');
const SHOTS = path.join(__dirname, 'screenshots');

function startServer(port, withKey) {
  const env = { ...process.env, FAKE_BOARD: '1', PYTHONPATH: ROOT };
  if (withKey) env.ANTHROPIC_API_KEY = 'dummy';
  else delete env.ANTHROPIC_API_KEY;
  const proc = spawn(PYTHON, ['-m', 'uvicorn', 'hacklab.app:app', '--port', String(port), '--log-level', 'warning'], { cwd: ROOT, env });
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + 20000;
    const tick = () => {
      http.get(`http://127.0.0.1:${port}/api/status`, (r) => (r.statusCode === 200 ? resolve(proc) : retry())).on('error', retry);
    };
    const retry = () => (Date.now() > deadline ? reject(new Error('uvicorn did not start')) : setTimeout(tick, 200));
    tick();
  });
}

const freePort = () => new Promise((resolve) => {
  const s = require('net').createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); });
});

let home, offline, homeUrl, offlineUrl;
test.beforeAll(async () => {
  const [p1, p2] = [await freePort(), await freePort()];
  [home, offline] = await Promise.all([startServer(p1, true), startServer(p2, false)]);
  homeUrl = `http://127.0.0.1:${p1}/`;
  offlineUrl = `http://127.0.0.1:${p2}/`;
});
test.afterAll(() => { home && home.kill(); offline && offline.kill(); });
// The kid uses an iPad: emulate one (viewport, touch, Safari UA, scale). The WebKit project is
// the iPad engine; isMobile is dropped because Firefox refuses it. (Owner hit an issue on the iPad.)
const { isMobile: _m, defaultBrowserType: _b, ...IPAD } = devices['iPad Pro 11 landscape'];
test.use({ ...IPAD });

// The selected box is server state shared by every test on that server: open
// the picker through the Hack Lab mark when a previous test already picked one.
const brand = (page) => page.getByRole('button', { name: /Hack Lab/ });
async function openPicker(page, url) {
  await page.goto(url);
  const picker = page.getByRole('heading', { name: 'Which box is plugged in?' });
  await expect(picker.or(brand(page))).toBeVisible({ timeout: 15000 }); // first render waits for /api/status
  if (!(await picker.isVisible())) await brand(page).click();
  await expect(picker).toBeVisible();
}
// Tapping a card picks the box and goes Home (no "Let's go", owner 2026-10-31).
async function pickTurret(page, url) {
  await openPicker(page, url);
  await page.getByRole('button', { name: 'IR Turret', exact: true }).click();
}
// P8 round 3: Send asks the helper; Go! is enabled only once it answers "ready", then flashes.
async function askAndGo(page, text) {
  await page.getByPlaceholder(/shake its head|Your answer/).fill(text);
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByRole('button', { name: 'Go!' })).toBeEnabled({ timeout: 15000 });
  await page.getByRole('button', { name: 'Go!' }).click();
}

test('box picker leads to Home when the AI helper is here', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible();
  await expect(page.getByText('AI helper is here')).toBeVisible();
  await expect(page.getByText('IR Turret · plugged in')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Change box' })).toHaveCount(0);   // owner: the Hack Lab mark is the way back
  await expect(brand(page)).toBeVisible();
  await expect(page.getByText('Try one of these')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Undo last change' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Back to how it came' })).toBeVisible();
});

test('asking walks the Working stages over SSE and lands on Done, then Undo', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByPlaceholder(/shake its head/).fill('Make it nod when I press 1');
  await page.getByRole('button', { name: 'Send' }).click();
  // the kid stays on Home while the helper thinks; stage text comes from the server (message_kid)
  await expect(page.locator('.chat')).toContainText('Make it nod when I press 1');
  await expect(page.getByText('The AI helper is thinking about your idea.')).toBeVisible();
  await expect(page.getByText('Press Go! to send it to the box.')).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: 'Go!' }).click();
  await expect(page.getByText('You asked')).toBeVisible();
  await expect(page.getByText('“Make it nod when I press 1”')).toBeVisible();
  await expect(page.getByText('Turning the code into robot language.')).toBeVisible({ timeout: 10000 });
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('The code that does it')).toBeVisible();  // (curiosity prompts: full-stack spec)
  await expect(page.locator('pre')).toContainText('void loop');
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible({ timeout: 15000 });
});

test('a failed job shows the kid message and one next action', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await askAndGo(page, 'fail on purpose');
  await expect(page.getByText('That one did not work. Try again, or press Undo.')).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();
  await expect(page.locator('main')).not.toContainText(/Traceback|Error:/);
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible();
});

test('without the AI helper the Offline screen offers tricks and the rescue buttons', async ({ page }) => {
  await pickTurret(page, offlineUrl);
  await expect(page.getByText('AI helper is away')).toBeVisible();
  await expect(page.getByText("The AI helper can't hear you right now")).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Pick a trick' })).toBeVisible();
  await expect(page.getByRole('button', { name: /Shake head/ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Undo last change' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Back to how it came' })).toBeVisible();
  await expect(page.locator('a[href^="http"]')).toHaveCount(0); // no external links, ever
});

test('Tweak sliders are bound to the behaviour ranges, clamp, and Reset restores the numbers', async ({ page }) => {
  await pickTurret(page, offlineUrl);
  await page.getByRole('button', { name: /Change the numbers/ }).click();
  await expect(page.getByText('Level 2: change the numbers')).toBeVisible();
  // pick a slider that has room to move (the stock yaw speed sits at its max)
  const idx = await page.locator('input[type=range]').evaluateAll((els) => els.findIndex((e) => Number(e.value) < Number(e.max)));
  expect(idx).toBeGreaterThanOrEqual(0);
  const slider = page.locator('input[type=range]').nth(idx);
  const name = await slider.getAttribute('data-tw');
  const max = await slider.getAttribute('max');
  const initial = await slider.inputValue();
  await expect(page.locator(`label[for="tw-${name}"] span`).first()).not.toHaveText(name); // kid label, not the variable
  await slider.fill(max);
  await expect(page.getByTestId(`val-${name}`)).toHaveText(max);
  await expect(page.locator('pre')).toContainText(max); // live code shows the value
  await page.getByRole('button', { name: 'Reset numbers' }).click();
  await expect(page.getByTestId(`val-${name}`)).toHaveText(initial);
  await page.getByRole('button', { name: /Send to IR Turret/ }).click();
  await expect(page.getByText('Turning the code into robot language.')).toBeVisible({ timeout: 10000 });
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
});

test('phone width has no horizontal scroll', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await pickTurret(page, homeUrl);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test('screenshots of every screen for review', async ({ page }, info) => {
  test.skip(info.project.name !== 'chromium', 'one set of screenshots is enough');
  const shot = (name) => page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
  await openPicker(page, homeUrl);
  await shot('1-box-picker');
  await page.getByRole('button', { name: 'IR Turret', exact: true }).click();
  await expect(page.getByText('Try one of these')).toBeVisible();
  await shot('2-home');
  await page.getByPlaceholder(/shake its head/).fill('Make it shake its head when I press 7');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByRole('button', { name: 'Go!' })).toBeEnabled({ timeout: 15000 });
  await shot('2b-ready');
  await page.getByRole('button', { name: 'Go!' }).click();
  await expect(page.getByText('Turning the code into robot language.')).toBeVisible({ timeout: 10000 });
  await shot('3-working');
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
  await shot('4-done');
  await page.goto(offlineUrl);
  await page.getByRole('button', { name: 'IR Turret', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Pick a trick' })).toBeVisible();
  await shot('5-offline');
  await page.getByRole('button', { name: /Change the numbers/ }).click();
  await expect(page.getByText('Level 2: change the numbers')).toBeVisible();
  await shot('6-tweak');
});


// ---------- remote view (owner's P5 notes) ----------
// The mock backend honours X-Hacklab-Source so a browser can act as a Tailscale viewer.
const asRemote = async (page) => page.setExtraHTTPHeaders({ 'X-Hacklab-Source': 'remote' });

test('a remote viewer sees everything but cannot change anything', async ({ page }) => {
  await asRemote(page);
  await page.goto(homeUrl);
  await expect(page.getByText('Remote view · read only')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Turn on helping' })).toBeVisible();
  await openPicker(page, homeUrl);
  await expect(page.getByRole('button', { name: 'IR Turret', exact: true })).toBeDisabled();   // read only: no picking
});

test('helping unlocks remote changes and the kid screen says Uncle is helping', async ({ page, browser }) => {
  await asRemote(page);
  await page.goto(homeUrl);
  await page.getByRole('button', { name: 'Turn on helping' }).click();
  await expect(page.getByText('Remote view · helping is on')).toBeVisible();
  await expect(page.getByText('Uncle is helping')).toBeVisible();
  await openPicker(page, homeUrl);
  await page.getByRole('button', { name: 'IR Turret', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible();
  // a second, local browser (the kid's iPad) shows the line and has no switch
  const kid = await (await browser.newContext()).newPage();
  await kid.goto(homeUrl);
  await expect(kid.getByText('Uncle is helping')).toBeVisible();
  await expect(kid.getByRole('button', { name: /helping/ })).toHaveCount(0);
  await expect(kid.getByText('Remote view')).toHaveCount(0);
  // turning it off locks the remote viewer again and the line disappears for the kid over SSE
  await page.getByRole('button', { name: 'Turn off helping' }).click();
  await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();
  await expect(kid.getByText('Uncle is helping')).toHaveCount(0, { timeout: 10000 });
  await kid.context().close();
});

test('?admin=1 turns helping on for a remote viewer and is ignored on the LAN', async ({ page, browser }) => {
  await asRemote(page);
  await page.goto(homeUrl + '?admin=1');
  await expect(page.getByText('Remote view · helping is on')).toBeVisible();
  await page.getByRole('button', { name: 'Turn off helping' }).click();
  const kid = await (await browser.newContext()).newPage();
  await kid.goto(homeUrl + '?admin=1');
  await expect(kid.locator('header')).toBeVisible();
  await expect(kid.getByText('Uncle is helping')).toHaveCount(0);
  await expect(kid.getByText('Remote view')).toHaveCount(0);
  await kid.context().close();
});

test('tapping a card goes Home by itself and shows a busy state on the way', async ({ page }) => {
  await page.route('**/api/box', async (route) => { await new Promise((r) => setTimeout(r, 1500)); await route.continue(); });
  await openPicker(page, homeUrl);
  await expect(page.getByRole('button', { name: "Let's go" })).toHaveCount(0);                      // owner: tap is enough
  const card = page.getByRole('button', { name: 'IR Turret', exact: true });
  await card.click();
  await expect(page.getByText('Getting ready')).toBeVisible();
  await expect(card).toBeDisabled();
  await expect(card).toHaveAttribute('aria-pressed', 'true');                                       // the tapped one stays marked
  const other = page.getByRole('button', { name: 'Omnibot Forklift', exact: true });
  await expect(other).toBeDisabled();                                                               // no re-picking mid-flight
  expect(parseFloat(await other.evaluate((el) => getComputedStyle(el).opacity))).toBeLessThan(0.7);  // greyed out
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible({ timeout: 10000 });
});


test('the Home placeholder and "Try one of these" come from the box profile', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await expect(page.getByPlaceholder('Make it shake its head when I press 7')).toBeVisible();
  for (const name of ['Shake its head no', 'Nod yes', 'Fire a burst']) await expect(page.getByRole('button', { name })).toBeVisible();
  // a box without shipped tricks suggests plain asks instead
  await openPicker(page, homeUrl);
  await page.getByRole('button', { name: 'Omnibot Forklift', exact: true }).click();
  await expect(page.getByPlaceholder('Lift the fork up and down every five seconds')).toBeVisible();
  await page.getByRole('button', { name: 'Say hello on the serial monitor' }).click();
  await expect(page.locator('.chat')).toContainText('Say hello on the serial monitor');  // the button's own words open the discussion
  await expect(page.getByRole('button', { name: 'Go!' })).toBeEnabled({ timeout: 15000 });
  await page.getByRole('button', { name: 'Go!' }).click();
  await expect(page.getByText('“Say hello on the serial monitor”')).toBeVisible();  // quoted by the button's own words
  await expect(page.getByText('Turning the code into robot language.')).toBeVisible({ timeout: 10000 });
});

test('a "Try one of these" button is quoted by its own words and becomes the Home card title', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByRole('button', { name: 'Shake its head no' }).click();
  await expect(page.getByText('“Shake its head no”')).toBeVisible();   // not the trick's internal title
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: 'Try something else' }).click();
  const card = page.locator('.panel', { hasText: 'Right now the IR Turret' });
  await expect(card).toContainText('Shake its head no');
  await expect(card).toContainText(/Change \d+ of \d+ · just now/);
  await page.getByRole('button', { name: 'Back to how it came' }).click();
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible({ timeout: 15000 });
  await expect(card).toContainText('How it came');
  await expect(card).toContainText('Nothing changed yet');
});

test('the code view has syntax colours and Level 3 opens a real editor with completions', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByRole('button', { name: 'Show me the code' }).click();
  const pre = page.locator('pre');
  await expect(pre).toContainText('void loop');
  await expect(pre.locator('.tok-keyword').first()).toBeVisible();          // syntax colours
  await expect(pre.locator('.hl, .set').first()).toBeVisible();              // tweakable marks still there
  await page.getByRole('button', { name: 'Level 3: edit all the code' }).click();
  const editor = page.locator('.cm-editor');
  await expect(editor).toBeVisible();
  await expect(editor.locator('.cm-content')).toContainText('LICENSE');  // CodeMirror renders only the visible lines
  await editor.locator('.cm-content').click();
  await page.keyboard.press(process.platform === 'darwin' ? 'Meta+End' : 'Control+End');
  await page.keyboard.press('Enter');
  await page.keyboard.type('shakeHe');
  const completion = page.locator('.cm-tooltip-autocomplete');
  await expect(completion).toBeVisible();
  await expect(completion).toContainText('shakeHeadNo');                     // seeded from the sketch's identifiers
  await page.keyboard.press('Escape');
});

test('Undo: disabled buttons say why, and every Undo path works on the iPad', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByRole('button', { name: 'Back to how it came' }).click();           // known clean start
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible({ timeout: 15000 });
  // Home: nothing to undo -> the button is disabled and says so
  await expect(page.getByRole('button', { name: 'Undo last change' })).toBeDisabled();
  await expect(page.getByText('Nothing to undo yet')).toBeVisible();
  // the code page: no Undo button at all when there is nothing to undo
  await page.getByRole('button', { name: 'Show me the code' }).click();
  await expect(page.getByRole('heading', { name: 'The code right now' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Undo', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Try something else' }).click();
  // after a trick: Done's Undo works
  await page.getByRole('button', { name: 'Nod yes' }).click();
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByText('You asked')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('Nothing changed yet')).toBeVisible();
  // after a trick: Home's Undo last change works, and the code page's Undo works
  await page.getByRole('button', { name: 'Nod yes' }).click();
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: 'Try something else' }).click();
  await expect(page.getByRole('button', { name: 'Undo last change' })).toBeEnabled();
  await page.getByRole('button', { name: 'Show me the code' }).click();
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('Nothing changed yet')).toBeVisible();
});

test('a question from the AI helper opens a discussion the kid can answer', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByPlaceholder(/shake its head/).fill('which key makes it dance');   // mock: "which..." -> a question back
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByText('The AI helper is thinking about your idea.')).toBeVisible();
  // still on Home, with the helper's question and the kid's words in a discussion; Go! stays off
  const chat = page.locator('.chat');
  await expect(chat).toContainText('which key makes it dance');
  await expect(chat).toContainText('Which key on the remote should start it?', { timeout: 15000 });
  await expect(page.getByRole('button', { name: 'Go!' })).toBeDisabled();
  await expect(page.getByPlaceholder('Your answer')).toBeVisible();
  await askAndGo(page, 'key 5');
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: 'Try something else' }).click();
  await expect(page.locator('.chat')).toHaveCount(0);                                 // a sketch answer ends the discussion
  await expect(page.getByPlaceholder(/shake its head/)).toBeVisible();
});

test('the ask box keeps a half-typed request through re-renders, hides the suggestions while typing, and the helper gates Go!', async ({ page }) => {
  await pickTurret(page, homeUrl);
  const box = page.locator('#ask');                                                  // its placeholder changes once the discussion opens
  await expect(page.getByText('Try one of these')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Go!' })).toBeDisabled();           // nothing to go with yet
  await box.fill('Make it spin\nthen stop');                                          // multiline is fine
  await expect(page.getByText('Try one of these')).toBeHidden();                      // not relevant while typing
  // the 20 s refresh and every board status event rebuild the screen: the draft must survive
  await page.evaluate(() => refresh().then(render));
  await expect(box).toHaveValue('Make it spin\nthen stop');
  await expect(page.getByRole('button', { name: 'Go!' })).toBeDisabled();
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.locator('.chat')).toContainText('Make it spin');
  await expect(page.locator('.chat')).toContainText('I know what to do', { timeout: 15000 });
  await expect(page.getByText('Press Go! to send it to the box.')).toBeVisible();
  const go = page.getByRole('button', { name: 'Go!' });
  await expect(go).toBeEnabled();
  await expect(box).toHaveValue('');
  await box.fill('and faster');                                                      // more words: the plan is stale
  await expect(go).toBeDisabled();
  await box.fill('');
  await expect(go).toBeEnabled();
  await go.click();
  await expect(page.getByText('You asked')).toBeVisible();
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
});

test('box picker cards: name on top, no tick, picture never cut off, at iPad and phone widths', async ({ page }) => {
  await openPicker(page, homeUrl);
  const card = page.getByRole('button', { name: 'IR Turret', exact: true });
  await expect(card.locator('.tick')).toHaveCount(0);                                       // selection by border, no checkmark
  expect(await card.evaluate((el) => el.firstElementChild.className)).toBe('boxname');       // text first, on top
  expect(await card.locator('.boxname').evaluate((el) => getComputedStyle(el).justifyContent)).toBe('center');
  for (const width of [1194, 390]) {
    await page.setViewportSize({ width, height: 834 });
    const img = card.locator('img');
    await expect(img).toBeVisible();
    const [ib, pb] = [await img.boundingBox(), await card.locator('.photo').boundingBox()];
    expect(ib.x).toBeGreaterThanOrEqual(pb.x - 1); expect(ib.x + ib.width).toBeLessThanOrEqual(pb.x + pb.width + 1);
    expect(ib.y).toBeGreaterThanOrEqual(pb.y - 1); expect(ib.y + ib.height).toBeLessThanOrEqual(pb.y + pb.height + 1);
    expect(await img.evaluate((el) => getComputedStyle(el).objectFit)).toBe('contain');
    expect(await card.locator('.photo').evaluate((el) => getComputedStyle(el).backgroundColor)).toBe('rgba(0, 0, 0, 0)');
  }
  // the drawing itself: no text, no opaque background
  const svg = await page.evaluate(async () => (await fetch('/static/boxes/ir-turret.svg')).text());
  expect(svg).not.toMatch(/<text/);
  expect(svg).not.toMatch(/<rect width="400" height="230" fill/);
});

test('picking another box starts fresh: no discussion, draft or plan from the last one', async ({ page }) => {
  await openPicker(page, homeUrl);
  await page.getByRole('button', { name: 'Omnibot Forklift', exact: true }).click();
  await page.getByRole('button', { name: 'Say hello on the serial monitor' }).click();     // an ask suggestion opens a discussion
  await expect(page.locator('.chat')).toContainText('Say hello on the serial monitor');
  await expect(page.getByRole('button', { name: 'Go!' })).toBeEnabled({ timeout: 15000 });
  await page.locator('#ask').fill('and drive slower');
  await brand(page).click();
  await page.getByRole('button', { name: 'IR Turret', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible();
  await expect(page.locator('.chat')).toHaveCount(0);                                        // the Forklift's talk is gone
  await expect(page.locator('#ask')).toHaveValue('');
  await expect(page.getByRole('button', { name: 'Go!' })).toBeDisabled();                    // and so is its plan
  await expect(page.getByText('Try one of these')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Shake its head no' })).toBeVisible();      // this box's suggestions
  await expect(page.getByPlaceholder(/shake its head/)).toBeVisible();
});

test('a box picture that fails to load (app restarting) is retried until it shows', async ({ page }) => {
  const refused = {};
  await page.route('**/static/boxes/*.svg', (route) => {
    const u = route.request().url().split('?')[0];
    refused[u] = (refused[u] || 0) + 1;
    return refused[u] <= 2 ? route.abort('connectionrefused') : route.continue();   // the first two tries fail
  });
  await openPicker(page, homeUrl);
  const imgs = page.locator('.boxcard img');
  await expect(imgs).toHaveCount(3);
  for (let i = 0; i < 3; i++) {
    await expect.poll(() => imgs.nth(i).evaluate((el) => el.naturalWidth), { timeout: 15000 }).toBeGreaterThan(0);
  }
  expect(Object.keys(refused).some((u) => /synthesizer\.svg/.test(u))).toBe(false);          // no guessed fallback file
});

test('the header chip is status; the Hack Lab mark is the way back to the picker', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await expect(page.getByText('IR Turret · plugged in')).toBeVisible();
  await expect(page.getByRole('button', { name: /plugged in/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Change box' })).toHaveCount(0);
  await brand(page).click();
  await expect(page.getByRole('heading', { name: 'Which box is plugged in?' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'IR Turret', exact: true })).toHaveAttribute('aria-pressed', 'true');  // the current box is marked
});

test('the code page explains itself: What does this code do, lines, how it all works; code steps aside when narrow', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByRole('button', { name: 'Show me the code' }).click();
  await expect(page.getByRole('button', { name: 'Hide code' })).toHaveCount(0);          // owner: gone
  // whole-sketch explanation: story, flow picture, metaphor, try-it line
  await page.getByRole('button', { name: 'What does this code do?' }).click();
  await expect(page.getByText('“What does this code do?”')).toBeVisible();
  const xp = page.getByRole('region', { name: 'What the code does' });
  await expect(xp).toBeVisible({ timeout: 15000 });
  await expect(xp.getByRole('heading', { name: 'The box waits, then acts' })).toBeVisible();
  await expect(xp.locator('.flow .step')).toHaveCount(4);
  await expect(xp.locator('.metaphor')).toContainText('tap');
  await expect(xp).toContainText('Try it: Press 7');
  await expect(page.locator('pre')).toBeVisible();                                        // iPad landscape: room for both
  // narrow screen: the code steps aside while explaining, and comes back on Close
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('pre')).toBeHidden();
  await xp.getByRole('button', { name: 'Close' }).click();
  await expect(page.locator('pre')).toBeVisible();
  await page.setViewportSize({ width: 1194, height: 834 });
  // tap two lines -> a range -> explain just those
  const lines = page.locator('pre .ln');
  await lines.nth(2).click();
  await expect(page.getByText(/Line 3 picked/)).toBeVisible();
  await lines.nth(5).click();
  await expect(page.getByText('Lines 3 to 6 picked.')).toBeVisible();
  await expect(page.locator('pre .ln.sel')).toHaveCount(4);
  await page.getByRole('button', { name: 'Explain lines 3-6' }).click();
  await expect(page.getByRole('region', { name: 'What the code does' })).toBeVisible({ timeout: 15000 });
  // how the whole thing works: static page with the picture, and back
  await page.getByRole('button', { name: 'Close' }).click();
  await page.getByRole('button', { name: 'How does the whole thing work?' }).click();
  await expect(page.getByRole('img', { name: /iPad to Hack Lab to the box/ })).toBeVisible();
  await expect(page.getByText(/USB cable/).first()).toBeVisible();
  await expect(page.locator('main')).not.toContainText(/http/);
  await page.getByRole('button', { name: 'Back to the code' }).click();
  await expect(page.getByRole('heading', { name: 'The code right now' })).toBeVisible();
});
