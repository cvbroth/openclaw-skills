import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { Type } from "typebox";
import { getSessionEntry, resolveStorePath } from "openclaw/plugin-sdk/session-store-runtime";
import { Registry, createTool } from "./runtime.mjs";

const object = fields => Type.Object(fields, { additionalProperties: false });
const id = Type.String({ pattern: "^[0-9a-f]{32}$" });
const interval = Type.Tuple([Type.Integer({ minimum: 1 }), Type.Integer({ minimum: 1 })]);
const time = Type.Tuple([Type.Number({ minimum: 0 }), Type.Number({ minimum: 0 })]);
const optional = Type.Optional;
const reading = { job_id: id, artifact_id: optional(id), pages: optional(interval), time_range: optional(time),
  paragraphs: optional(interval), offset: optional(Type.Integer({ minimum: 0, maximum: 2_000_000 })),
  max_chars: optional(Type.Integer({ minimum: 1, maximum: 12000 })) };

export const schemas = {
  inspect: object({ attachment_id: optional(id) }),
  extract: object({ attachment_id: id, config: object({
    mode: Type.Union([Type.Literal("preview"), Type.Literal("range"), Type.Literal("full")]),
    pages: optional(interval), time_range: optional(time), paragraphs: optional(interval),
    ocr: optional(Type.Union([Type.Literal("auto"), Type.Literal("always")])),
    language: optional(Type.Union([Type.Literal("zh"), Type.Literal("en")])) }) }),
  status: object({ job_id: id }), cancel: object({ job_id: id }), read: object(reading),
  find: object({ ...reading, keyword: Type.String({ minLength: 1, maxLength: 200 }) }),
  save_minutes: object({ job_id: id, text: Type.String({ minLength: 1, maxLength: 12000 }),
    source_segments: Type.Array(Type.Integer({ minimum: 1 }), { minItems: 1, maxItems: 100 }) }),
};
const binding = object({ user_id: Type.String(), agent_id: Type.String(), sender_id: Type.String({ minLength: 1 }),
  channel_id: Type.String({ minLength: 1 }), account_id: Type.String({ minLength: 1 }) });
export const configSchema = object({ bindings: Type.Array(binding, { maxItems: 16 }) });
export const registry = new Registry();
export const names = Object.keys(schemas).map(operation => `filetools_${operation}`);
const descriptions = {
  inspect: "List trusted attachments or inspect bounded metadata/preview. Never choose a path. Must precede extraction.",
  extract: "Queue extraction: explicit preview/range/full; large files should first use preview or requested range.",
  status: "Poll queued/running job. SUCCEEDED is success for requested scope only; inspect coverage and warnings.",
  cancel: "Request cancellation. RUNNING+cancel_requested means cancellation is pending; poll for terminal status.",
  read: "Read bounded evidence by pages, seconds or body blocks. Continue next_offset as needed; cite source.",
  find: "Locate a literal keyword in extracted scope. No match never proves absence in the whole original.",
  save_minutes: "Save unverified Agent-derived minutes separately from the original transcript; cite source segment IDs.",
};
const plugin = defineToolPlugin({ id: "nas-filetools", name: "NAS FileTools", description: "Temporary file evidence tools",
  configSchema, tools: tool => Object.entries(schemas).map(([operation, schema]) => tool({
    name: `filetools_${operation}`, label: `FileTools ${operation}`, description: descriptions[operation], parameters: schema,
    factory: ({ config, toolContext }) => {
      const instance = createTool(`filetools_${operation}`, operation, schema, config, toolContext, registry);
      return instance ? { ...instance, description: descriptions[operation] } : null;
    },
  })) });
const register = plugin.register;
plugin.register = api => {
  register(api);
  api.on("message_received", (event, context) => {
    // The 2026.9.4 inbound mapper normally has no runId. Read the runtime's existing
    // session epoch using the public storage-neutral SDK; never derive it from body text.
    const agentId = /^agent:([^:]+):/.exec(context.sessionKey ?? "")?.[1];
    let observed = { lookupSucceeded: false };
    try {
      if (agentId && context.sessionKey) {
        const storePath = resolveStorePath(api.config?.session?.store, { agentId });
        const entry = getSessionEntry({ agentId, sessionKey: context.sessionKey, storePath, readConsistency: "latest" });
        observed = { lookupSucceeded: true, sessionId: entry?.sessionId };
      }
    } catch { /* An unavailable trusted store must fail closed. */ }
    return registry.received(api.pluginConfig, event, context, observed);
  });
  api.on("session_start", (event, context) => registry.lifecycle(event, context));
  api.on("session_end", (event, context) => registry.lifecycle(event, context, true));
};
export default plugin;
