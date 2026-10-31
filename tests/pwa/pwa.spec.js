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
  await expect(page.getByRole('button', { name: 'Change box', exact: true })).toHaveCount(0);   // no bare label; the box button and the mark lead back
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
  await expect(page.getByRole('button', { name: /What does this code do\?$/ })).toBeVisible();  // (curiosity prompts: full-stack spec)
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
  await expect(page.locator(`label[for="tw-${name}"]`)).toBeVisible();   // the box's own numbers keep their code names (the hint explains them)
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
  await openPicker(page, offlineUrl);                                                           // the offline server may remember a box
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
  await expect(page.getByRole('status').filter({ hasText: 'Done! The last change is undone.' })).toBeVisible();   // owner: Home must say it finished
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

test('the code page gives the room to the code: full-width, viewport-high panel; message and buttons in one top row', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByRole('button', { name: 'Show me the code' }).click();
  await expect(page.getByRole('heading', { name: 'The code right now' })).toBeVisible();
  const [pre, main, h1, btn] = await Promise.all([
    page.locator('pre').boundingBox(), page.locator('main').boundingBox(),
    page.getByRole('heading', { name: 'The code right now' }).boundingBox(),
    page.getByRole('button', { name: 'Try something else' }).boundingBox()]);
  expect(pre.width).toBeGreaterThan(main.width * 0.9);                       // the code spans the page
  expect(pre.height).toBeGreaterThan(834 * 0.45);                            // and the bulk of the height (header, three rows, footer take the rest)
  expect(pre.y + pre.height).toBeLessThanOrEqual(834 + 1);                   // without growing the page
  expect(Math.abs(btn.y + btn.height / 2 - (h1.y + h1.height / 2))).toBeLessThan(40);  // buttons beside the message
  expect(await page.evaluate(() => document.documentElement.scrollHeight - innerHeight)).toBeLessThanOrEqual(1);
  expect(await page.locator('pre').evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);
  // after a trick, the Curious? prompts sit in a row above the code, buttons still up top
  await page.getByRole('button', { name: 'Try something else' }).click();
  await page.getByRole('button', { name: 'Nod yes' }).click();
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
  const [pre2, undo] = await Promise.all([page.locator('pre').boundingBox(), page.getByRole('button', { name: 'Undo', exact: true }).boundingBox()]);
  expect(pre2.width).toBeGreaterThan(main.width * 0.9);
  expect(undo.y).toBeLessThan(pre2.y);
  expect(await page.evaluate(() => document.documentElement.scrollHeight - innerHeight)).toBeLessThanOrEqual(1);
});

