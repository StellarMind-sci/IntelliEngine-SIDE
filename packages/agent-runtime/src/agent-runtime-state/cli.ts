import { executeFixtureSuite, parseAndValidateTransport } from "./runtime.ts";

const index = process.argv.indexOf("--contract-root");
if (index < 0 || !process.argv[index + 1]) throw new Error("--contract-root is required");
const rawIndex = process.argv.indexOf("--raw-hex");
if (rawIndex >= 0) {
  if (!process.argv[rawIndex + 1] || !/^(?:[0-9a-fA-F]{2})*$/.test(process.argv[rawIndex + 1])) throw new Error("--raw-hex must contain whole bytes");
  console.log(JSON.stringify(parseAndValidateTransport(Buffer.from(process.argv[rawIndex + 1], "hex"), process.argv[index + 1])));
} else {
  for (const item of executeFixtureSuite(process.argv[index + 1])) console.log(JSON.stringify({ case_id: item.case_id, ...item.actual }));
}