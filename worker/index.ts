import { Container, getContainer } from "@cloudflare/containers";
import { env as workerEnv } from "cloudflare:workers";


interface Env {
  API_CONTAINER: DurableObjectNamespace<LaundryApiContainer>;
  OPENAI_API_KEY: string;
  MONGODB_URI: string;
  R2_ACCESS_KEY_ID: string;
  R2_SECRET_ACCESS_KEY: string;
  R2_ENDPOINT: string;
  R2_BUCKET_NAME: string;
  RUNTIME_STATE_TOKEN: string;
  OPENAI_VISION_MODEL?: string;
  OPENAI_MATCHING_MODEL?: string;
  OPENAI_CHAT_MODEL?: string;
  OPENAI_ANNE_MODEL?: string;
}


interface ScopePayload {
  laundry_id?: string | null;
  business_id?: string | null;
  role: string;
}


interface ExportedContext {
  scope_key: string;
  snapshot: {
    laundry_id: string;
    business_id?: string | null;
    branch_id?: string | null;
    role: string;
  };
}


interface ConversationState {
  conversation_id: string;
  scope_key: string;
  role: string;
  messages: Array<{ role: string; content: string }>;
}


const cfEnv = workerEnv as unknown as Env;
const INTERNAL_PREFIX = "/_cloudflare/runtime-state";
const CHUNK_BYTES = 1_000_000;


function configuredContainerEnvironment(): Record<string, string> {
  const values: Record<string, string | undefined> = {
    OPENAI_API_KEY: cfEnv.OPENAI_API_KEY,
    MONGODB_URI: cfEnv.MONGODB_URI,
    R2_ACCESS_KEY_ID: cfEnv.R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY: cfEnv.R2_SECRET_ACCESS_KEY,
    R2_ENDPOINT: cfEnv.R2_ENDPOINT,
    R2_BUCKET_NAME: cfEnv.R2_BUCKET_NAME,
    RUNTIME_STATE_TOKEN: cfEnv.RUNTIME_STATE_TOKEN,
    OPENAI_VISION_MODEL: cfEnv.OPENAI_VISION_MODEL,
    OPENAI_MATCHING_MODEL: cfEnv.OPENAI_MATCHING_MODEL,
    OPENAI_CHAT_MODEL: cfEnv.OPENAI_CHAT_MODEL,
    OPENAI_ANNE_MODEL: cfEnv.OPENAI_ANNE_MODEL,
  };
  return Object.fromEntries(
    Object.entries(values).filter((entry): entry is [string, string] => Boolean(entry[1])),
  );
}


export class LaundryApiContainer extends Container<Env> {
  defaultPort = 8080;
  requiredPorts = [8080];
  pingEndpoint = "localhost/health";
  sleepAfter = "10m";
  enableInternet = true;
  envVars = configuredContainerEnvironment();

