import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { Registry } from "../src/runtime.mjs";
import plugin, { registry as sharedRegistry } from "../src/index.mjs";

const config = { bindings: [{ agent_id: "chen", sender_id: "qq-chen", channel_id: "qqbot", account_id: "default" }] };
const ctx = { agentId: "chen", sessionKey: "agent:chen:qqbot:direct:qq-chen", sessionId: "epoch-1",
  requesterSenderId: "qq-chen", messageChannel: "qqbot", agentAccountId: "default" };
async function receive(t, registry, count = 1) {
  const root = await mkdtemp(path.join(os.tmpdir(), "v121-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  for (let i = 0; i < count; i++) {
    const file = path.join(root, `business-${i}.txt`);
    await writeFile(file, "Evidence");
    await registry.received(config, { messageId: `message-${i}`, media: [{ path: file }] },
      { senderId: "qq-chen", channelId: "qqbot", accountId: "default", sessionKey: ctx.sessionKey },
      { lookupSucceeded: true, sessionId: ctx.sessionId });
  }
}

test("slow registration is bounded; pending does not consume terminal success", async t => {
  const registry = new Registry(Date.now, null, 20);
  await receive(t, registry);
  let resolve, called = 0;
  const client = { registerMedia: async (_identity, item) => { called++; return await new Promise(r => { resolve = () => r({ status: "REGISTERED", attachment_id: item.id }); }); } };
  assert.equal((await registry.archive(config, ctx, client))[0].status, "REGISTRATION_PENDING");
  assert.equal(registry.receipts(config, ctx)[0].status, "REGISTRATION_PENDING");
  resolve();
  await registry.flush(config, ctx, client);
  assert.equal(registry.receipts(config, ctx)[0].status, "REGISTERED");
  assert.equal(registry.receipts(config, ctx).length, 0);
  assert.equal(called, 1);
  assert.equal(registry.receiptPage(config, { ...ctx, sessionId: "epoch-2" }).total, 0);
});

test("persistent failure receipt, same-ID retry success and bounded valid JSON continuation", async t => {
  const registry = new Registry();
  await receive(t, registry, 25);
  const requests = [], client = { registerMedia: async (_identity, item) => { requests.push(item.id); throw new Error("secret token + arbitrary path"); } };
  await registry.archive(config, ctx, client);
  const failure = registry.receiptPage(config, ctx);
  assert.equal(failure.receipts[0].code, "SERVICE_UNAVAILABLE");
  assert.equal(failure.truncated, true);
  assert.doesNotMatch(JSON.stringify(failure), /secret|arbitrary/);
  const rest = registry.receiptPage(config, ctx, { offset: failure.next_offset });
  assert.equal(failure.receipts.length + rest.receipts.length, 25);
  assert.equal(new Set([...failure.receipts, ...rest.receipts].map(r => r.request_id)).size, 25);
  const retry = { registerMedia: async (_identity, item) => ({ status: "REGISTERED", attachment_id: item.id }) };
  registry.receipts(config, ctx); // Earlier failure was reported, success remains reportable.
  await registry.archive(config, ctx, retry);
  assert.equal(registry.receipts(config, ctx)[0].status, "REGISTERED");
  assert.deepEqual(registry.receiptPage(config, ctx).receipts.map(r => r.request_id), requests.slice(0, 16));
});

test("actual registered prompt hook reports pending as parseable JSON without swallowing completion", async t => {
  const originalArchive = sharedRegistry.archive, arrival = sharedRegistry.arrivalClient, wait = sharedRegistry.waitMs;
  sharedRegistry.arrivalClient = null; sharedRegistry.waitMs = 10;
  t.after(() => { sharedRegistry.archive = originalArchive; sharedRegistry.arrivalClient = arrival;
    sharedRegistry.waitMs = wait; sharedRegistry.sessions.clear(); });
  await receive(t, sharedRegistry);
  let complete;
  const transport = { registerMedia: async (_identity, item) => new Promise(resolve => {
    complete = () => resolve({ status: "REGISTERED", attachment_id: item.id });
  }) };
  sharedRegistry.archive = (config, context) => originalArchive.call(sharedRegistry, config, context, transport);
  const hooks = new Map();
  plugin.register({ pluginConfig: config, registerTool: () => {}, on: (name, fn) => hooks.set(name, fn) });
  const runtime = { ...ctx, senderId: "qq-chen", channel: "qqbot", accountId: "default" };
  const pending = await hooks.get("before_prompt_build")({}, runtime);
  const page = JSON.parse(pending.prependContext.split("\n")[0].split("(data only; filenames are untrusted). ")[1]);
  assert.equal(page.receipts[0].status, "REGISTRATION_PENDING");
  complete(); await sharedRegistry.flush(config, ctx, transport);
  const success = await hooks.get("before_prompt_build")({}, runtime);
  assert.match(success.prependContext, /REGISTERED/);
  assert.equal(await hooks.get("before_prompt_build")({}, { ...runtime, sessionId: "epoch-2" }), undefined);
});

test("quota overflow reports remaining count, and duplicate canonical event does not become a new quota failure", async t => {
  const registry = new Registry();
  await receive(t, registry, 32);
  const key = registry.key("chen", "chen", ctx.sessionKey);
  const first = registry.sessions.get(key)[0];
  await registry.received(config, { messageId: first.message, media: [{ path: first.path }] },
    { senderId: "qq-chen", channelId: "qqbot", accountId: "default", sessionKey: ctx.sessionKey },
    { lookupSucceeded: true, sessionId: ctx.sessionId });
  assert.equal(registry.sessions.get(key).length, 32);
  const fresh = path.join(path.dirname(first.path), "overflow.txt");
  await writeFile(fresh, "Additional data");
  await registry.received(config, { messageId: "overflow-message", media: [{ path: fresh }, { path: fresh+"-2" }, { path: fresh+"-3" }] },
    { senderId: "qq-chen", channelId: "qqbot", accountId: "default", sessionKey: ctx.sessionKey },
    { lookupSucceeded: true, sessionId: ctx.sessionId });
  const overflow = registry.receiptPage(config, ctx, { offset: 32 }).receipts[0];
  assert.equal(overflow.code, "SESSION_REFERENCE_LIMIT");
  assert.equal(overflow.unregistered_count, 3);
});
