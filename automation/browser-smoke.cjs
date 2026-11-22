// Offline smoke of the actual built extension, in a disposable profile inside
// a container without release credentials or network access.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const puppeteer = require('puppeteer-core')

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ws-ci-browser-'))
const extension = path.join(tmp, 'extension')
const profile = path.join(tmp, 'profile')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

async function retry(fn, description, timeout = 45000) {
  const end = Date.now() + timeout
  let last
  while (Date.now() < end) {
    try { if (await fn()) return } catch (err) { last = err }
    await sleep(500)
  }
  throw new Error(`${description} timed out${last ? `: ${last.message}` : ''}`)
}

async function main() {
  if (!process.env.CHROME_BINARY || !process.env.WS_EXPECTED_VERSION) throw new Error('Missing smoke-test configuration')
  fs.cpSync('/work/build', extension, { recursive: true })
  let browser
  try {
    browser = await puppeteer.launch({
      executablePath: process.env.CHROME_BINARY,
      headless: true,
      pipe: true,
      userDataDir: profile,
      timeout: 60000,
      ignoreDefaultArgs: ['--disable-extensions'],
      args: [
        '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
        '--disable-background-networking', '--no-first-run', '--no-default-browser-check',
        `--disable-extensions-except=${extension}`, `--load-extension=${extension}`,
      ],
    })
    const worker = await browser.waitForTarget(
      target => target.type() === 'service_worker' && /^chrome-extension:\/\/[a-p]{32}\/backgroundScripts\.js$/.test(target.url()),
      { timeout: 60000 },
    )
    const workerUrl = new URL(worker.url())
    const origin = `${workerUrl.protocol}//${workerUrl.host}`
    const page = await browser.newPage()
    await page.goto(`${origin}/popup.html`, { waitUntil: 'domcontentloaded', timeout: 30000 })
    await page.waitForFunction(() => document.getElementById('app-container')?.childElementCount > 0, { timeout: 45000 })
    const manifest = await page.evaluate(() => ({
      version: chrome.runtime.getManifest().version,
      mv: chrome.runtime.getManifest().manifest_version,
      proxy: !!chrome.proxy?.settings,
      webrtc: !!chrome.privacy?.network?.webRTCIPHandlingPolicy,
      dnr: !!chrome.declarativeNetRequest,
    }))
    assert.equal(manifest.version, process.env.WS_EXPECTED_VERSION)
    assert.equal(manifest.mv, 3)
    assert.equal(manifest.proxy && manifest.webrtc && manifest.dnr, true)
    await retry(async () => (await page.evaluate(async () => {
      const result = await chrome.runtime.sendMessage({ type: 'chromex.fetch_state', portName: 'WS_BROWSER_EXTENSION_STORE' })
      return !!result && typeof result.payload === 'object' && result.payload !== null
    })), 'initial Redux state')
    const rules = await page.evaluate(() => chrome.declarativeNetRequest.getEnabledRulesets())
    assert.ok(rules.length > 0, 'no filtering rulesets enabled')

    // A stopped extension worker can retain its DevTools target. Observe the
    // actual MV3 running-status transitions instead of relying on target removal.
    let stopped = false
    let restarted = false
    const cdp = await page.createCDPSession()
    cdp.on('ServiceWorker.workerVersionUpdated', event => {
      for (const version of event.versions) {
        if (version.scriptURL !== worker.url()) continue
        if (version.runningStatus === 'stopped') stopped = true
        if (stopped && version.runningStatus === 'running') restarted = true
        if (process.env.WS_SMOKE_DEBUG) console.log('Worker status:', version.runningStatus)
      }
    })
    await cdp.send('ServiceWorker.enable')
    await cdp.send('ServiceWorker.stopAllWorkers')
    await retry(() => stopped, 'service-worker shutdown', 20000)
    await retry(async () => (await page.evaluate(async () => {
      const result = await chrome.runtime.sendMessage({ type: 'chromex.fetch_state', portName: 'WS_BROWSER_EXTENSION_STORE' })
      return !!result && typeof result.payload === 'object' && result.payload !== null
    })), 'Redux state after service-worker restart')
    await retry(() => restarted, 'service-worker reactivation', 30000)
    console.log(`Offline built-extension smoke passed: MV3 ${manifest.version}, popup and Redux state, ${rules.length} enabled rulesets, worker stopped and reactivated`)
  } finally {
    if (browser) await browser.close()
    fs.rmSync(tmp, { recursive: true, force: true })
  }
}

main().catch(err => { console.error('Offline extension smoke failed:', err.message); process.exitCode = 1 })
