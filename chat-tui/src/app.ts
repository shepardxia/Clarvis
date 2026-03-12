/**
 * Application shell — owns TUI components, layout, overlays, and lifecycle.
 *
 * Central coordination point that replaces the closure-heavy main() function.
 * Event handlers, commands, and context utilities are pure functions that
 * receive App rather than a bag of captured variables.
 */

import {
	type CancellableLoader,
	type Component,
	CombinedAutocompleteProvider,
	Container,
	isKeyRelease,
	matchesKey,
	type OverlayOptions,
	type TUI,
} from "@mariozechner/pi-tui";

import { ChatClient } from "./daemon-client.js";
import { dispatchCommand, handleRewind, slashCommands } from "./commands.js";
import { handleChatEvent } from "./event-handler.js";
import { OutputLog } from "./components/output-log.js";
import { PromptInput } from "./components/prompt-input.js";
import { createLoader } from "./components/loading.js";
import { FilterSelectDialog, InputDialog, SelectDialog } from "./components/dialogs.js";
import { BOLD, CYAN, DIM, RESET } from "./theme.js";

const DIALOG_OVERLAY: OverlayOptions = {
	anchor: "bottom-center",
	width: "100%",
	margin: 0,
};

export class App {
	readonly tui: TUI;
	readonly output: OutputLog;
	readonly prompt: PromptInput;
	readonly chatClient: ChatClient;

	private root: Container;
	private loader: CancellableLoader | null = null;

	isStreaming = false;
	queuedMessages: string[] = [];

	constructor(tui: TUI) {
		this.tui = tui;
		this.output = new OutputLog();
		const autocomplete = new CombinedAutocompleteProvider(slashCommands);
		this.prompt = new PromptInput(tui, autocomplete);

		this.root = new Container();
		this.root.addChild(this.output);
		this.root.addChild(this.prompt);
		tui.addChild(this.root);
		tui.setFocus(this.prompt.editor);

		this.chatClient = new ChatClient(
			(event) => handleChatEvent(this, event),
			() => {
				this.output.handleError("Disconnected from daemon. Is clarvis running?");
				this.requestRender();
			},
		);

		this.setupInput();
	}

	// -- Layout --

	rebuildLayout(): void {
		this.root.clear();
		this.root.addChild(this.output);
		if (this.isStreaming && this.loader) this.root.addChild(this.loader);
		if (this.queuedMessages.length > 0) {
			this.root.addChild(this.queueDisplay);
		}
		this.root.addChild(this.prompt);
		this.tui.setFocus(this.prompt.editor);
		this.tui.requestRender();
	}

	private get queueDisplay(): Component {
		const lines: string[] = [];
		const rule = `${DIM}${"─".repeat(40)}${RESET}`;
		lines.push(rule);
		for (const msg of this.queuedMessages) {
			lines.push(`${CYAN}❯${RESET} ${msg}`);
		}
		lines.push(`${DIM}❯ Press up to edit queued messages${RESET}`);
		lines.push(rule);

		// Create a simple component that renders static lines
		return {
			render(width: number): string[] {
				return lines;
			},
		} as Component;
	}

	requestRender(full = false): void {
		this.tui.requestRender(full);
	}

	// -- Loading state --

	showLoading(): void {
		if (this.isStreaming) return;
		this.isStreaming = true;
		this.loader = createLoader(this.tui);
		this.loader.onAbort = () => this.abort();
		this.loader.start();
		this.rebuildLayout();
	}

	abort(): void {
		if (this.queuedMessages.length > 0) {
			this.chatClient.send({ type: "abort", steer: true });
			this.output.handleInfo("[steering to queued message]");
		} else {
			this.chatClient.send({ type: "abort" });
			this.output.handleInfo("[aborted]");
		}
		this.requestRender();
	}

	setLoadingMessage(msg: string): void {
		this.loader?.setMessage(msg);
	}

	hideLoading(): void {
		if (this.loader) {
			this.loader.stop();
			this.loader.dispose();
			this.loader = null;
		}
		this.isStreaming = false;
		this.rebuildLayout();
	}

	// -- Overlays --

	showOverlay(component: Component, options?: OverlayOptions): void {
		this.tui.showOverlay(component, options ?? DIALOG_OVERLAY);
	}

	hideOverlay(): void {
		this.tui.hideOverlay();
	}

	hasOverlay(): boolean {
		return this.tui.hasOverlay();
	}

	showSelect(title: string, options: string[], onDone: (value: string | undefined) => void): void {
		const dialog = new SelectDialog(title, options);
		dialog.onSelect = (value) => { this.hideOverlay(); onDone(value); };
		dialog.onCancel = () => { this.hideOverlay(); onDone(undefined); };
		this.showOverlay(dialog);
	}

