// Reads and writes data/manual/<CODE>/metas.json files.
// Format: a flat JSON array of "meta" objects (title, description, category, ...).
// The source file is already indented with 2 spaces, one object per block; we
// keep that exact format on write so Git diffs stay readable (a modified
// meta = a modified block of lines).

export function readMetas(raw) {
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed)) {
    throw new Error('Unexpected file: expected a JSON array of metas.');
  }
  return parsed;
}

export function writeMetas(list) {
  return JSON.stringify(list, null, 2) + '\n';
}
