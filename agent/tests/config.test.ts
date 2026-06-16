import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "../src/config.js";

const originalAutoApprove = process.env.AGENT_AUTO_APPROVE;
const originalMimoApiKey = process.env.MIMO_API_KEY;
const originalWebgisMimoApiKey = process.env.WEBGIS_AI_MIMO_API_KEY;

afterEach(() => {
  if (originalAutoApprove === undefined) {
    delete process.env.AGENT_AUTO_APPROVE;
  } else {
    process.env.AGENT_AUTO_APPROVE = originalAutoApprove;
  }
  if (originalMimoApiKey === undefined) {
    delete process.env.MIMO_API_KEY;
  } else {
    process.env.MIMO_API_KEY = originalMimoApiKey;
  }
  if (originalWebgisMimoApiKey === undefined) {
    delete process.env.WEBGIS_AI_MIMO_API_KEY;
  } else {
    process.env.WEBGIS_AI_MIMO_API_KEY = originalWebgisMimoApiKey;
  }
});

describe("loadConfig", () => {
  it("enables tool auto-approval by default", () => {
    delete process.env.AGENT_AUTO_APPROVE;

    expect(loadConfig({ apiKey: "test-key" }).autoApprove).toBe(true);
  });

  it("allows auto-approval to be disabled explicitly", () => {
    process.env.AGENT_AUTO_APPROVE = "false";

    expect(loadConfig({ apiKey: "test-key" }).autoApprove).toBe(false);
  });

  it("accepts the WebGIS unified MiMo API key environment variable", () => {
    delete process.env.MIMO_API_KEY;
    process.env.WEBGIS_AI_MIMO_API_KEY = "webgis-key";

    expect(loadConfig().apiKey).toBe("webgis-key");
  });
});
