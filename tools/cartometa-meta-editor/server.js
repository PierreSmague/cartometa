import express from 'express';
import path from 'path';
import fs from 'fs/promises';
import { fileURLToPath } from 'url';
import { readMetas, writeMetas } from './lib/metas.js';
import * as git from './lib/git.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Every one of these defaults is correct for the tool's one supported
// location (`tools/cartometa-meta-editor/` at the repo root) and for the
// one tier (`data/manual`) almost everyone uses — so config.json is now
// optional. It only needs to exist for the rare case of overriding one of
// these (an extra tier, a different port).
const DEFAULT_CONFIG = {
  repoRoot: '../..',
  tiers: [{ name: 'manual', dir: 'data/manual' }],
  baseBranch: 'master',
  port: 4545,
};

let config = DEFAULT_CONFIG;
try {
  const raw = await fs.readFile(path.join(__dirname, 'config.json'), 'utf-8');
  config = { ...DEFAULT_CONFIG, ...JSON.parse(raw) };
  console.log('Using tools/cartometa-meta-editor/config.json to override the defaults.');
} catch {
  console.log('No config.json — using the built-in defaults (see config.example.json to override one).');
}

const REPO_ROOT = path.resolve(__dirname, config.repoRoot);
const BASE_BRANCH = config.baseBranch || 'master';
const PORT = config.port || 4545;

// A "tier" is a top-level folder under the repo root containing one
// subfolder per country, each with a metas.json (e.g. data/manual/FR/metas.json).
// Multiple tiers can be aggregated together for the same country.
const TIERS = (config.tiers || [{ name: 'manual', dir: 'data/manual' }]).map((t) => ({
  name: t.name,
  dir: path.join(REPO_ROOT, t.dir),
}));

const app = express();
app.use(express.json({ limit: '20mb' }));
app.use(express.static(path.join(__dirname, 'public')));

// In-memory state, one session per country, kept for the lifetime of this
// process. Files under data/manual/ are only modified when "Publish" is
// clicked — but every edit before that is also mirrored to a draft file
// below, so a closed terminal, a crashed process, or a computer put to
// sleep does not silently erase an editing session.
const sessions = new Map();

function getSession(code) {
  const session = sessions.get(code);
  if (!session) throw new Error(`Country ${code} is not loaded. Reload the page.`);
  return session;
}

// Drafts: a lightweight, local-only recovery copy of each country's
// in-memory session, written to disk on every edit. Never committed (see
// this folder's .gitignore) — it exists purely so unpublished work survives
// this process dying, and is deleted once that country is actually
// published (at that point the edit is safe on a pushed branch instead).
const DRAFTS_DIR = path.join(__dirname, '.drafts');

function draftPath(code) {
  return path.join(DRAFTS_DIR, `${code}.json`);
}

async function saveDraft(code, session) {
  try {
    await fs.mkdir(DRAFTS_DIR, { recursive: true });
    const files = {};
    for (const [filePath, list] of session.listsByFile) {
      files[path.relative(REPO_ROOT, filePath)] = list;
    }
    const draft = {
      savedAt: new Date().toISOString(),
      modifiedIds: [...session.modifiedIds],
      files,
    };
    await fs.writeFile(draftPath(code), JSON.stringify(draft), 'utf-8');
  } catch (err) {
    // The draft is a safety net on top of the in-memory session, not the
    // primary save path — a write failure here must not fail the edit
    // itself, only lose the extra safety net for this one save.
    console.error(`Could not write draft for ${code}:`, err.message);
  }
}

async function loadDraft(code) {
  try {
    return JSON.parse(await fs.readFile(draftPath(code), 'utf-8'));
  } catch {
    return null;
  }
}

async function clearDraft(code) {
  try {
    await fs.unlink(draftPath(code));
  } catch {
    // nothing to remove
  }
}

async function hasDraft(code) {
  try {
    await fs.access(draftPath(code));
    return true;
  } catch {
    return false;
  }
}

app.get('/api/config', (req, res) => {
  res.json({ tiers: TIERS.map((t) => t.name), baseBranch: BASE_BRANCH, repoRoot: REPO_ROOT });
});

