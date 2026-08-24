import { executeFixtureSuite } from "./runtime.ts";

const index = process.argv.indexOf("--contract-root");
if (index < 0 || !process.argv[index + 1]) throw new Error("--contract-root is required");
for (const item of executeFixtureSuite(process.argv[index + 1])) console.log(JSON.stringify({ case_id: item.case_id, ...item.actual }));