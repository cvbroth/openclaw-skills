/** Trusted Gateway management subprocess. No shell, identity and config never come from tool parameters. */
import { spawn } from "node:child_process";
import path from "node:path";
import { client } from "./client.mjs";

export function managementRequest(config, identity, operation, params, signal) {
  const management = config?.management;
  if (!management || ![management.python, management.entry, management.config].every(p => typeof p === "string" && path.isAbsolute(p))) {
    return Promise.resolve({ status: "ERROR", code: "MANAGEMENT_NOT_CONFIGURED" });
  }
  const payload = Buffer.from(JSON.stringify({ identity, operation, params }));
  if (payload.length > 512*1024) return Promise.resolve({ status: "ERROR", code: "REQUEST_LIMIT" });
  return new Promise(resolve => {
    const child = spawn(management.python, ["-I", management.entry, "--config", management.config], {
      shell: false, windowsHide: true, stdio: ["pipe", "pipe", "ignore"] });
    let bytes = 0, settled = false;
    const chunks = [];
    const finish = result => { if (settled) return; settled = true; clearTimeout(timer); signal?.removeEventListener("abort", abort); resolve(result); };
    const abort = () => { child.kill(); finish({ status: "ERROR", code: "REGISTRATION_INTERRUPTED" }); };
    const timer = setTimeout(abort, operation.startsWith("register") ? 3600_000 : 60_000);
    child.stdout.on("data", part => { bytes += part.length; if (bytes > 2*1024**2) abort(); else chunks.push(part); });
    child.on("error", () => finish({ status: "ERROR", code: "MANAGEMENT_UNAVAILABLE" }));
    child.stdin.on("error", () => finish({ status: "ERROR", code: "MANAGEMENT_UNAVAILABLE" }));
    child.on("close", () => {
      try { const result = JSON.parse(Buffer.concat(chunks)); if (typeof result.status !== "string") throw Error(); finish(result); }
      catch { finish({ status: "ERROR", code: "MANAGEMENT_INVALID_RESPONSE" }); }
    });
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort(); else child.stdin.end(payload);
  });
}

export function configuredClient(config, transport = client) {
  if (!config?.management) return transport; // Explicit legacy bridge, never selected by a V1.2 install.
  return {
    capabilities: transport.capabilities.bind(transport),
    call(identity, operation, params, signal) {
      return ["register", "files"].includes(operation)
        ? managementRequest(config, identity, operation, params, signal)
        : transport.call(identity, operation, params, signal);
    },
    registerMedia(identity, item, signal) {
      const profile = config.workspaces?.[identity.agent_id];
      if (!profile) return Promise.resolve({ status: "ERROR", code: "WORKSPACE_MAPPING_REQUIRED" });
      // Roots are administrator configuration; metadata cannot add or widen an allowed root.
      const roots = { workspace: { path: profile.workspace }, ...profile.source_roots };
      const entry = Object.entries(roots).find(([, root]) => {
        const relative = path.relative(root.path, item.path);
        return relative && !relative.startsWith(".."+path.sep) && relative !== ".." && !path.isAbsolute(relative);
      });
      if (!entry) return Promise.resolve({ status: "ERROR", code: "SOURCE_ROOT_DENIED" });
      return managementRequest(config, identity, "register_media", { source_root: entry[0],
        source_path: path.relative(entry[1].path, item.path), mode: "snapshot", request_id: item.id,
        source: { message_id: item.message, channel: item.channel, description_trust: "untrusted" } }, signal);
    },
  };
}