app.get('/api/countries', async (req, res) => {
  try {
    const byCode = new Map();
    for (const tier of TIERS) {
      let entries;
      try {
        entries = await fs.readdir(tier.dir, { withFileTypes: true });
      } catch {
        continue; // this tier doesn't exist yet, skip it
      }
      for (const e of entries) {
        if (!e.isDirectory()) continue;
        const filePath = path.join(tier.dir, e.name, 'metas.json');
        try {
          const raw = await fs.readFile(filePath, 'utf-8');
          const list = readMetas(raw);
          const prev = byCode.get(e.name) || { code: e.name, count: 0 };
          prev.count += list.length;
          byCode.set(e.name, prev);
        } catch {
          // no metas.json for this country in this tier
        }
      }
    }
    // Pending = either an open in-memory session with unpublished edits, or
    // a draft left behind by a previous run of this tool that was never
    // published — either way, the sidebar should say so before you even
    // open that country, not just after.
    for (const [code, entry] of byCode) {
      const session = sessions.get(code);
      entry.pending = Boolean(session && session.modifiedIds.size > 0) || (await hasDraft(code));
    }
    const countries = [...byCode.values()].sort((a, b) => a.code.localeCompare(b.code));
    res.json(countries);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/categories', async (req, res) => {
  try {
    const categories = new Set();
    for (const tier of TIERS) {
      let entries;
      try {
        entries = await fs.readdir(tier.dir, { withFileTypes: true });
      } catch {
        continue;
      }
      for (const e of entries) {
        if (!e.isDirectory()) continue;
        const filePath = path.join(tier.dir, e.name, 'metas.json');
        try {
          const raw = await fs.readFile(filePath, 'utf-8');
          readMetas(raw).forEach((m) => m.category && categories.add(m.category));
        } catch {
          // ignore
        }
      }
    }
    res.json([...categories].sort());
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/countries/:code', async (req, res) => {
  const { code } = req.params;
  // Re-selecting a country already open (even by accident) must not
  // re-read from disk: that would silently discard any edit not yet
  // published. `sessions` is a Map precisely so several countries — and
  // revisits to the same one — can coexist; reuse it if present.
  const existing = sessions.get(code);
  if (existing) {
    return res.json({ metas: existing.allMetas, draftResumedAt: null });
  }
  try {
    // No live session (fresh process, or first time this code is opened):
    // a draft on disk, if any, is more recent than the committed file and
    // takes priority — it is exactly the unpublished work a previous run
    // of this tool didn't get to publish before closing.
    const draft = await loadDraft(code);
    if (draft) {
      const fileByMetaId = new Map();
      const listsByFile = new Map();
      const allMetas = [];
      for (const [relPath, list] of Object.entries(draft.files)) {
        const filePath = path.join(REPO_ROOT, relPath);
        listsByFile.set(filePath, list);
        list.forEach((m) => {
          fileByMetaId.set(m.id, filePath);
          allMetas.push(m);
        });
      }
      const session = { fileByMetaId, listsByFile, modifiedIds: new Set(draft.modifiedIds), allMetas };
      sessions.set(code, session);
      return res.json({ metas: allMetas, draftResumedAt: draft.savedAt });
    }

    const fileByMetaId = new Map();
    const listsByFile = new Map();
    const allMetas = [];

    for (const tier of TIERS) {
      const filePath = path.join(tier.dir, code, 'metas.json');
      let raw;
      try {
        raw = await fs.readFile(filePath, 'utf-8');
      } catch {
        continue;
      }
      const list = readMetas(raw);
      listsByFile.set(filePath, list);
      list.forEach((m) => {
        fileByMetaId.set(m.id, filePath);
        allMetas.push(m);
      });
    }

    if (allMetas.length === 0) {
      return res.status(404).json({ error: `No metas.json found for ${code} in the configured tiers.` });
    }

    // `allMetas` holds the same object references as `listsByFile`'s lists,
    // so in-place edits (findMeta + assignment) stay visible through it —
    // no separate sync needed on the reuse path above.
    sessions.set(code, { fileByMetaId, listsByFile, modifiedIds: new Set(), allMetas });
    res.json({ metas: allMetas, draftResumedAt: null });
  } catch (err) {
    res.status(404).json({ error: `Could not load ${code}: ${err.message}` });
  }
});

function findMeta(session, id) {
  const filePath = session.fileByMetaId.get(id);
  if (!filePath) return null;
  const list = session.listsByFile.get(filePath);
  return list.find((m) => m.id === id) || null;
}

// IMPORTANT: this route must be declared BEFORE the `/metas/:id` route
// below. Express matches routes in declaration order; if `:id` came first,
// a request to `.../metas/bulk` would be caught by it (id="bulk") and would
// never reach this handler.
// Bulk edit: applies category / difficulty / source_url to several metas at
// once. Only fields present in `fields` are applied.
app.put('/api/countries/:code/metas/bulk', async (req, res) => {
  const { code } = req.params;
  try {
    const session = getSession(code);
    const { ids, fields } = req.body;
    if (!Array.isArray(ids) || ids.length === 0) {
      return res.status(400).json({ error: 'Missing ids' });
    }
    let applied = 0;
    for (const id of ids) {
      const meta = findMeta(session, id);
      if (!meta) continue;
      if ('category' in fields) meta.category = fields.category;
      if ('difficulty' in fields) {
        if (fields.difficulty) meta.difficulty = fields.difficulty;
        else delete meta.difficulty;
      }
      if ('source_url' in fields) meta.source_url = fields.source_url;
      session.modifiedIds.add(id);
      applied++;
    }
    if (applied > 0) await saveDraft(code, session);
    res.json({ ok: true, applied, modifiedCount: session.modifiedIds.size });
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

app.put('/api/countries/:code/metas/:id', async (req, res) => {
  const { code, id } = req.params;
  try {
    const session = getSession(code);
    const meta = findMeta(session, id);
    if (!meta) return res.status(404).json({ error: 'Meta not found' });

    const { title, description, source_url, category, difficulty } = req.body;
    meta.title = title ?? meta.title;
    meta.description = description ?? meta.description;
    meta.source_url = source_url ?? '';
    meta.category = category ?? meta.category;
    if (difficulty) meta.difficulty = difficulty;
    else delete meta.difficulty;

    session.modifiedIds.add(id);
    await saveDraft(code, session);
    res.json({ ok: true, modifiedCount: session.modifiedIds.size });
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

// Serves images referenced by "image" (path relative to the repo root).
app.get('/api/image', async (req, res) => {
  try {
    const rel = req.query.path;
    if (!rel) return res.status(400).end();
    const abs = path.resolve(REPO_ROOT, rel);
    if (!abs.startsWith(REPO_ROOT)) {
      return res.status(403).json({ error: 'Path outside the repo is not allowed' });
    }
    res.sendFile(abs);
  } catch (err) {
    res.status(404).json({ error: err.message });
  }
});

app.post('/api/countries/:code/publish', async (req, res) => {
  const { code } = req.params;
  try {
    const session = getSession(code);
    if (session.modifiedIds.size === 0) {
      return res.status(400).json({ error: 'Nothing to publish.' });
    }

    const touchedFiles = new Set();
    for (const id of session.modifiedIds) {
      const f = session.fileByMetaId.get(id);
      if (f) touchedFiles.add(f);
    }
    const files = [...touchedFiles];

    await git.assertCleanOrOnly(REPO_ROOT, files);
    await git.assertGhReady();

    const startingBranch = await git.currentBranch(REPO_ROOT);
    const branch = `meta-edit/${code.toLowerCase()}-${git.timestamp()}`;
    await git.createBranch(REPO_ROOT, branch, BASE_BRANCH);

    for (const f of files) {
      await fs.writeFile(f, writeMetas(session.listsByFile.get(f)), 'utf-8');
    }

    const ids = [...session.modifiedIds];
    const details = ids.map((id) => {
      const m = findMeta(session, id);
      return `- ${id}${m ? ` — ${m.title}` : ''}`;
    });
    const message = `Update metas (${code}): ${ids.length} entrie(s) modified\n\n${details.join('\n')}`;

    await git.commit(REPO_ROOT, files, message);
    await git.push(REPO_ROOT, branch);
    const prUrl = await git.createPR(REPO_ROOT, {
      title: `Meta updates: ${code} (${ids.length} entries)`,
      body: message,
      base: BASE_BRANCH,
      head: branch,
    });

    await git.checkout(REPO_ROOT, BASE_BRANCH === startingBranch ? BASE_BRANCH : startingBranch);

    session.modifiedIds.clear();
    // The edit is now safe on a pushed branch with an open PR — the local
    // recovery draft has done its job and would otherwise resurrect these
    // already-published changes as "unpublished" the next time this country
    // is opened.
    await clearDraft(code);
    res.json({ ok: true, prUrl, branch });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`Cartometa meta-editor → http://localhost:${PORT}`);
  console.log(`Tiers: ${TIERS.map((t) => `${t.name} (${t.dir})`).join(', ')}`);
  console.log(`Git repo: ${REPO_ROOT} (base branch: ${BASE_BRANCH})`);
});
