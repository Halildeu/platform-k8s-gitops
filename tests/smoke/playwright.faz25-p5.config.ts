import { defineConfig } from '@playwright/test';

const chromiumExecutablePath = process.env.P5_CHROMIUM_EXECUTABLE_PATH;
if (!chromiumExecutablePath) {
  throw new Error('P5_CHROMIUM_EXECUTABLE_PATH is required');
}

export default defineConfig({
  testDir: '.',
  testMatch: /faz25-p5-product-surface\.spec\.ts/,
  timeout: 180_000,
  expect: {
    timeout: 20_000,
  },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['line']],
  use: {
    baseURL: process.env.P5_BASE_URL ?? 'https://testai.acik.com',
    browserName: 'chromium',
    headless: true,
    launchOptions: {
      executablePath: chromiumExecutablePath,
    },
    serviceWorkers: 'block',
    viewport: { width: 1440, height: 1000 },
    screenshot: 'off',
    trace: 'off',
    video: 'off',
  },
});