test('Curious? is always on the code page, and nothing that acts looks like a hyperlink', async ({ page }) => {
  await pickTurret(page, homeUrl);
  const noLinkLook = async (name) => {
    const b = page.getByRole('button', { name: new RegExp(name.replace(/[?]/g, '\\?') + '$') });   // chips carry a "?" icon before the words
    await expect(b).toBeVisible();
    const st = await b.evaluate((el) => { const c = getComputedStyle(el); return { underline: c.textDecorationLine, border: parseFloat(c.borderTopWidth), bg: c.backgroundColor }; });
    expect(st.underline, name).toBe('none');
    expect(st.border > 0 || st.bg !== 'rgba(0, 0, 0, 0)', `${name} has a button face`).toBe(true);
  };
  await noLinkLook('Show me the code');
  await page.getByRole('button', { name: 'Show me the code' }).click();
  await expect(page.getByRole('heading', { name: 'The code right now' })).toBeVisible();
  // owner's tweaks: no "Curious?" / "The code that does it" labels; the version line sits beside the heading;
  // the two code questions are chips in the prompt row, first, then the box's own prompts (no fresh job here)
  await expect(page.getByText('Curious?')).toHaveCount(0);
  await expect(page.getByText('The code that does it')).toHaveCount(0);
  const [h1, ver] = await Promise.all([page.getByRole('heading', { name: 'The code right now' }).boundingBox(), page.getByText(/^Version \S+\.$/).boundingBox()]);   // mock versions carry a .ino suffix
  expect(Math.abs(ver.y + ver.height / 2 - (h1.y + h1.height / 2))).toBeLessThan(30);     // same row
  expect(ver.x).toBeGreaterThan(h1.x + h1.width - 1);                                        // to its right
  const chips = page.locator('.prompt');
  await expect(chips.first()).toBeVisible();
  const texts = await chips.allTextContents();                                               // "What just changed?" may lead when a change is known
  const i = texts.findIndex((t) => /What does this code do\?/.test(t));
  expect(i).toBeGreaterThanOrEqual(0);
  expect(texts[i + 1]).toMatch(/How does the whole thing work\?/);
  expect(texts.length).toBeGreaterThanOrEqual(i + 3);
  await chips.nth(i + 2).click();
  await expect(page.locator('.explain.warm')).toBeVisible();
  for (const name of ['Change the numbers', 'Level 3: edit all the code', 'What does this code do?', 'How does the whole thing work?']) await noLinkLook(name);
  await page.getByRole('button', { name: 'Try something else' }).click();
  await page.getByPlaceholder(/shake its head/).fill('which key');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.locator('.chat')).toContainText('Which key', { timeout: 15000 });
  await noLinkLook('Start over');
});

test('picking lines keeps the code scroll, works in any order, and a further tap expands or contracts the range', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByRole('button', { name: 'Show me the code' }).click();
  const pre = page.locator('pre');
  await expect(pre).toBeVisible();
  await pre.evaluate((el) => { el.scrollTop = 300; });                                    // lines ~14-30 are in view now
  const lines = page.locator('pre .ln');
  const picked = async () => (await page.locator('pre .ln.sel').evaluateAll((els) => els.map((e) => Number(e.dataset.ln)))).join(',');
  const scrollKept = async () => expect(await pre.evaluate((el) => el.scrollTop)).toBeGreaterThan(250);
  await lines.nth(19).click();                                                            // line 20 (data-ln is 1-based)
  await expect(page.getByText(/Line 20 picked/)).toBeVisible();
  await scrollKept();                                                                     // the panel did not jump to the top
  await lines.nth(16).click();                                                            // above the first: 17 to 20
  await expect(page.getByText('Lines 17 to 20 picked.')).toBeVisible();
  expect(await picked()).toBe('17,18,19,20');
  await scrollKept();
  await lines.nth(22).click();                                                            // below the range: expands
  await expect(page.getByText('Lines 17 to 23 picked.')).toBeVisible();
  await lines.nth(14).click();                                                            // above the range: expands
  await expect(page.getByText('Lines 15 to 23 picked.')).toBeVisible();
  await lines.nth(20).click();                                                            // inside, nearer the end: contracts the end
  await expect(page.getByText('Lines 15 to 21 picked.')).toBeVisible();
  await lines.nth(15).click();                                                            // inside, nearer the start: contracts the start
  await expect(page.getByText('Lines 16 to 21 picked.')).toBeVisible();
  expect(await picked()).toBe('16,17,18,19,20,21');
  await scrollKept();
  await page.getByRole('button', { name: 'Clear' }).click();
  await expect(page.locator('pre .ln.sel')).toHaveCount(0);
  await lines.nth(17).click();
  await lines.nth(17).click();                                                            // the same line again: nothing picked
  await expect(page.locator('pre .ln.sel')).toHaveCount(0);
});

