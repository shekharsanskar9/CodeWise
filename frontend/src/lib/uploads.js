// Collecting files from inputs / drag-and-drop (including whole folders), filtering them
// with the server's upload rules, and uploading them in batches.
import axios from "axios";

// Used until /api/upload-rules has loaded (or if it fails).
const DEFAULT_RULES = {
  supported_extensions: [".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".go", ".rb", ".php", ".swift", ".kt", ".rs", ".txt", ".md", ".json", ".yaml", ".yml", ".xml",
    ".html", ".css", ".sql", ".toml"],
  ignored_dirs: ["node_modules", ".git", "dist", "build", "venv", ".venv", "__pycache__", ".next", "coverage"],
  ignored_filenames: ["package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"],
  ignored_suffixes: [".min.js", ".min.css", ".map"],
  max_file_bytes: 1_000_000,
  max_request_bytes: 100_000_000,
  max_archive_bytes: 100_000_000,
};

export async function fetchUploadRules(api) {
  try {
    const res = await axios.get(`${api}/api/upload-rules`);
    return { ...DEFAULT_RULES, ...res.data };
  } catch {
    return DEFAULT_RULES;
  }
}

const basename = (path) => path.split("/").pop();
const extension = (name) => (name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "");

export function isIgnoredDir(name, rules) {
  return rules.ignored_dirs.includes(name);
}

// Returns null if the file should be uploaded, otherwise the reason it is skipped.
export function skipReason(path, size, rules) {
  const name = basename(path);
  const dirs = path.split("/").slice(0, -1);
  if (dirs.some((d) => isIgnoredDir(d, rules))) return "ignored folder";
  if (name === ".gitignore") return null; // sent so the server can apply it
  if (rules.ignored_filenames.includes(name)) return "generated file";
  if (rules.ignored_suffixes.some((s) => name.toLowerCase().endsWith(s))) return "minified/generated";
  const ext = extension(name);
  if (ext === ".zip") return size > rules.max_archive_bytes ? "archive too large" : null;
  if (!rules.supported_extensions.includes(ext)) return "unsupported type";
  if (size > rules.max_file_bytes) return "too large";
  return null;
}

// Files from an <input type="file"> (with or without webkitdirectory).
export function entriesFromFileList(fileList) {
  return Array.from(fileList).map((file) => ({ file, path: file.webkitRelativePath || file.name }));
}

// Files from a drop event, walking dropped folders recursively. Ignored folders
// (node_modules, .git, ...) are never descended into, which keeps big drops fast.
export async function entriesFromDrop(dataTransfer, rules) {
  const items = Array.from(dataTransfer.items || []);
  const roots = items.map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
  if (roots.length === 0) return entriesFromFileList(dataTransfer.files || []);

  const out = [];
  const walk = async (entry, prefix) => {
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      out.push({ file, path: prefix + entry.name });
    } else if (entry.isDirectory && !isIgnoredDir(entry.name, rules)) {
      const reader = entry.createReader();
      // readEntries returns results in pages; keep reading until it returns nothing.
      for (;;) {
        const page = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        if (page.length === 0) break;
        for (const child of page) await walk(child, `${prefix}${entry.name}/`);
      }
    }
  };
  for (const root of roots) await walk(root, "");
  return out;
}

export function filterEntries(entries, rules) {
  const kept = [];
  let skipped = 0;
  for (const entry of entries) {
    if (skipReason(entry.path, entry.file.size, rules)) skipped += 1;
    else kept.push(entry);
  }
  return { kept, skipped };
}

// Split into requests under the server's size limit. .gitignore files go in every batch
// so the server can apply them to all files.
function makeBatches(entries, maxBytes, maxFiles = 200) {
  const gitignores = entries.filter((e) => basename(e.path) === ".gitignore");
  const others = entries.filter((e) => basename(e.path) !== ".gitignore");
  const baseBytes = gitignores.reduce((n, e) => n + e.file.size, 0);
  const budget = Math.max(maxBytes * 0.9 - baseBytes, 1);
  const batches = [];
  let current = [];
  let bytes = 0;
  for (const entry of others) {
    if (current.length && (bytes + entry.file.size > budget || current.length >= maxFiles)) {
      batches.push(current);
      current = [];
      bytes = 0;
    }
    current.push(entry);
    bytes += entry.file.size;
  }
  if (current.length) batches.push(current);
  return batches.map((batch) => [...gitignores, ...batch]);
}

export async function uploadEntries(api, projectId, entries, rules, onProgress) {
  const batches = makeBatches(entries, rules.max_request_bytes);
  const total = { indexed: 0, skipped: 0, failed: 0, failures: [], metadata: null };
  for (let i = 0; i < batches.length; i++) {
    onProgress?.(i + 1, batches.length);
    const form = new FormData();
    for (const { file, path } of batches[i]) form.append("files", file, path);
    let data;
    try {
      const res = await axios.post(`${api}/api/projects/${projectId}/upload`, form);
      data = res.data;
    } catch (err) {
      // 400 = nothing in this batch could be indexed (e.g. all ignored); keep going.
      if (!err.response?.data?.uploads) throw err;
      data = err.response.data;
    }
    total.indexed += data.summary?.indexed ?? 0;
    total.skipped += data.summary?.skipped ?? 0;
    total.failed += data.summary?.failed ?? 0;
    total.failures.push(...(data.uploads || []).filter((u) => !u.success && !u.skipped));
    total.metadata = data.metadata || total.metadata;
  }
  return total;
}
