/**
 * Slash command definitions and dispatch logic.
 *
 * Categories:
 * - Local: /help, /clear, /quit, /rewind — handled in TUI
 * - Session: /new — forwarded via chat socket
 * - Daemon: /reflect, /reload — JSON-RPC to daemon socket
 * - Pi RPC: /thinking, /model — forwarded to agent subprocess
 *
 * Unrecognized slash commands fall through as agent prompts.
 */

import type { SlashCommand } from "@mariozechner/pi-tui";
import { DaemonClient } from "./daemon-client.js";
import type { App } from "./app.js";
import { type RewindEntry, RewindDialog } from "./components/dialogs.js";
import { extractText } from "./context.js";

export type CommandResult =
	| { handled: true }
	| { handled: false };

function errorMsg(err: unknown): string {
	return err instanceof Error ? err.message : String(err);
}

// ============================================================================
// Command definitions for autocomplete
// ============================================================================

const THINKING_LEVELS = ["off", "minimal", "low", "medium", "high"];

export const slashCommands: SlashCommand[] = [
	// Session commands
	{ name: "new", description: "Start a new session" },
	{ name: "reflect", description: "Consolidate memories" },
	{ name: "reload", description: "Reload agent prompts" },

	// Agent settings (Pi RPC)
	{ name: "thinking", description: "Set thinking level (off/minimal/low/medium/high)" },
	{ name: "model", description: "Switch model (e.g. /model claude-sonnet-4-6)" },

	// Local commands
	{ name: "help", description: "Show available commands" },
	{ name: "clear", description: "Clear the output log" },
	{ name: "rewind", description: "Fork conversation from a previous turn" },
	{ name: "quit", description: "Exit the chat TUI" },
];

// ============================================================================
// Dispatch
// ============================================================================

export function dispatchCommand(input: string, app: App): CommandResult {
	const match = input.match(/^\/(\S+)\s*(.*)/);
	if (!match) return { handled: false };

	const [, cmd] = match;

	// Local commands
	if (cmd === "help") {
		showHelp(app);
		return { handled: true };
	}
	if (cmd === "clear") {
		app.output.clear();
		app.requestRender();
		return { handled: true };
	}
	if (cmd === "quit" || cmd === "exit") {
		app.exit();
		return { handled: true };
	}
	if (cmd === "rewind") {
		handleRewind(app);
		return { handled: true };
	}

	// /new — reset agent session and clear TUI
	if (cmd === "new") {
		app.chatClient.send({ type: "new_session" });
		app.output.clear();
		app.output.handleInfo("[session reset]");
		app.requestRender();
		return { handled: true };
	}

	// Daemon commands (same IPC as `clarvis` CLI)
	if (cmd === "reflect") {
		executeDaemonCommand("nudge", { reason: "reflect" }, app);
		return { handled: true };
	}
	if (cmd === "reload") {
		executeDaemonCommand("reload_agents", {}, app);
		return { handled: true };
	}

	// Pi RPC commands (forwarded to agent subprocess)
	if (cmd === "thinking") {
		executeThinkingCommand(app);
		return { handled: true };
	}
	if (cmd === "model") {
		executeModelCommand(app);
		return { handled: true };
	}

	// Unrecognized — fall through as agent prompt
	return { handled: false };
}

// ============================================================================
// Rewind / fork
// ============================================================================

export async function handleRewind(app: App): Promise<void> {
	try {
		const resp = await app.chatClient.request({ type: "get_fork_messages" });
		const messages = resp.messages as Array<Record<string, unknown>> | undefined;
		if (!messages || messages.length === 0) {
			app.output.handleInfo("No messages to rewind to.");
			app.requestRender();
			return;
		}

		const entries: RewindEntry[] = messages.map((m) => {
			const text = extractText(m).trim();
			return {
				entryId: m.entryId as string,
				role: m.role as string,
				text,
			};
		});

		const dialog = new RewindDialog(entries);

		dialog.onSelect = async (entry) => {
			app.hideOverlay();
			app.output.handleInfo("[rewinding...]");
			app.requestRender();

			try {
				const forkResp = await app.chatClient.request(
					{ type: "fork", entryId: entry.entryId },
				);
				const text = forkResp.text as string | undefined;
				if (text) {
					app.prompt.editor.setText(text);
				}
				app.requestRender();
			} catch (err) {
				const msg = errorMsg(err);
				app.output.handleError(`Fork failed: ${msg}`);
				app.requestRender();
			}
		};

		dialog.onCancel = () => {
			app.hideOverlay();
		};

		app.showOverlay(dialog);
	} catch (err) {
		const msg = errorMsg(err);
		app.output.handleError(`Rewind failed: ${msg}`);
		app.requestRender();
	}
}

