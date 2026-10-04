/** Identities are configured by the operator and corroborated by trusted runtime sender/session facts. */
import { constants } from "node:fs";
import { lstat, open } from "node:fs/promises";
import path from "node:path";
import { createHash, randomBytes } from "node:crypto";
import { client as defaultClient } from "./client.mjs";
import { configuredClient } from "./management.mjs";

export const AGENT_USERS = { main: "chen", chen: "chen", liang: "liang", ziling: "azl" };

const TTL = 72 * 3600_000;
const same = (a, b) => ["dev", "ino", "size", "mtimeNs", "ctimeNs"].every(k => a[k] === b[k]);

export function binding(config, context, ingress = false) {
  const { agentId, sessionKey } = context;
  const sender = ingress ? context.senderId : context.requesterSenderId;
  const channel = ingress ? context.channelId : context.messageChannel;
  const account = ingress ? context.accountId : context.agentAccountId;
  if (typeof agentId !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(agentId) || typeof sessionKey !== "string" || !sessionKey.startsWith(`agent:${agentId}:`) ||
      !sessionKey.includes(":direct:") || /:(group|channel):/.test(sessionKey) ||
      typeof sender !== "string" || !sender || !account || !channel) return null;
  const matches = (config?.bindings ?? []).filter(b => b.agent_id === agentId && (b.user_id === undefined || b.user_id === (AGENT_USERS[agentId] ?? agentId)) &&
    b.sender_id === sender && b.channel_id === channel && b.account_id === account);
  return matches.length === 1 ? { ...matches[0], user_id: AGENT_USERS[agentId] ?? agentId } : null;
}

export function trustedIdentity(config, context) {
  const selected = binding(config, context);
  if (!selected || typeof context.sessionId !== "string" || !context.sessionId) return null;
  return { user_id: selected.user_id, agent_id: context.agentId,
    session_hash: createHash("sha256").update(`${context.sessionKey}\0${context.sessionId}`).digest("hex") };
}

