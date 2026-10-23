import { realpathSync } from "node:fs";
import { isAbsolute, relative, resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** Scope the teacher's read-only tools to its curated evidence snapshot. No shell. */
export default function (pi: ExtensionAPI) {
  const root = realpathSync(process.cwd());
  const allowed = new Set(["read", "grep", "find", "ls"]);
  pi.on("tool_call", async (event) => {
    if (!allowed.has(event.toolName)) {
      return { block: true, reason: "Teacher has read-only evidence tools; no shell, CAD or writes." };
    }
    const input = event.input as { path?: string; pattern?: string };
    if (event.toolName === "find" && input.pattern &&
        (isAbsolute(input.pattern) || input.pattern.split(/[\\/]/).includes(".."))) {
      return { block: true, reason: "Find patterns must stay inside the evidence snapshot." };
    }
    const requested = input.path ?? ".";
    try {
      const target = realpathSync(resolve(root, requested));
      const rel = relative(root, target);
      if (rel === ".." || rel.startsWith("../") || isAbsolute(rel)) {
        return { block: true, reason: "Path is outside the teacher evidence snapshot." };
      }
    } catch {
      return { block: true, reason: "Evidence path does not exist or cannot be resolved." };
    }
    return undefined;
  });
}
