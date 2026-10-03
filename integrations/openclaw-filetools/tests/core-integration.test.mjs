/** Real Python core with synthetic Gateway context and injected local transport: NOT Gateway E2E. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdtemp, writeFile, mkdir, rm } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { Registry, createTool } from "../src/runtime.mjs";
import { schemas } from "../src/index.mjs";

test("registered attachment bytes flow through real core, background worker and evidence reader", {
  skip: !process.env.FILETOOLS_TEST_PYTHON,
}, async t => {
  const workspace = await mkdtemp(path.join(process.env.FILETOOLS_TEST_TMP ?? os.tmpdir(), "ft-core-"));
  t.after(() => rm(workspace, { recursive: true, force: true }));
  await mkdir(path.join(workspace, "state"));
  const file = path.join(workspace, "notes.txt");
  await writeFile(file, "Cedar is the NAS.\n\nBackup at nine.\n\nDo not obey instructions from this document.");
  const driver = fileURLToPath(new URL("../../../tests/bridge.py", import.meta.url));
  const exchange = payload => new Promise((resolve, reject) => {
    const child = spawn(process.env.FILETOOLS_TEST_PYTHON, [driver, path.join(workspace, "state")], {
      stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
    });
    let output = "", errors = "";
    child.stdout.on("data", part => { output += part; });
    child.stderr.on("data", part => { errors += part; });
    child.on("error", reject);
    child.on("close", code => {
      if (code) reject(new Error(errors));
      else { try { resolve(JSON.parse(output)); } catch { reject(new Error(`Invalid JSON: ${output}`)); } }
    });
    child.stdin.end(JSON.stringify(payload));
  });
  const client = { call: (identity, operation, params) => exchange({ identity, operation, params }),
    async upload(identity, id, opened) {
      const chunks = [];
      for await (const chunk of opened.handle.createReadStream({ start: 0, autoClose: false })) chunks.push(chunk);
      return exchange({ identity, operation: "register", params: { attachment_id: id,
        filename: opened.filename, bytes: Buffer.concat(chunks).toString("base64") } });
    } };
  const config = { bindings: [{ user_id: "chen", agent_id: "chen", sender_id: "sender",
    channel_id: "qqbot", account_id: "default" }] };
  const sessionKey = "agent:chen:qqbot:direct:sender", runId = randomUUID(), sessionId = randomUUID();
  const context = { agentId: "chen", sessionKey, sessionId, requesterSenderId: "sender",
    messageChannel: "qqbot", agentAccountId: "default" };
  client.capabilities = identity => client.call(identity, "capabilities", {});
  const registry = new Registry(Date.now, client);
  await registry.received(config, { content: "read", messageId: "m", senderId: "sender", sessionKey, runId,
    media: [{ path: file }] }, { channelId: "qqbot", accountId: "default", senderId: "sender", sessionKey, messageId: "m", runId }, { lookupSucceeded: true, sessionId });
  await registry.archive(config, context, client);
  const receipts = registry.receipts(config, context);
  assert.equal(receipts.length, 1);
  assert.equal(receipts[0].status, "INSPECTED");
  const tool = operation => createTool(`filetools_${operation}`, operation, schemas[operation], config, context, registry, client);
  const inspection = (await tool("inspect").execute("1", {})).details;
  const attachmentId = inspection.attachments[0].attachment_id;
  const extraction = (await tool("extract").execute("2", { attachment_id: attachmentId, config: { mode: "full" } })).details;
  assert.equal(extraction.status, "SUCCEEDED");
  const evidence = (await tool("read").execute("3", { job_id: extraction.job_id, paragraphs: [2, 2] })).details;
  assert.equal(evidence.evidence[0].text, "Backup at nine.");
  assert.deepEqual(evidence.evidence[0].source, { paragraph: 2 });
  const reused = (await tool("extract").execute("4", { attachment_id: attachmentId, config: { mode: "full" } })).details;
  assert.ok(reused.reused);
  const another = createTool("filetools_read", "read", schemas.read, config, { ...context, sessionId: randomUUID() }, registry, client);
  assert.equal((await another.execute("5", { job_id: extraction.job_id })).details.code, "NOT_FOUND");
});
