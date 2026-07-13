import { config as dotenvConfig } from "dotenv";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

// Load .env from project root
dotenvConfig({ path: resolve(__dirname, "..", ".env") });

export type LlmProvider = "mimo" | "minimax";

export interface AgentConfig {
  /** LLM provider: "mimo" (Xiaomi, OpenAI-compatible) or "minimax" (Anthropic-compatible) */
  provider: LlmProvider;
  /** LLM API key for the active provider */
  apiKey: string;
  /** LLM API base URL for the active provider */
  baseUrl: string;
  /** Model identifier */
  model: string;
  /** Max completion tokens */
  maxTokens: number;
  /** Sampling temperature */
  temperature: number;
  /** WebGIS backend URL */
  backendUrl: string;
  /** Current working directory */
  cwd: string;
  /** Max agent loop turns */
  maxTurns: number;
  /** Session storage directory */
  sessionDir: string;
  /** Auto-approve all tools (skip permission prompts) */
  autoApprove: boolean;
}

// MiniMax Anthropic-compatible endpoint. The Anthropic-style path
// `/v1/messages` is appended by the adapter. See:
// https://platform.minimaxi.com/docs/api-reference/text-anthropic-api
const DEFAULT_MINIMAX_ANTHROPIC_BASE_URL = "https://api.minimaxi.com/anthropic";
const DEFAULT_MINIMAX_MODEL = "MiniMax-M2.7-highspeed";
const DEFAULT_MIMO_BASE_URL = "https://api.xiaomimimo.com/v1";
const DEFAULT_MIMO_MODEL = "mimo-v2.5-pro";

function env(key: string, fallback = ""): string {
  return process.env[key]?.trim() || fallback;
}

function firstEnv(keys: string[], fallback = ""): string {
  for (const key of keys) {
    const value = env(key);
    if (value) return value;
  }
  return fallback;
}

function numberEnv(key: string, fallback: number): number {
  const value = Number(env(key, String(fallback)));
  return Number.isFinite(value) ? value : Number.NaN;
}

const MIMO_KEY_ENVS = ["MIMO_API_KEY", "WEBGIS_AI_MIMO_API_KEY", "XIAOMI_MIMO_API_KEY"];
const MINIMAX_KEY_ENVS = ["MINIMAX_API_KEY", "WEBGIS_AI_MINIMAX_API_KEY"];

function resolveProvider(): LlmProvider {
  const explicit = firstEnv(["AGENT_LLM_PROVIDER", "WEBGIS_AI_LLM_PROVIDER"]).toLowerCase();
  if (explicit === "mimo" || explicit === "minimax") {
    return explicit;
  }
  // No explicit provider: MiniMax is the default (the MiMo upstream has been
  // retired). Only a MiMo-only key shape keeps the legacy provider alive.
  if (firstEnv(MINIMAX_KEY_ENVS)) return "minimax";
  if (firstEnv(MIMO_KEY_ENVS)) return "mimo";
  return "minimax";
}

export function loadConfig(overrides: Partial<AgentConfig> = {}): AgentConfig {
  const homeDir = process.env.HOME || process.env.USERPROFILE || ".";
  const provider = overrides.provider ?? resolveProvider();

  const apiKey =
    overrides.apiKey ??
    (provider === "minimax" ? firstEnv(MINIMAX_KEY_ENVS) : firstEnv(MIMO_KEY_ENVS));
  const baseUrl =
    overrides.baseUrl ??
    (provider === "minimax"
      ? firstEnv(
          ["MINIMAX_ANTHROPIC_BASE_URL", "WEBGIS_AI_MINIMAX_ANTHROPIC_BASE_URL", "MINIMAX_BASE_URL"],
          DEFAULT_MINIMAX_ANTHROPIC_BASE_URL,
        )
      : firstEnv(["MIMO_BASE_URL", "WEBGIS_AI_MIMO_BASE_URL"], DEFAULT_MIMO_BASE_URL));
  const model =
    overrides.model ??
    (provider === "minimax"
      ? firstEnv(["MINIMAX_MODEL", "WEBGIS_AI_MINIMAX_MODEL"], DEFAULT_MINIMAX_MODEL)
      : firstEnv(["MIMO_MODEL", "WEBGIS_AI_MIMO_MODEL"], DEFAULT_MIMO_MODEL));

  return {
    provider,
    apiKey,
    baseUrl,
    model,
    maxTokens: overrides.maxTokens ?? numberEnv("AGENT_MAX_TOKENS", 4096),
    temperature: overrides.temperature ?? numberEnv("AGENT_TEMPERATURE", 0.2),
    backendUrl: overrides.backendUrl ?? env("WEBGIS_BACKEND_URL", "http://127.0.0.1:18999"),
    cwd: overrides.cwd ?? process.cwd(),
    maxTurns: overrides.maxTurns ?? numberEnv("AGENT_MAX_TURNS", 50),
    sessionDir: overrides.sessionDir ?? resolve(homeDir, ".webgis-agent", "sessions"),
    autoApprove: overrides.autoApprove ?? env("AGENT_AUTO_APPROVE", "true").toLowerCase() === "true",
  };
}

export function validateConfig(config: AgentConfig): string[] {
  const errors: string[] = [];
  if (!config.apiKey) {
    if (config.provider === "minimax") {
      errors.push("MINIMAX_API_KEY or WEBGIS_AI_MINIMAX_API_KEY is required. Set it in .env or environment.");
    } else {
      errors.push("MIMO_API_KEY or WEBGIS_AI_MIMO_API_KEY is required. Set it in .env or environment.");
    }
  }
  if (!Number.isFinite(config.maxTokens) || config.maxTokens < 256) {
    errors.push("AGENT_MAX_TOKENS must be a number at least 256.");
  }
  if (!Number.isFinite(config.maxTurns) || config.maxTurns < 1) {
    errors.push("AGENT_MAX_TURNS must be a positive number.");
  }
  if (!Number.isFinite(config.temperature) || config.temperature < 0 || config.temperature > 2) {
    errors.push("AGENT_TEMPERATURE must be a number between 0 and 2.");
  }
  return errors;
}
