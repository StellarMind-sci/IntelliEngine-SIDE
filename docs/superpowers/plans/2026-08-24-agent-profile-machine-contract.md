# AgentProfile 1.0.0 机器契约 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 SIDE 的长期可召唤 Agent 个体交付一个语言无关、离线只读、可锁定验证的 AgentProfile 1.0.0 公共契约。

**Architecture:** `packages/agent-runtime` 只定义 Agent 的可移植身份锚点：身份、人格描述、目标、工作偏好、能力声明、协作偏好与来源引用。运行状态、私有记忆、能力证据、模型/权限绑定、团队或项目关系均不进入该 Profile。验证器只消费原始 JSON bytes 与显式 provenance 引用快照，分别得出 transport、reference 或 revision-transition 结论，不查询网络、模型、记忆库或用户文件。

**Tech Stack:** JSON Schema Draft 2020-12；I-JSON 兼容 JSON；JCS SHA-256 锁；Python 标准库 `unittest`；复用 `packages/cognitive-ir/python/intelliengine_conformance` 的严格 JSON/JCS/schema 工具。

**Spec:** `docs/rfc/0004-agent-profile-long-lived-agent-contract.md`、`docs/adr/0008-agent-profile-long-lived-agent-contract.md`、GitHub Issue #44。

## Global Constraints

- 只修改 `packages/agent-runtime/**` 和本计划；本 Issue 只能新增 `AgentProfile 1.0.0` 一项公共契约。
- Profile 精确字段为 `contract_version`、`id`、`revision`、`display_name`、`persona`、`goals`、`working_style`、`declared_capabilities`、`collaboration_preferences`、`provenance_refs`；所有对象 `additionalProperties: false`。
- `persona` 为 `summary`、`principles`、`communication_style`；`working_style` 为 `planning_preference`、`reasoning_preference`、`verification_preference`；`collaboration_preferences` 为 `interaction_preference`、`feedback_preference`。这些均是用户可填写的描述文本，不得引入固定角色 enum 或权限含义。
- `declared_capabilities` 是非空、按 unsigned UTF-8 规范排序的 capability identifier 集合，只能描述能力，不能授予任何模型、文件、网络、设备或工程写入权限。
- `goals`、`persona.principles`、`declared_capabilities`、`provenance_refs` 是唯一且按 unsigned UTF-8 排序的集合；`provenance_refs` 非空。所有 revision 都使用 canonical lowercase UUIDv7 ID 与 1..9007199254740991 的 safe integer。
- `AgentProfileRef` 只能为 `{id, revision}`；不能使用 `latest`、模型 ID、状态或权限替代精确 revision。
- Profile 与 `AgentProfileReferenceSnapshot` 的 `contract_version` 都是 canonical SemVer。未知 major 为 invalid；同 major 的较新 minor 仅可作为无副作用 `compatible_read+succeeded` 的 Profile 读取，不得用于写入或智能副作用。
- `AgentProfileReferenceSnapshot` 不属于 Profile，包含 `contract_version` 和非空 `provenance` entries；entry 为 `{ref, object_result}`，状态只允许 `available`、`invalid`、`opaque`、`compatible_read`。快照必须按 ref 规范排序且与 Profile provenance refs 完全闭包匹配。entry 的 `compatible_read` 仍导致 reference 结论 `not_evaluated+indeterminate`，不是 Profile 的 compatible read。
- validation result 按 mode 封闭：`transport`/`profile` 为 `valid+succeeded`、`invalid+succeeded` 或 `compatible_read+succeeded`；`reference` 为 `valid+succeeded`、`invalid+succeeded` 或 `not_evaluated+indeterminate`；`revision_transition` 仅为 `valid+succeeded` 或 `invalid+succeeded`。诊断必须为稳定 `agent_profile.*`、最小 JSON Pointer；`agent_profile.compatible_read` 为 warning，其余当前 catalog 代码为 error。
- 未提供快照、快照版本非本 major、`opaque` 或 `compatible_read` 来源均是 `not_evaluated+indeterminate`；完整快照中的 `invalid`/悬空来源是 `invalid+succeeded`。
- revision transition 只能同 ID 且 candidate revision 严格增加、去掉 revision 后内容不同；契约不执行 ChangeSet、运行状态切换、写入、召唤、删除、模型调用、记忆访问、团队调度或权限判断。
- raw transport 必须拒绝 BOM、重复 key、非法 UTF-8、非法 JSON/代理项和未知 major；Issue #22 未完成前只宣称应用层离线只读确定性校验，不宣称 OS 级隔离。
- 所有 JSON 工件（不含 `lock.json`）必须被 `lock.json` 以 JCS SHA-256 完整闭包锁定，`self_digest` 固定为 `excluded`，每个 entry 固定 `digest_kind: "jcs_sha256"` 且 path 防 escape；Task 3 verifier 必须真实强制 entry path 的规范排序与路径唯一性，不能误用 JSON Schema `uniqueItems` 代替。验证器不得重放 fixture expected 作为计算结果。
- `reference-snapshot.provenance` 与 fixture suite `cases` 均至少一项，fixture `case_id` 使用 canonical kebab identifier。Task 2/3 verifier 必须真实检查 provenance entries 与 fixture cases 的 key 唯一性和规范排序，不能声称 JSON Schema `uniqueItems` 已充分保证。

