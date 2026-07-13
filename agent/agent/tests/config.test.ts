import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { loadConfig } from "../src/config.js";

const MANAGED_ENV_KEYS = [
  "AGENT_AUTO_APPROVE",
  "AGENT_LLM_PROVIDER",
  "WEBGIS_AI_LLM_PROVIDER",
  "MIMO_API_KEY",
  "WEBGIS_AI_MIMO_API_KEY",
  "XIAOMI_MIMO_API_KEY",
  "MINIMAX_API_KEY",
  "WEBGIS_AI_MINIMAX_API_KEY",
  "MINIMAX_ANTHROPIC_BASE_URL",
  "WEBGIS_AI_MINIMAX_ANTHROPIC_BASE_URL",
  "MINIMAX_BASE_URL",
  "MINIMAX_MODEL",
  "WEBGIS_AI_MINIMAX_MODEL",
] as const;

const originalEnv: Record<string, string | undefined> = {};

beforeEach(() => {
  for (const key of MANAGED_ENV_KEYS) {
    originalEnv[key] = process.env[key];
    delete process.env[key];
  }
});

afterEach(() => {
  for (const key of MANAGED_ENV_KEYS) {
    if (originalEnv[key] === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = originalEnv[key];
    }
  }
});

describe("loadConfig", () => {
  it("enables tool auto-approval by default", () => {
    expect(loadConfig({ apiKey: "test-key" }).autoApprove).toBe(true);
  });

  it("allows auto-approval to be disabled explicitly", () => {
    process.env.AGENT_AUTO_APPROVE = "false";

    expect(loadConfig({ apiKey: "test-key" }).autoApprove).toBe(false);
  });

  it("accepts the WebGIS unified MiMo API key environment variable", () => {
    process.env.WEBGIS_AI_MIMO_API_KEY = "webgis-key";

    const config = loadConfig();
    expect(config.provider).toBe("mimo");
    expect(config.apiKey).toBe("webgis-key");
  });

  it("auto-selects the MiniMax provider when only its key is present", () => {
    process.env.MINIMAX_API_KEY = "minimax-key";

    const config = loadConfig();
    expect(config.provider).toBe("minimax");
    expect(config.apiKey).toBe("minimax-key");
    expect(config.baseUrl).toBe("https://api.minimaxi.com/anthropic");
    expect(config.model).toBe("MiniMax-M2.7-highspeed");
  });

  it("honours an explicit provider even when both keys exist", () => {
    process.env.MIMO_API_KEY = "mimo-key";
    process.env.MINIMAX_API_KEY = "minimax-key";
    process.env.AGENT_LLM_PROVIDER = "mimo";

    const config = loadConfig();
    expect(config.provider).toBe("mimo");
    expect(config.apiKey).toBe("mimo-key");
  });

  it("prefers MiniMax when both keys exist without an explicit provider", () => {
    process.env.MIMO_API_KEY = "mimo-key";
    process.env.MINIMAX_API_KEY = "minimax-key";

    const config = loadConfig();
    expect(config.provider).toBe("minimax");
    expect(config.apiKey).toBe("minimax-key");
  });
});
