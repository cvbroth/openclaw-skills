import http from "node:http";

export const SOCKET = "/run/nas-filetools/service.sock";
const RESPONSE_LIMIT = 2 * 1024 * 1024;

export function exchange(route, identity, params, opened, signal, limits) {
  return new Promise((resolve, reject) => {
    const payload = opened ? null : Buffer.from(JSON.stringify({ identity, ...params }));
    if (payload && limits && payload.length > limits.max_control_bytes) { reject(new Error("REQUEST_LIMIT")); return; }
    const request = http.request({ socketPath: SOCKET, path: route, method: "POST",
      headers: { "Content-Length": opened ? String(opened.stat.size) : payload.length,
        "Content-Type": opened ? "application/octet-stream" : "application/json",
        ...(opened ? { "X-Filetools-Identity": JSON.stringify(identity),
          "X-Attachment-Id": params.attachment_id,
          "X-Content-SHA256": opened.sha256,
          "X-Source-Message-Id": JSON.stringify(opened.message_id).replace(/[^\x00-\x7f]/g,
            c => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`),
          "X-Filename": JSON.stringify(opened.filename).replace(/[^\x00-\x7f]/g,
            c => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`) } : {}) } }, response => {
      const chunks = [];
      let bytes = 0;
      response.on("data", part => {
        bytes += part.length;
        if (bytes > (limits?.max_response_bytes ?? RESPONSE_LIMIT)) request.destroy(new Error("RESPONSE_LIMIT"));
        else chunks.push(part);
      });
      response.on("aborted", () => finish(new Error("RESPONSE_ABORTED")));
      response.on("error", finish);
      response.on("end", () => {
        try {
          if (response.statusCode !== 200) throw new Error("SERVICE_HTTP_ERROR");
          const result = JSON.parse(Buffer.concat(chunks).toString("utf8"));
          if (!result || typeof result !== "object" || Array.isArray(result) || typeof result.status !== "string") {
            throw new Error("INVALID_RESPONSE");
          }
          finish(null, result);
        } catch (error) { finish(error); }
      });
    });
    let settled = false;
    let stream;
    const abort = () => request.destroy(new Error("REQUEST_ABORTED"));
    const timer = setTimeout(() => request.destroy(new Error("SERVICE_TIMEOUT")), opened ? (limits?.upload_timeout_seconds ?? 3600)*1000 : 60_000);
    function finish(error, result) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      stream?.destroy();
      if (error) reject(error); else resolve(result);
    }
    signal?.addEventListener("abort", abort, { once: true });
    request.on("error", finish);
    if (signal?.aborted) { abort(); return; }
    if (opened) {
      stream = opened.handle.createReadStream({ start: 0, autoClose: false });
      stream.on("error", error => request.destroy(error));
      stream.pipe(request);
    } else request.end(payload);
  });
}

export const client = {
  capabilities: async identity => exchange("/v1/tool", { user_id: identity.user_id, agent_id: identity.agent_id,
    session_hash: identity.session_hash }, { operation: "capabilities", params: {} }),
  async call(identity, operation, params, signal) {
    const { limits } = await this.capabilities(identity);
    return exchange("/v1/tool", identity, { operation, params }, null, signal, limits);
  },
  async upload(identity, id, opened, signal) {
    const { limits } = await this.capabilities(identity);
    if (opened.stat.size > BigInt(limits.max_receive_bytes)) throw new Error("RECEIVE_SIZE_LIMIT");
    return exchange("/v1/attachment", identity, { attachment_id: id }, opened, signal, limits);
  },
};
