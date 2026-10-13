'use strict';
// A minimal test runner, so the tests need nothing but node: `node test/run.js` from editors/vscode.
// Each *.test.js file calls the global test(name, fn); fn may be async.

const fs = require('fs');
const path = require('path');

const tests = [];
global.test = (name, fn) => tests.push({ name, fn });

for (const file of fs.readdirSync(__dirname).filter((f) => f.endsWith('.test.js')).sort()) {
  require(path.join(__dirname, file));
}

(async () => {
  let failed = 0;
  for (const { name, fn } of tests) {
    try {
      await fn();
      console.log(`ok   ${name}`);
    } catch (err) {
      failed++;
      console.log(`FAIL ${name}\n${String(err && err.stack ? err.stack : err).replace(/^/gm, '     ')}`);
    }
  }
  console.log(`\n${tests.length - failed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
})();
