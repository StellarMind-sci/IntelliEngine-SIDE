import { resolve } from "node:path";

import { runFixtureSuite } from "./runtime.ts";


const index = process.argv.indexOf("--contract-root");
if (index < 0 || index + 1 >= process.argv.length) {
  process.stderr.write("missing --contract-root\n");
  process.exitCode = 2;
} else {
  for (const row of runFixtureSuite(resolve(process.argv[index + 1]))) {
    process.stdout.write(`${JSON.stringify(row)}\n`);
  }
}
