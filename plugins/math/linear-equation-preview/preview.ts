export type Equation = {
  variable: string;
  coefficient: number;
  constant: number;
  right_hand_side: number;
};

export type Ref = { id: string; revision: number };

type Behavior = {
  behavior_id: string;
  kind: string;
  capability: string;
};

type KnowledgeUnit = {
  id: string;
  revision: number;
  title: string;
  behaviors: Behavior[];
};

type ProjectionUnit = {
  ref: Ref;
  status: "ready" | "blocked" | "needs_evidence";
  missing_prerequisite_refs: Ref[];
  missing_evidence_node_refs: Ref[];
};

type FlowStep = {
  step_id: string;
  kind: string;
  behavior_ref?: {
    knowledge_unit_ref: Ref;
    behavior_id: string;
  };
};

export type PreviewRequest = {
  equation: Equation;
  knowledge_units: KnowledgeUnit[];
  projection: { units: ProjectionUnit[] };
  flow: { steps: FlowStep[] };
};

export type PreviewProposal = {
  canonical_equation: string;
  solution: { variable: string; value: string };
  sympy_source: string;
  verification_assertion: string;
};

export type PreviewReason = {
  knowledge_unit_ref: Ref;
  status: "blocked" | "needs_evidence";
  missing_prerequisite_refs: Ref[];
  missing_evidence_node_refs: Ref[];
};

export type PreviewResult = {
  mode: "preview";
  side_effects: "forbidden";
  state: "ready" | "blocked" | "needs_evidence" | "empty" | "invalid_input";
  equation: Equation;
  proposal: PreviewProposal | null;
  impacted_steps: Array<{ step_id: string; kind: string }>;
  reasons: PreviewReason[];
};

type Rational = { numerator: bigint; denominator: bigint };

const OPERATION_ID = "solve-linear-equation";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isRef(value: unknown): value is Ref {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.revision === "number" &&
    Number.isSafeInteger(value.revision)
  );
}

function isEquationShape(value: unknown): value is Equation {
  return (
    isRecord(value) &&
    typeof value.variable === "string" &&
    typeof value.coefficient === "number" &&
    typeof value.constant === "number" &&
    typeof value.right_hand_side === "number"
  );
}

function isBehavior(value: unknown): value is Behavior {
  return (
    isRecord(value) &&
    typeof value.behavior_id === "string" &&
    typeof value.kind === "string" &&
    typeof value.capability === "string"
  );
}

function isKnowledgeUnit(value: unknown): value is KnowledgeUnit {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.revision === "number" &&
    Number.isSafeInteger(value.revision) &&
    typeof value.title === "string" &&
    Array.isArray(value.behaviors) &&
    value.behaviors.every(isBehavior)
  );
}

function isProjectionUnit(value: unknown): value is ProjectionUnit {
  return (
    isRecord(value) &&
    isRef(value.ref) &&
    (value.status === "ready" || value.status === "blocked" || value.status === "needs_evidence") &&
    Array.isArray(value.missing_prerequisite_refs) &&
    value.missing_prerequisite_refs.every(isRef) &&
    Array.isArray(value.missing_evidence_node_refs) &&
    value.missing_evidence_node_refs.every(isRef)
  );
}

function isFlowStep(value: unknown): value is FlowStep {
  if (!isRecord(value) || typeof value.step_id !== "string" || typeof value.kind !== "string") return false;
  if (value.behavior_ref === undefined) return true;
  return (
    isRecord(value.behavior_ref) &&
    isRef(value.behavior_ref.knowledge_unit_ref) &&
    typeof value.behavior_ref.behavior_id === "string"
  );
}

function hasUniqueStepIds(steps: unknown[]): boolean {
  const stepIds = new Set<string>();
  for (const step of steps) {
    if (!isFlowStep(step) || stepIds.has(step.step_id)) return false;
    stepIds.add(step.step_id);
  }
  return true;
}

function isPreviewRequest(value: unknown): value is PreviewRequest {
  return (
    isRecord(value) &&
    isEquationShape(value.equation) &&
    Array.isArray(value.knowledge_units) &&
    value.knowledge_units.every(isKnowledgeUnit) &&
    isRecord(value.projection) &&
    Array.isArray(value.projection.units) &&
    value.projection.units.every(isProjectionUnit) &&
    isRecord(value.flow) &&
    Array.isArray(value.flow.steps) &&
    hasUniqueStepIds(value.flow.steps)
  );
}

