// Full-stack browser tests: the real runner, sketch store, box profiles, tweak
// rendering and genie skeleton assembly on the emulated board, with the AI
// helper replaying the recorded goldens (HACKLAB_GENIE=golden). Everything the
// kid does is verified end to end except the USB cable, which scripts/hil-*.sh
// cover on the Pi. Run with the machine-wide harness:  pw test tests/pwa
const { test, expect, devices } = require('@playwright/test');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const fs = require('fs');
const os = require('os');

const ROOT = path.resolve(__dirname, '..', '..');
const PYTHON = process.env.HACKLAB_PYTHON || path.join(ROOT, '.venv', 'bin', 'python');

function startFullStack(port, dataDir) {
  const env = { ...process.env, PYTHONPATH: ROOT, HACKLAB_BOARD: 'fake', HACKLAB_GENIE: 'golden',
    ANTHROPIC_API_KEY: 'dummy', HACKLAB_DATA_DIR: dataDir };
  delete env.FAKE_BOARD;
  const proc = spawn(PYTHON, ['-m', 'uvicorn', 'hacklab.app:app', '--port', String(port), '--log-level', 'warning'], { cwd: ROOT, env });
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + 30000;
    const tick = () => http.get(`http://127.0.0.1:${port}/api/status`, (r) => (r.statusCode === 200 ? resolve(proc) : retry())).on('error', retry);
    const retry = () => (Date.now() > deadline ? reject(new Error('uvicorn did not start')) : setTimeout(tick, 200));
    tick();
  });
}
const freePort = () => new Promise((resolve) => {
  const s = require('net').createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); });
});

let proc, url, dataDir;
test.beforeAll(async () => {
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hacklab-fullstack-'));
  const port = await freePort();
  proc = await startFullStack(port, dataDir);
  url = `http://127.0.0.1:${port}/`;
});
test.afterAll(() => { proc && proc.kill(); });
// The kid uses an iPad: emulate one (viewport, touch, Safari UA, scale). The WebKit project is
// the iPad engine; isMobile is dropped because Firefox refuses it. (Owner hit an issue on the iPad.)
const { isMobile: _m, defaultBrowserType: _b, ...IPAD } = devices['iPad Pro 11 landscape'];
test.use({ ...IPAD });

async function pickTurret(page) {
  await page.goto(url);
  const picker = page.getByRole('heading', { name: 'Which box is plugged in?' });
  const brand = page.getByRole('button', { name: /Hack Lab/ });
  await expect(picker.or(brand)).toBeVisible({ timeout: 15000 }); // first render waits for /api/status
  if (!(await picker.isVisible())) await brand.click();
  await expect(picker).toBeVisible();
  await page.getByRole('button', { name: 'IR Turret', exact: true }).click();                   // tap = pick + go
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible({ timeout: 15000 });
}
// The Done screen's heading IS the kid message from the server, so wait for the screen's buttons.
const doneScreen = (page) => page.getByRole('button', { name: 'Try something else' });

test('the whole loop: ask -> real compile/flash on the emulated board -> Done with the real code -> Undo', async ({ page }) => {
  await pickTurret(page);
  await expect(page.getByText('How it came', { exact: true })).toBeVisible();
  await expect(page.getByText('Nothing changed yet')).toBeVisible();
  await page.getByPlaceholder(/shake its head/).fill('make it shake its head when I press 7');
  await page.getByRole('button', { name: 'Send' }).click();
  // the recorded answer is "ready": its words appear on Home and Go! wakes up; nothing flashed yet
  await expect(page.getByRole('button', { name: 'Go!' })).toBeEnabled({ timeout: 30000 });
  await expect(page.getByText('Nothing changed yet')).toBeVisible();
  await page.getByRole('button', { name: 'Go!' }).click();
  await expect(doneScreen(page)).toBeVisible({ timeout: 30000 });
  // the kid message is the recorded model answer, not page copy; prompts come from the box's concepts
  await expect(page.locator('main')).toContainText(/Press 7|press 7/);
  await expect(page.getByRole('button', { name: /Want to/ }).first()).toBeVisible();   // the model's curiosity prompts, as chips
  await page.getByRole('button', { name: /Want to/ }).first().click();
  await expect(page.locator('main')).not.toContainText(/http/);
  // the code shown is the assembled skeleton with the model's rule inside the real stock sketch
  await expect(page.locator('pre')).toContainText('cmd7');
  await expect(page.locator('pre')).toContainText('IrReceiver.decode()');
  await expect(page.locator('pre')).not.toContainText('//@@');
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible({ timeout: 30000 });
  await expect(page.getByText('How it came', { exact: true })).toBeVisible();
  // the store on disk agrees: baseline only after the undo
  const versions = fs.readdirSync(path.join(dataDir, 'ir-turret', 'versions'));
  expect(versions).toEqual(['0000']);
});

test('a trick from the box profile flashes and becomes a version; the code is the shipped behaviour', async ({ page }) => {
  await pickTurret(page);
  // the turret profile's [copy] lists these three tricks
  for (const name of ['Shake its head no', 'Nod yes', 'Fire a burst']) await expect(page.getByRole('button', { name })).toBeVisible();
  await page.getByRole('button', { name: 'Shake its head no' }).click();
  await expect(doneScreen(page)).toBeVisible({ timeout: 30000 });
  await expect(page.locator('pre')).toContainText('shakeNo(3)');  // the shipped behaviour's own code
  const stored = fs.readdirSync(path.join(dataDir, 'ir-turret', 'versions')).sort();
  expect(stored[stored.length - 1]).not.toBe('0000');
  // the Home card names the version by what the kid tapped, with a relative time (spec: Main.dc.html)
  await page.getByRole('button', { name: 'Try something else' }).click();
  const card = page.locator('.panel', { hasText: 'Right now the IR Turret' });
  await expect(card).toContainText('Shake its head no');
  await expect(card).toContainText(/Change \d+ of \d+ · just now/);
});

