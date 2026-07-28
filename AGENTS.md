# AGENTS.md

## Mission

Follow the approved MIKE architecture and implementation constraints. Do not redesign the system. Implement only the requested scope, preserve existing architecture, and keep documentation aligned with behavior.

## Architectural Grounding

- MIKE is a cognitive operating system for organizations.
- The architecture contains exactly 17 frozen foundational engines.
- Engines never call one another directly.
- Coordination occurs through immutable events and runtime handlers.
- Runtime owns technical mechanics; it does not own business meaning.
- Reasoning, authority, execution, transition, and verification remain separate.
- Every organization-owned object must be tenant-scoped.
- MIKE starts as a modular monolith.
- Do not introduce microservices or distributed infrastructure without an approved architectural decision.

## Implementation Rules

- Do not create empty modules for all 17 engines.
- Build small working vertical slices.
- Do not invent canonical objects, protocols, lifecycle states, or business rules that have not been approved.
- Documentation is the architectural source of truth.
- Existing architecture may not be redesigned during implementation tasks.
- Before modifying code, inspect the relevant architecture documents and the existing implementation.
- Every implementation task must include appropriate tests.
- Prefer explicit, typed, readable Python over clever abstractions.
- Preserve tenant isolation, traceability, immutability, and auditability.
- Never place secrets or real credentials in the repository.

## Required Workflow

1. Inspect
   - Read the relevant architecture documents and current implementation.
   - Identify the smallest scope that satisfies the request.
2. Plan
   - State the intended change, affected files, and risks.
3. Implement the smallest requested scope
   - Make the minimal change that fits the approved architecture.
4. Run tests and checks
   - Execute relevant tests and validation steps.
5. Report results and unresolved risks
   - Report exactly which files changed and which checks were run.

## Reporting

Every task must end with:

- the exact files changed;
- the checks or tests run;
- any unresolved risks or architectural ambiguity.
