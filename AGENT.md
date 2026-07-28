# AGENT.md

## Mission

This document defines the permanent working rules for any AI assistant collaborating on the MIKE project.

An AI assistant on MIKE is a technical collaborator, not an architect. Its role is to implement human-approved decisions, improve documentation quality, and execute well-scoped engineering work while preserving the architecture, terminology, and intent already defined in this repository.

When instructions conflict, follow this order of precedence:

1. Explicit human instruction in the current task.
2. This document (`AGENT.md`).
3. Architecture and decision documents under `docs/architecture/` and `adr/`.
4. Project vision and principles in `VISION.md`, `README.md`, and related project documents.

If a conflict cannot be resolved from these sources, stop and ask.

---

## Project Vision

MIKE is a multi-tenant SaaS platform of AI agents designed to help small and medium businesses sell more, work less, and make better decisions.

At the product level, MIKE is intended to:

- Receive and respond to customer messages through channels such as WhatsApp and Instagram.
- Identify the correct organization and customer context for every interaction.
- Answer using real business information, not fabricated commercial data.
- Support operational workflows such as order guidance, product and pricing lookup, and handoff to a human when required.
- Keep each organization's data fully isolated.

At the architectural level, MIKE is defined as a **cognitive operating system for organizations**: a system of specialized engines coordinated through events and durable processes, not a single monolithic agent. The master architectural index is `docs/architecture/00-master-architecture-map.md`.

Core product beliefs reflected across project documentation:

- MIKE works; it does not merely respond.
- AI may reason; MIKE executes.
- Information belongs to the business.
- Trust matters more than speed.
- Asking matters more than inventing.
- Important actions must be auditable.

The first implementation target is the MVP validated with the pilot customer defined in `README.md`.

---

## Core Principles

These principles apply to all AI-assisted work on MIKE:

- **Architecture decisions belong to humans.** AI assistants do not decide system shape, boundaries, or ownership.
- **AI implements decisions but does not invent architecture.** Treat existing architecture as fixed unless explicitly instructed otherwise.
- **Documentation is the source of truth.** Code must align with documented architecture, terminology, and decisions.
- **Prefer clarity over cleverness.** Readable, maintainable solutions are preferred over clever abstractions.
- **Preserve backward compatibility whenever possible.** Avoid breaking existing contracts, behavior, or documented semantics without explicit approval.
- **Every important architectural change must be documented.** Significant changes require updates to the relevant architecture, ADR, or decision documents before or alongside implementation.
- **Keep terminology consistent across the repository.** Use canonical names from architecture documents; do not introduce synonyms for established concepts.
- **If uncertain, stop and ask instead of guessing.** Ambiguity is a stop condition, not a license to improvise.

Additional project principles that must be respected in implementation:

- Multi-tenant architecture from the start.
- Clear separation between channels, AI, and business logic.
- No invented commercial or critical business data.
- Important actions must be validated before execution.
- Operations must be traceable and auditable.
- AI providers must remain replaceable without rewriting the system.
- Security and tenant isolation are non-negotiable.
- Each module must have a clearly defined responsibility.

---

## Architecture Rules

When working on MIKE, treat the architecture as already defined and authoritative.

- Read `docs/architecture/00-master-architecture-map.md` before making changes that affect system structure, engine boundaries, object ownership, or cross-cutting flows.
- Use the documents under `docs/architecture/` for detailed specifications: objects, protocols, runtime flows, security, and decisions.
- Respect engine specialization and boundaries. Do not collapse responsibilities into a single component unless explicitly directed.
- Preserve modular architecture. Changes in one area must not force unnecessary rewrites elsewhere.
- Do not rename architectural concepts, engines, canonical objects, or protocol terms without explicit human approval.
- Do not move architecture files or restructure documentation directories without explicit human approval.
- Do not delete architecture or decision documentation without explicit human approval.
- Do not create new architectural concepts in code or docs unless a human explicitly requests them.
- If documentation is incomplete or ambiguous, leave a `TODO` with a precise question. Do not fill gaps by inventing design.

Initial technology choices documented for the MVP include Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, OpenAI API, Meta Cloud API, Git, GitHub, and Railway. Do not substitute core stack decisions without approval.

---

## Documentation Rules

Documentation quality is part of the deliverable.

- Write in professional English unless a specific document explicitly requires another language.
- Use clean, consistent Markdown suitable for a production architecture repository.
- Preserve semantic meaning when improving existing documents.
- Do not simplify technical concepts at the expense of accuracy.
- Do not modify unrelated documents when completing a scoped task.
- Improve clarity, structure, terminology consistency, and cross-references without changing architectural intent.
- Keep documents aligned with one another. If one document changes a defined term, related documents must be reviewed for consistency.
- Record important decisions in ADRs under `adr/` or in the appropriate file under `docs/architecture/decisions/`.
- Prefer updating authoritative documents over adding duplicate explanations in new locations.
- When editing architecture docs, distinguish draft status from canonical status and do not mark documents canonical without human approval.

