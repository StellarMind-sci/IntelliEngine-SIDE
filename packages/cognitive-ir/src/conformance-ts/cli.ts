import { resolve } from "node:path";

import { runConformance } from "./consumer.ts";

function profileRoot(argv: string[]) {
  const index = argv.indexOf("--profile-root");
  if (index < 0 || index + 1 >= argv.length || argv.length !== 2) throw new Error("usage: cli.ts --profile-root <path>");
  return resolve(argv[index + 1]);
}

try {
  const rows = runConformance(profileRoot(process.argv.slice(2)));
  process.stdout.write(rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
}
