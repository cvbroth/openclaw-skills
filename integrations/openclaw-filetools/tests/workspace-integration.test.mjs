/** Actual SDK factory + management process + shared filesystem + real worker. Channel identity/transport injected. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, writeFile, readFile, rm } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { Registry, createTool, trustedIdentity } from "../src/runtime.mjs";
import { schemas } from "../src/index.mjs";
import { managementRequest } from "../src/management.mjs";

test("shared canonical relative attachment registers without byte upload; text/XLSX outputs can be fetched", {
  skip: !process.env.FILETOOLS_TEST_PYTHON,
}, async t => {
  const directory = await mkdtemp(path.join(process.env.FILETOOLS_TEST_TMP ?? os.tmpdir(), "v12-shared-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const workspace = path.join(directory, "agent-chen");
  await mkdir(workspace);
  await writeFile(path.join(workspace, "notes.txt"), "Cedar NAS evidence");
  const profiles = { chen: { workspace, service_root: path.join(workspace, "filetools") } };
  const configuration = path.join(directory, "mapping.json");
  await writeFile(configuration, JSON.stringify({ limits: { enabled_agents: ["chen"], script_isolation: "development" }, workspaces: profiles }));
  const driver = fileURLToPath(new URL("../../../tests/bridge_v12.py", import.meta.url));
  const manager = fileURLToPath(new URL("../../../scripts/filetools_manage.py", import.meta.url));
  const config = { bindings: [{ agent_id: "chen", sender_id: "sender", channel_id: "qqbot", account_id: "default" }],
    workspaces: { chen: { workspace } }, management: { python: process.env.FILETOOLS_TEST_PYTHON, entry: manager, config: configuration } };
  const context = { agentId: "chen", sessionKey: "agent:chen:qqbot:direct:sender", sessionId: "epoch-1", requesterSenderId: "sender",
    messageChannel: "qqbot", agentAccountId: "default" };
  const calls = [];
  const exchange = payload => new Promise((resolve, reject) => {
    assert.ok(Buffer.byteLength(JSON.stringify(payload)) < 16384);
    const process = spawn(config.management.python, [driver, configuration], { windowsHide: true });
    let output = "", error = "";
    process.stdout.on("data", part => output += part); process.stderr.on("data", part => error += part);
    process.on("error", reject); process.on("close", code => code ? reject(Error(error)) : resolve(JSON.parse(output)));
    process.stdin.end(JSON.stringify(payload));
  });
  const transport = { async capabilities(identity) { return exchange({ identity, operation: "capabilities", params: {} }); },
    async call(identity, operation, params) { calls.push(operation); return exchange({ identity, operation, params }); },
    upload() { throw Error("V1.2 MUST NOT UPLOAD BYTES"); } };
  const registry = new Registry(Date.now, transport);
  const event = { content: "[Attachment: /private/auth]", messageId: "m1", media: [{ path: "notes.txt", workspaceDir: workspace }] };
  await registry.received(config, event, { channelId: "qqbot", accountId: "default", senderId: "sender", sessionKey: context.sessionKey },
    { lookupSucceeded: true, sessionId: context.sessionId });
  await registry.flush(config, context, transport);
  const receipt = registry.receipts(config, context)[0];
  assert.equal(receipt.status, "REGISTERED");
  assert.equal(registry.receipts(config, context).length, 0);
  assert.equal((await exchange({ identity: trustedIdentity(config, context), operation: "count_jobs", params: {} })).jobs, 0);
  const tool = op => createTool(`filetools_${op}`, op, schemas[op], config, context, registry, transport);
  const registered = (await tool("register").execute("r", { source_path: "notes.txt" })).details;
  assert.equal(registered.file_id, receipt.file_id);
  const result = (await tool("python").execute("p", { attachment_id: receipt.attachment_id,
    description: "Create Markdown and spreadsheet copies", outputs: ["answer.md", "result.xlsx"],
    code: "from pathlib import Path\nimport os,openpyxl\nPath('answer.md').write_text(Path(os.environ['FILETOOLS_INPUT']).read_text())\nw=openpyxl.Workbook()\nw.active['A1']='Cedar'\nw.save('result.xlsx')",
    checks: [{ file: "result.xlsx", sheet: "Sheet", cell: "A1", equals: "Cedar" }] })).details;
  assert.equal(result.status, "SUCCEEDED", JSON.stringify(result));
  const markdown = result.artifacts.find(a => a.file.endsWith("answer.md"));
  assert.equal(await readFile(markdown.gateway_path, "utf8"), "Cedar NAS evidence");
  assert.equal((await tool("read").execute("read", { job_id: result.job_id, artifact_id: markdown.artifact_id })).details.text, "Cedar NAS evidence");
  const xlsx = result.artifacts.find(a => a.file.endsWith("result.xlsx"));
  const reference = (await tool("files").execute("get", { action: "artifact_path", job_id: result.job_id, artifact_id: xlsx.artifact_id })).details;
  assert.equal(reference.gateway_path, xlsx.gateway_path);
  assert.equal((await readFile(reference.gateway_path)).subarray(0,2).toString(), "PK");
  // This is local fetch proof, NOT QQ delivery. Simulated channel receipt is explicitly labelled below.
  const simulateSend = async media => { assert.equal((await readFile(media)).length, reference.bytes); return { simulated: true, messageId: "mock-1" }; };
  assert.equal((await simulateSend(reference.gateway_path)).simulated, true);
  const identity = trustedIdentity(config, context);
  assert.equal((await managementRequest(config, identity, "lease_path", { path: markdown.workspace_relative_path, token: "read-call" })).status, "LEASED");
  assert.equal((await managementRequest(config, identity, "finish_access", { path: markdown.workspace_relative_path, token: "read-call", success: true })).status, "TOUCHED");
  const saved = (await tool("files").execute("save", { action: "save", job_id: result.job_id, artifact_id: markdown.artifact_id })).details;
  await tool("files").execute("clean", { action: "delete_cache", job_id: result.job_id });
  assert.equal((await tool("files").execute("saved", { action: "saved_read", saved_id: saved.saved_id })).details.text, "Cedar NAS evidence");
  const fake = new Registry();
  await fake.received(config, { ...event, media: [{ path: "notes.txt", workspaceDir: path.dirname(workspace) }] },
    { channelId: "qqbot", accountId: "default", senderId: "sender", sessionKey: context.sessionKey }, { lookupSucceeded: true, sessionId: context.sessionId });
  assert.equal(fake.sessions.size, 0);
  assert.ok(calls.includes("python"));
});
