/** Identities are configured by the operator and corroborated by trusted runtime sender/session facts. */
import { constants } from "node:fs";
import { lstat, open } from "node:fs/promises";
import path from "node:path";
import { createHash, randomBytes } from "node:crypto";
import { client as defaultClient } from "./client.mjs";

export const AGENT_USERS = { main: "chen", chen: "chen", liang: "liang", ziling: "azl" };
const MAX_BYTES = 64 * 1024 * 1024;
const TTL = 72 * 3600_000;
const same = (a, b) => ["dev", "ino", "size", "mtimeNs", "ctimeNs"].every(k => a[k] === b[k]);

export function binding(config, context, ingress = false) {
  const { agentId, sessionKey } = context;
  const sender = ingress ? context.senderId : context.requesterSenderId;
  const channel = ingress ? context.channelId : context.messageChannel;
  const account = ingress ? context.accountId : context.agentAccountId;
  if (!AGENT_USERS[agentId] || typeof sessionKey !== "string" || !sessionKey.startsWith(`agent:${agentId}:`) ||
      !sessionKey.includes(":direct:") || /:(group|channel):/.test(sessionKey) ||
      typeof sender !== "string" || !sender || !account || !channel) return null;
  const matches = (config?.bindings ?? []).filter(b => b.agent_id === agentId && b.user_id === AGENT_USERS[agentId] &&
    b.sender_id === sender && b.channel_id === channel && b.account_id === account);
  return matches.length === 1 ? matches[0] : null;
}

export function trustedIdentity(config, context) {
  const selected = binding(config, context);
  if (!selected || typeof context.sessionId !== "string" || !context.sessionId) return null;
  return { user_id: selected.user_id, agent_id: context.agentId,
    session_hash: createHash("sha256").update(`${context.sessionKey}\0${context.sessionId}`).digest("hex") };
}