function safeEquation(value: unknown): Equation {
  const equation = isRecord(value) ? value : {};
  const safeNumber = (candidate: unknown): number =>
    typeof candidate === "number" && Number.isFinite(candidate) && Number.isSafeInteger(candidate) ? candidate : 0;
  return {
    variable: typeof equation.variable === "string" ? equation.variable : "",
    coefficient: safeNumber(equation.coefficient),
    constant: safeNumber(equation.constant),
    right_hand_side: safeNumber(equation.right_hand_side),
  };
}

function refKey(ref: Ref): string {
  return JSON.stringify([ref.id, ref.revision]);
}

function compareRefs(left: Ref, right: Ref): number {
  const idComparison = left.id.localeCompare(right.id);
  return idComparison === 0 ? left.revision - right.revision : idComparison;
}

function hasUniqueRefs(refs: Ref[]): boolean {
  const keys = new Set<string>();
  for (const ref of refs) {
    const key = refKey(ref);
    if (keys.has(key)) return false;
    keys.add(key);
  }
  return true;
}

function projectionStateIsConsistent(unit: ProjectionUnit): boolean {
  const hasPrerequisites = unit.missing_prerequisite_refs.length > 0;
  const hasEvidence = unit.missing_evidence_node_refs.length > 0;
  if (unit.status === "ready") return !hasPrerequisites && !hasEvidence;
  if (unit.status === "blocked") return hasPrerequisites;
  return !hasPrerequisites && hasEvidence;
}

function hasConsistentReferences(request: PreviewRequest): boolean {
  return (
    hasUniqueRefs(request.knowledge_units.map((unit) => ({ id: unit.id, revision: unit.revision }))) &&
    hasUniqueRefs(request.projection.units.map((unit) => unit.ref)) &&
    request.projection.units.every(projectionStateIsConsistent)
  );
}

function copyRef(ref: Ref): Ref {
  return { id: ref.id, revision: ref.revision };
}

function validEquation(equation: Equation): boolean {
  return (
    /^[A-Za-z]$/.test(equation.variable) &&
    [equation.coefficient, equation.constant, equation.right_hand_side].every(
      (value) => Number.isFinite(value) && Number.isSafeInteger(value),
    ) &&
    equation.coefficient !== 0
  );
}

function copyEquation(equation: Equation): Equation {
  return {
    variable: equation.variable,
    coefficient: equation.coefficient,
    constant: equation.constant,
    right_hand_side: equation.right_hand_side,
  };
}

function impactedSteps(steps: FlowStep[], operation: FlowStep): Array<{ step_id: string; kind: string }> {
  return [operation, ...steps.filter((step) => step.kind === "verification")]
    .map((step) => ({ step_id: step.step_id, kind: step.kind }))
    .sort((left, right) => left.step_id.localeCompare(right.step_id));
}

function projectionReason(
  unit: ProjectionUnit & { status: "blocked" | "needs_evidence" },
): PreviewReason {
  return {
    knowledge_unit_ref: copyRef(unit.ref),
    status: unit.status,
    missing_prerequisite_refs: [...unit.missing_prerequisite_refs].sort(compareRefs).map(copyRef),
    missing_evidence_node_refs: [...unit.missing_evidence_node_refs].sort(compareRefs).map(copyRef),
  };
}

function numberText(value: number): string {
  return String(value);
}

function equationText(equation: Equation): string {
  const constant = equation.constant < 0 ? `- ${numberText(Math.abs(equation.constant))}` : `+ ${numberText(equation.constant)}`;
  return `${numberText(equation.coefficient)}*${equation.variable} ${constant} = ${numberText(equation.right_hand_side)}`;
}

function greatestCommonDivisor(left: bigint, right: bigint): bigint {
  let dividend = left < 0n ? -left : left;
  let divisor = right < 0n ? -right : right;
  while (divisor !== 0n) {
    const remainder = dividend % divisor;
    dividend = divisor;
    divisor = remainder;
  }
  return dividend;
}

function exactSolution(equation: Equation): Rational {
  let numerator = BigInt(equation.right_hand_side) - BigInt(equation.constant);
  let denominator = BigInt(equation.coefficient);
  if (denominator < 0n) {
    numerator = -numerator;
    denominator = -denominator;
  }
  const divisor = greatestCommonDivisor(numerator, denominator);
  return { numerator: numerator / divisor, denominator: denominator / divisor };
}