---

### Task 1: 建立 AgentProfile 的封闭机器 schema 与稳定诊断目录

**Files:**
- Create: `packages/agent-runtime/package.json`
- Create: `packages/agent-runtime/contracts/agent-profile/1.0.0/contract.json`
- Create: `packages/agent-runtime/contracts/agent-profile/1.0.0/schemas/agent-profile.schema.json`
- Create: `packages/agent-runtime/contracts/agent-profile/1.0.0/schemas/agent-profile-ref.schema.json`
- Create: `packages/agent-runtime/contracts/agent-profile/1.0.0/schemas/reference-snapshot.schema.json`
- Create: `packages/agent-runtime/contracts/agent-profile/1.0.0/schemas/diagnostic.schema.json`
- Create: `packages/agent-runtime/contracts/agent-profile/1.0.0/schemas/validation-result.schema.json`
- Create: `packages/agent-runtime/contracts/agent-profile/1.0.0/schemas/fixture-suite.schema.json`
- Create: `packages/agent-runtime/contracts/agent-profile/1.0.0/schemas/lock.schema.json`
- Create: `packages/agent-runtime/contracts/agent-profile/1.0.0/diagnostics/agent-profile.json`
- Create: `packages/agent-runtime/tests/test_contract.py`

**Interfaces:**
- Consumes: RFC-0004/ADR-0008 的 Profile 边界，以及 CognitiveNode conformance package 的离线 schema/JCS 定义。
- Produces: `AgentProfile`、`AgentProfileRef`、`AgentProfileReferenceSnapshot`、`AgentProfileValidationResult` 的 1.0.0 machine schema；诊断 catalog 至少包含 `invalid_json`、`missing_field`、`unsupported_contract_version`、`invalid_id`、`invalid_revision`、`invalid_profile_field`、`noncanonical_set`、`forbidden_runtime_field`、`reference_snapshot_incomplete`、`opaque_provenance_reference`、`dangling_provenance_reference`、`revision_identity_mismatch`、`revision_not_increased`、`revision_without_change`。

- [ ] **Step 1: 写出失败的 schema/目录存在性测试**

```python
def test_contract_declares_all_agent_profile_schemas_and_diagnostics():
    report = verifier.verify_contract(CONTRACT_ROOT)
    assert report["contract_version"] == "1.0.0"
```

- [ ] **Step 2: 运行测试，确认它因缺少 verifier/contract 而失败**

Run: `python -m unittest packages/agent-runtime/tests/test_contract.py`
Expected: non-zero；错误仅表明 AgentProfile 工件尚未建立。

- [ ] **Step 3: 用严格封闭 schema 和 catalog 完成最小结构**

`contract.json` 必须声明 `contract_family: "agent-profile"`、`contract_version: "1.0.0"`、`side_effects: "forbidden"`、全部 schema 路径、diagnostics、fixtures、limits 和 `set_order: "unsigned-utf8"`。不要把 runtime state、model、memory、permission、team 或 project 字段加进 schema。

- [ ] **Step 4: 运行测试，确认失败已从缺文件收敛到尚无 fixture/lock 或验证逻辑**

