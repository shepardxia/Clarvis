/**
 * Clarvis Chat TUI — Entry point.
 *
 * Connects to the daemon's ChatBridge via /tmp/clarvis-chat.sock for streaming
 * agent interaction, and to /tmp/clarvis-daemon.sock for ctools commands.
 */

import {
	type CancellableLoader,
	CombinedAutocompleteProvider,
	Container,
	isKeyRelease,
	matchesKey,
	type OverlayOptions,
	ProcessTerminal,
	TUI,
} from "@mariozechner/pi-tui";

import { spawnSync } from "node:child_process";
import { ChatClient, type ChatEvent } from "./daemon-client.js";
import { dispatchCommand, slashCommands } from "./commands.js";
import { OutputLog } from "./components/output-log.js";
import { PromptInput } from "./components/prompt-input.js";
import { createLoader } from "./components/loading.js";
import {
	type ExtensionUIRequest,
	InputDialog,
	type RewindEntry,
	RewindDialog,
	SelectDialog,
	FilterSelectDialog,
} from "./components/dialogs.js";
import { BOLD, DIM, MAGENTA, RED, RESET, YELLOW } from "./theme.js";

// ============================================================================
// CLI argument parsing
// ============================================================================

function parseArgs(): { agent?: string } {
	const args = process.argv.slice(2);
	for (let i = 0; i < args.length; i++) {
		if (args[i] === "--agent" && i + 1 < args.length) {
			return { agent: args[i + 1] };
		}
	}
	return {};
}

// ============================================================================
// Main
// ============================================================================