test('changing the numbers renders the chosen value into the flashed sketch, clamped to the range', async ({ page }) => {
  await pickTurret(page);
  await page.getByRole('button', { name: 'Shake its head no' }).click();
  await expect(doneScreen(page)).toBeVisible({ timeout: 30000 });
  await page.getByRole('button', { name: 'Try it' }).click();
  await expect(page.getByText('Level 2: change the numbers')).toBeVisible();
  const shakes = page.getByLabel(/How many shakes/);
  await expect(shakes).toHaveAttribute('max', '10');
  await shakes.fill('7');
  await page.getByRole('button', { name: /Send to IR Turret/ }).click();
  await expect(doneScreen(page)).toBeVisible({ timeout: 30000 });
  await expect(page.locator('pre')).toContainText(/shakeNo\(7\)|int shakes = 7;/);
  // what was actually "uploaded": the stored current version carries the number
  const cur = fs.readFileSync(path.join(dataDir, 'ir-turret', 'current'), 'utf8').trim();
  const dir = path.join(dataDir, 'ir-turret', 'versions', cur);
  const ino = fs.readdirSync(dir).find((d) => d !== 'meta.json');
  const src = fs.readFileSync(path.join(dir, ino, `${ino}.ino`), 'utf8');
  expect(src).toMatch(/shakeNo\(7\)/);
});

test('Back to how it came restores the stock sketch after several changes', async ({ page }) => {
  await pickTurret(page);
  for (const name of ['Nod yes', 'Fire a burst']) {
    await page.getByRole('button', { name }).click();
    await expect(doneScreen(page)).toBeVisible({ timeout: 30000 });
    await page.getByRole('button', { name: 'Try something else' }).click();
  }
  await page.getByRole('button', { name: 'Back to how it came' }).click();
  await expect(page.getByText('How it came', { exact: true })).toBeVisible({ timeout: 30000 });
  expect(fs.readdirSync(path.join(dataDir, 'ir-turret', 'versions'))).toEqual(['0000']);
});

test('Level 3: what the kid types in the editor is exactly what gets flashed', async ({ page }) => {
  await pickTurret(page);
  await page.getByRole('button', { name: 'Show me the code' }).click();
  await page.getByRole('button', { name: 'Level 3: edit all the code' }).click();
  const content = page.locator('.cm-editor .cm-content');
  await expect(content).toContainText('LICENSE');  // only the visible lines are in the DOM
  await content.click();
  await page.keyboard.press(process.platform === 'darwin' ? 'Meta+End' : 'Control+End');
  await page.keyboard.press('Enter');
  await page.keyboard.type('// hello from level 3');
  await page.getByRole('button', { name: /^Send to IR Turret/ }).click();
  await expect(doneScreen(page)).toBeVisible({ timeout: 30000 });
  await expect(page.locator('pre')).toContainText('hello from level 3');
  const versions = fs.readdirSync(path.join(dataDir, 'ir-turret', 'versions')).sort();
  const latest = versions[versions.length - 1];
  const files = fs.readdirSync(path.join(dataDir, 'ir-turret', 'versions', latest), { recursive: true });
  const ino = files.find((f) => String(f).endsWith('.ino'));
  expect(fs.readFileSync(path.join(dataDir, 'ir-turret', 'versions', latest, ino), 'utf8')).toContain('// hello from level 3');
});

test('discussion: the recorded clarify answer asks a question; the reply (with history) gets a sketch', async ({ page }) => {
  await pickTurret(page);
  await page.getByPlaceholder(/shake its head/).fill('make it move when I press a key');  // golden: clarify
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.locator('.chat')).toContainText(/Which key/, { timeout: 30000 });
  await expect(page.getByRole('button', { name: 'Go!' })).toBeDisabled();
  await page.getByPlaceholder('Your answer').fill('key 7, shake its head');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByRole('button', { name: 'Go!' })).toBeEnabled({ timeout: 30000 });
  await page.getByRole('button', { name: 'Go!' }).click();
  await expect(doneScreen(page)).toBeVisible({ timeout: 30000 });
  await expect(page.locator('pre')).toContainText('IrReceiver.decode()');
});

test('explanations come from the recorded model answers and are cached per version', async ({ page }) => {
  await pickTurret(page);
  await page.getByRole('button', { name: 'Show me the code' }).click();
  await page.getByRole('button', { name: 'What does this code do?' }).click();
  const xp = page.getByRole('region', { name: 'What the code does' });
  await expect(xp).toBeVisible({ timeout: 30000 });
  await expect(xp.locator('.xstep').first()).toBeVisible();
  await expect(xp.locator('.xstep pre.snip').first()).toBeVisible();                   // the recorded steps carry line ranges
  await expect(xp).not.toContainText(/http/);
  const cached = fs.readdirSync(path.join(dataDir, 'ir-turret', 'versions', '0000')).filter((f) => f.startsWith('explain-'));
  expect(cached).toContain('explain-sketch.json');
  await xp.getByRole('button', { name: 'Close' }).click();
  await page.locator('pre .ln').nth(100).click();
  await page.locator('pre .ln').nth(110).click();
  await page.getByRole('button', { name: /Explain lines 101-111/ }).click();
  await expect(page.getByRole('region', { name: 'What the code does' })).toBeVisible({ timeout: 30000 });
});
