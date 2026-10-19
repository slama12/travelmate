import { defineConfig } from "@playwright/test";

const chromeWinPath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

export default defineConfig({
  testDir: "./tests",
  timeout: 90_000,
  retries: 0,
  use: {
    baseURL: process.env.FRONTEND_BASE_URL || "http://localhost:5173",
    headless: true,
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROME_PATH || chromeWinPath,
      args: ["--disable-gpu", "--no-sandbox"],
    },
  },
});
