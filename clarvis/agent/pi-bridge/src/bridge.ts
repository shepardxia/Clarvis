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
 *   PI_BRIDGE_SESSION_FILE — JSONL file for session persistence
 *   PI_BRIDGE_MODEL        — model id (e.g. "claude-sonnet-4-6")
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

// ── Config from env ──

const SOCKET_PATH = process.env.PI_BRIDGE_SOCKET;
const CWD = process.env.PI_BRIDGE_CWD || process.cwd();
const SESSION_FILE = process.env.PI_BRIDGE_SESSION_FILE;
const MODEL_ID = process.env.PI_BRIDGE_MODEL || "claude-sonnet-4-6";
const THINKING = (process.env.PI_BRIDGE_THINKING || "off") as
  | "off"
  | "low"
  | "medium"
  | "high";

if (!SOCKET_PATH) {
  console.error("PI_BRIDGE_SOCKET is required");
  process.exit(1);
}

// ── Session setup ──

let session: AgentSession;
let promptInFlight = false;

async function initSession(): Promise<void> {
  const authStorage = AuthStorage.create();
  if (process.env.ANTHROPIC_API_KEY) {
    authStorage.setRuntimeApiKey("anthropic", process.env.ANTHROPIC_API_KEY);
  }

  const model = getModel("anthropic", MODEL_ID as Parameters<typeof getModel>[1]);

  const sessionManager = SESSION_FILE
    ? SessionManager.open(SESSION_FILE)
    : SessionManager.inMemory();

  const tools = createCodingTools(CWD);

  const result = await createAgentSession({
    cwd: CWD,
    model,
    thinkingLevel: THINKING,
    tools,
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
  | { method: "reset" }
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

    case "reset": {
      try {
        await session.newSession();
        console.error("[bridge] New session started");
        writeLine(client, { event: "reset_done" });
      } catch (e) {
        writeLine(client, {
          event: "error",
          message: `Reset failed: ${e instanceof Error ? e.message : String(e)}`,
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
    console.log("READY");
    console.error(`[bridge] Listening on ${SOCKET_PATH}`);
  });

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
