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
  solution: { variable: string; value: number };
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

const OPERATION_ID = "solve-linear-equation";

function refKey(ref: Ref): string {
  return `${ref.id}@${ref.revision}`;
}

function compareRefs(left: Ref, right: Ref): number {
  return refKey(left).localeCompare(refKey(right));
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

function expressionText(equation: Equation, solution: number): string {
  const constant = equation.constant < 0 ? `- ${numberText(Math.abs(equation.constant))}` : `+ ${numberText(equation.constant)}`;
  return `${numberText(equation.coefficient)} * ${numberText(solution)} ${constant}`;
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

export function createLinearEquationPreview(request: PreviewRequest): PreviewResult {
  const equation = copyEquation(request.equation);
  if (!validEquation(equation)) return invalidResult(equation);

  const operation = request.flow.steps.find(
    (step) => step.kind === "operation" && step.behavior_ref?.behavior_id === OPERATION_ID,
  );
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
  if (projectionUnit.status !== "ready") return invalidResult(equation);

  const value = (equation.right_hand_side - equation.constant) / equation.coefficient;
  const canonicalEquation = equationText(equation);
  const verificationAssertion = `${expressionText(equation, value)} == ${numberText(equation.right_hand_side)}`;
  return {
    mode: "preview",
    side_effects: "forbidden",
    state: "ready",
    equation,
    proposal: {
      canonical_equation: canonicalEquation,
      solution: { variable: equation.variable, value },
      sympy_source: [
        "import sympy as sp",
        `${equation.variable} = sp.symbols('${equation.variable}')`,
        `equation = sp.Eq(${numberText(equation.coefficient)} * ${equation.variable} ${equation.constant < 0 ? "-" : "+"} ${numberText(Math.abs(equation.constant))}, ${numberText(equation.right_hand_side)})`,
        `solution = sp.solve(equation, ${equation.variable})[0]`,
      ].join("\n"),
      verification_assertion: verificationAssertion,
    },
    impacted_steps: steps,
    reasons: [],
  };
}
