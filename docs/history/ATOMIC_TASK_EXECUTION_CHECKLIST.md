# EduMatrix Atomic Task Execution Checklist

> Status: mandatory. Applies to F0-F10, fixes, documentation, tests, visual review, handoff, and long-running task recovery.
>
> This file is the operational checklist. `outputs/原系统融合重构执行/15_逐任务原子要求强制执行协议.md` is the process authority. The current task's `task_atomic_execution_contract` and atomic ledger define the task scope. If sources conflict, stop and resolve the conflict against the authoritative source and approved product decisions.

## 1. Non-negotiable rules

1. Every task must independently understand its own atomic requirements. Understanding, code, screenshots, tests, worklogs, or chat memory from a previous task never substitutes for the current task's understanding or evidence.
2. Read and reconcile every primary and related atom separately. A task title, summary, atom-ID list, keyword match, or group conclusion is not sufficient.
3. For every atom, record the source text and image context, product meaning, required behavior, prohibited behavior, affected route/file/state, implementation scope, automatic verification, manual acceptance, and current evidence.
4. Any edit, test, screenshot, refactor, interface change, state transition, or cleanup that cannot be mapped to a current atom or an explicit protection contract is out of scope. Stop it instead of doing it opportunistically.
5. `PENDING`, blank, placeholder, stale-hash, duplicate-ID, "covered", or test-count-only entries are not completion evidence.
6. Without per-atom evidence, do not enter `CONTEXT_VERIFIED`, `CODE_COMPLETE`, `TESTED`, `EVIDENCE_VERIFIED`, or `CLOSED`, and do not hand the task to the next task.

## 2. Read order at task start, resume, and task switch

Read these in order. Do not replace them with a previous chat summary:

1. Root `AGENTS.md`.
2. `outputs/原系统融合重构执行/15_逐任务原子要求强制执行协议.md`.
3. `outputs/原系统融合重构执行/evidence/context_recovery/active_manifest.json` and the current `current_checkpoint.json`.
4. `00_唯一执行状态.md`, `06_用户意图与产品宪法.md`, `11_上下文恢复与实施索引.md`, and `14_长期任务无损上下文与恢复协议.md`.
5. The current task packet and its complete `task_atomic_execution_contract`.
6. The current task's atomic ledger, including the complete source text, Word paragraphs, image references, product interpretation, scope, prohibited boundaries, automatic verification, and manual acceptance for every primary and related atom.
7. The Word source, full-size reference images, product plan, implementation plan, and protection pages cited by the current ledger.
8. Run the authoritative loader and required atomic-gate checks. If loading fails, hashes disagree, the contract does not match, or the ledger is incomplete, stop business editing and repair the recovery package first.

## 3. Required current-task card before any work

Create or locate the current task card in the task packet/ledger's permitted location. It must include:

```text
goal_id:
task_id:
phase:
checkpoint_state:
task_atomic_execution_contract: verified / blocked
primary_atom_ids:
related_atom_ids:
source_refs:
protection_contracts:

for every atom:
  atom_id:
  role: primary / related
  original_text_and_image_context:
  product_meaning:
  required_behavior:
  prohibited_behavior:
  affected_routes_files_interfaces_states:
  implementation_scope:
  automatic_verification:
  manual_acceptance:
  current_implementation_evidence:
  current_verification_evidence:
  current_user_visible_result:
  deferral_or_conflict_reason:
  confirmed:
```

If any field is blank, a placeholder, only an atom ID, or merely a reference to another atom, editing cannot begin.

## 4. Atomic mapping loop for every batch

### 4.1 Before the batch

Write the mapping before executing the batch:

| Batch action | Directly implemented atoms | Related/protected atoms or contracts | Concrete result | Verification |
|---|---|---|---|---|
| File, interface, page, state, or test action | List each ID | List each ID or contract | State what the user will see | Test, browser, or manual steps |

Unmapped actions must not run. If one action affects several atoms, list each atom's effect separately instead of using one group ID.

### 4.2 During the batch

- Modify only the files, interfaces, pages, and states allowed by the current task card.
- Preserve original-version protection contracts, closed-task behavior, permissions, data integrity, assessment gates, and source-of-truth boundaries.
- If implementation conflicts with source text, images, product contracts, or approved decisions, pause that path and re-check the authoritative sources.
- Do not treat "the code runs" as proof that an atom is implemented. Do not treat "the page exists" as proof that interaction and failure states are complete.

### 4.3 Immediately after the batch

Before starting another batch, update the same atomic ledger for every affected atom with:

- implementation file, interface, component, route, or data protocol;
- actual test command, result, screenshot, or browser evidence;
- user-visible result;
- compatibility, protection, or coordination evidence for related atoms;
- the real reason for failure, incompleteness, external dependency, or missing manual acceptance.

## 5. Per-atom closure and handoff review

Read the ledger from the first atom to the last and answer separately for each atom:

1. What are its complete source words and image context?
2. What does the user see, click, and receive?
3. Which behaviors are required and which are prohibited?
4. Which file, interface, page, state, or task owns it?
5. How are automatic verification and desktop manual acceptance reproduced? What is shown in loading, empty, generating, failed, retry, recovery, and complete states?
6. Is the evidence a real file, test result, screenshot, or compatibility record rather than "implemented" or "covered"?
7. Does it conflict with the 7.20 version, a closed task, another atom, or a protection contract?
8. If deferred, what is the actual reason, impact, next step, and blocking condition?

A primary atom without implementation, verification, or user-result evidence cannot close. A related atom without compatibility or protection evidence cannot close. Never replace this review with "all atoms are covered".

## 6. Context loss, restart, network interruption, or handoff

When context is compressed, the computer restarts, the network drops, the model changes, the task pauses, or work is handed off:

1. Discard execution assumptions from the previous chat turn.
2. Restart the read order in section 2 from the current checkpoint and current task ledger.
3. Continue only from current ledger entries that are confirmed but still lack sufficient realization evidence. Never copy understanding or evidence from a previous task.
4. Check whether the last batch mapping and ledger update are complete. If not, complete the ledger before any business edit.
5. If checkpoint, packet, ledger, source hashes, or active manifest disagree, preserve the current state and stop business editing until the recovery package is repaired.

## 7. Documentation and test tasks are also atomic tasks

"No code change" does not remove the atomic mapping requirement. Product plans, UI specifications, test scripts, screenshots, audit reports, worklogs, and handoff documents must state which current atoms they implement or protect. Do not describe future design as implemented, and do not use a test count as a substitute for per-atom evidence.

## 8. Minimum completion report

Use this structure only after per-atom reconciliation:

```text
task_id:
primary_atoms: list each atom with status and evidence
related_atoms: list each atom with compatibility/protection evidence
changed_files_and_surfaces:
tests_and_manual_acceptance:
failed_or_deferred_atoms:
checkpoint_transition:
next_task:
```

If any atom is `PENDING`, lacks evidence, lacks manual acceptance, or has an unresolved source conflict, the report must say `NOT COMPLETE` and must not announce task completion.
