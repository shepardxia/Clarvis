/**
 * Pi-coding-agent bridge for Clarvis.
 *
 * Wraps createAgentSession() and exposes it over a Unix socket using
 * a JSON-lines protocol.  Each Clarvis agent (voice, channels) spawns
 * its own bridge process.
 *
 * Env vars:
 *   PI_BRIDGE_SOCKET       — Unix socket path (required)
 *   PI_BRIDGE_CWD          — working directory for the agent
 *   PI_BRIDGE_MCP_PORT     — Clarvis MCP HTTP port for custom tools
 *   PI_BRIDGE_SESSION_FILE — JSONL file for session persistence
 *   PI_BRIDGE_MODEL        — model id (e.g. "claude-sonnet-4-5")
 *   PI_BRIDGE_THINKING     — thinking level ("off"|"low"|"medium"|"high")
 *   ANTHROPIC_API_KEY      — Anthropic API key
 */

import * as net from "node:net";
import * as fs from "node:fs";
import { getModel } from "@mariozechner/pi-ai";
import {
  AuthStorage,
  createAgentSession,
  SessionManager,
  createCodingTools,
  type AgentSession,
} from "@mariozechner/pi-coding-agent";
import { Type } from "@mariozechner/pi-ai";

// ── Config from env ──

const SOCKET_PATH = process.env.PI_BRIDGE_SOCKET;
const CWD = process.env.PI_BRIDGE_CWD || process.cwd();
const MCP_PORT = process.env.PI_BRIDGE_MCP_PORT
  ? parseInt(process.env.PI_BRIDGE_MCP_PORT, 10)
  : undefined;
const SESSION_FILE = process.env.PI_BRIDGE_SESSION_FILE;
const MODEL_ID = process.env.PI_BRIDGE_MODEL || "claude-sonnet-4-5";
const THINKING = (process.env.PI_BRIDGE_THINKING || "off") as
  | "off"
  | "low"
  | "medium"
  | "high";

if (!SOCKET_PATH) {
  console.error("PI_BRIDGE_SOCKET is required");
  process.exit(1);
}

// ── MCP Streamable HTTP client ──

interface McpTool {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

const MCP_HEADERS = {
  "Content-Type": "application/json",
  Accept: "application/json, text/event-stream",
};

/** Parse a JSON-RPC result from an SSE or JSON response body. */
async function parseMcpResponse(resp: Response): Promise<any> {
  const ct = resp.headers.get("content-type") ?? "";
  const text = await resp.text();

  if (ct.includes("text/event-stream")) {
    // SSE format: "event: message\ndata: {...}\n\n"
    for (const line of text.split("\n")) {
      if (line.startsWith("data: ")) {
        return JSON.parse(line.slice(6));
      }
    }
    throw new Error(`No data line in SSE response: ${text.slice(0, 200)}`);
  }
  // Plain JSON
  return JSON.parse(text);
}

/** MCP session ID obtained during initialization. */
let mcpSessionId: string | undefined;

/** Initialize an MCP session and store the session ID. */
async function initMcpSession(port: number): Promise<void> {
  const resp = await fetch(`http://127.0.0.1:${port}/mcp`, {
    method: "POST",
    headers: MCP_HEADERS,
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 0,
      method: "initialize",
      params: {
        protocolVersion: "2025-03-26",
        capabilities: {},
        clientInfo: { name: "clarvis-pi-bridge", version: "0.1.0" },
      },
    }),
  });

  mcpSessionId = resp.headers.get("mcp-session-id") ?? undefined;
  if (!mcpSessionId) {
    throw new Error("MCP server did not return mcp-session-id header");
  }

  // Parse to validate
  await parseMcpResponse(resp);
  console.error(`[bridge] MCP session initialized: ${mcpSessionId}`);
}

/** Send an MCP JSON-RPC request with session headers. */
async function mcpRequest(port: number, method: string, params: any): Promise<any> {
  const headers: Record<string, string> = { ...MCP_HEADERS };
  if (mcpSessionId) {
    headers["mcp-session-id"] = mcpSessionId;
  }

  const resp = await fetch(`http://127.0.0.1:${port}/mcp`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: Math.floor(Math.random() * 1e9),
      method,
      params,
    }),
  });

  return parseMcpResponse(resp);
}

async function discoverMcpTools(port: number): Promise<McpTool[]> {
  await initMcpSession(port);
  const data = await mcpRequest(port, "tools/list", {});
  return data.result?.tools ?? [];
}

function buildMcpProxyTools(mcpTools: McpTool[], port: number) {
  // MCP inputSchemas are JSON Schema objects discovered at runtime.
  // TypeBox TSchema is structurally compatible — cast through `any`.
  return mcpTools.map((t) => ({
    name: t.name,
    label: t.name,
    description: t.description ?? "",
    parameters: (t.inputSchema ?? Type.Object({})) as any,
    execute: async (_id: string, params: Record<string, unknown>) => {
      try {
        const data = await mcpRequest(port, "tools/call", {
          name: t.name,
          arguments: params,
        });
        if (data.error) {
          return {
            content: [{ type: "text" as const, text: data.error.message }],
            isError: true,
            details: {},
          };
        }
        return {
          content: data.result?.content ?? [
            { type: "text" as const, text: "ok" },
          ],
          details: {},
        };
      } catch (e) {
        return {
          content: [{ type: "text" as const, text: `MCP call failed: ${e}` }],
          isError: true,
          details: {},
        };
      }
    },
  }));
}