test('Level 2 on the box\'s own code: Change the numbers shows the IDE markers from every file, previews live, sends', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByRole('button', { name: 'Show me the code' }).click();
  await expect(page.getByRole('button', { name: 'Try it' })).toHaveCount(0);                   // renamed
  await page.getByRole('button', { name: 'Change the numbers' }).click();
  await expect(page.getByText(/Level 2: change the numbers/)).toBeVisible();
  const speed = page.locator('input[data-tw="yawPrecision"]');                                   // a CrunchLabs marker in the Turret's own code
  await expect(speed).toBeVisible();
  await expect(page.locator('.hint').filter({ hasText: /time in milliseconds that the YAW motor/ })).toBeVisible();   // the author's comment as the hint
  await speed.fill('500');
  await expect(page.getByTestId('val-yawPrecision')).toHaveText('500');
  await expect(page.locator('pre .set').filter({ hasText: '500' })).toBeVisible();              // live code shows the new number
  await page.getByRole('button', { name: /^Send to/ }).click();
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: 'Try something else' }).click();
  await expect(page.getByText('My numbers', { exact: true })).toBeVisible();                     // the Home card names the change
  // the synthesizer keeps its numbers in config.h: they show too, grouped by file
  await brand(page).click();
  await page.getByRole('button', { name: 'Laser Synthesizer', exact: true }).click();
  await page.getByRole('button', { name: 'Show me the code' }).click();
  await page.getByRole('button', { name: 'Change the numbers' }).click();
  await expect(page.getByText('config.h', { exact: true }).first()).toBeVisible();
  await expect(page.locator('input[data-tw="TOUCHPAD_X_MIN"]')).toBeVisible();
  expect(await page.locator('input[data-tw]').count()).toBeGreaterThan(20);
});

test('What just changed? appears only once a change is known, and explains it', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByRole('button', { name: 'Back to how it came' }).click().catch(() => {});       // a clean start if an earlier test left a change
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible({ timeout: 20000 });
  await page.getByRole('button', { name: 'Show me the code' }).click();
  await expect(page.getByRole('heading', { name: 'The code right now' })).toBeVisible();
  await expect(page.getByRole('button', { name: /What just changed\?/ })).toHaveCount(0);        // stock: nothing to compare
  await page.getByRole('button', { name: 'Try something else' }).click();
  await page.getByRole('button', { name: 'Nod yes' }).click();
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
  const chip = page.getByRole('button', { name: /What just changed\?/ });
  await expect(chip).toBeVisible();                                                              // first in the row
  expect(await page.locator('.prompt').first().textContent()).toMatch(/What just changed\?/);
  await chip.click();
  const xp = page.getByRole('region', { name: 'What the code does' });
  await expect(xp).toBeVisible({ timeout: 15000 });
  await expect(xp.locator('.xstep').first()).toBeVisible();
});

test('Stop ends a job before the box is written; the Failed screen says so', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByRole('button', { name: 'Fire a burst' }).click();
  await expect(page.getByText('You asked')).toBeVisible();
  const stop = page.getByRole('button', { name: 'Stop' });
  await expect(stop).toBeVisible();                                                               // queued / compiling: safe to stop
  await stop.click();
  await expect(page.getByText('Stopped. Nothing was changed.')).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('button', { name: 'Stop' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible();
});

test('Back to how it came finishes with a visible confirmation on Home', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByRole('button', { name: 'Nod yes' }).click();
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: 'Try something else' }).click();
  await page.getByRole('button', { name: 'Back to how it came' }).click();
  await expect(page.getByText('You asked')).toBeVisible();                                     // the Working screen shows the flash
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible({ timeout: 20000 });
  const notice = page.getByRole('status').filter({ hasText: 'Done! The IR Turret is back to how it came.' });
  await expect(notice).toBeVisible();
  await expect(page.getByText('How it came', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Shake its head no' }).click();                        // the next action clears it
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: 'Try something else' }).click();
  await expect(page.getByRole('status').filter({ hasText: /back to how it came/ })).toHaveCount(0);
});

