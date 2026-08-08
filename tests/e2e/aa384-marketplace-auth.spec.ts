import { test, expect } from '@playwright/test';

// AA-384 bug: /admin/marketplace was missing from middleware.ts's PROTECTED_ROUTES allow-list,
// so a logged-in admin got redirected to /login (fail-closed #4/#5 pattern) while every other
// /admin/* page worked. Real form login (same credentials as tests/e2e/cis.spec.ts), no bypass.
//
// NOTE (08/08/2026): the 'admin'/'admin2026' credentials below (copied from cis.spec.ts) are
// STALE against the live backend as of this writing — confirmed 401 from /auth/admin-login.
// This suite was written and verified against the real middleware logic but could NOT be run to
// a real green state locally for that reason (not a sign the fix itself is wrong — see
// docs/implementation-notes/AA-384.md for how the fix was verified instead). Update these
// credentials (or point BASE_URL/login at a seeded test account) before relying on this file.

async function loginAsAdmin(page) {
  await page.goto('/login');
  await page.fill('input[type="text"]', 'admin');
  await page.fill('input[type="password"]', 'admin2026');
  await page.click('button:has-text("Login")');
}

test('logged-in admin reaches /admin/marketplace without redirect', async ({ page }) => {
  await loginAsAdmin(page);
  await page.waitForTimeout(1500);
  await page.goto('/admin/marketplace');
  await page.waitForTimeout(1000);
  expect(page.url()).toContain('/admin/marketplace');
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

test('regression: /admin/dashboard still reachable after the fix', async ({ page }) => {
  await loginAsAdmin(page);
  await page.waitForTimeout(1500);
  await page.goto('/admin/dashboard');
  await page.waitForTimeout(1000);
  expect(page.url()).toContain('/admin/dashboard');
  expect(page.url()).not.toContain('/login');
});