function rationalText(value: Rational): string {
  return value.denominator === 1n ? value.numerator.toString() : `${value.numerator}/${value.denominator}`;
}

function multiplicationOperand(value: Rational): string {
  const text = rationalText(value);
  return value.numerator < 0n || value.denominator !== 1n ? `(${text})` : text;
}

function sympyRationalText(value: Rational): string {
  return value.denominator === 1n
    ? `sp.Integer(${value.numerator.toString()})`
    : `sp.Rational(${value.numerator.toString()}, ${value.denominator.toString()})`;
}

function expressionText(equation: Equation, solution: Rational): string {
  const constant = equation.constant < 0 ? `- ${numberText(Math.abs(equation.constant))}` : `+ ${numberText(equation.constant)}`;
  return `${numberText(equation.coefficient)} * ${multiplicationOperand(solution)} ${constant}`;
}

function invalidResult(equation: Equation): PreviewResult {
  return {
    mode: "preview",
    side_effects: "forbidden",
    state: "invalid_input",
    equation: copyEquation(equation),
    proposal: null,
    impacted_steps: [],
    reasons: [],
  };
}

export function createLinearEquationPreview(request: PreviewRequest): PreviewResult;
export function createLinearEquationPreview(request: unknown): PreviewResult {
  const equationSource = isRecord(request) ? request.equation : undefined;
  const equation = safeEquation(equationSource);
  if (!isPreviewRequest(request) || !validEquation(equation) || !hasConsistentReferences(request)) {
    return invalidResult(equation);
  }

  const operation = request.flow.steps
    .filter((step) => step.kind === "operation" && step.behavior_ref?.behavior_id === OPERATION_ID)
    .sort((left, right) => left.step_id.localeCompare(right.step_id))[0];
  if (operation?.behavior_ref === undefined) {
    return {
      mode: "preview",
      side_effects: "forbidden",
      state: "empty",
      equation,
      proposal: null,
      impacted_steps: [],
      reasons: [],
    };
  }

  const behaviorRef = operation.behavior_ref;
  const knowledgeUnit = request.knowledge_units.find(
    (unit) => unit.id === behaviorRef.knowledge_unit_ref.id && unit.revision === behaviorRef.knowledge_unit_ref.revision,
  );
  const behavior = knowledgeUnit?.behaviors.find(
    (candidate) =>
      candidate.behavior_id === OPERATION_ID &&
      candidate.kind === "calculation" &&
      candidate.capability === "runtime.math.symbolic",
  );
  const projectionUnit = request.projection.units.find((unit) => refKey(unit.ref) === refKey(behaviorRef.knowledge_unit_ref));
  if (knowledgeUnit === undefined || knowledgeUnit.title.length === 0 || behavior === undefined || projectionUnit === undefined) {
    return invalidResult(equation);
  }

  const steps = impactedSteps(request.flow.steps, operation);
  if (projectionUnit.status === "blocked" || projectionUnit.status === "needs_evidence") {
    return {
      mode: "preview",
      side_effects: "forbidden",
      state: projectionUnit.status,
      equation,
      proposal: null,
      impacted_steps: steps,
      reasons: [projectionReason(projectionUnit)],
    };
  }

  const solution = exactSolution(equation);
  const solutionText = rationalText(solution);
  const canonicalEquation = equationText(equation);
  const verificationAssertion = `${expressionText(equation, solution)} == ${numberText(equation.right_hand_side)}`;
  return {
    mode: "preview",
    side_effects: "forbidden",
    state: "ready",
    equation,
    proposal: {
      canonical_equation: canonicalEquation,
      solution: { variable: equation.variable, value: solutionText },
      sympy_source: [
        "import sympy as sp",
        `${equation.variable} = sp.symbols('${equation.variable}')`,
        `equation = sp.Eq(${numberText(equation.coefficient)} * ${equation.variable} ${equation.constant < 0 ? "-" : "+"} ${numberText(Math.abs(equation.constant))}, ${numberText(equation.right_hand_side)})`,
        `solution = sp.solve(equation, ${equation.variable})[0]`,
        `assert solution == ${sympyRationalText(solution)}`,
      ].join("\n"),
      verification_assertion: verificationAssertion,
    },
    impacted_steps: steps,
    reasons: [],
  };
}
