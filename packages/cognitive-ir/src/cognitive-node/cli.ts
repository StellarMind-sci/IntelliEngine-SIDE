import { resolve } from "node:path";

import { runFixtureSuite } from "./runtime.ts";


function argument(name: string) {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) throw new Error(`missing ${name}`);
  return resolve(process.argv[index + 1]);
}


for (const row of runFixtureSuite(argument("--contract-root"), argument("--profile-root"))) {
  process.stdout.write(`${JSON.stringify(row)}\n`);
}
