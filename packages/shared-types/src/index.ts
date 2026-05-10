/**
 * @kraken-signal/shared-types
 *
 * Shared TypeScript contracts for the Crypto Momentum Alert Copilot.
 * Used by: apps/web (Next.js dashboard) and future TypeScript tooling.
 * The Python scanner mirrors these shapes with dataclasses/TypedDicts.
 *
 * Modules:
 *   enums    — String union types for every enum-like DB column + const maps
 *   database — Supabase Database type (Row / Insert / Update per table)
 *   models   — Typed StrategySettings domain model + dashboard composite types
 *   scanner  — Scanner pipeline step contracts (inter-stage data shapes)
 *   discord  — Discord webhook payload types
 */

export * from "./enums";
export * from "./database";
export * from "./models";
export * from "./scanner";
export * from "./discord";
