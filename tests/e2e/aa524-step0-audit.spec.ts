import { test } from '@playwright/test';

const SHOT_DIR = 'tests/e2e/results/aa524-step0';
const API_KEY = process.env.WANDERLUX_API_KEY || '';

// Vietnamese diacritic range, same detection approach used for the codebase grep.
const VN_RE = /[àáâãèéêìíòóôõùúăđĩũơưẠ-ỹ]/;

test.describe.configure({ mode: 'serial' });

test.beforeEach(async ({ page }) => {
  test.skip(!API_KEY, 'WANDERLUX_API_KEY env var not set');
  await page.goto('/tenant-login');
  await page.fill('input[type="password"]', API_KEY);
  await page.click('button:has-text("Access Portal")');
  await page.waitForURL('**/portal**', { timeout: 10000 });
});

const PAGES: { name: string; path: string; scrollListSelector?: string }[] = [
  { name: 't7-planning-social-content', path: '/portal/t7-planning' },
  { name: 't8-angle-gate-write-content', path: '/portal/t8-angle-gate' },
  { name: 't10-review-my-content', path: '/portal/t10-review' },
  { name: 't11-publish', path: '/portal/t11-publish' },
];

for (const { name, path } of PAGES) {
  test(`audit ${name}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(path);
    await page.waitForTimeout(2000);

    // 1. Top-of-page screenshot (viewport only, not fullPage) — shows real narrow-vs-wide layout
    await page.screenshot({ path: `${SHOT_DIR}/${name}-top.png` });

    // 2. Full-page screenshot for whitespace/width inspection
    await page.screenshot({ path: `${SHOT_DIR}/${name}-full.png`, fullPage: true });

    // 3. Scroll down inside the page, then screenshot again — sticky-header check
    await page.evaluate(() => {
      const main = document.querySelector('main');
      if (main) main.scrollTop = 600;
      window.scrollTo(0, 600);
    });
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOT_DIR}/${name}-scrolled.png` });

    // 4. Text content dump + Vietnamese-diacritic scan
    const bodyText = await page.evaluate(() => document.body.innerText);
    const vnLines = bodyText.split('\n').filter(l => VN_RE.test(l));
    console.log(`=== ${name} — Vietnamese lines found: ${vnLines.length} ===`);
    vnLines.forEach(l => console.log('  VN:', l.trim()));

    // 5. Measure main content width vs viewport (narrow-layout check)
    const widths = await page.evaluate(() => {
      const main = document.querySelector('main');
      const card = document.querySelector('main > div, main > *');
      return {
        viewportWidth: window.innerWidth,
        mainWidth: main?.clientWidth ?? null,
        firstChildWidth: card?.clientWidth ?? null,
      };
    });
    console.log(`=== ${name} — widths:`, JSON.stringify(widths));
  });
}

// Slate: click into a Channel with content, expand a subject row, to see AngleGateWizard inline
test('audit slate expanded state', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/portal/t7-planning');
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${SHOT_DIR}/slate-initial.png`, fullPage: true });

  const bodyText = await page.evaluate(() => document.body.innerText);
  const vnLines = bodyText.split('\n').filter(l => VN_RE.test(l));
  console.log(`=== slate — Vietnamese lines found: ${vnLines.length} ===`);
  vnLines.forEach(l => console.log('  VN:', l.trim()));
});

// My Content (Review): expand a card if any exist
test('audit review expanded card', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/portal/t10-review');
  await page.waitForTimeout(2000);
  const firstCard = page.locator('button').filter({ hasText: /./ }).first();
  const count = await page.locator('[id^="review-card-"]').count();
  console.log(`=== review cards found: ${count} ===`);
  if (count > 0) {
    await page.locator('[id^="review-card-"] button').first().click();
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${SHOT_DIR}/review-expanded.png`, fullPage: true });
  }
});
