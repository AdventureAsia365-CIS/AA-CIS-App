import { test, expect } from '@playwright/test';

// AA-437 bug: /admin/a4-oversight (PR #196) was missing from middleware.ts's PROTECTED_ROUTES
// allow-list, so a logged-in admin got redirected to /login (same fail-closed #4/#5 pattern as
// AA-384/AA-388/AA-405 before it) while every other /admin/* page worked fine in the same
// session. PR #196's own "post-deploy live verification" note only checked the UNAUTHENTICATED
// case (307 there is expected either way — via middleware.ts's `!route` branch OR its `!role`
// branch — so it never actually proved this entry existed). Nghiep caught it live: dashboard/
// metrics/notifications all 200/304 in a real session, but /admin/a4-oversight still 307'd.
//
// Uses the dedicated `e2e-test-admin` account (shared.admin_users, role=admin) instead of the
// stale 'admin'/'admin2026' creds AA-384's spec used (confirmed 401 against live backend as of
// 23/08/2026) — password reset once for this verification, see docs/implementation-notes/
// AA-437-03-middleware-allowlist-fix.md for the new value.

async function loginAsAdmin(page) {
  await page.goto('/login');
  await page.fill('input[type="text"]', 'e2e-test-admin');
  await page.fill('input[type="password"]', 'e2eTest2026!');
  await page.click('button:has-text("Login")');
}

test('logged-in admin reaches /admin/a4-oversight without redirect', async ({ page }) => {
  await loginAsAdmin(page);
  await page.waitForTimeout(1500);
  await page.goto('/admin/a4-oversight');
  await page.waitForTimeout(1000);
  expect(page.url()).toContain('/admin/a4-oversight');
  expect(page.url()).not.toContain('/login');
});

test('regression: /admin/dashboard still reachable after the fix', async ({ page }) => {
  await loginAsAdmin(page);
  await page.waitForTimeout(1500);
  await page.goto('/admin/dashboard');
  await page.waitForTimeout(1000);
  expect(page.url()).toContain('/admin/dashboard');
  expect(page.url()).not.toContain('/login');
});

test('regression: /admin/tenants still reachable after the fix', async ({ page }) => {
  await loginAsAdmin(page);
  await page.waitForTimeout(1500);
  await page.goto('/admin/tenants');
  await page.waitForTimeout(1000);
  expect(page.url()).toContain('/admin/tenants');
  expect(page.url()).not.toContain('/login');
});

test('unauthenticated request to /admin/a4-oversight still redirects to /login', async ({ page }) => {
  await page.goto('/admin/a4-oversight');
  await page.waitForTimeout(1000);
  expect(page.url()).toContain('/login');
});