Run: `python -m unittest packages/agent-runtime/tests/test_contract.py`
Expected: non-zero；只允许与 Task 2 尚未实现的 fixture/verifier 行为有关。

- [ ] **Step 5: 提交本任务的结构性进度**

Run: `git add packages/agent-runtime/package.json packages/agent-runtime/contracts/agent-profile/1.0.0 packages/agent-runtime/tests/test_contract.py && git commit -m "feat(agent-runtime): define AgentProfile contract schemas"`

### Task 2: 以真实长期 Agent 个体案例实现离线 verifier 与引用/revision 结论

**Files:**
- Create: `packages/agent-runtime/contracts/agent-profile/1.0.0/fixtures/cases.json`
- Create: `packages/agent-runtime/contracts/tools/verify_contract.py`
- Modify: `packages/agent-runtime/tests/test_contract.py`

**Interfaces:**
- Consumes: Task 1 的全部 schema、diagnostic catalog 与 `intelliengine_conformance.json_codec.parse_json_bytes`、`canonicalize`、`schema_validation.is_valid`。
- Produces: `validate_raw(raw: bytes, root: Path) -> dict`、`validate_profile(profile: object, schema: object | None = None) -> dict`、`validate_reference_snapshot(profile: object, snapshot: object | None) -> dict`、`validate_revision_transition(previous: object, candidate: object) -> dict`、`validate_case(case: dict, root: Path) -> dict`、`verify_contract(root: Path) -> dict`。

- [ ] **Step 1: 增加失败的真实行为测试**

```python
def test_profile_rejects_runtime_or_private_memory_fields():
    result = verifier.validate_profile({**valid_profile, "runtime_state": "active"})
    assert result["issues"][0]["code"] == "agent_profile.forbidden_runtime_field"

def test_missing_snapshot_is_indeterminate_not_invalid():
    result = verifier.validate_reference_snapshot(valid_profile, None)
    assert result["object_result"] == "not_evaluated"
    assert result["operation_outcome"] == "indeterminate"

def test_revision_must_change_content_and_increase():
    candidate = {**valid_profile, "revision": 2}
    assert verifier.validate_revision_transition(valid_profile, candidate)["issues"][0]["code"] == "agent_profile.revision_without_change"
```

- [ ] **Step 2: 运行测试，确认每个目标行为失败**

Run: `python -m unittest packages/agent-runtime/tests/test_contract.py`
Expected: non-zero；新增测试不能因 fixture expected 被直接回放而通过。

- [ ] **Step 3: 实现最小纯函数验证器**

先做 strict raw parse，再作 required/unknown field、版本、UUID、safe integer、字符串、集合排序/去重与 schema 校验；始终返回第一条稳定诊断。`forbidden_runtime_field` 仅用于已知安全边界字段（`runtime_state`、`memory`、`private_memory`、`model`、`model_binding`、`permission`、`permissions`、`team`、`project`）；其他未知字段返回 `invalid_profile_field`。snapshot 和 transition 在 Profile 无效时先返回 Profile 的 invalid 结论。

- [ ] **Step 4: 编写 language-neutral fixture suite**

至少覆盖：
1. 多个独立、用户自定义的数学导师/科学导师/协作者 Profiles 均 valid，且不使用 role enum；
2. 无 runtime/model/memory/team 的 Profile valid；
3. 缺字段、UUID/revision/version 错误、空 persona/goals、重复或非规范 capabilities/provenance 被拒绝；
4. known forbidden runtime field 与一般 unknown field 分别返回稳定 diagnostics；
5. raw duplicate key、BOM 与 invalid UTF-8 拒绝；
6. snapshot 缺失、版本不支持、opaque/compatible read 为 indeterminate；完整 snapshot 中 provenance invalid 或闭包不匹配为 invalid；
7. revision 正常增长且内容改变 valid；revision-only、回退、ID 不匹配拒绝。

- [ ] **Step 5: 运行行为测试，确认绿色**

Run: `python -m unittest packages/agent-runtime/tests/test_contract.py`
Expected: zero exit；所有真实 profile、raw、snapshot 和 revision 断言通过。

- [ ] **Step 6: 提交行为与 fixture 进度**

Run: `git add packages/agent-runtime/contracts/agent-profile/1.0.0/fixtures packages/agent-runtime/contracts/tools/verify_contract.py packages/agent-runtime/tests/test_contract.py && git commit -m "feat(agent-runtime): validate AgentProfile fixtures"`

