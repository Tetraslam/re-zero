import { Command } from "commander";
import chalk from "chalk";
import ora from "ora";
import { resolve } from "node:path";
import { existsSync } from "node:fs";
import { init, apiPost, apiGet, uploadTarball } from "../lib/api.js";
import { getGitRemoteUrl, getRepoName } from "../lib/git.js";
import { createTarball, listFiles, getGitRoot } from "../lib/tarball.js";
import { renderAction, renderFindings, renderJson, renderCi } from "../lib/output.js";
import type { LaunchResponse, PollResponse, Finding } from "../types.js";

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function isUrl(str: string): boolean {
  return /^https?:\/\//.test(str) || /^git@/.test(str);
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function scanCommand(): Command {
  return new Command("scan")
    .description("Scan a repository for security vulnerabilities")
    .argument("[path]", "Path to repository or GitHub URL", ".")
    .option("--remote", "Scan the GitHub remote instead of local files")
    .option("--repo <url>", "Repository URL (overrides git remote detection)")
    .option("--agent <name>", "Agent to use", "opus")
    .option("--json", "Output raw JSON")
    .option("--ci", "CI mode: minimal output, exit code based on severity")
    .option("--dry-run", "List files that would be uploaded without scanning")
    .option("--timeout <seconds>", "Max poll time in seconds", "600")
    .action(async (pathArg: string, opts) => {
      const isJson = opts.json;
      const isCi = opts.ci;
      const isDryRun = opts.dryRun;
      const timeoutMs = parseInt(opts.timeout) * 1000;

      // Determine scan mode: URL arg → remote, --remote → remote, else → local tarball
      const isUrlArg = isUrl(pathArg);
      const useRemote = isUrlArg || opts.remote || !!opts.repo;

      if (!isDryRun) {
        try {
          await init();
        } catch (e) {
          console.error(chalk.red((e as Error).message));
          process.exit(2);
        }
      }

      if (isDryRun) {
        // Dry run: list files that would be packaged
        const absPath = resolve(pathArg);
        if (!existsSync(absPath)) {
          console.error(chalk.red(`Path not found: ${absPath}`));
          process.exit(2);
        }
        const files = listFiles(absPath);
        console.log();
        console.log(chalk.dim("rem") + " — dry run");
        console.log();
        for (const f of files) {
          console.log(chalk.dim("  ") + f);
        }
        console.log();
        console.log(`${chalk.bold(String(files.length))} files would be uploaded`);
        console.log(chalk.dim("Add patterns to .remignore to exclude files."));
        process.exit(0);
      }

      let repoUrl: string | undefined;
      let repoName: string;
      let storageId: string | undefined;

      if (useRemote) {
        // Remote scan — use git clone flow
        if (isUrlArg) {
          repoUrl = pathArg;
        } else {
          repoUrl = opts.repo || getGitRemoteUrl(resolve(pathArg));
        }
        if (!repoUrl) {
          console.error(chalk.red("No git remote found. Use --repo <url> to specify."));
          process.exit(2);
        }
        repoName = getRepoName(repoUrl!);

        if (!isJson && !isCi) {
          console.log();
          console.log(chalk.dim("rem") + " — re:zero security scanner");
          console.log();
          console.log(`Scanning ${chalk.bold(repoName)} ${chalk.dim("(remote)")}`);
          console.log(chalk.dim(repoUrl));
          console.log();
        }
      } else {
        // Local tarball scan
        const absPath = resolve(pathArg);
        if (!existsSync(absPath)) {
          console.error(chalk.red(`Path not found: ${absPath}`));
          process.exit(2);
        }

        const gitRoot = getGitRoot(absPath);
        repoName = getRepoName(getGitRemoteUrl(absPath) || gitRoot || absPath);

        if (!isJson && !isCi) {
          console.log();
          console.log(chalk.dim("rem") + " — re:zero security scanner");
          console.log();
        }

        // Package and upload tarball
        const packSpinner = !isJson && !isCi ? ora({ text: "Packaging files...", color: "cyan" }).start() : null;

        let tarball;
        try {
          tarball = createTarball(absPath);
        } catch (e) {
          packSpinner?.fail((e as Error).message);
          process.exit(2);
        }

        packSpinner?.succeed(
          `Packaged ${chalk.bold(String(tarball.fileCount))} files (${formatSize(tarball.sizeBytes)})`,
        );

        const uploadSpinner = !isJson && !isCi ? ora({ text: "Uploading...", color: "cyan" }).start() : null;

        try {
          storageId = await uploadTarball(tarball.tarballPath);
        } catch (e) {
          uploadSpinner?.fail("Upload failed: " + (e as Error).message);
          process.exit(2);
        }

        uploadSpinner?.succeed("Uploaded");

        if (!isJson && !isCi) {
          console.log();
          console.log(`Scanning ${chalk.bold(repoName)} ${chalk.dim("(local)")}`);
          console.log();
        }
      }

      // Launch scan
      let scanId: string;
      let projectId: string;
      const startTime = Date.now();

      try {
        const body: Record<string, string> = {
          target_type: "oss",
          agent: opts.agent,
        };
        if (repoUrl) body.repo_url = repoUrl;
        if (storageId) body.storage_id = storageId;
        body.repo_name = repoName;

        const res = await apiPost<LaunchResponse>("/scans/launch", body);
        scanId = res.scan_id;
        projectId = res.project_id;
      } catch (e) {
        console.error(chalk.red("Failed to start scan: " + (e as Error).message));
        process.exit(2);
      }

      // Poll loop
      const spinner = !isJson && !isCi ? ora({ text: "Rem is starting up...", color: "cyan" }).start() : null;
      let after = 0;
      const deadline = Date.now() + timeoutMs;

      // Handle Ctrl+C gracefully
      process.on("SIGINT", () => {
        spinner?.stop();
        console.log();
        console.log(chalk.yellow("Scan interrupted. It continues running on the server."));
        console.log(chalk.dim(`Check results: rem status (scan_id: ${scanId})`));
        process.exit(0);
      });

      while (Date.now() < deadline) {
        await sleep(2000);

        let poll: PollResponse;
        try {
          poll = await apiGet<PollResponse>(`/scans/${scanId}/poll`, {
            after: String(after),
          });
        } catch {
          // Network error — retry
          continue;
        }

        // Render new actions
        if (!isJson && !isCi && poll.actions.length > 0) {
          spinner?.stop();
          for (const action of poll.actions) {
            const line = renderAction(action);
            if (line) console.log(line);
            after = Math.max(after, action.timestamp);
          }
          // Restart spinner with latest reasoning
          const lastReasoning = [...poll.actions]
            .reverse()
            .find((a) => a.type === "reasoning");
          if (lastReasoning) {
            const text = typeof lastReasoning.payload === "string"
              ? lastReasoning.payload
              : (lastReasoning.payload as { text?: string })?.text || "";
            const short = text.length > 60 ? text.slice(0, 60) + "..." : text;
            spinner?.start(chalk.dim(`Rem: ${short}`));
          } else {
            spinner?.start("Rem is working...");
          }
        } else if (poll.actions.length > 0) {
          // Just track timestamp in json/ci mode
          for (const action of poll.actions) {
            after = Math.max(after, action.timestamp);
          }
        }

        // Check terminal states
        if (poll.status === "completed") {
          spinner?.stop();
          const durationMs = Date.now() - startTime;
          const findings: Finding[] = poll.report?.findings || [];

          if (isJson) {
            renderJson(scanId, projectId, durationMs, findings, poll.report?.summary);
            const hasCritical = findings.some((f) => f.severity === "critical" || f.severity === "high");
            process.exit(hasCritical ? 1 : 0);
          }

          if (isCi) {
            renderCi(findings);
            const hasCritical = findings.some((f) => f.severity === "critical" || f.severity === "high");
            process.exit(hasCritical ? 1 : 0);
          }

          // Default output
          const durationSec = Math.round(durationMs / 1000);
          const mins = Math.floor(durationSec / 60);
          const secs = durationSec % 60;
          console.log();
          console.log(
            `Scan complete. ${chalk.bold(String(findings.length))} findings in ${mins}m ${secs}s.`,
          );

          if (findings.length > 0) {
            renderFindings(findings);
          } else {
            console.log();
            console.log(chalk.green("No vulnerabilities found."));
          }

          console.log();
          console.log(chalk.dim(`View full report: https://rezero.sh/projects/${projectId}/scan/${scanId}`));
          process.exit(0);
        }

        if (poll.status === "failed") {
          spinner?.stop();
          console.error(chalk.red(`Scan failed: ${poll.error || "Unknown error"}`));
          process.exit(2);
        }
      }

      // Timeout
      spinner?.stop();
      console.log(chalk.yellow("Scan still running (timeout reached)."));
      console.log(chalk.dim(`Check results later: rem status (scan_id: ${scanId})`));
      process.exit(0);
    });
}
