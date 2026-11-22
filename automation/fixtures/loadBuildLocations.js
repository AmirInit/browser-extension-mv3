const fs = require('fs')
const locales = require('./buildUtils/constants/locales')

// Accept only the fields consumed by the warp generators. In particular,
// never propagate account data, proxy credentials, or API tokens into a build.
function loadBuildLocations(file) {
  const parsed = JSON.parse(fs.readFileSync(file, 'utf8'))
  if (!Array.isArray(parsed?.data) || parsed.data.length === 0) {
    throw new Error('Build locations must contain a non-empty data array')
  }
  const locationIds = new Set()
  const datacenterIds = new Set()
  const data = parsed.data.map(location => {
    if (!Number.isSafeInteger(location?.id) || location.id <= 0 || locationIds.has(location.id)) {
      throw new Error('Invalid or duplicate location ID in build locations')
    }
    locationIds.add(location.id)
    const countryCode = location.country_code ?? 'AUTO'
    if (typeof countryCode !== 'string' || !Object.hasOwn(locales, countryCode)) {
      throw new Error('Unknown country code in build locations')
    }
    const tz = location.tz
    if (tz != null) {
      if (typeof tz !== 'string' || !/^[A-Za-z0-9_+.-]+(?:\/[A-Za-z0-9_+.-]+)+$/.test(tz)) {
        throw new Error('Invalid timezone in build locations')
      }
      try {
        new Intl.DateTimeFormat('en', { timeZone: tz })
      } catch (_) {
        throw new Error('Unknown timezone in build locations')
      }
    }
    if (location.groups != null && !Array.isArray(location.groups)) {
      throw new Error('Invalid datacenter list in build locations')
    }
    const groups = (location.groups ?? []).map(group => {
      if (!Number.isSafeInteger(group?.id) || group.id <= 0 || datacenterIds.has(group.id)) {
        throw new Error('Invalid or duplicate datacenter ID in build locations')
      }
      datacenterIds.add(group.id)
      let gps = group.gps
      if (gps != null) {
        if (typeof gps !== 'string') throw new Error('Invalid coordinates in build locations')
        const parts = gps.split(',')
        if (parts.length !== 2 || !parts.every(x => /^\s*[+-]?\d+(?:\.\d+)?\s*$/.test(x))) {
          throw new Error('Invalid coordinates in build locations')
        }
        const [latitude, longitude] = parts.map(Number)
        if (Math.abs(latitude) > 90 || Math.abs(longitude) > 180) {
          throw new Error('Coordinates out of range in build locations')
        }
        gps = `${latitude},${longitude}`
      }
      return { id: group.id, ...(gps == null ? {} : { gps }) }
    })
    return { id: location.id, country_code: countryCode, ...(tz == null ? {} : { tz }), groups }
  })
  return { data }
}

module.exports = loadBuildLocations
