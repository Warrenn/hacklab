// Full-stack browser tests: the real runner, sketch store, box profiles, tweak
// rendering and genie skeleton assembly on the emulated board, with the AI
// helper replaying the recorded goldens (HACKLAB_GENIE=golden). Everything the
// kid does is verified end to end except the USB cable, which scripts/hil-*.sh
// cover on the Pi. Run with the machine-wide harness:  pw test tests/pwa
const { test, expect } = require('@playwright/test');
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
test.beforeEach(async ({ page }) => page.setViewportSize({ width: 1180, height: 820 }));

async function pickTurret(page) {
  await page.goto(url);
  const picker = page.getByRole('heading', { name: 'Which box is plugged in?' });
  const chip = page.getByRole('button', { name: /plugged in/ });
  await expect(picker.or(chip)).toBeVisible({ timeout: 15000 }); // first render waits for /api/status
  if (!(await picker.isVisible())) await chip.click();
  await expect(picker).toBeVisible();
  await page.getByRole('button', { name: 'IR Turret', exact: true }).click();
  await page.getByRole('button', { name: "Let's go" }).click();
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible({ timeout: 15000 });
}
// The Done screen's heading IS the kid message from the server, so wait for the screen's buttons.
const doneScreen = (page) => page.getByRole('button', { name: 'Try something else' });

test('the whole loop: ask -> real compile/flash on the emulated board -> Done with the real code -> Undo', async ({ page }) => {
  await pickTurret(page);
  await expect(page.getByText('How it came', { exact: true })).toBeVisible();
  await expect(page.getByText('version 0000')).toBeVisible();
  await page.getByPlaceholder(/shake its head/).fill('make it shake its head when I press 7');
  await page.getByRole('button', { name: 'Go!' }).click();
  await expect(doneScreen(page)).toBeVisible({ timeout: 30000 });
  // the kid message is the recorded model answer, not page copy; prompts come from the box's concepts
  await expect(page.locator('main')).toContainText(/Press 7|press 7/);
  await expect(page.getByText('Curious?')).toBeVisible();
  await page.getByRole('button', { name: /Want to/ }).first().click();
  await expect(page.locator('main')).not.toContainText(/http/);
  // the code shown is the assembled skeleton with the model's rule inside the real stock sketch
  await expect(page.locator('pre')).toContainText('cmd7');
  await expect(page.locator('pre')).toContainText('IrReceiver.decode()');
  await expect(page.locator('pre')).not.toContainText('//@@');
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible({ timeout: 30000 });
  await expect(page.getByText('version 0000')).toBeVisible();
  // the store on disk agrees: baseline only after the undo
  const versions = fs.readdirSync(path.join(dataDir, 'ir-turret', 'versions'));
  expect(versions).toEqual(['0000']);
});

test('a trick from the box profile flashes and becomes a version; the code is the shipped behaviour', async ({ page }) => {
  await pickTurret(page);
  await page.getByRole('button', { name: /Dance/ }).click();
  await expect(doneScreen(page)).toBeVisible({ timeout: 30000 });
  await expect(page.locator('pre')).toContainText('shakeNo(1)');  // the shipped behaviour's own code
  const stored = fs.readdirSync(path.join(dataDir, 'ir-turret', 'versions')).sort();
  expect(stored[stored.length - 1]).not.toBe('0000');
});

test('changing the numbers renders the chosen value into the flashed sketch, clamped to the range', async ({ page }) => {
  await pickTurret(page);
  await page.getByRole('button', { name: /Dance/ }).click();
  await expect(doneScreen(page)).toBeVisible({ timeout: 30000 });
  await page.getByRole('button', { name: 'Try it' }).click();
  await expect(page.getByText('Level 2: change the numbers')).toBeVisible();
  const rounds = page.getByLabel(/How many rounds/);
  await expect(rounds).toHaveAttribute('max', '5');
  await rounds.fill('4');
  await page.getByRole('button', { name: /Send to IR Turret/ }).click();
  await expect(doneScreen(page)).toBeVisible({ timeout: 30000 });
  await expect(page.locator('pre')).toContainText(/i < 4;/);
  // what was actually "uploaded": the stored current version carries the number
  const cur = fs.readFileSync(path.join(dataDir, 'ir-turret', 'current'), 'utf8').trim();
  const dir = path.join(dataDir, 'ir-turret', 'versions', cur);
  const ino = fs.readdirSync(dir).find((d) => d !== 'meta.json');
  const src = fs.readFileSync(path.join(dir, ino, `${ino}.ino`), 'utf8');
  expect(src).toMatch(/i < 4;/);
});

test('Back to how it came restores the stock sketch after several changes', async ({ page }) => {
  await pickTurret(page);
  for (const name of [/Dance/, /Fire a burst/]) {
    await page.getByRole('button', { name }).click();
    await expect(doneScreen(page)).toBeVisible({ timeout: 30000 });
    await page.getByRole('button', { name: 'Try something else' }).click();
  }
  await page.getByRole('button', { name: 'Back to how it came' }).click();
  await expect(page.getByText('version 0000')).toBeVisible({ timeout: 30000 });
  expect(fs.readdirSync(path.join(dataDir, 'ir-turret', 'versions'))).toEqual(['0000']);
});