	showFilterSelect(title: string, options: string[], onDone: (value: string | undefined) => void): void {
		const dialog = new FilterSelectDialog(title, options);
		dialog.onSelect = (value) => { this.hideOverlay(); onDone(value); };
		dialog.onCancel = () => { this.hideOverlay(); onDone(undefined); };
		this.showOverlay(dialog);
	}

	showInput(title: string, prefill?: string, onDone?: (value: string | undefined) => void): void {
		const dialog = new InputDialog(title, prefill);
		dialog.onSubmit = (value) => { this.hideOverlay(); onDone?.(value.trim() || undefined); };
		dialog.onEscape = () => { this.hideOverlay(); onDone?.(undefined); };
		dialog.onCtrlD = () => this.exit();
		this.showOverlay(dialog);
	}

	// -- Lifecycle --

	exit(): void {
		if (this.loader) {
			this.loader.stop();
			this.loader.dispose();
		}
		if (process.env.TERM_PROGRAM === "iTerm.app") {
			process.stdout.write("\x1b]50;SetProfile=Default\x07");
		}
		this.tui.stop();
		this.chatClient.disconnect();
		process.exit(0);
	}

	async start(agent?: string): Promise<void> {
		this.tui.start();
		this.tui.terminal.clearScreen();

		if (process.env.TERM_PROGRAM === "iTerm.app") {
			process.stdout.write("\x1b]50;SetProfile=ClarvisChat\x07");
		}

		const agentLabel = agent ? ` (${agent})` : "";
		this.output.append(`${BOLD}Clarvis Chat${agentLabel}${RESET}`);
		this.output.append(
			`${DIM}Type a message and press Enter. Esc to abort, Esc×2 to rewind, Ctrl+L to expand tool output, Ctrl+D to quit.${RESET}`,
		);
		this.output.append("");

		try {
			await this.chatClient.connect();
			this.output.append(`${DIM}Connected to daemon.${RESET}`);
			this.chatClient.send({ type: "get_state" });

			const initResp = await this.chatClient.request({
				type: "init",
				agent: agent ?? "clarvis",
			});
			const initAgent = initResp.agent as string | undefined;
			const initUserName = initResp.user_name as string | undefined;
			if (initAgent) {
				this.output.agentLabel = initAgent.charAt(0).toUpperCase() + initAgent.slice(1);
			}
			if (initUserName) {
				this.output.userLabel = initUserName;
				this.prompt.userLabel = initUserName;
			}
			this.output.append(`${DIM}Connected as ${initAgent ?? "clarvis"}.${RESET}`);

			this.chatClient.send({ type: "get_messages" });
			this.requestRender();
		} catch {
			this.output.handleError(
				"Could not connect to daemon. Is clarvis running? (clarvis start)",
			);
			this.requestRender();
		}
	}

	// -- Private --

	private setupInput(): void {
		this.prompt.onSubmit = (value: string) => {
			const trimmed = value.trim();
			if (!trimmed) return;

			this.prompt.editor.setText("");
			this.prompt.editor.addToHistory(trimmed);

			// If streaming, queue the message instead of sending
			if (this.isStreaming) {
				this.chatClient.send({ type: "prompt", message: trimmed });
				// Bridge will queue it and send back a "queued" event
				return;
			}

			const result = dispatchCommand(trimmed, this);
			if (!result.handled) {
				this.output.appendUserMessage(trimmed);
				this.chatClient.send({ type: "prompt", message: trimmed });
				this.requestRender();
			}
		};

		this.prompt.onCtrlD = () => this.exit();

		let escPressCount = 0;
		let escResetTimer: ReturnType<typeof setTimeout> | null = null;

		this.tui.addInputListener((data: string) => {
			if (isKeyRelease(data)) return undefined;

			if (matchesKey(data, "escape") && !this.hasOverlay() && !this.prompt.editor.isShowingAutocomplete()) {
				if (this.isStreaming) {
					this.abort();
				} else {
					escPressCount++;
					if (escResetTimer) clearTimeout(escResetTimer);
					if (escPressCount >= 2) {
						escPressCount = 0;
						handleRewind(this);
					} else {
						escResetTimer = setTimeout(() => { escPressCount = 0; }, 600);
					}
				}
				return { consume: true };
			}

			// Up arrow with empty editor + queued messages → dequeue
			if (matchesKey(data, "up") && this.queuedMessages.length > 0 && !this.prompt.editor.getText()) {
				this.chatClient.send({ type: "dequeue" });
				return { consume: true };
			}

			if (matchesKey(data, "ctrl+l")) {
				this.output.toggleDetail();
				this.requestRender(true);
				return { consume: true };
			}

			if (matchesKey(data, "ctrl+d")) {
				this.exit();
				return { consume: true };
			}

			return undefined;
		});
	}
}