export class Registry {
  constructor(now = Date.now, arrivalClient = null, waitMs = 5000) { this.now = now; this.arrivalClient = arrivalClient; this.waitMs = waitMs; this.sessions = new Map(); this.pending = new Map(); this.pendingEpochs = new Map(); this.firstSessions = new Map(); }
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
      if (record.sessionId && !record.invalid && this.arrivalClient) {
        void this.archive(record.config, { ...record.toolContext, sessionId: record.sessionId }, this.arrivalClient);
      }
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
      invalid: !observed.lookupSucceeded, created: this.now(), config,
      toolContext: { agentId: agent, sessionKey: session, requesterSenderId: context.senderId,
        messageChannel: context.channelId, agentAccountId: context.accountId } };
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
      const current = items.filter(i => !i.epochRecord.invalid && i.epochRecord.sessionId === epochRecord.sessionId);
      const limits = this.arrivalClient ? (await this.arrivalClient.capabilities({ ...epochRecord.toolContext,
        user_id: selected.user_id, agent_id: agent, session_hash: createHash("sha256").update(`${session}\0${epochRecord.sessionId}`).digest("hex") }).catch(() => ({}))).limits : null;
      for (const media of (event.media ?? [])) {
        if (current.length >= (limits?.max_references_per_session ?? 32)) {
          items.push({ error: "SESSION_REFERENCE_LIMIT", filename: path.basename(media.path ?? "attachment"),
            created: this.now(), epochRecord, id: randomBytes(16).toString("hex") });
          break;
        }
        let mediaPath = media.path;
        if (mediaPath && !path.isAbsolute(mediaPath)) {
          const workspace = config.workspaces?.[agent]?.workspace;
          if (!workspace || !media.workspaceDir || path.resolve(media.workspaceDir) !== path.resolve(workspace)) continue;
          mediaPath = path.resolve(workspace, mediaPath);
          if (path.relative(workspace, mediaPath).startsWith("..")) continue;
        }
        if (!mediaPath || !path.isAbsolute(mediaPath) ||
            (media.messageId && media.messageId !== event.messageId) ||
            items.some(i => i.message === event.messageId && i.path === mediaPath)) continue;
        try {
          const stat = await lstat(mediaPath, { bigint: true });
          if (!stat.isFile() || stat.isSymbolicLink()) continue;
          const item = { id: createHash("sha256").update(`${agent}\0${session}\0${epochRecord.sessionId}\0${event.messageId}\0${mediaPath}`).digest("hex").slice(0,32),
            message: event.messageId, channel: context.channelId, epochRecord, path: mediaPath,
            stat, filename: path.basename(mediaPath), created: this.now(), epoch: null,
            error: stat.size <= 0n || (limits && stat.size > BigInt(limits.max_receive_bytes)) ? "RECEIVE_SIZE_LIMIT" : null };
          items.push(item); current.push(item);
        } catch { /* Unavailable canonical media never becomes selectable. */ }
      }
      if (items.length) this.sessions.set(key, items);
    });
    this.pending.set(key, next);
    this.pendingEpochs.set(key, epochRecord);
    void next.finally(() => { if (this.pending.get(key) === next) { this.pending.delete(key); this.pendingEpochs.delete(key); } }).catch(() => {});
    if (epochRecord.sessionId && !epochRecord.invalid && this.arrivalClient) {
      void next.then(() => this.archive(config, { ...epochRecord.toolContext, sessionId: epochRecord.sessionId }, this.arrivalClient)).catch(() => {});
    }
    return next;
  }
  async archive(config, context, client) {
    let timer;
    try { return await Promise.race([this.flush(config, context, client), new Promise(resolve => {
      timer = setTimeout(() => resolve([{ status: "REGISTRATION_PENDING" }]), this.waitMs);
    })]); }
    catch { return [{ status: "ERROR", code: "REGISTRATION_PENDING" }]; }
    finally { clearTimeout(timer); }
  }
  receipts(config, context) {
    return this.receiptPage(config, context, { consume: true }).receipts;
  }
  receiptPage(config, context, { offset = 0, consume = false } = {}) {
    const identity = trustedIdentity(config, context);
    if (!identity) return { status: "ERROR", code: "FORBIDDEN", receipts: [] };
    const key = this.key(identity.user_id, identity.agent_id, context.sessionKey);
    const items = (this.sessions.get(key) ?? []).filter(i => !i.epochRecord.invalid &&
      i.epochRecord.sessionId === context.sessionId);
    const receipts = [];
    let cursor = offset, chars = 0;
    for (; cursor < items.length; cursor++) {
      const item = items[cursor];
      const raw = item.sending ? { status: "REGISTRATION_PENDING" } : item.receipt ??
        (item.error ? { status: "ERROR", code: item.error } : { status: "REGISTRATION_PENDING" });
      const receipt = { status: raw.status, request_id: item.id, filename: item.filename?.slice(0, 200) };
      for (const key of ["attachment_id", "file_id", "bytes", "reused", "mode"]) if (raw[key] !== undefined) receipt[key] = raw[key];
      if (raw.code) {
        receipt.code = /^[A-Z][A-Z0-9_]{0,79}$/.test(raw.code) ? raw.code : "SERVICE_UNAVAILABLE";
        receipt.recovery = ["SERVICE_UNAVAILABLE", "MANAGEMENT_UNAVAILABLE", "MANAGEMENT_INVALID_RESPONSE", "REGISTRY_BUSY", "REGISTRATION_INTERRUPTED"].includes(receipt.code) ? "Check management/worker service, then inspect again to retry the same request ID. Do not re-upload." :
          "Check source version, size limit and trusted session; changed originals need a new registration.";
      }
      const signature = JSON.stringify(receipt);
      if (consume && item.reported === signature) continue;
      if (receipts.length >= 16 || chars + signature.length > 6500) break;
      receipts.push(receipt); chars += signature.length;
      // Pending is an observation, never a consumed terminal receipt.
      if (consume && receipt.status !== "REGISTRATION_PENDING") item.reported = signature;
    }
    const pendingEpoch = this.pendingEpochs.get(key);
    if (!items.length && this.pending.has(key) && pendingEpoch?.sessionId === context.sessionId && !pendingEpoch.invalid) receipts.push({ status: "REGISTRATION_PENDING" });
    return { status: "REGISTRATION_RECEIPTS", receipts, total: items.length, offset,
      next_offset: cursor < items.length ? cursor : null, truncated: cursor < items.length,
      continuation: "filetools_inspect({registration_only:true,receipt_offset:next_offset}); completion appears on next Agent run or inspect, without proactive push" };
  }
  async flush(config, context, client, signal) {
    client = configuredClient(config, client);
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
          if (client.registerMedia) {
            const result = await client.registerMedia(identity, item, signal);
            item.receipt = result;
            if (result.status === "REGISTERED") item.uploaded = true;
            return result;
          }
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
          item.receipt = result;
          if (result.status === "INSPECTED") item.uploaded = true;
          return result;
        } catch (error) {
          item.receipt = { status: "ERROR", code: /^(ATTACHMENT_CHANGED|REGISTRATION_PENDING)$/.test(error.message) ? error.message : "SERVICE_UNAVAILABLE" };
          if (error.message === "ATTACHMENT_CHANGED") item.error = error.message;
          return item.receipt;
        }
        finally { await handle?.close(); }
      })();
      try { results.push(await item.sending); } finally { item.sending = null; }
    }
    return results;
  }
}

export function createTool(name, operation, schema, config, context, registry, client = defaultClient) {
  client = configuredClient(config, client);
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
          // Poll receipts without restarting a failed attempt; ordinary inspect retries idempotently.
          const registrations = params.registration_only ? [] : await registry.archive(config, context, client);
          const page = registry.receiptPage(config, context, { offset: params.receipt_offset ?? 0 });
          result = params.registration_only ? page : { ...await client.call(identity, operation,
            params.attachment_id ? { attachment_id: params.attachment_id } : {}, signal), registration: page };
          const errors = registrations.filter(r => r.status === "ERROR");
          if (errors.length) result = { ...result, registration_errors: errors };
        } else result = await client.call(identity, operation, params, signal);
      } catch (error) { result = { status: "ERROR", code: error.message === "REGISTRATION_PENDING" ? error.message : "SERVICE_UNAVAILABLE",
        recovery: "Check configured management/runtime service and trusted session; do not change identities or install dependencies." }; }
      return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    } };
}
