const assert = require('node:assert/strict');
const { test } = require('node:test');
const { chromium } = require('playwright');

test('scorecard role locators remain stable as controlled fields change', async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    // Controlled textarea rendering can mirror value into defaultValue/textContent.
    const fixture = Array.from({ length: 3 }, () => `
      <fieldset>
        <label>Kanıt düzeyi (1–4)<select>
          <option value="">Seçin</option><option value="3">3 · Yeterli kanıt</option>
        </select></label>
        <label>Somut iş kanıtı<textarea oninput="this.defaultValue=this.value"></textarea></label>
      </fieldset>`).join('');
    await page.setContent(fixture);
    assert.equal(await page.getByLabel('Kanıt düzeyi (1–4)', { exact: true }).count(), 0);
    const oldEvidence = page.getByLabel('Somut iş kanıtı', { exact: true });
    assert.equal(await oldEvidence.count(), 3);
    await oldEvidence.nth(0).fill('Synthetic evidence');
    assert.equal(await oldEvidence.count(), 2);

    await page.setContent(fixture);
    const ratings = page.getByRole('combobox', { name: 'Kanıt düzeyi (1–4)', exact: true });
    const evidence = page.getByRole('textbox', { name: 'Somut iş kanıtı', exact: true });
    for (let index = 0; index < 3; index += 1) {
      await ratings.nth(index).selectOption('3');
      await evidence.nth(index).fill(`Synthetic evidence ${index}`);
      assert.equal(await ratings.count(), 3);
      assert.equal(await evidence.count(), 3);
    }
    assert.deepEqual(await ratings.evaluateAll(fields => fields.map(field => field.value)), ['3', '3', '3']);
    assert.deepEqual(await evidence.evaluateAll(fields => fields.map(field => field.value)),
      ['Synthetic evidence 0', 'Synthetic evidence 1', 'Synthetic evidence 2']);

    await page.setContent('<label>Gerekçe<textarea oninput="this.defaultValue=this.value">Görüşme tamamlandı</textarea></label>');
    assert.equal(await page.getByLabel('Gerekçe', { exact: true }).count(), 0);
    const reason = page.getByRole('textbox', { name: 'Gerekçe', exact: true });
    await reason.fill('Synthetic completion reason');
    assert.equal(await reason.inputValue(), 'Synthetic completion reason');
    assert.equal(await reason.count(), 1);
  } finally {
    await browser.close();
  }
});
