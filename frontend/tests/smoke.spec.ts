import {expect, test} from '@playwright/test';

const apiBaseUrl = process.env.API_BASE_URL ?? 'http://127.0.0.1:8000/api';

test('Meeting tasks view renders tasks coming from the API', async ({page, request}) => {
    const tasksResponse = await request.get(`${apiBaseUrl}/tasks`);
    expect(tasksResponse.status()).toBe(200);
    const tasks = (await tasksResponse.json()) as Array<{
        summary: string;
        meetingId: string;
    }>;
    expect(tasks.length).toBeGreaterThan(0);
    const firstTask = tasks[0];
    const meetingResponse = await request.get(`${apiBaseUrl}/meetings/${firstTask.meetingId}`);
    expect(meetingResponse.status()).toBe(200);
    const meeting = (await meetingResponse.json()) as { title: string };
    await page.goto(`/meetings/${firstTask.meetingId}/tasks`);
    await expect(page.getByRole('heading', {name: meeting.title})).toBeVisible();
    await expect(page.getByText(firstTask.summary, {exact: false})).toBeVisible();
});

test('Meetings list displays records persisted in SQLite', async ({page, request}) => {
    const title = `E2E Meeting ${Date.now()}`;
    const startedAt = new Date().toISOString();
    const createResponse = await request.post(`${apiBaseUrl}/meetings`, {
        data: {title, startedAt},
    });
    expect(createResponse.status()).toBe(201);
    const meeting = (await createResponse.json()) as { id: string };

    await page.goto('/meetings');
    await expect(page.getByRole('heading', {name: 'Meetings'})).toBeVisible();
    await expect(page.getByText(title)).toBeVisible();

    await request.delete(`${apiBaseUrl}/meetings/${meeting.id}`);
});
