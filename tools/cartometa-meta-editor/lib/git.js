import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);

async function run(cmd, args, opts = {}) {
  try {
    const { stdout, stderr } = await execFileAsync(cmd, args, {
      cwd: opts.cwd || process.cwd(),
      maxBuffer: 1024 * 1024 * 10,
    });
    return stdout.trim() || stderr.trim();
  } catch (err) {
    const details = err.stderr || err.stdout || err.message;
    const wrapped = new Error(`Command failed: ${cmd} ${args.join(' ')}\n${details}`);
    // Preserved so callers can tell "the executable itself isn't on PATH"
    // (ENOENT) apart from "the command ran and failed" — e.g. assertGhReady
    // below gives a very different fix depending on which one it is.
    wrapped.code = err.code;
    throw wrapped;
  }
}

export function timestamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(
    d.getMinutes()
  )}`;
}

// Checks that `gh` is installed and authenticated before doing anything else.
// Kept as two distinct messages rather than one generic one: "not on PATH"
// (gh may well be installed — a fresh install often needs a new terminal
// before PATH picks it up) and "not authenticated" send someone to a
// completely different fix, and the generic message pointed the wrong way
// often enough in practice to be worth splitting.
export async function assertGhReady() {
  try {
    await run('gh', ['auth', 'status']);
  } catch (err) {
    if (err.code === 'ENOENT') {
      throw new Error(
        '`gh` (GitHub CLI) was not found on PATH.\n' +
          'If you just installed it, try opening a new terminal first — PATH changes from an ' +
          'installer often do not apply to terminals already open.\n' +
          'https://cli.github.com/'
      );
    }
    throw new Error(
      '`gh` (GitHub CLI) is installed but not authenticated.\n' +
        'Run `gh auth login` before publishing.\n' +
        'https://cli.github.com/'
    );
  }
}

// Refuses to publish if the repo has changes unrelated to the edited
// file(s) (one per touched tier), so nothing else ever gets swept into the
// commit by accident.
export async function assertCleanOrOnly(repoRoot, filePaths) {
  const status = await run('git', ['status', '--porcelain'], { cwd: repoRoot });
  if (!status) return;
  const targets = filePaths.map((fp) => path.relative(repoRoot, fp));
  const lines = status.split('\n').filter(Boolean);
  const foreign = lines.filter((l) => !targets.some((t) => l.trim().endsWith(t)));
  if (foreign.length > 0) {
    throw new Error(
      'The repo has changes unrelated to this edit. ' +
        'Commit or stash them before publishing:\n' +
        foreign.join('\n')
    );
  }
}

export async function currentBranch(repoRoot) {
  return run('git', ['rev-parse', '--abbrev-ref', 'HEAD'], { cwd: repoRoot });
}

export async function createBranch(repoRoot, branch, base) {
  await run('git', ['checkout', base], { cwd: repoRoot });
  await run('git', ['pull', 'origin', base], { cwd: repoRoot });
  await run('git', ['checkout', '-b', branch], { cwd: repoRoot });
}

export async function commit(repoRoot, filePaths, message) {
  await run('git', ['add', ...filePaths], { cwd: repoRoot });
  await run('git', ['commit', '-m', message], { cwd: repoRoot });
}

export async function push(repoRoot, branch) {
  await run('git', ['push', '-u', 'origin', branch], { cwd: repoRoot });
}

export async function checkout(repoRoot, branch) {
  await run('git', ['checkout', branch], { cwd: repoRoot });
}

export async function createPR(repoRoot, { title, body, base, head }) {
  const out = await run(
    'gh',
    ['pr', 'create', '--title', title, '--body', body, '--base', base, '--head', head],
    { cwd: repoRoot }
  );
  const lines = out.split('\n').filter(Boolean);
  return lines[lines.length - 1];
}