async function main() {
	const cliArgs = parseArgs();

	const terminal = new ProcessTerminal();
	const tui = new TUI(terminal);

	const outputLog = new OutputLog();
	const autocomplete = new CombinedAutocompleteProvider(slashCommands);
	const promptInput = new PromptInput(tui, autocomplete);
	let loader: CancellableLoader | null = null;

	const root = new Container();
	root.addChild(outputLog);
	root.addChild(promptInput);

	tui.addChild(root);
	tui.setFocus(promptInput.editor);

	// -- State --

	let isStreaming = false;
	let hasTextOutput = false;

	const dialogOverlayOptions: OverlayOptions = {
		anchor: "bottom-center",
		width: "100%",
		margin: 0,
	};

	// -- Layout management --

	function rebuildLayout(): void {
		root.clear();
		root.addChild(outputLog);
		if (isStreaming && loader) root.addChild(loader);
		root.addChild(promptInput);
		tui.setFocus(promptInput.editor);
		tui.requestRender();
	}

	function showLoading(): void {
		if (!isStreaming) {
			isStreaming = true;
			hasTextOutput = false;
			loader = createLoader(tui);
			loader.onAbort = () => {
				chatClient.send({ type: "abort" });
				outputLog.handleInfo("[aborted]");
				tui.requestRender();
			};
			loader.start();
			rebuildLayout();
		}
	}

	function hideLoading(): void {
		if (loader) {
			loader.stop();
			loader.dispose();
			loader = null;
		}
		isStreaming = false;
		rebuildLayout();
	}

	function exit(): void {
		if (loader) {
			loader.stop();
			loader.dispose();
		}
		tui.stop();
		chatClient.disconnect();
		process.exit(0);
	}

	function toggleDetail(): void {
		outputLog.toggleDetail();
		tui.requestRender(true);
	}

	// -- Extension UI dialog handling --

	function showSelectDialog(
		title: string,
		options: string[],
		onDone: (value: string | undefined) => void,
	): void {
		const dialog = new SelectDialog(title, options);
		dialog.onSelect = (value) => {
			tui.hideOverlay();
			onDone(value);
		};
		dialog.onCancel = () => {
			tui.hideOverlay();
			onDone(undefined);
		};
		tui.showOverlay(dialog, dialogOverlayOptions);
	}

	function showFilterSelectDialog(
		title: string,
		options: string[],
		onDone: (value: string | undefined) => void,
	): void {
		const dialog = new FilterSelectDialog(title, options);
		dialog.onSelect = (value) => {
			tui.hideOverlay();
			onDone(value);
		};
		dialog.onCancel = () => {
			tui.hideOverlay();
			onDone(undefined);
		};
		tui.showOverlay(dialog, dialogOverlayOptions);
	}

	function showInputDialog(
		title: string,
		prefill?: string,
		onDone?: (value: string | undefined) => void,
	): void {
		const dialog = new InputDialog(title, prefill);
		dialog.onSubmit = (value) => {
			tui.hideOverlay();
			onDone?.(value.trim() || undefined);
		};
		dialog.onEscape = () => {
			tui.hideOverlay();
			onDone?.(undefined);
		};
		dialog.onCtrlD = exit;
		tui.showOverlay(dialog, dialogOverlayOptions);
	}

	function handleExtensionUI(req: ExtensionUIRequest): void {
		const { id, method } = req;

		switch (method) {
			case "select": {
				showSelectDialog(req.title ?? "Select", req.options ?? [], (value) => {
					if (value !== undefined) {
						chatClient.send({ type: "extension_ui_response", id, value });
					} else {
						chatClient.send({ type: "extension_ui_response", id, cancelled: true });
					}
				});
				break;
			}

			case "confirm": {
				const title = req.message
					? `${req.title}: ${req.message}`
					: (req.title ?? "Confirm");
				showSelectDialog(title, ["Yes", "No"], (value) => {
					chatClient.send({
						type: "extension_ui_response",
						id,
						confirmed: value === "Yes",
					});
				});
				break;
			}

			case "input": {
				const title = req.placeholder
					? `${req.title} (${req.placeholder})`
					: (req.title ?? "Input");
				showInputDialog(title, undefined, (value) => {
					if (value !== undefined) {
						chatClient.send({ type: "extension_ui_response", id, value });
					} else {
						chatClient.send({ type: "extension_ui_response", id, cancelled: true });
					}
				});
				break;
			}

			case "editor": {
				const prefill = req.prefill?.replace(/\n/g, " ");
				showInputDialog(req.title ?? "Editor", prefill, (value) => {
					if (value !== undefined) {
						chatClient.send({ type: "extension_ui_response", id, value });
					} else {
						chatClient.send({ type: "extension_ui_response", id, cancelled: true });
					}
				});
				break;
			}

			case "notify": {
				const notifyType = req.notifyType ?? "info";
				const color =
					notifyType === "error" ? RED : notifyType === "warning" ? YELLOW : MAGENTA;
				outputLog.append(`${color}${BOLD}Notification:${RESET} ${req.message}`);
				tui.requestRender();
				break;
			}

			case "setStatus":
				outputLog.append(
					`${MAGENTA}${BOLD}Notification:${RESET} ${DIM}[status: ${req.statusKey}]${RESET} ${req.statusText ?? "(cleared)"}`,
				);
				tui.requestRender();
				break;

			case "setWidget": {
				const lines = req.widgetLines;
				if (lines && lines.length > 0) {
					outputLog.append(
						`${MAGENTA}${BOLD}Notification:${RESET} ${DIM}[widget: ${req.widgetKey}]${RESET}`,
					);
					for (const wl of lines) {
						outputLog.append(`  ${DIM}${wl}${RESET}`);
					}
					tui.requestRender();
				}
				break;
			}

			case "set_editor_text":
				promptInput.editor.setText(req.text ?? "");
				tui.requestRender();
				break;
		}
	}

	// -- History rendering --

	function extractText(msg: Record<string, unknown>): string {
		// Pi messages use content: [{type: "text", text: "..."}] (API format)
		const content = msg.content;
		let text: string;
		if (typeof content === "string") {
			text = content;
		} else if (Array.isArray(content)) {
			text = content
				.filter((c: Record<string, unknown>) => c.type === "text")
				.map((c: Record<string, unknown>) => c.text as string)
				.join("");
		} else {
			text = (msg.text as string) ?? "";
		}
		return text;
	}

	/** Strip injected context (memory grounding, ambient) from user messages */
	function stripContext(text: string): string {
		let stripped = text;
		// Remove <memory_context>...</memory_context> blocks
		stripped = stripped.replace(/<memory_context>[\s\S]*?<\/memory_context>/g, "");
		// Remove ambient context lines (date/time, weather/location)
		stripped = stripped.replace(/^\s*\w+day,\s+\w+\s+\d+,\s+\d+:\d+[ap]m\s*/im, "");
		stripped = stripped.replace(/^\s*[\d.]+°?F\s+.*?\(.*?\)\s*/im, "");
		return stripped.trim();
	}

	function renderHistory(messages: unknown[]): void {
		outputLog.clear();
		for (const msg of messages) {
			const m = msg as Record<string, unknown>;
			const role = m.role as string;
			const raw = extractText(m);
			if (!raw) continue;
			const text = role === "user" ? stripContext(raw) : raw;
			if (!text) continue;
			if (role === "user") {
				outputLog.appendUserMessage(text);
			} else if (role === "assistant") {
				outputLog.appendMarkdown(text);
			}
		}
		outputLog.append("");
		tui.requestRender();
	}

	// -- Rewind/fork flow --

	async function handleRewind(): Promise<void> {
		try {
			const resp = await chatClient.request({ type: "get_fork_messages" });
			const messages = resp.messages as Array<Record<string, unknown>> | undefined;
			if (!messages || messages.length === 0) {
				outputLog.handleInfo("No messages to rewind to.");
				tui.requestRender();
				return;
			}

			const entries: RewindEntry[] = messages.map((m) => {
				const raw = extractText(m);
				const text = (m.role === "user" ? stripContext(raw) : raw).trim();
				return {
					entryId: m.entryId as string,
					role: m.role as string,
					text,
				};
			});

			const dialog = new RewindDialog(entries);

			dialog.onSelect = async (entry) => {
				tui.hideOverlay();
				outputLog.handleInfo("[rewinding...]");
				tui.requestRender();

				try {
					const forkResp = await chatClient.request(
						{ type: "fork", entryId: entry.entryId },
					);
					const text = forkResp.text as string | undefined;
					if (text) {
						promptInput.editor.setText(text);
					}
					tui.requestRender();
				} catch (err) {
					const msg = err instanceof Error ? err.message : String(err);
					outputLog.handleError(`Fork failed: ${msg}`);
					tui.requestRender();
				}
			};

			dialog.onCancel = () => {
				tui.hideOverlay();
			};

			tui.showOverlay(dialog, dialogOverlayOptions);
		} catch (err) {
			const msg = err instanceof Error ? err.message : String(err);
			outputLog.handleError(`Rewind failed: ${msg}`);
			tui.requestRender();
		}
	}

	// -- Chat socket event handler --

	function handleChatEvent(event: ChatEvent): void {
		const type = event.type as string;

		if (type === "agent_start") {
			showLoading();
			return;
		}

		if (type === "extension_ui_request") {
			handleExtensionUI(event as unknown as ExtensionUIRequest);
			return;
		}

		if (type === "message_update") {
			const evt = event.assistantMessageEvent as Record<string, unknown> | undefined;
			if (evt?.type === "text_delta") {
				if (!hasTextOutput) {
					hasTextOutput = true;
					outputLog.startResponseBlock();
				}
				outputLog.handleTextDelta(evt.delta as string);
				tui.requestRender();
			} else if (evt?.type === "thinking" || evt?.type === "thinking_delta") {
				const delta = (evt.thinking ?? evt.delta ?? "") as string;
				if (delta) {
					outputLog.handleThinkingDelta(delta);
					tui.requestRender();
				}
			}
			return;
		}

		if (type === "tool_execution_start") {
			outputLog.handleToolStart(
				event.toolName as string,
				event.toolInput as Record<string, unknown> | undefined,
			);
			tui.requestRender();
			return;
		}

		if (type === "tool_execution_end") {
			outputLog.handleToolEnd(
				event.toolName as string,
				event.result,
			);
			tui.requestRender();
			return;
		}

		if (type === "agent_end") {
			outputLog.handleAgentEnd();
			hideLoading();
			return;
		}

		if (type === "error") {
			outputLog.handleError(event.message as string);
			hideLoading();
			return;
		}

		if (type === "state") {
			if (event.agent_busy) {
				const owner = event.owner ? ` (${event.owner})` : "";
				outputLog.handleInfo(`Agent busy${owner}`);
				tui.requestRender();
			}
			return;
		}

		if (type === "history") {
			const messages = event.messages as unknown[];
			if (messages) {
				renderHistory(messages);
			}
			return;
		}

		if (type === "init_ack") {
			const agent = event.agent as string | undefined;
			const userName = event.user_name as string | undefined;
			if (agent) {
				outputLog.agentLabel = agent.charAt(0).toUpperCase() + agent.slice(1);
			}
			if (userName) {
				outputLog.userLabel = userName;
			}
			outputLog.append(`${DIM}Connected as ${agent ?? "clarvis"}.${RESET}`);
			tui.requestRender();
			return;
		}

		if (type === "response" && event.success === false) {
			outputLog.handleError(`${event.command}: ${event.error}`);
			tui.requestRender();
			return;
		}
	}

	// -- Chat client --

	const chatClient = new ChatClient(handleChatEvent, () => {
		outputLog.handleError("Disconnected from daemon. Is clarvis running?");
		tui.requestRender();
	});

	// -- User input --

	promptInput.onSubmit = (value: string) => {
		const trimmed = value.trim();
		if (!trimmed) return;

		promptInput.editor.setText("");
		promptInput.editor.addToHistory(trimmed);

		// Try slash command dispatch
		const result = dispatchCommand(trimmed, {
			chatClient,
			outputLog,
			onClear: () => {
				outputLog.clear();
				tui.requestRender();
			},
			onQuit: exit,
			onRewind: () => { handleRewind(); },
			requestRender: () => tui.requestRender(),
			showSelect: showSelectDialog,
			showFilterSelect: showFilterSelectDialog,
		});

		// Only show user input for unhandled commands (agent prompts)
		if (!result.handled) {
			outputLog.appendUserMessage(trimmed);
			chatClient.send({ type: "prompt", message: trimmed });
			tui.requestRender();
		}
	};

	promptInput.onCtrlD = exit;

	// Escape: abort if streaming, double-tap to rewind. Ctrl+D to quit.
	let escPressCount = 0;
	let escResetTimer: ReturnType<typeof setTimeout> | null = null;
	tui.addInputListener((data: string) => {
		if (isKeyRelease(data)) return undefined;
		if (matchesKey(data, "escape") && !tui.hasOverlay() && !promptInput.editor.isShowingAutocomplete()) {
			if (isStreaming) {
				chatClient.send({ type: "abort" });
				outputLog.handleInfo("[aborted]");
				tui.requestRender();
			} else {
				escPressCount++;
				if (escResetTimer) clearTimeout(escResetTimer);
				if (escPressCount >= 2) {
					escPressCount = 0;
					handleRewind();
				} else {
					escResetTimer = setTimeout(() => { escPressCount = 0; }, 600);
				}
			}
			return { consume: true };
		}
		if (matchesKey(data, "ctrl+l")) {
			toggleDetail();
			return { consume: true };
		}
		if (matchesKey(data, "ctrl+d")) {
			exit();
			return { consume: true };
		}
		return undefined;
	});

	// -- Connect and start --

	const agentLabel = cliArgs.agent ? ` (${cliArgs.agent})` : "";
	outputLog.append(`${BOLD}Clarvis Chat${agentLabel}${RESET}`);
	outputLog.append(
		`${DIM}Type a message and press Enter. Esc to abort, Esc×2 to rewind, Ctrl+L to expand tool output, Ctrl+D to quit.${RESET}`,
	);
	outputLog.append("");

	tui.start();

	try {
		await chatClient.connect();
		outputLog.append(`${DIM}Connected to daemon.${RESET}`);
		chatClient.send({ type: "get_state" });

		// Always send init to get agent + user names from daemon config
		const initResp = await chatClient.request({ type: "init", agent: cliArgs.agent ?? "clarvis" });
		const initAgent = initResp.agent as string | undefined;
		const initUserName = initResp.user_name as string | undefined;
		if (initAgent) {
			outputLog.agentLabel = initAgent.charAt(0).toUpperCase() + initAgent.slice(1);
		}
		if (initUserName) {
			outputLog.userLabel = initUserName;
			promptInput.userLabel = initUserName;
		}
		outputLog.append(`${DIM}Connected as ${initAgent ?? "clarvis"}.${RESET}`);

		chatClient.send({ type: "get_messages" });
		tui.requestRender();
	} catch {
		outputLog.handleError(
			"Could not connect to daemon. Is clarvis running? (clarvis start)",
		);
		tui.requestRender();
	}
}

main().catch((err) => {
	console.error(err);
	process.exit(1);
});
