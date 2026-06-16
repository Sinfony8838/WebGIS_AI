import { config as dotenvConfig } from "dotenv";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

// Load .env from project root
dotenvConfig({ path: resolve(__dirname, "..", ".env") });

export interface AgentConfig {
  /** MiMo API key */
  apiKey: string;
  /** MiMo API base URL */
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

export function loadConfig(overrides: Partial<AgentConfig> = {}): AgentConfig {
  const homeDir = process.env.HOME || process.env.USERPROFILE || ".";

  return {
    apiKey: overrides.apiKey ?? firstEnv(["MIMO_API_KEY", "WEBGIS_AI_MIMO_API_KEY", "XIAOMI_MIMO_API_KEY"]),
    baseUrl: overrides.baseUrl ?? firstEnv(["MIMO_BASE_URL", "WEBGIS_AI_MIMO_BASE_URL"], "https://api.xiaomimimo.com/v1"),
    model: overrides.model ?? firstEnv(["MIMO_MODEL", "WEBGIS_AI_MIMO_MODEL"], "mimo-v2.5-pro"),
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
    errors.push("MIMO_API_KEY or WEBGIS_AI_MIMO_API_KEY is required. Set it in .env or environment.");
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
