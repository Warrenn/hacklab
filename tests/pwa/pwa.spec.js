// Kid-facing PWA against the mock backend. Run from the repo root with the
// machine-wide harness:  pw test tests/pwa      (HACKLAB_PYTHON=<python> to override .venv)
// Two uvicorn instances per worker: one with ANTHROPIC_API_KEY (Home), one
// without (Offline). PYTHONPATH pins `hacklab` to this checkout; `python -m
// uvicorn` avoids the venv's console-script launchers (their shebang breaks
// when the checkout folder is renamed).
const { test, expect } = require('@playwright/test');
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
test.beforeEach(async ({ page }) => page.setViewportSize({ width: 1180, height: 820 })); // iPad landscape

async function pickTurret(page, url) {
  await page.goto(url);
  await expect(page.getByRole('heading', { name: 'Which box is plugged in?' })).toBeVisible();
  await page.getByRole('button', { name: /IR Turret/ }).click();
  await page.getByRole('button', { name: "Let's go" }).click();
}

test('box picker leads to Home when the AI helper is here', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible();
  await expect(page.getByText('AI helper is here')).toBeVisible();
  await expect(page.getByText('IR Turret · plugged in')).toBeVisible();
  await expect(page.getByText('Try one of these')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Undo last change' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Back to how it came' })).toBeVisible();
});

test('asking walks the Working stages over SSE and lands on Done, then Undo', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByPlaceholder(/shake its head/).fill('Make it nod when I press 1');
  await page.getByRole('button', { name: 'Go!' }).click();
  await expect(page.getByText('You asked')).toBeVisible();
  await expect(page.getByText('“Make it nod when I press 1”')).toBeVisible();
  // Stage text comes from the server (message_kid), not from the page.
  await expect(page.getByText('The AI helper is thinking about your idea.')).toBeVisible();
  await expect(page.getByText('Turning the code into robot language.')).toBeVisible({ timeout: 10000 });
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('Curious?')).toBeVisible();
  await expect(page.getByText('The code that does it')).toBeVisible();
  await expect(page.locator('pre')).toContainText('void loop');
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What should the IR Turret do?' })).toBeVisible({ timeout: 15000 });
});

test('a failed job shows the kid message and one next action', async ({ page }) => {
  await pickTurret(page, homeUrl);
  await page.getByPlaceholder(/shake its head/).fill('fail on purpose');
  await page.getByRole('button', { name: 'Go!' }).click();
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
  await expect(page.getByRole('button', { name: /Shake its head no/ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Undo last change' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Back to how it came' })).toBeVisible();
  await expect(page.locator('a[href^="http"]')).toHaveCount(0); // no external links, ever
});

test('Tweak sliders are bound to the behaviour ranges and clamp', async ({ page }) => {
  await pickTurret(page, offlineUrl);
  await page.getByRole('button', { name: /Change the numbers/ }).click();
  await expect(page.getByText('Level 2: change the numbers')).toBeVisible();
  const shakes = page.getByLabel('shakes');
  await expect(shakes).toHaveAttribute('max', '10');
  await shakes.fill('10');
  await expect(page.getByTestId('val-shakes')).toHaveText('10');
  await page.getByRole('button', { name: 'Reset numbers' }).click();
  await expect(page.getByTestId('val-shakes')).toHaveText('3');
  await expect(page.locator('pre')).toContainText('3'); // live code shows the value
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
  await page.goto(homeUrl);
  await expect(page.getByRole('heading', { name: 'Which box is plugged in?' })).toBeVisible();
  await shot('1-box-picker');
  await page.getByRole('button', { name: /IR Turret/ }).click();
  await page.getByRole('button', { name: "Let's go" }).click();
  await expect(page.getByText('Try one of these')).toBeVisible();
  await shot('2-home');
  await page.getByPlaceholder(/shake its head/).fill('Make it shake its head when I press 7');
  await page.getByRole('button', { name: 'Go!' }).click();
  await expect(page.getByText('Turning the code into robot language.')).toBeVisible({ timeout: 10000 });
  await shot('3-working');
  await expect(page.getByRole('heading', { name: /^Done!/ })).toBeVisible({ timeout: 15000 });
  await shot('4-done');
  await page.goto(offlineUrl);
  await page.getByRole('button', { name: /IR Turret/ }).click();
  await page.getByRole('button', { name: "Let's go" }).click();
  await expect(page.getByRole('heading', { name: 'Pick a trick' })).toBeVisible();
  await shot('5-offline');
  await page.getByRole('button', { name: /Change the numbers/ }).click();
  await expect(page.getByText('Level 2: change the numbers')).toBeVisible();
  await shot('6-tweak');
});
