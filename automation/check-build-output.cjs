// Upstream's generated-script validators only log errors. Treat those
// messages as fatal so a malformed privacy bundle cannot be published.
const fs = require('node:fs')
const output = fs.readFileSync(process.argv[2], 'utf8')
const failure = /(?:Content does not exist|Content not embedded correctly|File not found:|Error reading file )/
if (failure.test(output)) {
  console.error('Upstream generated-script validator reported an error; release blocked.')
  process.exit(1)
}
console.log('Generated-script validator output contains no reported errors.')
