---
title: Product Vision
status: active
owner: root-architect-execution maintainers
last_reviewed: 2026-09-17
---

# Product Vision

## Purpose

`root-architect-execution` exists to make implementation-plan execution by coding agents auditable, bounded, and recoverable. It separates architectural authority from product-code mutation: the root session keeps the plan, Git, ledger, dispatch state, and final acceptance authority; cheaper isolated workers perform implementation and review.

## Problem

Agentic coding workflows commonly collapse planning, implementation, review, Git mutation, and acceptance into one context. That makes failures difficult to attribute and permits an agent to silently widen scope, approve its own work, bypass failed delegation, or treat malformed prose as evidence.

The project addresses this with explicit roles, schema-checked handoffs, host capability declarations, generated adapters, runtime guards, and a fail-closed gate sequence.

## Product principles

- Root owns authority; workers own bounded execution.
- Product code is delegated rather than written by root.
- Implementer, specification review, and quality review are distinct roles.
- Worker returns are data contracts, not instructions to root.
- One dependent dispatch is active at a time.
- Git mutation stays at root.
- Generated artifacts are reproducible from declared sources.
- Unsupported host guarantees are disclosed rather than silently assumed.
- Targeted tests support task decisions; the full outcome gate supports completion.
- Corrupt durable state blocks mutation rather than being interpreted as absence of state.

## Current scope

The repository provides installable/built host support for Claude Code and Codex, with Cursor retained as an incompletely sourced/reference host path. The repository reports the root half of an end-to-end run as observed, while orchestrator-to-worker execution and live guard firing remain items requiring complete live observation.

## Non-goals

The protocol is not a generic one-shot coding assistant, not a replacement for the governing implementation plan, and not a mechanism for workers to coordinate directly with each other or the human owner.
