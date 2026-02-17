import { execSync } from "node:child_process";
import { readFileSync, statSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { randomBytes } from "node:crypto";

const MAX_FILE_SIZE = 500 * 1024; // 500KB per file
const MAX_TARBALL_SIZE = 50 * 1024 * 1024; // 50MB

export interface TarballResult {
  tarballPath: string;
  fileCount: number;
  sizeBytes: number;
}

function loadRemignore(repoRoot: string): string[] {
  try {
    const content = readFileSync(join(repoRoot, ".remignore"), "utf-8");
    return content
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith("#"));
  } catch {
    return [];
  }
}

function matchesPattern(filePath: string, pattern: string): boolean {
  // Simple glob matching: *.ext, dir/*, **/pattern
  const escaped = pattern
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*\*/g, "{{GLOBSTAR}}")
    .replace(/\*/g, "[^/]*")
    .replace(/\?/g, "[^/]")
    .replace(/\{\{GLOBSTAR\}\}/g, ".*");
  return new RegExp(`^${escaped}$`).test(filePath);
}

export function getGitRoot(path: string): string | null {
  try {
    return execSync("git rev-parse --show-toplevel", {
      cwd: path,
      encoding: "utf-8",
      stdio: ["pipe", "pipe", "pipe"],
    }).trim();
  } catch {
    return null;
  }
}

export function createTarball(repoPath: string): TarballResult {
  const absPath = resolve(repoPath);
  const gitRoot = getGitRoot(absPath) || absPath;

  // Get all tracked + untracked (non-ignored) files
  const raw = execSync("git ls-files -co --exclude-standard", {
    cwd: gitRoot,
    encoding: "utf-8",
    stdio: ["pipe", "pipe", "pipe"],
    maxBuffer: 10 * 1024 * 1024,
  });

  let files = raw
    .trim()
    .split("\n")
    .filter((f) => f.length > 0);

  // Filter out large files
  files = files.filter((f) => {
    try {
      const s = statSync(join(gitRoot, f));
      return s.size <= MAX_FILE_SIZE;
    } catch {
      return false;
    }
  });

  // Apply .remignore patterns
  const ignorePatterns = loadRemignore(gitRoot);
  if (ignorePatterns.length > 0) {
    files = files.filter(
      (f) => !ignorePatterns.some((p) => matchesPattern(f, p)),
    );
  }

  if (files.length === 0) {
    throw new Error("No files to package. Is this a git repository?");
  }

  // Write file list to temp file, then tar
  const tmpDir = mkdtempSync(join(tmpdir(), "rem-"));
  const fileListPath = join(tmpDir, "filelist.txt");
  writeFileSync(fileListPath, files.join("\n") + "\n");

  const tarballName = `rem-${randomBytes(8).toString("hex")}.tar.gz`;
  const tarballPath = join(tmpDir, tarballName);

  execSync(`tar czf "${tarballPath}" -T "${fileListPath}"`, {
    cwd: gitRoot,
    stdio: ["pipe", "pipe", "pipe"],
  });

  const sizeBytes = statSync(tarballPath).size;
  if (sizeBytes > MAX_TARBALL_SIZE) {
    throw new Error(
      `Tarball too large (${(sizeBytes / 1024 / 1024).toFixed(1)}MB). Max is 50MB. Add patterns to .remignore to exclude files.`,
    );
  }

  return { tarballPath, fileCount: files.length, sizeBytes };
}

export function listFiles(repoPath: string): string[] {
  const absPath = resolve(repoPath);
  const gitRoot = getGitRoot(absPath) || absPath;

  const raw = execSync("git ls-files -co --exclude-standard", {
    cwd: gitRoot,
    encoding: "utf-8",
    stdio: ["pipe", "pipe", "pipe"],
    maxBuffer: 10 * 1024 * 1024,
  });

  let files = raw
    .trim()
    .split("\n")
    .filter((f) => f.length > 0);

  files = files.filter((f) => {
    try {
      const s = statSync(join(gitRoot, f));
      return s.size <= MAX_FILE_SIZE;
    } catch {
      return false;
    }
  });

  const ignorePatterns = loadRemignore(gitRoot);
  if (ignorePatterns.length > 0) {
    files = files.filter(
      (f) => !ignorePatterns.some((p) => matchesPattern(f, p)),
    );
  }

  return files;
}
