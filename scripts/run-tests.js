/**
 * Cross-platform test runner for Forge.
 * Detects virtual environments on Linux, macOS, and Windows with fallback to system Python.
 */
const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const rootDir = path.resolve(__dirname, '..');
const pythonBackendDir = path.join(rootDir, 'python_backend');

// Candidate python paths in order of preference
const candidates = [
  path.join(pythonBackendDir, '.venv', 'bin', 'python'),
  path.join(pythonBackendDir, '.venv', 'Scripts', 'python.exe'),
  process.platform === 'win32' ? 'python' : 'python3',
  'python'
];

let pythonBin = null;
for (const cand of candidates) {
  if (path.isAbsolute(cand)) {
    if (fs.existsSync(cand)) {
      pythonBin = cand;
      break;
    }
  } else {
    // Check if in PATH
    const check = spawnSync(cand, ['--version'], { stdio: 'ignore' });
    if (check.status === 0) {
      pythonBin = cand;
      break;
    }
  }
}

if (!pythonBin) {
  console.error('[test-runner] Error: Could not locate Python executable.');
  process.exit(1);
}

const env = {
  ...process.env,
  PYTHONPATH: pythonBackendDir + (process.env.PYTHONPATH ? path.delimiter + process.env.PYTHONPATH : '')
};

const testFiles = [
  path.join(pythonBackendDir, 'tests', 'test_phase1.py'),
  path.join(pythonBackendDir, 'tests', 'test_phase2.py'),
  path.join(pythonBackendDir, 'tests', 'test_phase3.py'),
  path.join(pythonBackendDir, 'tests', 'test_phase4.py'),
  path.join(pythonBackendDir, 'tests', 'evals', 'test_ragas.py'),
  path.join(pythonBackendDir, 'tests', 'test_phase5.py'),
  path.join(pythonBackendDir, 'tests', 'test_phase6.py'),
  path.join(pythonBackendDir, 'tests', 'test_guardrails.py'),
  path.join(pythonBackendDir, 'tests', 'test_undo.py'),
  path.join(pythonBackendDir, 'tests', 'test_topic_gate.py')
];

console.log(`[test-runner] Using Python: ${pythonBin}`);
console.log(`[test-runner] Running ${testFiles.length} test suites...\n`);

let passed = 0;
let failed = 0;

for (const testFile of testFiles) {
  if (!fs.existsSync(testFile)) continue;
  const relPath = path.relative(rootDir, testFile);
  console.log(`\n=== Running ${relPath} ===`);
  const res = spawnSync(pythonBin, [testFile], {
    env,
    cwd: rootDir,
    stdio: 'inherit'
  });

  if (res.status === 0) {
    passed++;
  } else {
    failed++;
    console.error(`[test-runner] FAILED: ${relPath} (exit code ${res.status})`);
    process.exit(res.status || 1);
  }
}

console.log(`\n[test-runner] All ${passed} test suites passed successfully!`);
process.exit(0);