test('the header box button (drawing, name, state) and the Hack Lab mark both lead to the picker', async ({ page }) => {
  await pickTurret(page, homeUrl);
  const boxBtn = page.getByRole('button', { name: /Change box: IR Turret, plugged in/ });
  await expect(boxBtn).toBeVisible();
  await expect(boxBtn).toContainText('IR Turret · plugged in');
  await expect(boxBtn.locator('img')).toHaveAttribute('src', '/static/boxes/ir-turret.svg');   // the box's drawing
  await expect.poll(() => boxBtn.locator('img').evaluate((el) => el.naturalWidth)).toBeGreaterThan(0);
  const face = await boxBtn.evaluate((el) => { const c = getComputedStyle(el); return { border: parseFloat(c.borderTopWidth), bg: c.backgroundColor, color: c.color }; });
  expect(face.border).toBeGreaterThan(0);                                                        // looks like a button
  expect(face.bg).not.toBe('rgba(0, 0, 0, 0)');
  await expect(page.getByText('Change box', { exact: true })).toHaveCount(0);                   // no label, the control is self-evident
  await boxBtn.click();
  await expect(page.getByRole('heading', { name: 'Which box is plugged in?' })).toBeVisible();
  await expect(page.getByRole('button', { name: /Change box:/ })).toHaveCount(0);               // not on the picker itself
  await page.getByRole('button', { name: 'IR Turret', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible();
  await brand(page).click();                                                                     // the mark still works
  await expect(page.getByRole('heading', { name: 'Which box is plugged in?' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'IR Turret', exact: true })).toHaveAttribute('aria-pressed', 'true');
});

test('the code page explains itself: the explanation is one column with the lines embedded under each step', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByRole('button', { name: 'Show me the code' }).click();
  await expect(page.getByRole('button', { name: 'Hide code' })).toHaveCount(0);          // owner: gone
  await page.getByRole('button', { name: 'What does this code do?' }).click();
  await expect(page.getByText('“What does this code do?”')).toBeVisible();
  const xp = page.getByRole('region', { name: 'What the code does' });
  await expect(xp).toBeVisible({ timeout: 15000 });
  await expect(xp.getByRole('heading', { name: 'The box waits, then acts' })).toBeVisible();
  // owner: no side bar of code; each step carries the lines it talks about, numbered
  await expect(page.locator('pre:not(.snip)')).toHaveCount(0);
  const steps = xp.locator('.xstep');
  await expect(steps).toHaveCount(4);
  await expect(steps.nth(0).locator('pre.snip .ln')).toHaveCount(2);                     // mock: lines 1-2
  await expect(steps.nth(0).locator('pre.snip .ln').first()).toHaveAttribute('data-ln', '1');
  await expect(steps.nth(2).locator('pre.snip .ln').first()).toHaveAttribute('data-ln', '5');
  // a long cited range must not take the whole screen: a snippet shows about 14 lines and scrolls inside
  const cap = await steps.nth(0).locator('pre.snip').evaluate((el) => { const c = getComputedStyle(el); return { max: parseFloat(c.maxHeight), overflow: c.overflowY, line: parseFloat(c.lineHeight) }; });
  expect(cap.max).toBeGreaterThan(cap.line * 10);
  expect(cap.max).toBeLessThan(cap.line * 18);
  expect(cap.overflow).toBe('auto');
  await expect(xp.locator('.metaphor')).toContainText('tap');
  await expect(xp).toContainText('Try it: Press 7');
  await expect(page.getByText(/^(Version \S+\.|That was change \d+ since it came\.|It is back to how it came\.)$/)).toHaveCount(1);   // owner: the version line, not repeated (mock versions carry a .ino suffix)
  const [xb, mb] = await Promise.all([xp.boundingBox(), page.locator('main').boundingBox()]);
  expect(xb.width).toBeGreaterThan(mb.width * 0.9);                                       // one column, no wasted side
  await xp.getByRole('button', { name: 'Close' }).click();
  await expect(page.locator('pre:not(.snip)')).toBeVisible();
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