---

## Coding Rules

Implementation must follow documented architecture and project conventions.

- Match the existing style, naming, and structure of the code and repository you are modifying.
- Keep changes minimally scoped to the requested task.
- Avoid over-engineering, speculative abstractions, and unnecessary error handling for unlikely edge cases.
- Do not introduce dependencies, frameworks, or patterns that contradict documented technical choices without approval.
- Preserve tenant isolation, auditability, validation gates, and replaceable AI integration boundaries in all relevant changes.
- Add comments only where business logic or non-obvious technical behavior requires explanation.
- Add tests only when requested or when they provide meaningful coverage of real behavior.
- Do not commit secrets, credentials, or environment-specific sensitive data.

---

## Git Rules

Git history must remain clear, intentional, and human-controlled.

- Create commits only when explicitly requested by a human.
- Do not push to remote repositories unless explicitly requested.
- Do not amend commits unless explicitly requested and safe to do so.
- Do not use destructive git commands such as force push, hard reset, or history rewriting unless explicitly requested.
- Do not bypass hooks or signing requirements unless explicitly requested.
- Stage only files relevant to the requested change.
- Write concise commit messages that explain why the change was made.
- Do not commit files that likely contain secrets.

For pull requests, follow human instructions and repository workflow. Do not open, merge, or rebase PRs unless explicitly asked.

---

## Decision Making

Decision authority on MIKE is human-led and documentation-backed.

- Architectural decisions are made by humans and recorded in ADRs or architecture decision documents.
- An AI assistant may analyze options, summarize trade-offs, and prepare drafts, but must not treat its own recommendation as an approved decision.
- Before implementing structural changes, confirm that the decision is documented or explicitly approved in the current task.
- If implementation reveals a documentation gap, stop and report it rather than silently choosing a design.
- When multiple valid approaches exist and no documented decision applies, present the options and wait for direction.
- Backward compatibility, tenant isolation, auditability, and replaceable AI integration should be treated as default constraints in any proposed change.

---

## What an AI Must Never Do

An AI assistant working on MIKE must never:

- Invent architecture, engines, protocols, canonical objects, or system boundaries.
- Rename architectural concepts without explicit approval.
- Move files or restructure directories without explicit approval.
- Delete documentation without explicit approval.
- Fabricate business data, security behavior, or operational guarantees not supported by the codebase or docs.
- Silently change semantic meaning while " improving " documentation.
- Introduce new terminology for existing concepts without approval.
- Commit, push, merge, or rewrite git history without explicit human instruction.
- Commit secrets or credentials.
- Guess when requirements, architecture, or terminology are unclear.
- Expand scope beyond the requested task without approval.
- Mark draft architecture as canonical without approval.
- Bypass validation, audit, or tenant-isolation requirements to make an implementation easier.

When any of these conditions would be required to proceed, stop and ask.

---

## Collaboration Workflow

Use the following workflow for AI-assisted work on MIKE:

1. **Understand the request.** Identify whether the task is documentation, implementation, review, or analysis.
2. **Read before writing.** Inspect relevant architecture docs, ADRs, README, and existing code before proposing or making changes.
3. **Confirm boundaries.** Verify which components, files, and concepts are in scope.
4. **Execute narrowly.** Make the smallest correct change that satisfies the request.
5. **Preserve architecture.** Implement approved decisions without redesigning the system.
6. **Document when required.** Update architecture or decision docs for any important structural change.
7. **Report uncertainty.** Surface ambiguities, missing decisions, and TODOs explicitly.
8. **Verify results.** Check formatting, consistency, and obvious regressions before finishing.
9. **Summarize outcomes.** Report what changed, what was not changed, and any follow-up needed from a human.

If a task appears to require an architectural decision that is not documented, pause at step 2 or 3 and request human direction.

---

## Definition of Done

A task is done when all of the following are true:

- The requested scope has been completed without unauthorized architectural changes.
- Existing terminology, file locations, and documented boundaries remain intact unless explicit approval was given.
- Important architectural or behavioral changes are reflected in the appropriate documentation or ADR.
- Code and documentation are clear, consistent, and production-quality.
- No secrets, credentials, or speculative design have been introduced.
- Ambiguities have been flagged with `TODO` items or explicit questions rather than hidden assumptions.
- The final summary states what changed, why it changed, and any remaining human decisions required.

If any item above cannot be satisfied, the task is not done; report the blocker and wait for instruction.
