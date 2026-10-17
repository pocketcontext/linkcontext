const { chromium } = require('../ui/node_modules/@playwright/test');
(async () => {
  const [, , base, table, id, title, password] = process.argv;
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(base + '/#/' + table + '/' + id);
  await page.getByLabel('Email', { exact: true }).fill('reader@example.com');
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('heading', { name: new RegExp(title) }).waitFor();
  await page.reload();
  await page.getByRole('heading', { name: new RegExp(title) }).waitFor();
  const second = await context.newPage();
  await second.goto(base + '/#/' + table + '/' + id);
  await second.getByRole('heading', { name: new RegExp(title) }).waitFor();
  await second.close();
  await page.getByLabel('Collection').selectOption(table);
  await page.getByRole('searchbox').fill('Synthetic reader');
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page.getByText('Synthetic reader 34').waitFor();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.getByRole('button', { name: 'Sign in', exact: true }).waitFor();
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