### Task 3: 锁定工件闭包并完成独立可执行验证

**Files:**
- Create: `packages/agent-runtime/contracts/agent-profile/1.0.0/lock.json`
- Modify: `packages/agent-runtime/contracts/tools/verify_contract.py`
- Modify: `packages/agent-runtime/tests/test_contract.py`

**Interfaces:**
- Consumes: Task 1/2 产生的全部 JSON 工件。
- Produces: `verify_contract(root)` 返回精确 `{ "case_count": <N>, "contract_version": "1.0.0" }`；嵌套 JSON、新增 JSON、错误 digest 或 fixture expected 篡改均不能绕过验证。

- [ ] **Step 1: 写出 lock closure 和 expected-not-replayed 的失败测试**

```python
def test_nested_json_cannot_escape_lock_closure():
    # copy contract, add schemas/nested/lock.json, expect ValueError("lock closure mismatch")

def test_fixture_expected_is_not_replayed():
    case["expected"] = invalid_expected
    assert verifier.validate_case(case, CONTRACT_ROOT) != case["expected"]
```

- [ ] **Step 2: 运行测试，确认它们失败**

Run: `python -m unittest packages/agent-runtime/tests/test_contract.py`
Expected: non-zero；不足的 lock/verification 行为被测试捕获。

- [ ] **Step 3: 实现 lock closure、JCS digest 和整个 suite 的自校验**

`verify_contract` 必须验证 contract manifest、schema 形状、catalog、fixture suite、每个 expected result、每个真实 computed result、诊断 code 所属 catalog 和递归 JSON closure。按 UTF-8 canonical JSON 写出 lock，排除 `lock.json` 自身。

- [ ] **Step 4: 运行所有 Issue 验收命令**

Run: `python packages/agent-runtime/contracts/tools/verify_contract.py`
Expected: JSON report，zero exit。

Run: `python -m unittest packages/agent-runtime/tests/test_contract.py`
Expected: zero exit；测试包含 raw 输入、schema、reference、revision、lock 与 anti-replay 证据。

Run: `python scripts/verify_governance.py`
Expected: zero exit。

- [ ] **Step 5: 审计范围并提交**

Run: `git status --short && git diff --check && git diff --cached --name-only`
Expected: 仅允许本 Issue 的 `packages/agent-runtime/**` 与本计划文件。

Run: `git add packages/agent-runtime docs/superpowers/plans/2026-08-24-agent-profile-machine-contract.md && git commit -m "feat(agent-runtime): lock AgentProfile machine contract"`

### Task 4: 独立契约审查与合并交接（中央协调任务）

**Files:**
- Read-only review: RFC-0004、ADR-0008、Issue #44、`packages/agent-runtime/**`、本计划。
- Optional follow-up only if review finds a concrete violation: 原 Issue worktree 内的最小修正。

**Interfaces:**
- Consumes: 已提交的 Issue #44 branch、验证命令输出。
- Produces: 独立审查结论，明确 public-interface compatibility、Profile/runtime 边界、provenance 结论、determinism、lock closure、测试覆盖；随后由中央任务创建 PR、等待 CI、合并或回修。

- [ ] **Step 1: 创建独立 read-only contract review**
- [ ] **Step 2: 对阻断问题回交原实现 worktree，重新运行受影响测试**
- [ ] **Step 3: 中央任务核验 commit、push、PR、CI 与独立审查后自主合并**

## Final Self-Review

- [ ] `AgentProfile` 仍只描述长期个体身份，不承载 runtime/memory/model/control/team/project。
- [ ] 角色、人格和能力声明没有变成权限或固定模板。
- [ ] raw、reference 和 revision 都有真实计算的 fixture，且 `expected` 不可驱动结果。
- [ ] snapshot 的“不知道”与“已知错误”分别输出 indeterminate 与 invalid，未混淆。
- [ ] lock 递归覆盖所有 JSON，JSON Schema 使用离线 `$ref`，并且所有测试和治理验证都由本次实际输出支持。
- [ ] Issue #44 之外的运行时、CLI、差分、状态/记忆/团队功能没有混入本 PR；下一项独立 Issue 才实现 Python/TypeScript 消费者。
