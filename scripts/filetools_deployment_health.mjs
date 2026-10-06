// Administrator probe: pipe into node --input-type=module in the real Gateway /app.
// Uses an existing SDK session epoch; no inbound event, recipient or fake identity.
import { listSessionEntries, resolveStorePath } from "openclaw/plugin-sdk/session-store-runtime";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { exchange } from "/home/node/.openclaw/extensions/nas-filetools/src/client.mjs";

const sessions = listSessionEntries({ agentId: "chen",
  storePath: resolveStorePath(undefined, { agentId: "chen" }), readOnly: true,
  hydrateSkillPromptRefs: false }).filter(x => x.sessionKey.includes(":qqbot:direct:") && x.entry.sessionId);
if (sessions.length !== 1) throw new Error("REAL_CHEN_QQ_SESSION_NOT_UNIQUE");
const identity = { user_id: "chen", agent_id: "chen", session_hash: createHash("sha256")
  .update(`${sessions[0].sessionKey}\0${sessions[0].entry.sessionId}`).digest("hex") };
const owner = createHash("sha256").update(`chen\0chen\0${identity.session_hash}`).digest("hex");
const rows = Number(execFileSync("python3", ["-B", "-c", `
import sqlite3,sys
d=sqlite3.connect("file:/home/node/.openclaw/workspace-chen/filetools/registry.sqlite?mode=ro",uri=True)
print(d.execute("SELECT count(*) FROM jobs WHERE owner=? AND agent=?",(sys.stdin.read().strip(),"chen")).fetchone()[0])
d.close()
`], { input: owner }).toString());
if (!rows) throw new Error("REAL_SESSION_NOT_MATCHED_TO_PERSISTED_OWNER");
const health = await exchange("/v1/tool", identity, { operation: "health", params: {} });
console.log(JSON.stringify({ identity_source: "read-only SDK Chen QQ direct epoch; persisted owner matched",
  transport: "installed plugin client /v1/tool over Gateway Unix socket", health }));
if (health.status !== "HEALTHY" || !health.scheduler_alive || health.error) process.exitCode = 2;
