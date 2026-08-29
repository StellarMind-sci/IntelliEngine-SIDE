const { readFileSync } = require("node:fs");
const { createLinearEquationPreview } = require("./preview.ts");
const { renderLinearEquationPreviewHtml } = require("./render.ts");

function parseArguments(arguments_) {
  if (arguments_.length !== 4 || arguments_[0] !== "--case" || arguments_[2] !== "--format") {
    return { error: "usage: --case <case-id> --format <json|html>" };
  }
  const caseId = arguments_[1];
  const format = arguments_[3];
  if (format !== "json" && format !== "html") return { error: `unknown output format: ${format}` };
  return { caseId, format };
}

function writeError(message) {
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
}

function run() {
  const parsed = parseArguments(process.argv.slice(2));
  if ("error" in parsed) {
    writeError(parsed.error);
    return;
  }

  let fixtures;
  try {
    fixtures = JSON.parse(readFileSync(`${__dirname}/fixtures/demo-cases.json`, "utf8"));
  } catch {
    writeError("invalid demo fixture");
    return;
  }
  if (typeof fixtures !== "object" || fixtures === null || Array.isArray(fixtures)) {
    writeError("invalid demo fixture");
    return;
  }

  if (!Object.hasOwn(fixtures, parsed.caseId)) {
    writeError(`unknown demo case: ${parsed.caseId}`);
    return;
  }
  const request = fixtures[parsed.caseId];

  const preview = createLinearEquationPreview(request);
  const output = parsed.format === "json" ? JSON.stringify(preview, null, 2) : renderLinearEquationPreviewHtml(preview);
  process.stdout.write(`${output}\n`);
}

run();
