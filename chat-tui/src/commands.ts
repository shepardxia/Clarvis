/**
 * Slash command definitions and dispatch logic.
 *
 * Three categories:
 * - Pi RPC: /compact, /model, /thinking, /new, /stats -> forward via chat socket
 * - Daemon: /spotify, /timer, /reflect, /reload -> send via daemon socket (ctools)
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

interface CommandContext {
	chatClient: ChatClient;
	outputLog: OutputLog;
	onClear: () => void;
	onQuit: () => void;
	onRewind: () => void;
	requestRender: () => void;
}

// ============================================================================
// Command definitions for autocomplete
// ============================================================================

export const slashCommands: SlashCommand[] = [
	// Pi RPC commands
	{ name: "compact", description: "Compact conversation context" },
	{ name: "model", description: "Show or change the model" },
	{ name: "thinking", description: "Toggle extended thinking" },
	{ name: "new", description: "Start a new session" },
	{ name: "stats", description: "Show session statistics" },

	// Daemon commands
	{ name: "spotify", description: "Control Spotify playback" },
	{ name: "timer", description: "Manage timers" },
	{ name: "reflect", description: "Trigger memory consolidation" },
	{ name: "reload", description: "Reload agent prompts" },

	// Local commands
	{ name: "help", description: "Show available commands" },
	{ name: "clear", description: "Clear the output log" },
	{ name: "rewind", description: "Fork conversation from a previous turn" },
	{ name: "quit", description: "Exit the chat TUI" },
];

// ============================================================================
// Pi RPC commands — forwarded via chat socket
// ============================================================================

const PI_RPC_COMMANDS = new Set(["compact", "model", "thinking", "stats"]);

// ============================================================================
// Daemon commands — sent via daemon socket (ctools)
// ============================================================================

interface DaemonCommand {
	method: string;
	parseArgs?: (args: string) => Record<string, unknown>;
}

const DAEMON_COMMANDS: Record<string, DaemonCommand> = {
	spotify: {
		method: "spotify",
		parseArgs: (args) => ({ command: args }),
	},
	timer: {
		method: "timer",
		parseArgs: (args) => {
			try {
				return JSON.parse(args);
			} catch {
				return { action: "list" };
			}
		},
	},
	reflect: { method: "nudge", parseArgs: () => ({ reason: "reflect" }) },
	reload: { method: "reload_agents" },
};

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

	// /new — special: sends new_session to chat socket
	if (cmd === "new") {
		ctx.chatClient.send({ type: "new_session" });
		ctx.outputLog.handleInfo("[session reset]");
		ctx.requestRender();
		return { handled: true };
	}

	// Pi RPC commands
	if (PI_RPC_COMMANDS.has(cmd)) {
		// Forward as a prompt starting with / so Pi interprets as command
		ctx.chatClient.send({ type: "prompt", message: input });
		return { handled: true };
	}

	// Daemon commands
	const daemonCmd = DAEMON_COMMANDS[cmd];
	if (daemonCmd) {
		executeDaemonCommand(daemonCmd, trimmedArgs, ctx);
		return { handled: true };
	}

	// Unrecognized — fall through as agent prompt
	return { handled: false };
}

async function executeDaemonCommand(
	cmd: DaemonCommand,
	args: string,
	ctx: CommandContext,
): Promise<void> {
	try {
		const params = cmd.parseArgs ? cmd.parseArgs(args) : {};
		const result = await DaemonClient.send(cmd.method, params);
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
		"  /compact     Compact conversation context",
		"  /model       Show or change model",
		"  /thinking    Toggle extended thinking",
		"  /stats       Show session statistics",
		"",
		"  /spotify     Control Spotify playback",
		"  /timer       Manage timers",
		"  /reflect     Trigger memory consolidation",
		"  /reload      Reload agent prompts",
		"",
		"  /rewind      Fork from a previous turn",
		"  /clear       Clear output",
		"  /help        Show this help",
		"  /quit        Exit",
		"",
		"  Esc          Abort current response / exit",
		"  Ctrl+D       Exit",
	];
	for (const line of lines) {
		ctx.outputLog.handleInfo(line);
	}
	ctx.requestRender();
}