// ============================================================================
// Pi RPC commands
// ============================================================================

async function executeThinkingCommand(app: App): Promise<void> {
	// Query current level first to show (current) marker
	let currentLevel = "unknown";
	try {
		const state = await app.chatClient.request({ type: "command", command: "get_state", args: {} });
		currentLevel = String((state.result as Record<string, unknown>)?.thinkingLevel ?? "unknown");
	} catch { /* proceed without marker */ }

	const options = THINKING_LEVELS.map((l) => l === currentLevel ? `${l} (current)` : l);
	app.showSelect("Thinking level", options, async (value) => {
		if (!value) return;
		const level = value.replace(" (current)", "");
		try {
			await app.chatClient.request({
				type: "command", command: "set_thinking_level", args: { level },
			});
			app.output.handleInfo(`Thinking: ${level}`);
		} catch (err) {
			const msg = errorMsg(err);
			app.output.handleError(msg);
		}
		app.requestRender();
	});
}

async function executeModelCommand(app: App): Promise<void> {
	// Query available models from Pi
	let models: Array<Record<string, unknown>> = [];
	let currentModelId = "";
	try {
		const [state, resp] = await Promise.all([
			app.chatClient.request({ type: "command", command: "get_state", args: {} }),
			app.chatClient.request({ type: "command", command: "get_available_models", args: {} }),
		]);
		const result = state.result as Record<string, unknown>;
		currentModelId = String((result?.model as Record<string, unknown>)?.modelId ?? "");

		const data = resp.result as Record<string, unknown>;
		if (Array.isArray(data)) {
			models = data as Array<Record<string, unknown>>;
		} else if (Array.isArray(data?.models)) {
			models = data.models as Array<Record<string, unknown>>;
		}
	} catch { /* fall through with empty list */ }

	if (models.length === 0) {
		app.output.handleError("Could not fetch available models");
		app.requestRender();
		return;
	}

	const options = models.map((m) => {
		const id = String(m.modelId ?? m.name ?? "unknown");
		return id === currentModelId ? `${id} (current)` : id;
	});

	app.showFilterSelect("Model", options, async (value) => {
		if (!value) return;
		const modelId = value.replace(" (current)", "");
		try {
			await app.chatClient.request({
				type: "command", command: "set_model", args: { modelId },
			});
			app.output.handleInfo(`Model: ${modelId}`);
		} catch (err) {
			const msg = errorMsg(err);
			app.output.handleError(msg);
		}
		app.requestRender();
	});
}

// ============================================================================
// Daemon commands
// ============================================================================

async function executeDaemonCommand(
	method: string,
	params: Record<string, unknown>,
	app: App,
): Promise<void> {
	try {
		const result = await DaemonClient.send(method, params);
		const text = typeof result === "string" ? result : JSON.stringify(result, null, 2);
		app.output.handleInfo(text);
	} catch (err) {
		const msg = errorMsg(err);
		app.output.handleError(msg);
	}
	app.requestRender();
}

// ============================================================================
// Help
// ============================================================================

function showHelp(app: App): void {
	const lines = [
		"Commands:",
		"  /new         Start a new session",
		"  /reflect     Consolidate memories",
		"  /reload      Reload agent prompts",
		"  /thinking    Set thinking (off/minimal/low/medium/high)",
		"  /model       Switch model (e.g. /model claude-sonnet-4-6)",
		"",
		"  /rewind      Fork from a previous turn",
		"  /clear       Clear output",
		"  /help        Show this help",
		"  /quit        Exit",
		"",
		"  Esc          Steer agent (if queued) / abort",
		"  Esc×2        Rewind / fork (when idle)",
		"  Up           Edit queued message (when busy)",
		"  Ctrl+L       Toggle expanded tool output",
		"  Ctrl+D       Exit",
		"",
		"Messages sent while busy are queued and auto-sent when done.",
	];
	for (const line of lines) {
		app.output.handleInfo(line);
	}
	app.requestRender();
}
