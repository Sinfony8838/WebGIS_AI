import type { Tool } from "./tool.js";

export type PermissionDecision = "allow" | "deny" | "confirm";

interface PermissionRule {
  pattern: RegExp;
  decision: PermissionDecision;
}

// Default permission rules
const DEFAULT_RULES: PermissionRule[] = [
  // Read-only tools: always allow
  { pattern: /^(read_file|list_files|grep_files|web_fetch|ask_user|gis_health|gis_list_.*|gis_get_project|gis_workflow_status|gis_kb_search)$/, decision: "allow" },
  // GIS write tools: allow (HTTP calls to backend)
  { pattern: /^gis_/, decision: "allow" },
  // Write tools: confirm
  { pattern: /^(write_file|edit_file)$/, decision: "confirm" },
  // Bash: confirm
  { pattern: /^run_command$/, decision: "confirm" },
];

export class PermissionManager {
  private rules: PermissionRule[];
  private autoApprove: boolean;
  private sessionApprovals = new Set<string>();

  constructor(autoApprove = false, extraRules: PermissionRule[] = []) {
    this.autoApprove = autoApprove;
    this.rules = [...extraRules, ...DEFAULT_RULES];
  }

  check(tool: Tool): PermissionDecision {
    if (this.autoApprove) return "allow";

    // Check if already approved this session
    if (this.sessionApprovals.has(tool.name)) return "allow";

    // Match rules in order
    for (const rule of this.rules) {
      if (rule.pattern.test(tool.name)) {
        return rule.decision;
      }
    }

    // Default: allow
    return "allow";
  }

  /** Remember that the user approved this tool for the rest of the session */
  approveForSession(toolName: string): void {
    this.sessionApprovals.add(toolName);
  }
}
