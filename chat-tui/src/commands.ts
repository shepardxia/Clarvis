/**
 * Slash command definitions and dispatch logic.
 *
 * Two categories:
 * - Session: /new -> forward via chat socket
 * - Local: /help, /clear, /quit, /rewind -> handle in TUI
 *
 * Unrecognized slash commands fall through as agent prompts.
 */

import type { SlashCommand } from "@mariozechner/pi-tui";
import type { ChatClient } from "./daemon-client.js";
import { DaemonClient } from "./daemon-client.js";
import type { OutputLog } from "./components/output-log.js";

export type CommandResult =
	| { handled: true }
	| { handled: false };

export interface CommandContext {
	chatClient: ChatClient;
	outputLog: OutputLog;
	onClear: () => void;
	onQuit: () => void;
	onRewind: () => void;
	requestRender: () => void;
	showSelect: (title: string, options: string[], onDone: (value: string | undefined) => void) => void;
	showFilterSelect: (title: string, options: string[], onDone: (value: string | undefined) => void) => void;
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

export function dispatchCommand(input: string, ctx: CommandContext): CommandResult {
	const match = input.match(/^\/(\S+)\s*(.*)/);
	if (!match) return { handled: false };

	const [, cmd, args] = match;
	const trimmedArgs = args.trim();

	// Local commands
	if (cmd === "help") {
		showHelp(ctx);
		return { handled: true };
	}
	if (cmd === "clear") {
		ctx.onClear();
		return { handled: true };
	}
	if (cmd === "quit" || cmd === "exit") {
		ctx.onQuit();
		return { handled: true };
	}
	if (cmd === "rewind") {
		ctx.onRewind();
		return { handled: true };
	}

	// /new — sends new_session to chat socket
	if (cmd === "new") {
		ctx.chatClient.send({ type: "new_session" });
		ctx.outputLog.handleInfo("[session reset]");
		ctx.requestRender();
		return { handled: true };
	}

	// Daemon commands (same IPC as `clarvis` CLI)
	if (cmd === "reflect") {
		executeDaemonCommand("nudge", { reason: "reflect" }, ctx);
		return { handled: true };
	}
	if (cmd === "reload") {
		executeDaemonCommand("reload_agents", {}, ctx);
		return { handled: true };
	}

	// Pi RPC commands (forwarded to agent subprocess)
	if (cmd === "thinking") {
		executeThinkingCommand(ctx);
		return { handled: true };
	}
	if (cmd === "model") {
		executeModelCommand(ctx);
		return { handled: true };
	}

	// Unrecognized — fall through as agent prompt
	return { handled: false };
}

async function executeThinkingCommand(ctx: CommandContext): Promise<void> {
	// Query current level first to show (current) marker
	let currentLevel = "unknown";
	try {
		const state = await ctx.chatClient.request({ type: "command", command: "get_state", args: {} });
		currentLevel = String((state.result as Record<string, unknown>)?.thinkingLevel ?? "unknown");
	} catch { /* proceed without marker */ }

	const options = THINKING_LEVELS.map((l) => l === currentLevel ? `${l} (current)` : l);
	ctx.showSelect("Thinking level", options, async (value) => {
		if (!value) return;
		const level = value.replace(" (current)", "");
		try {
			await ctx.chatClient.request({
				type: "command", command: "set_thinking_level", args: { level },
			});
			ctx.outputLog.handleInfo(`Thinking: ${level}`);
		} catch (err) {
			const msg = err instanceof Error ? err.message : String(err);
			ctx.outputLog.handleError(msg);
		}
		ctx.requestRender();
	});
}

async function executeModelCommand(ctx: CommandContext): Promise<void> {
	// Query available models from Pi
	let models: Array<Record<string, unknown>> = [];
	let currentModelId = "";
	try {
		const state = await ctx.chatClient.request({ type: "command", command: "get_state", args: {} });
		const result = state.result as Record<string, unknown>;
		currentModelId = String((result?.model as Record<string, unknown>)?.modelId ?? "");

		const resp = await ctx.chatClient.request({ type: "command", command: "get_available_models", args: {} });
		const data = resp.result as Record<string, unknown>;
		if (Array.isArray(data)) {
			models = data as Array<Record<string, unknown>>;
		} else if (Array.isArray(data?.models)) {
			models = data.models as Array<Record<string, unknown>>;
		}
	} catch { /* fall through with empty list */ }

	if (models.length === 0) {
		ctx.outputLog.handleError("Could not fetch available models");
		ctx.requestRender();
		return;
	}

	const options = models.map((m) => {
		const id = String(m.modelId ?? m.name ?? "unknown");
		return id === currentModelId ? `${id} (current)` : id;
	});

	ctx.showFilterSelect("Model", options, async (value) => {
		if (!value) return;
		const modelId = value.replace(" (current)", "");
		try {
			await ctx.chatClient.request({
				type: "command", command: "set_model", args: { modelId },
			});
			ctx.outputLog.handleInfo(`Model: ${modelId}`);
		} catch (err) {
			const msg = err instanceof Error ? err.message : String(err);
			ctx.outputLog.handleError(msg);
		}
		ctx.requestRender();
	});
}

async function executeDaemonCommand(
	method: string,
	params: Record<string, unknown>,
	ctx: CommandContext,
): Promise<void> {
	try {
		const result = await DaemonClient.send(method, params);
		const text = typeof result === "string" ? result : JSON.stringify(result, null, 2);
		ctx.outputLog.handleInfo(text);
	} catch (err) {
		const msg = err instanceof Error ? err.message : String(err);
		ctx.outputLog.handleError(msg);
	}
	ctx.requestRender();
}

function showHelp(ctx: CommandContext): void {
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
		"  Esc          Abort current response",
		"  Esc×2        Rewind / fork",
		"  Ctrl+L       Toggle expanded tool output",
		"  Ctrl+D       Exit",
	];
	for (const line of lines) {
		ctx.outputLog.handleInfo(line);
	}
	ctx.requestRender();
}
