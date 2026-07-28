# MIKE — Architecture Inventory

**Document status:** Approved  
**Architecture version:** 0.1  
**Document version:** 1.0  
**Canonical:** Yes

## 1. Engines

### 01 — Perception & Understanding
- **Status:** Frozen
- **Responsibility:** Convert external inputs into structured organizational information consumable by MIKE.

### 02 — World Model
- **Status:** Frozen
- **Responsibility:** Maintain the best current structured, time-aware, evidence-linked representation of organizational reality.

### 03 — Cognitive Episode
- **Status:** Frozen
- **Responsibility:** Maintain the bounded cognitive context of one organizational situation.

### 04 — Memory
- **Status:** Frozen
- **Responsibility:** Preserve, organize, and retrieve organizational knowledge across time.

### 05 — Reasoning & Decision
- **Status:** Frozen
- **Responsibility:** Analyze organizational situations and produce justified recommendations or decisions.

### 06 — Policy, Authority & Governance
- **Status:** Frozen
- **Responsibility:** Ensure proposed organizational actions comply with policy, authority, governance, and operational constraints.

### 07 — Transition
- **Status:** Frozen
- **Responsibility:** Validate and apply state transitions to canonical organizational objects while preserving lifecycle rules, invariants, causality, traceability, and consistency.

### 08 — Commitment
- **Status:** Frozen
- **Responsibility:** Create, manage, and track organizational commitments throughout their lifecycle, independently of how they are planned or executed.

### 09 — Work
- **Status:** Frozen
- **Responsibility:** Represent, organize, decompose, and manage organizational work independently of scheduling, capacity planning, and execution.

### 10 — Capacity & Resource
- **Status:** Frozen
- **Responsibility:** Represent, evaluate, allocate, reserve, and monitor organizational resources and operational capacity required to perform work.

### 11 — Scheduler
- **Status:** Frozen
- **Responsibility:** Plan, sequence, schedule, and continuously adapt organizational work over time while respecting priorities, dependencies, deadlines, capacity, and operational constraints.

### 12 — Focus
- **Status:** Frozen
- **Responsibility:** Continuously determine, prioritize, and manage MIKE’s cognitive attention across organizational situations according to relevance, urgency, impact, risk, and changing context.

### 13 — Communication
- **Status:** Frozen
- **Responsibility:** Manage bidirectional organizational communication across supported channels while remaining independent of reasoning, governance, and execution.

### 14 — Execution & Skills
- **Status:** Frozen
- **Responsibility:** Execute authorized organizational actions through reusable operational skills and external capabilities while abstracting implementation details from the rest of MIKE.

### 15 — Verification
- **Status:** Frozen
- **Responsibility:** Evaluate observed outcomes against expected results, acceptance criteria, and available evidence, producing traceable verification conclusions without executing actions or applying state transitions.

### 16 — Learning & Reflection
- **Status:** Frozen
- **Responsibility:** Extract, validate, consolidate, and propose organizational learning from accumulated experience in order to improve future knowledge, reasoning, policies, and operational performance while respecting governance constraints.

### 17 — Orchestration & Event Runtime
- **Status:** Frozen
- **Responsibility:** Coordinate all architectural interactions through events, durable processes, timers, retries, and runtime services while remaining independent of business meaning, organizational rules, and domain knowledge.

### Global Principles
- **MIKE has exactly 17 foundational engines.**
- **Engines never call one another directly.**
- **Coordination occurs through immutable events and runtime processes.**
- **Events are immutable.**
- **Cognitive Episodes represent bounded organizational situations.**
- **Runtime manages technical mechanics, not business meaning.**
- **Reasoning and authority are separate.**
- **Execution does not decide.**
- **Technical execution success does not by itself prove organizational success.**
- **Tenant isolation is mandatory.**
- **MIKE begins implementation as a modular monolith, not as microservices.**
- **Documentation is the architectural source of truth.**

## 2. Canonical Objects

**Status:** Not yet frozen.

## 3. Protocols

**Status:** Not yet frozen.

## 4. Runtime

**Status:** Not yet frozen.

## 5. Security

**Status:** Not yet frozen.

## 6. Architectural Decisions

**Status:** Not yet frozen.
