// Browser regression: native modal chrome focus is valid; background DOM focus is not.
const assert = require('node:assert/strict');
const path = require('node:path');
const { assertModalFocus } = require(path.resolve(process.argv[2] || 'scripts/react-checks.cjs'));
const { chromium } = require(process.argv[3]);

(async () => {
  assert.equal(typeof assertModalFocus, 'function');
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent('<button id="before">Before</button><dialog data-testid="brief-dialog"><button>Close</button><input><input><textarea></textarea><button>Submit</button></dialog><button id="after">After</button>');
    await page.locator('dialog').evaluate(el => el.showModal());
    await assertModalFocus(page);
    await page.setContent('<button>Before</button><div data-testid="brief-dialog" role="dialog" aria-modal="true"><input id="first"><button id="last">Submit</button></div><button>After</button>');
    await page.locator('#first').focus();
    await assert.rejects(assertModalFocus(page), /outside/);
    await page.evaluate(() => {
      document.addEventListener('keydown', event => {
        if (event.key !== 'Tab') return;
        const first = document.querySelector('#first'), last = document.querySelector('#last');
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      });
      document.querySelector('#first').focus();
    });
    await assertModalFocus(page);
    console.log(JSON.stringify({ nativeModalAccepted: true, backgroundFocusRejected: true, customTrapAccepted: true }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
