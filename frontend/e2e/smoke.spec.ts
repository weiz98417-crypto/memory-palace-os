import { expect, test } from '@playwright/test'

test('health and protected entries respond on the real stack', async ({ page, request }) => {
  expect((await request.get('/health')).status()).toBe(200)
  for (const path of ['/admin/', '/assistant/', '/operations/scenic/', '/operations/evaluation/', '/simulator/wecom/']) {
    const response = await page.goto(path)
    expect(response?.status()).toBeLessThan(500)
  }
})

test('manager can authenticate when demo credentials are configured', async ({ page }) => {
  const password = process.env.SCENIC_DEMO_PASSWORD
  test.skip(!password, 'SCENIC_DEMO_PASSWORD is required for authenticated UI acceptance')
  await page.goto('/admin/')
  await page.locator('#login-username').fill('wangfang')
  await page.locator('#login-password').fill(password!)
  await page.locator('#login-submit').click()
  await expect(page.locator('#app-screen')).toHaveClass(/active/, { timeout: 15_000 })
  await expect(page.locator('body')).toContainText(/指挥中心|下一步处置|Memory Palace/i)
})