// ── Session setup ──

let session: AgentSession;
let promptInFlight = false;

async function initSession(): Promise<void> {
  const authStorage = AuthStorage.create();
  if (process.env.ANTHROPIC_API_KEY) {
    authStorage.setRuntimeApiKey("anthropic", process.env.ANTHROPIC_API_KEY);
  }

  // Cast needed: env-supplied model ID may not be in the union literal type
  const model = getModel("anthropic", MODEL_ID as Parameters<typeof getModel>[1]);

  const sessionManager = SESSION_FILE
    ? SessionManager.open(SESSION_FILE)
    : SessionManager.inMemory();

  const tools = createCodingTools(CWD);

  let customTools: any[] = [];
  if (MCP_PORT) {
    try {
      const mcpTools = await discoverMcpTools(MCP_PORT);
      customTools = buildMcpProxyTools(mcpTools, MCP_PORT);
      console.error(
        `[bridge] Discovered ${mcpTools.length} MCP tools on :${MCP_PORT}`
      );
    } catch (e) {
      console.error(`[bridge] MCP discovery failed: ${e}`);
    }
  }

  const result = await createAgentSession({
    cwd: CWD,
    model,
    thinkingLevel: THINKING,
    tools,
    customTools,
    sessionManager,
    authStorage,
  } as any);
  session = result.session;
}

// ── JSON-lines protocol ──

type Command =
  | { method: "prompt"; params: { text: string } }
  | { method: "abort" }
  | { method: "reload" }
  | { method: "shutdown" };

function writeLine(socket: net.Socket, obj: Record<string, unknown>): void {
  socket.write(JSON.stringify(obj) + "\n");
}

async function handleCommand(
  cmd: Command,
  client: net.Socket
): Promise<void> {
  switch (cmd.method) {
    case "prompt": {
      if (promptInFlight) {
        writeLine(client, {
          event: "error",
          message: "prompt already in flight",
        });
        return;
      }
      promptInFlight = true;

      const unsubscribe = session.subscribe((event) => {
        switch (event.type) {
          case "message_update":
            if (event.assistantMessageEvent.type === "text_delta") {
              writeLine(client, {
                event: "text_delta",
                text: event.assistantMessageEvent.delta,
              });
            }
            break;
          case "tool_execution_start":
            writeLine(client, {
              event: "tool_start",
              name: event.toolName,
            });
            break;
          case "tool_execution_end":
            writeLine(client, {
              event: "tool_end",
              name: event.toolName,
            });
            break;
        }
      });

      try {
        await session.prompt(cmd.params.text);
        writeLine(client, { event: "agent_end" });
      } catch (e) {
        writeLine(client, {
          event: "error",
          message: e instanceof Error ? e.message : String(e),
        });
      } finally {
        unsubscribe();
        promptInFlight = false;
      }
      break;
    }

    case "abort": {
      if (promptInFlight) {
        try {
          await session.steer("Cancel the current operation immediately.");
        } catch {
          // steer may throw if nothing is in flight
        }
      }
      break;
    }

    case "reload": {
      try {
        await session.reload();
        console.error("[bridge] Reloaded session (prompts, skills, extensions)");
        writeLine(client, { event: "reload_done" });
      } catch (e) {
        writeLine(client, {
          event: "error",
          message: `Reload failed: ${e instanceof Error ? e.message : String(e)}`,
        });
      }
      break;
    }

    case "shutdown": {
      process.exit(0);
    }
  }
}

// ── Unix socket server ──

async function main(): Promise<void> {
  await initSession();

  // Clean up stale socket
  if (fs.existsSync(SOCKET_PATH!)) {
    fs.unlinkSync(SOCKET_PATH!);
  }

  const server = net.createServer((client) => {
    let buffer = "";

    client.on("data", (chunk) => {
      buffer += chunk.toString();
      let newlineIdx: number;
      while ((newlineIdx = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, newlineIdx).trim();
        buffer = buffer.slice(newlineIdx + 1);
        if (!line) continue;
        try {
          const cmd = JSON.parse(line) as Command;
          handleCommand(cmd, client).catch((e) => {
            writeLine(client, {
              event: "error",
              message: e instanceof Error ? e.message : String(e),
            });
          });
        } catch {
          writeLine(client, {
            event: "error",
            message: `Invalid JSON: ${line.slice(0, 100)}`,
          });
        }
      }
    });
  });

  server.listen(SOCKET_PATH!, () => {
    // Signal readiness to parent process on stdout
    console.log("READY");
    console.error(`[bridge] Listening on ${SOCKET_PATH}`);
  });

  // Graceful shutdown
  process.on("SIGTERM", () => {
    server.close();
    process.exit(0);
  });
  process.on("SIGINT", () => {
    server.close();
    process.exit(0);
  });
}

main().catch((e) => {
  console.error(`[bridge] Fatal: ${e}`);
  process.exit(1);
});
