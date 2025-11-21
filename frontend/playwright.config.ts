import {defineConfig} from '@playwright/test';

const reuseServer = process.env.CI ? false : true;

export default defineConfig({
    testDir: './tests',
    fullyParallel: true,
    timeout: 120_000,
    use: {
        baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:4173',
        headless: true,
        trace: 'on-first-retry',
    },
    webServer: [
        {
            command:
                'poetry run uvicorn backend.app:app --host 127.0.0.1 --port 8000',
            url: 'http://127.0.0.1:8000/api/meetings',
            reuseExistingServer: reuseServer,
            cwd: '..',
            timeout: 120_000,
        },
        {
            command: 'npm run preview -- --host 127.0.0.1 --port 4173',
            url: 'http://127.0.0.1:4173',
            reuseExistingServer: reuseServer,
            timeout: 120_000,
        },
    ],
});
