const assert = require('assert');
const path = require('path');
const { spawnSync } = require('child_process');

const cwd = path.resolve(__dirname, '..');
const result = spawnSync(process.execPath, ['index.js', '--self-test-append'], {
  cwd,
  encoding: 'utf8',
  env: {
    ...process.env,
    TUI_ENABLE_MOUSE: '0',
  },
});

if (result.error) {
  throw result.error;
}

assert.strictEqual(
  result.status,
  0,
  `self-test exited with code ${result.status}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`
);
assert.match(result.stdout, /SELFTEST_OK/, `unexpected stdout:\n${result.stdout}`);

console.log('append transcript self-test passed');
