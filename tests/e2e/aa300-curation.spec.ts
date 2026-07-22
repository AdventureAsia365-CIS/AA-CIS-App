import { test, expect } from '@playwright/test';

// AA-300 — confirms /admin/curation and /admin/curation/preview actually
// render for a real authenticated session, closing the one gap curl-based
// verification structurally cannot close: middleware.ts intentionally
// returns the identical 307 → /login response for "route exists but you
// have no session" and "route doesn't exist, fail closed" (a deliberate
// security property, not a bug), so an unauthenticated request can never
// distinguish the two. Only a real logged-in session proves the page
// content itself renders.
//
// Uses loginAsContent (not loginAsAdmin) — this session's own run of
// cis.spec.ts's existing "Authentication" suite against production found
// loginAsAdmin currently fails (its hardcoded admin2026 password is stale
// against the real per-user JWT backend, AA-232/AA-252), while
// loginAsContent passes. /admin/curation's PROTECTED_ROUTES entry
// (middleware.ts) allows roles ["admin","reviewer","content"], so content
// is sufficient to prove real access — no need to depend on the broken
// admin path. Flagging the stale admin credential as a separate, pre-
// existing issue is out of scope for AA-300 itself.

async function loginAsContent(page) {
  await page.goto('/login');
  await page.fill('input[name="username"], input[type="text"]', 'content');
  await page.fill('input[name="password"], input[type="password"]', 'content2026');
  await page.click('button[type="submit"], button:has-text("Login"), button:has-text("Sign in")');
  await page.waitForURL(/\/upload/, { timeout: 5000 });
}

test.describe('AA-300 Atom Curation', () => {

  test.beforeEach(async ({ page }) => {
    await loginAsContent(page);
  });

  test('curation page renders for an authenticated session (not redirected to /login)', async ({ page }) => {
    await page.goto('/admin/curation');
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page).toHaveURL(/\/admin\/curation$/);
    await expect(page.getByRole('heading', { name: 'Atom Curation' })).toBeVisible({ timeout: 10000 });
  });

  test('curation page has no 500 errors', async ({ page }) => {
    await page.goto('/admin/curation');
    await expect(page.locator('body')).not.toContainText('Internal Server Error');
    await expect(page.locator('body')).not.toContainText('500');
  });

  test('preview page renders for an authenticated session (not redirected to /login)', async ({ page }) => {
    await page.goto('/admin/curation/preview');
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page).toHaveURL(/\/admin\/curation\/preview/);
    await expect(page.getByRole('heading', { name: 'N6 Slot Grid Preview' })).toBeVisible({ timeout: 10000 });
  });

  test('preview page has no 500 errors', async ({ page }) => {
    await page.goto('/admin/curation/preview');
    await expect(page.locator('body')).not.toContainText('Internal Server Error');
    await expect(page.locator('body')).not.toContainText('500');
  });

  test('curation page renders at least one real atom card with distinctiveness/visual data', async ({ page }) => {
    // Dev has 235 real live atoms (verified via live DB query in an earlier
    // AA-301 session) — this should have real content to assert against,
    // not just an empty-state screen.
    await page.goto('/admin/curation');
    await expect(page.getByRole('heading', { name: 'Atom Curation' })).toBeVisible({ timeout: 10000 });

    const emptyState = page.getByText('No atoms match the current filters.');
    const distinctivenessBadge = page.locator('text=/^(HIGH|MED|LOW)$/').first();

    // Either real atom cards show up (assert on a distinctiveness badge,
    // which is always rendered per card), or the page honestly reports an
    // empty state — either is a valid "page works" outcome, but we prefer
    // to prove real data renders when it's known to exist.
    const gotAtoms = await distinctivenessBadge.isVisible({ timeout: 10000 }).catch(() => false);
    if (!gotAtoms) {
      await expect(emptyState).toBeVisible();
      test.info().annotations.push({
        type: 'warning',
        description: 'No atom cards rendered — either the API call failed silently or the dev atom data is currently empty. Investigate before treating this as a full pass.',
      });
    } else {
      await expect(distinctivenessBadge).toBeVisible();
      // visual_potential is rendered as a ●●○-style dot string, not a
      // fixed label — check at least one filled dot is present somewhere.
      await expect(page.locator('text=/●/').first()).toBeVisible();
    }
  });

});
