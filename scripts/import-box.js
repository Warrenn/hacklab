// Dump one Hack Pack box's files from the IDE's Monaco editor.
// Run with the machine-wide harness (no project installs):
//   pw scripts/import-box.js <slug> <out.json> [folderName]
// Writes {slug, files: {"<Dir>/<file>": text}}. Idempotent: same page, same dump.
// The explorer sidebar lists EVERY box's folder (only the current one expanded). Under our
// folder sit either files (IRTurret: stock.ino, passcode.ino) or sketch subfolders, some
// collapsed (OmnibotForklift: AdvancedSwagDrive, Gyro, StockCode). We expand the collapsed
// subfolders, then click every file button and wait for its model to appear in Monaco.
// Our folder is matched by name (IRTurret ~ ir-turret); pass folderName when that fails
// (e.g. "Synthesizer" for laser-synthesizer). The next box's folder ends our section.
const { chromium } = require('@playwright/test');
const fs = require('fs');

const [slug, out, folderArg] = process.argv.slice(2);
if (!slug || !out) { console.error('usage: pw scripts/import-box.js <slug> <out.json> [folderName]'); process.exit(2); }
const norm = (s) => s.toLowerCase().replace(/[^a-z0-9]/g, '');
const isFile = (s) => /\.(ino|h|hpp|cpp|c|txt|md|json)$/i.test(s.trim());

const monacoModels = () => {
  const fr = [...document.querySelectorAll('iframe')].find((f) => /monaco/.test(f.src));
  return fr?.contentWindow?.monaco?.editor?.getModels?.() || [];
};
const dumpModels = (page) => page.evaluate(() => {
  const fr = [...document.querySelectorAll('iframe')].find((f) => /monaco/.test(f.src));
  const files = {};
  for (const m of fr?.contentWindow?.monaco?.editor?.getModels?.() || []) files[m.uri.toString().replace(/^inmemory:\//, '')] = m.getValue();
  return files;
});

(async () => {
  const browser = await chromium.launch({ headless: process.env.HEADLESS !== 'false' });
  try {
    const page = await browser.newPage();
    await page.goto('https://ide.crunchlabs.com/', { waitUntil: 'domcontentloaded' });
    const slugs = await page.locator('a[href*="/editor/"]').evaluateAll((as) => as.map((a) => a.getAttribute('href').split('/editor/')[1].split(/[/?#]/)[0]));
    const others = new Set(slugs.filter((s) => s && s !== slug).map(norm));

    await page.goto(`https://ide.crunchlabs.com/editor/${slug}`, { waitUntil: 'domcontentloaded' });
    await page.locator('iframe[src*="monaco"]').waitFor({ timeout: 60000 });
    const closeModal = page.getByRole('dialog').getByRole('button', { name: '✕' });
    await closeModal.waitFor({ timeout: 8000 }).then(() => closeModal.click()).catch(() => {});
    await page.waitForFunction(`(${monacoModels})().length > 0`, null, { timeout: 60000 }); // main sketch opens itself

    const sidebar = page.locator('aside, [role="complementary"]').first();
    const buttons = sidebar.getByRole('button');
    await buttons.first().waitFor({ timeout: 60000 });
    const readNames = async () => (await buttons.allTextContents()).map((s) => s.trim());
    let names = await readNames();
    const want = norm(folderArg || slug);
    const start = names.findIndex((n) => !isFile(n) && (norm(n) === want || want.endsWith(norm(n)) || norm(n).endsWith(want)));
    if (start < 0) throw new Error(`folder for ${slug} not found in the explorer (${names.filter((n) => !isFile(n)).join(', ')}); pass folderName`);
    const sectionEnd = (ns) => { let e = ns.length; for (let i = start + 1; i < ns.length; i++) if (!isFile(ns[i]) && others.has(norm(ns[i]))) { e = i; break; } return e; };
    const isOtherBox = (n) => !isFile(n) && others.has(norm(n));

    // expand collapsed subfolders: a folder followed directly by a folder (or the end) has no files showing
    for (let i = start + 1; i < sectionEnd(names); i++) {
      if (isFile(names[i]) || isOtherBox(names[i])) continue;
      const next = names[i + 1];
      if (next !== undefined && isFile(next)) continue; // already expanded
      if ((await buttons.nth(i).textContent()).trim() !== names[i]) throw new Error('explorer changed under us; rerun');
      await buttons.nth(i).click({ timeout: 10000 });
      await page.waitForTimeout(800);
      names = await readNames();
    }
    const end = sectionEnd(names);
    const fileIdx = [];
    for (let i = start + 1; i < end; i++) if (isFile(names[i])) fileIdx.push(i);
    if (!fileIdx.length) throw new Error(`no files listed under ${names[start]}: ${names.slice(start + 1, end).join(', ')}`);

    for (const i of fileIdx) {
      const b = buttons.nth(i);
      if ((await b.textContent()).trim() !== names[i]) throw new Error('explorer changed under us; rerun');
      await b.click({ timeout: 10000 });
      // nested sketches: the model uri is <Sub>/<file> (two config.h files must not be confused)
      let j = i - 1;
      while (j > start && isFile(names[j])) j--;
      const tail = (j > start ? `/${names[j]}` : '') + `/${names[i]}`;
      await page.waitForFunction(`(${monacoModels})().some((m) => m.uri.toString().endsWith(${JSON.stringify(tail)}))`, null, { timeout: 15000 })
        .catch(() => console.error(`warning: ${tail} never appeared in the editor`));
    }
    const wanted = new Set(fileIdx.map((i) => names[i]));
    const files = {};
    for (const [k, v] of Object.entries(await dumpModels(page))) {
      const file = k.split('/').pop();
      if (!wanted.has(file)) continue;
      files[k.includes('/') ? k : `${file.replace(/\.[^.]+$/, '')}/${file}`] = v;
    }
    fs.writeFileSync(out, JSON.stringify({ slug, files }, null, 1) + '\n');
    console.log(`${Object.keys(files).length} file(s) -> ${out}: ${Object.keys(files).join(', ')}`);
  } finally {
    await browser.close();
  }
})().catch((err) => { console.error(err); process.exit(1); });