  override async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname.startsWith(INTERNAL_PREFIX)) {
      return Response.json({ detail: "Not found." }, { status: 404 });
    }

    if (request.method === "POST" && url.pathname === "/api/v1/context/prepare") {
      return this.handlePrepare(request);
    }
    if (request.method === "POST" && url.pathname === "/api/v1/chat") {
      return this.handleChat(request);
    }
    return this.containerFetch(request);
  }

  private async handlePrepare(request: Request): Promise<Response> {
    const payload = await this.readJson<ScopePayload>(request.clone());
    const response = await this.containerFetch(request);
    if (!response.ok || !payload) {
      return response;
    }

    try {
      const exported = await this.internalJson<ExportedContext>(
        "/context/export",
        payload,
      );
      await this.persistContext(exported);
      await this.clearScopeConversations(exported.scope_key, exported.snapshot.role);
      return response;
    } catch (error) {
      console.error("Failed to persist prepared context", error);
      return Response.json(
        { detail: "Context was prepared but could not be persisted." },
        { status: 503 },
      );
    }
  }

  private async handleChat(request: Request): Promise<Response> {
    const payload = await this.readJson<ScopePayload & { conversation_id?: string | null }>(
      request.clone(),
    );
    if (payload) {
      await this.restoreContextIfNeeded(payload);
      if (payload.conversation_id) {
        await this.restoreConversationIfNeeded(payload.conversation_id);
      }
    }

    const response = await this.containerFetch(request);
    if (!response.ok) {
      return response;
    }

    try {
      const body = await response.clone().json<{ conversation_id?: string }>();
      if (body.conversation_id) {
        const conversation = await this.internalJson<ConversationState>(
          "/conversation/export",
          { conversation_id: body.conversation_id },
        );
        await this.persistConversation(conversation);
      }
      return response;
    } catch (error) {
      console.error("Failed to persist conversation", error);
      return Response.json(
        { detail: "The answer was generated but its conversation state could not be persisted." },
        { status: 503 },
      );
    }
  }

  private async restoreContextIfNeeded(payload: ScopePayload): Promise<void> {
    const status = await this.internalJson<{ exists: boolean }>("/context/has", payload);
    if (status.exists) {
      return;
    }

    const lookupKey = payload.laundry_id
      ? `context-lookup:laundry:${payload.laundry_id}:${payload.role}`
      : payload.business_id
        ? `context-lookup:business:${payload.business_id}:${payload.role}`
        : null;
    if (!lookupKey) {
      return;
    }
    const canonicalKey = await this.ctx.storage.get<string>(lookupKey);
    if (!canonicalKey) {
      return;
    }
    const snapshot = await this.getChunkedJson<Record<string, unknown>>(canonicalKey);
    if (snapshot) {
      await this.internalJson("/context/import", snapshot);
    }
  }

  private async restoreConversationIfNeeded(conversationId: string): Promise<void> {
    const status = await this.internalJson<{ exists: boolean }>(
      "/conversation/has",
      { conversation_id: conversationId },
    );
    if (status.exists) {
      return;
    }
    const state = await this.getChunkedJson<ConversationState>(
      `conversation:${conversationId}`,
    );
    if (state) {
      await this.internalJson("/conversation/import", state);
    }
  }

  private async persistContext(exported: ExportedContext): Promise<void> {
    const { snapshot, scope_key: scopeKey } = exported;
    const canonicalKey = `context:${encodeURIComponent(scopeKey)}:${snapshot.role}`;
    await this.putChunkedJson(canonicalKey, snapshot);
    if (snapshot.branch_id || !snapshot.business_id) {
      await this.ctx.storage.put(
        `context-lookup:laundry:${snapshot.laundry_id}:${snapshot.role}`,
        canonicalKey,
      );
    }
    if (snapshot.business_id && !snapshot.branch_id) {
      await this.ctx.storage.put(
        `context-lookup:business:${snapshot.business_id}:${snapshot.role}`,
        canonicalKey,
      );
    }
  }

  private async persistConversation(state: ConversationState): Promise<void> {
    await this.putChunkedJson(`conversation:${state.conversation_id}`, state);
    await this.ctx.storage.put(
      this.conversationScopeIndexKey(state.scope_key, state.role, state.conversation_id),
      state.conversation_id,
    );
  }

  private async clearScopeConversations(scopeKey: string, role: string): Promise<void> {
    const prefix = this.conversationScopeIndexKey(scopeKey, role, "");
    const indexed = await this.ctx.storage.list<string>({ prefix });
    for (const [indexKey, conversationId] of indexed) {
      await this.deleteChunkedJson(`conversation:${conversationId}`);
      await this.ctx.storage.delete(indexKey);
    }
  }

  private conversationScopeIndexKey(
    scopeKey: string,
    role: string,
    conversationId: string,
  ): string {
    return `conversation-scope:${encodeURIComponent(scopeKey)}:${role}:${conversationId}`;
  }

  private async internalJson<T = Record<string, unknown>>(
    path: string,
    payload: unknown,
  ): Promise<T> {
    const response = await this.containerFetch(
      new Request(`http://container${INTERNAL_PREFIX}${path}`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-runtime-state-token": cfEnv.RUNTIME_STATE_TOKEN,
        },
        body: JSON.stringify(payload),
      }),
    );
    if (!response.ok) {
      throw new Error(`Runtime state request failed with ${response.status}: ${await response.text()}`);
    }
    return response.json<T>();
  }

  private async readJson<T>(request: { text(): Promise<string> }): Promise<T | null> {
    try {
      return JSON.parse(await request.text()) as T;
    } catch {
      return null;
    }
  }

  private async putChunkedJson(key: string, value: unknown): Promise<void> {
    await this.deleteChunkedJson(key);
    const encoded = new TextEncoder().encode(JSON.stringify(value));
    const chunks = Math.max(1, Math.ceil(encoded.byteLength / CHUNK_BYTES));
    for (let index = 0; index < chunks; index += 1) {
      const start = index * CHUNK_BYTES;
      await this.ctx.storage.put(
        `${key}:chunk:${index}`,
        encoded.slice(start, Math.min(start + CHUNK_BYTES, encoded.byteLength)),
      );
    }
    await this.ctx.storage.put(`${key}:meta`, { chunks });
  }

  private async getChunkedJson<T>(key: string): Promise<T | null> {
    const meta = await this.ctx.storage.get<{ chunks: number }>(`${key}:meta`);
    if (!meta) {
      return null;
    }
    const parts: Uint8Array[] = [];
    let totalLength = 0;
    for (let index = 0; index < meta.chunks; index += 1) {
      const part = await this.ctx.storage.get<Uint8Array>(`${key}:chunk:${index}`);
      if (!part) {
        throw new Error(`Persistent state chunk ${index} is missing for ${key}`);
      }
      parts.push(part);
      totalLength += part.byteLength;
    }
    const combined = new Uint8Array(totalLength);
    let offset = 0;
    for (const part of parts) {
      combined.set(part, offset);
      offset += part.byteLength;
    }
    return JSON.parse(new TextDecoder().decode(combined)) as T;
  }

  private async deleteChunkedJson(key: string): Promise<void> {
    const meta = await this.ctx.storage.get<{ chunks: number }>(`${key}:meta`);
    if (!meta) {
      return;
    }
    const keys = Array.from(
      { length: meta.chunks },
      (_, index) => `${key}:chunk:${index}`,
    );
    keys.push(`${key}:meta`);
    await this.ctx.storage.delete(keys);
  }
}


export default {
  fetch(request: Request, env: Env): Promise<Response> {
    return getContainer(env.API_CONTAINER, "primary").fetch(request);
  },
} satisfies ExportedHandler<Env>;
