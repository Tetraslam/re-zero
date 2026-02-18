#!/usr/bin/env node

import { Command } from "commander";
import chalk from "chalk";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { scanCommand } from "./commands/scan.js";
import { loginCommand } from "./commands/login.js";
import { statusCommand } from "./commands/status.js";
import { initCommand } from "./commands/init.js";
import { updateCommand } from "./commands/update.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const pkg = JSON.parse(readFileSync(join(__dirname, "../package.json"), "utf-8"));

const program = new Command();

program
  .name("rem")
  .description(chalk.dim("re:zero") + " security scanner")
  .version(pkg.version);

program.addCommand(initCommand());
program.addCommand(scanCommand());
program.addCommand(loginCommand());
program.addCommand(statusCommand());
program.addCommand(updateCommand());

program.parse();