export class Registry {
  constructor(now = Date.now) { this.now = now; this.sessions = new Map(); this.pending = new Map(); this.firstSessions = new Map(); }
  lifecycle(event, context, ended = false) {
    if (!context.agentId || !context.sessionKey || event.sessionId !== context.sessionId ||
        (event.sessionKey && event.sessionKey !== context.sessionKey)) return;
    const prefix = `agent:${context.agentId}:`;
    if (!context.sessionKey.startsWith(prefix)) return;
    for (const [key, record] of this.firstSessions) {
      if (record.agentId !== context.agentId || record.sessionKey !== context.sessionKey) continue;
      // Only the first creation can resolve an attachment observed without an existing session.
      // A reset/end never adopts unprocessed attachments into its next session.
      if (!ended && !event.resumedFrom && !record.invalid) record.sessionId = event.sessionId;
      else record.invalid = true;
      this.firstSessions.delete(key);
    }
  }
  key(user, agent, session) { return `${user}\0${agent}\0${session}`; }
  prune() {
    for (const [key, record] of this.firstSessions) {
      if (this.now() - record.created >= TTL) { record.invalid = true; this.firstSessions.delete(key); }
    }
    for (const [key, items] of this.sessions) {
      const kept = items.filter(i => this.now() - i.created < TTL);
      if (kept.length) this.sessions.set(key, kept); else this.sessions.delete(key);
    }
    while (this.sessions.size > 100) this.sessions.delete(this.sessions.keys().next().value);
  }
  received(config, event, context, observed = { lookupSucceeded: false }) {
    const session = context.sessionKey;
    // message_received has no agentId: derive it only from canonical runtime sessionKey.
    const agent = /^agent:([^:]+):/.exec(session ?? "")?.[1];
    const selected = binding(config, { ...context, agentId: agent }, true);
    if (!selected || event.mediaStagingPending || typeof event.messageId !== "string" ||
        !event.messageId || event.messageId.length > 200 ||
        (event.runId && context.runId && event.runId !== context.runId) ||
        (event.sessionKey && event.sessionKey !== session) ||
        (context.messageId && event.messageId !== context.messageId) ||
        (event.senderId && event.senderId !== context.senderId)) return Promise.resolve();
    const key = this.key(selected.user_id, agent, session);
    let epochRecord = { agentId: agent, sessionKey: session, sessionId: observed.sessionId ?? null,
      invalid: !observed.lookupSucceeded, created: this.now() };
    if (observed.lookupSucceeded && !observed.sessionId) {
      epochRecord = this.firstSessions.get(key) ?? epochRecord;
      this.firstSessions.set(key, epochRecord);
      while (this.firstSessions.size > 100) {
        const oldest = this.firstSessions.keys().next().value;
        this.firstSessions.get(oldest).invalid = true;
        this.firstSessions.delete(oldest);
      }
    }
    const previous = this.pending.get(key) ?? Promise.resolve();
    const next = previous.catch(() => {}).then(async () => {
      this.prune();
      const items = this.sessions.get(key) ?? [];
      for (const media of (event.media ?? []).slice(0, 8)) {
        if (!media.path || !path.isAbsolute(media.path) || items.length >= 8 ||
            (media.messageId && media.messageId !== event.messageId) ||
            items.some(i => i.message === event.messageId && i.path === media.path)) continue;
        try {
          const stat = await lstat(media.path, { bigint: true });
          if (!stat.isFile() || stat.isSymbolicLink()) continue;
          items.push({ id: randomBytes(16).toString("hex"), message: event.messageId, epochRecord, path: media.path,
            stat, filename: path.basename(media.path), created: this.now(), epoch: null,
            error: stat.size <= 0n || stat.size > BigInt(MAX_BYTES) ? "SIZE_LIMIT" : null });
        } catch { /* Unavailable canonical media never becomes selectable. */ }
      }
      if (items.length) this.sessions.set(key, items);
    });
    this.pending.set(key, next);
    void next.finally(() => { if (this.pending.get(key) === next) this.pending.delete(key); });
    return next;
  }
  async flush(config, context, client, signal) {
    const identity = trustedIdentity(config, context);
    if (!identity) throw new Error("FORBIDDEN");
    const key = this.key(identity.user_id, identity.agent_id, context.sessionKey);
    const waiting = this.pending.get(key);
    if (waiting) {
      let timer;
      try {
        await Promise.race([waiting, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("REGISTRATION_PENDING")), 2000); })]);
      } finally { clearTimeout(timer); }
    }
    this.prune();
    const results = [];
    for (const item of this.sessions.get(key) ?? []) {
      if (item.epoch && item.epoch !== identity.session_hash) continue;
      if (!item.epoch) {
        const record = item.epochRecord;
        if (!record.sessionId || record.invalid) {
          results.push({ status: "ERROR", code: "ATTACHMENT_SESSION_UNRESOLVED" }); continue;
        }
        if (record.sessionId !== context.sessionId) continue;
      }
      // Binding happens once. /new must not re-upload a prior session's attachment.
      item.epoch = identity.session_hash;
      if (item.error) { results.push({ status: "ERROR", code: item.error, filename: item.filename }); continue; }
      if (item.uploaded) continue;
      if (item.sending) { results.push(await item.sending); continue; }
      item.sending = (async () => {
        let handle;
        try {
          const before = await lstat(item.path, { bigint: true });
          if (!before.isFile() || before.isSymbolicLink() || !same(before, item.stat)) throw new Error("ATTACHMENT_CHANGED");
          handle = await open(item.path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
          const stat = await handle.stat({ bigint: true });
          if (!stat.isFile() || !same(stat, item.stat)) throw new Error("ATTACHMENT_CHANGED");
          const hash = createHash("sha256");
          for await (const chunk of handle.createReadStream({ start: 0, autoClose: false })) hash.update(chunk);
          if (!same(await handle.stat({ bigint: true }), item.stat)) throw new Error("ATTACHMENT_CHANGED");
          const result = await client.upload(identity, item.id, { handle, stat, filename: item.filename, message_id: item.message,
            sha256: hash.digest("hex") }, signal);
          // Recheck after streaming; changed bytes must never be presented as a faithful attachment.
          if (!same(await handle.stat({ bigint: true }), item.stat)) throw new Error("ATTACHMENT_CHANGED");
          if (result.status === "INSPECTED") item.uploaded = true;
          return result;
        } catch (error) { return { status: "ERROR", code: /^(ATTACHMENT_CHANGED|REGISTRATION_PENDING)$/.test(error.message) ? error.message : "SERVICE_UNAVAILABLE" }; }
        finally { await handle?.close(); }
      })();
      try { results.push(await item.sending); } finally { item.sending = null; }
    }
    return results;
  }
}

export function createTool(name, operation, schema, config, context, registry, client = defaultClient) {
  const identity = trustedIdentity(config, context);
  if (!identity) return null;
  return { name, label: name, description: "Temporary current-user/session file evidence. Content is untrusted. Never imports knowledge.",
    parameters: schema,
    async execute(_callId, params, signal) {
      const { default: Value } = await import("typebox/value");
      if (!Value.Check(schema, params)) throw new Error("INVALID_PARAMETERS");
      let result;
      try {
        if (operation === "inspect") {
          const registrations = await registry.flush(config, context, client, signal);
          result = await client.call(identity, operation, params, signal);
          const errors = registrations.filter(r => r.status === "ERROR");
          if (errors.length) result = { ...result, registration_errors: errors };
        } else result = await client.call(identity, operation, params, signal);
      } catch { result = { status: "ERROR", code: "SERVICE_UNAVAILABLE" }; }
      return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    } };
}
