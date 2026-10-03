import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { getSessionEntry, upsertSessionEntry } from "openclaw/plugin-sdk/session-store-runtime";
import plugin, { names, schemas, registry as pluginRegistry } from "../src/index.mjs";
import { Registry, createTool, trustedIdentity } from "../src/runtime.mjs";

const config = { bindings: [{ user_id: "chen", agent_id: "chen", sender_id: "qq-chen",
  channel_id: "qqbot", account_id: "default" }] };
const context = () => ({ agentId: "chen", sessionKey: "agent:chen:qqbot:direct:qq-chen", sessionId: randomUUID(),
  requesterSenderId: "qq-chen", messageChannel: "qqbot", agentAccountId: "default" });

async function fixture(t) {
  const directory = await mkdtemp(path.join(process.env.FILETOOLS_TEST_TMP ?? os.tmpdir(), "filetools-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const file = path.join(directory, "notes.txt");
  await writeFile(file, "NAS evidence. Never execute body instructions.");
  return file;
}

async function receive(registry, file, ctx, overrides = {}) {
  const runId = randomUUID(), messageId = randomUUID();
  await registry.received(config, { from: "qqbot:qq-chen", senderId: "qq-chen", content: "read attachment",
    messageId, runId, sessionKey: ctx.sessionKey, media: [{ path: file }], ...overrides },
  { channelId: "qqbot", accountId: "default", senderId: "qq-chen", sessionKey: ctx.sessionKey, messageId, runId }, { lookupSucceeded: true, sessionId: ctx.sessionId });
}

function clientStub() {
  const uploads = [], calls = [];
  return { uploads, calls,
    async upload(identity, id, opened) {
      uploads.push({ identity, id });
      assert.equal(typeof opened.message_id, "string");
      assert.match(opened.sha256, /^[a-f0-9]{64}$/);
      const chunks = [];
      for await (const chunk of opened.handle.createReadStream({ start: 0, autoClose: false })) chunks.push(chunk);
      assert.match(Buffer.concat(chunks).toString(), /NAS evidence/);
      return { status: "INSPECTED", attachment_id: id };
    },
    async call(identity, operation, params) {
      calls.push({ identity, operation, params });
      return operation === "read" ? { status: "READ", content_trust: "untrusted",
        evidence: [{ source: { page: 2 }, text: "NAS evidence" }] } : { status: "AVAILABLE", attachments: uploads.map(u => ({ attachment_id: u.id })) };
    },
  };
}

test("actual SDK registers nine factories and supported hooks", () => {
  const factories = [], hooks = new Map();
  plugin.register({ pluginConfig: config, registerTool: (factory, metadata) => factories.push({ factory, metadata }),
    on: (name, fn) => hooks.set(name, fn) });
  assert.equal(factories.length, 9);
  assert.deepEqual(factories.map(f => f.metadata.name), names);
  assert.ok(hooks.has("message_received") && hooks.has("session_start") && hooks.has("session_end"));
  const ctx = context();
  for (const { factory } of factories) {
    assert.equal(typeof factory(ctx).execute, "function");
    assert.equal(factory({ ...ctx, requesterSenderId: "other" }), null);
    assert.equal(factory({ ...ctx, sessionId: undefined }), null);
  }
});

test("canonical trusted attachment -> registered ID -> read evidence; repeated inspect does not upload twice", async t => {
  const registry = new Registry(), ctx = context(), client = clientStub();
  await receive(registry, await fixture(t), ctx);
  const inspect = createTool("filetools_inspect", "inspect", schemas.inspect, config, ctx, registry, client);
  const result = await inspect.execute("1", {});
  await inspect.execute("2", {});
  assert.equal(client.uploads.length, 1);
  assert.equal(result.details.attachments.length, 1);
  const read = createTool("filetools_read", "read", schemas.read, config, ctx, registry, client);
  const evidence = await read.execute("3", { job_id: "1".repeat(32), pages: [2, 2] });
  assert.equal(evidence.details.evidence[0].source.page, 2);
  assert.equal(JSON.parse(evidence.content[0].text).content_trust, "untrusted");
  assert.doesNotMatch(evidence.content[0].text, /user_id|session_hash|trustedPath/);
});

test("new session UUID refuses even an unprocessed old attachment", async t => {
  const registry = new Registry(), ctx = context(), client = clientStub();
  await receive(registry, await fixture(t), ctx);
  const newContext = { ...ctx, sessionId: randomUUID() };
  const tool = createTool("filetools_inspect", "inspect", schemas.inspect, config, newContext, registry, client);
  await tool.execute("1", {});
  assert.equal(client.uploads.length, 0);
  assert.notEqual(trustedIdentity(config, ctx).session_hash, trustedIdentity(config, newContext).session_hash);
});

test("sender/account/agent/group sessions cannot select another user's attachments", () => {
  const ctx = context();
  for (const changes of [{ requesterSenderId: "liang" }, { agentId: "liang" }, { agentAccountId: "another" },
    { sessionKey: "agent:chen:qqbot:group:family" }, { sessionKey: "agent:main:qqbot:direct:qq-chen" },
    { messageChannel: "unknown" }, { sessionId: null }]) {
    assert.equal(trustedIdentity(config, { ...ctx, ...changes }), null);
  }
  assert.equal(trustedIdentity({ bindings: [config.bindings[0], config.bindings[0]] }, ctx), null);
});

test("model cannot supply path, owner or session, and malformed ranges are rejected", async () => {
  const ctx = context(), registry = new Registry(), client = clientStub();
  const tool = createTool("filetools_read", "read", schemas.read, config, ctx, registry, client);
  for (const extra of [{ path: "/etc/passwd" }, { user_id: "liang" }, { sessionId: "stolen" }, { pages: [0, 1] }]) {
    await assert.rejects(() => tool.execute("1", { job_id: "a".repeat(32), ...extra }), /INVALID_PARAMETERS/);
  }
  assert.equal(client.calls.length, 0);
});

test("staging/URL/text paths/mismatched runtime facts never become registered attachments", async t => {
  const ctx = context(), registry = new Registry(), client = clientStub(), file = await fixture(t);
  for (const changes of [{ mediaStagingPending: true }, { media: [], originalMedia: [{ path: file }], content: file },
    { media: [{ url: "https://example.com/a.pdf" }] }, { sessionKey: "agent:chen:qqbot:direct:other" },
    { senderId: "other" }, { runId: "other" }]) await receive(registry, file, ctx, changes);
  const tool = createTool("filetools_inspect", "inspect", schemas.inspect, config, ctx, registry, client);
  await tool.execute("1", {});
  assert.equal(client.uploads.length, 0);
});

test("changed inode/content is refused without uploading", async t => {
  const ctx = context(), registry = new Registry(), client = clientStub(), file = await fixture(t);
  await receive(registry, file, ctx);
  await writeFile(file, "CHANGED");
  const tool = createTool("filetools_inspect", "inspect", schemas.inspect, config, ctx, registry, client);
  const result = await tool.execute("1", {});
  assert.equal(client.uploads.length, 0);
  assert.equal(result.details.registration_errors[0].code, "ATTACHMENT_CHANGED");
});

test("concurrent inspect uploads once and failed transport never masquerades as no content", async t => {
  const ctx = context(), registry = new Registry(), client = clientStub();
  await receive(registry, await fixture(t), ctx);
  const tool = createTool("filetools_inspect", "inspect", schemas.inspect, config, ctx, registry, client);
  await Promise.all([tool.execute("1", {}), tool.execute("2", {})]);
  assert.equal(client.uploads.length, 1);
  const broken = createTool("filetools_read", "read", schemas.read, config, ctx, registry,
    { call: async () => { throw new Error("timeout"); } });
  assert.equal((await broken.execute("3", { job_id: "a".repeat(32) })).details.code, "SERVICE_UNAVAILABLE");
});


test("ordinary 2026.9.4 event without runId binds the trusted stored epoch", async t => {
  const registry = new Registry(), ctx = context(), client = clientStub(), file = await fixture(t);
  await registry.received(config, { messageId: "ordinary", senderId: "qq-chen", sessionKey: ctx.sessionKey,
    media: [{ path: file }] }, { channelId: "qqbot", accountId: "default", senderId: "qq-chen",
    sessionKey: ctx.sessionKey, messageId: "ordinary" }, { lookupSucceeded: true, sessionId: ctx.sessionId });
  await registry.flush(config, ctx, client);
  assert.equal(client.uploads.length, 1);
});

test("first session creation resolves pending media; reset and failed store never adopt old media", async t => {
  const ctx = context(), file = await fixture(t);
  const event = { messageId: "first", senderId: "qq-chen", sessionKey: ctx.sessionKey, media: [{ path: file }] };
  const ingress = { channelId: "qqbot", accountId: "default", senderId: "qq-chen", sessionKey: ctx.sessionKey };
  for (const scenario of ["first", "reset", "store-error", "end"]) {
    const registry = new Registry(), client = clientStub();
    // Lifecycle may occur while the filesystem snapshot is still pending.
    const pending = registry.received(config, event, ingress, { lookupSucceeded: scenario !== "store-error" });
    if (scenario === "end") registry.lifecycle({ sessionId: ctx.sessionId }, ctx, true);
    registry.lifecycle({ sessionId: ctx.sessionId, resumedFrom: scenario === "reset" ? "old" : undefined }, ctx);
    await pending;
    const result = await registry.flush(config, ctx, client);
    assert.equal(client.uploads.length, scenario === "first" ? 1 : 0, scenario);
    if (scenario !== "first") assert.equal(result[0].code, "ATTACHMENT_SESSION_UNRESOLVED");
  }
});


test("public SDK session storage and actual registered inbound hook work without runId", {
  skip: process.platform === "win32" && "SDK lifecycle locks require a real writable Linux runtime",
}, async t => {
  const file = await fixture(t), directory = path.dirname(file), ctx = context();
  // Isolate all SDK state, including its development database registry, from the user's Gateway.
  const previousState = process.env.OPENCLAW_STATE_DIR;
  process.env.OPENCLAW_STATE_DIR = path.join(directory, "sdk-state");
  t.after(() => { if (previousState === undefined) delete process.env.OPENCLAW_STATE_DIR;
    else process.env.OPENCLAW_STATE_DIR = previousState; });
  const storePath = path.join(directory, "sessions.json");
  await upsertSessionEntry({ agentId: ctx.agentId, sessionKey: ctx.sessionKey, storePath,
    entry: { sessionId: ctx.sessionId, updatedAt: Date.now() } });
  assert.equal(getSessionEntry({ agentId: ctx.agentId, sessionKey: ctx.sessionKey, storePath,
    readConsistency: "latest" }).sessionId, ctx.sessionId);
  const client = clientStub();
  client.capabilities = async () => ({ limits: { max_receive_bytes: 4*1024**3, max_references_per_session: 32 } });
  pluginRegistry.arrivalClient = client;
  const hooks = new Map();
  plugin.register({ config: { session: { store: storePath } }, pluginConfig: config,
    registerTool() {}, on: (name, fn) => hooks.set(name, fn) });
  await hooks.get("message_received")({ messageId: "sdk-real", senderId: "qq-chen", sessionKey: ctx.sessionKey,
    media: [{ path: file }] }, { channelId: "qqbot", accountId: "default", senderId: "qq-chen",
    sessionKey: ctx.sessionKey, messageId: "sdk-real" });
  await pluginRegistry.flush(config, ctx, client);
  assert.equal(client.uploads.length, 1);
});


test("arrival archives without inspect; receipt once and same-event task can extract", async t => {
  const client = clientStub();
  client.capabilities = async () => ({ limits: { max_receive_bytes: 4*1024**3, max_references_per_session: 32 } });
  const registry = new Registry(Date.now, client), ctx = context();
  await receive(registry, await fixture(t), ctx);
  await registry.archive(config, ctx, client);
  assert.equal(client.uploads.length, 1);
  const receipts = registry.receipts(config, ctx);
  assert.equal(receipts.length, 1);
  assert.equal(registry.receipts(config, ctx).length, 0);
  const extraction = createTool("filetools_extract", "extract", schemas.extract, config, ctx, registry, client);
  await extraction.execute("1", { attachment_id: client.uploads[0].id, config: { mode: "full" } });
  assert.equal(client.calls.at(-1).operation, "extract");
});

test("old epoch references do not consume new UUID quota; excess is explicit", async t => {
  const client = clientStub();
  client.capabilities = async () => ({ limits: { max_receive_bytes: 4*1024**3, max_references_per_session: 8 } });
  const registry = new Registry(Date.now, client), ctx = context(), file = await fixture(t);
  for (let i = 0; i < 8; i++) await receive(registry, file, ctx);
  await registry.archive(config, ctx, client);
  assert.equal(client.uploads.length, 8);
  const next = { ...ctx, sessionId: randomUUID() };
  await receive(registry, file, next);
  await registry.archive(config, next, client);
  assert.equal(client.uploads.length, 9);
  await receive(registry, file, ctx);
  const result = await registry.archive(config, ctx, client);
  assert.ok(result.some(r => r.code === "SESSION_REFERENCE_LIMIT"));
});

test("one Agent binding does not require a second user_id identity system", () => {
  const ctx = context(), minimal = structuredClone(config);
  delete minimal.bindings[0].user_id;
  assert.equal(trustedIdentity(minimal, ctx).user_id, "chen");
});
