import { ToolRegistry } from "./tool.js";
import { askUserTool } from "./tools/ask-user.js";
import { editFileTool } from "./tools/edit-file.js";
import { allGisTools } from "./tools/gis-tools.js";
import { grepFilesTool } from "./tools/grep-files.js";
import { listFilesTool } from "./tools/list-files.js";
import { readFileTool } from "./tools/read-file.js";
import { runCommandTool } from "./tools/run-command.js";
import { webFetchTool } from "./tools/web-fetch.js";
import { writeFileTool } from "./tools/write-file.js";

export function createToolRegistry(): ToolRegistry {
  const registry = new ToolRegistry();
  registry.register(readFileTool);
  registry.register(writeFileTool);
  registry.register(editFileTool);
  registry.register(listFilesTool);
  registry.register(grepFilesTool);
  registry.register(runCommandTool);
  registry.register(webFetchTool);
  registry.register(askUserTool);
  registry.registerAll(allGisTools);
  return registry;
}
