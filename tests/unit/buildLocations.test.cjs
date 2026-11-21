const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { test } = require('node:test')
const loadBuildLocations = require('../../scripts/loadBuildLocations')

test('validated build locations retain only warp metadata and reject unsafe input', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'windscribe-build-locations-test-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  const file = path.join(root, 'locations.json')
  const good = {
    data: [
      {
        id: 1,
        country_code: 'US',
        tz: 'America/New_York',
        groups: [{ id: 2, gps: '40.7,-74.0', password: 'must-not-be-retained' }],
        token: 'must-not-be-retained',
      },
    ],
  }
  const write = value => fs.writeFileSync(file, JSON.stringify(value))
  write(good)
  assert.deepEqual(loadBuildLocations(file), {
    data: [
      { id: 1, country_code: 'US', tz: 'America/New_York', groups: [{ id: 2, gps: '40.7,-74' }] },
    ],
  })

  for (const bad of [
    { data: [] },
    { data: [{ ...good.data[0], id: -1 }] },
    { data: [{ ...good.data[0], country_code: '__proto__' }] },
    { data: [{ ...good.data[0], tz: "America/New_York');alert(1)//" }] },
    { data: [{ ...good.data[0], tz: 'Unknown/Invalid' }] },
    { data: [{ ...good.data[0], groups: [{ id: 2, gps: '91,0' }] }] },
    { data: [{ ...good.data[0], groups: [{ id: 2, gps: '1,2);alert(1)' }] }] },
    { data: [good.data[0], good.data[0]] },
  ]) {
    write(bad)
    assert.throws(() => loadBuildLocations(file))
  }
})
