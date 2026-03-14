/**
 * Chat event routing and extension UI handling.
 *
 * Translates incoming ChatBridge events into OutputLog updates,
 * loading state changes, and extension UI dialog flows.
 */

import type { ChatEvent } from "./daemon-client.js";
import type { App } from "./app.js";
import type { ExtensionUIRequest } from "./components/dialogs.js";
import { BOLD, DIM, MAGENTA, RED, RESET, YELLOW } from "./theme.js";
import { renderHistory } from "./context.js";

/** Route a single chat event to the appropriate App/OutputLog handler */
export function handleChatEvent(app: App, event: ChatEvent): void {
	const type = event.type as string;

	switch (type) {
		case "agent_start":
			app.showLoading();
			return;

		case "extension_ui_request":
			handleExtensionUI(app, event as unknown as ExtensionUIRequest);
			return;

		case "message_update": {
			const evt = event.assistantMessageEvent as Record<string, unknown> | undefined;
			if (evt?.type === "text_delta") {
				if (!app.output.hasActiveResponse) {
					app.output.startResponseBlock();
					app.setLoadingMessage("RESPONDING...");
				}
				app.output.handleTextDelta(evt.delta as string);
				app.requestRender();
			} else if (evt?.type === "thinking" || evt?.type === "thinking_delta") {
				const delta = (evt.thinking ?? evt.delta ?? "") as string;
				if (delta) {
					app.output.handleThinkingDelta(delta);
					app.requestRender();
				}
			}
			return;
		}

		case "tool_execution_start": {
			const toolName = (event.toolName ?? event.tool_name) as string;
			app.output.handleToolStart(
				toolName,
				(event.toolInput ?? event.tool_input ?? event.args) as Record<string, unknown> | undefined,
			);
			app.setLoadingMessage(`RUNNING ${toolName}...`);
			app.requestRender();
			return;
		}

		case "tool_execution_end":
			app.output.handleToolEnd(
				(event.toolName ?? event.tool_name) as string,
				event.result,
			);
			app.setLoadingMessage("THINKING...");
			app.requestRender();
			return;

		case "agent_end":
			app.output.handleAgentEnd();
			app.hideLoading();
			return;

		case "error":
			app.output.handleError(event.message as string);
			app.hideLoading();
			return;

		case "state":
			if (event.agent_busy) {
				const owner = event.owner ? ` (${event.owner})` : "";
				app.output.handleInfo(`AGENT BUSY${owner}`);
				app.requestRender();
			}
			return;

		case "history": {
			const messages = event.messages as unknown[];
			if (messages) {
				renderHistory(app.output, messages);
				app.requestRender();
			}
			return;
		}

		case "queued":
			app.queuedMessages = (event.messages as string[]) ?? [];
			app.rebuildLayout();
			return;

		case "dequeued": {
			const text = (event.text as string) ?? "";
			app.queuedMessages = [];
			app.prompt.editor.setText(text);
			app.rebuildLayout();
			return;
		}

		case "queued_sent": {
			// Queued messages were auto-sent after agent finished
			const sent = (event.text as string) ?? "";
			app.queuedMessages = [];
			if (sent) app.output.appendUserMessage(sent);
			app.rebuildLayout();
			return;
		}

		case "session_reset":
			app.output.clear();
			app.output.handleInfo("[SESSION RESET]");
			app.requestRender();
			return;

		case "response":
			if (event.success === false) {
				app.output.handleError(`${event.command}: ${event.error}`);
				app.requestRender();
			}
			return;
	}
}

/** Send an extension UI response — value or cancelled */
function sendUIResponse(app: App, id: string, value: string | undefined): void {
	if (value !== undefined) {
		app.chatClient.send({ type: "extension_ui_response", id, value });
	} else {
		app.chatClient.send({ type: "extension_ui_response", id, cancelled: true });
	}
}

/** Handle extension UI requests by spawning the appropriate dialog */
function handleExtensionUI(app: App, req: ExtensionUIRequest): void {
	const { id, method } = req;

	switch (method) {
		case "select":
			app.showSelect(req.title ?? "Select", req.options ?? [], (value) => {
				sendUIResponse(app, id, value);
			});
			break;

		case "confirm": {
			const title = req.message
				? `${req.title}: ${req.message}`
				: (req.title ?? "Confirm");
			app.showSelect(title, ["Yes", "No"], (value) => {
				app.chatClient.send({
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
			app.showInput(title, undefined, (value) => {
				sendUIResponse(app, id, value);
			});
			break;
		}

		case "editor": {
			const prefill = req.prefill?.replace(/\n/g, " ");
			app.showInput(req.title ?? "Editor", prefill, (value) => {
				sendUIResponse(app, id, value);
			});
			break;
		}

		case "notify": {
			const notifyType = req.notifyType ?? "info";
			const color = notifyType === "error" ? RED : notifyType === "warning" ? YELLOW : MAGENTA;
			app.output.append(`${color}${BOLD}Notification:${RESET} ${req.message}`);
			app.requestRender();
			break;
		}

		case "setStatus":
			app.output.append(
				`${MAGENTA}${BOLD}Notification:${RESET} ${DIM}[status: ${req.statusKey}]${RESET} ${req.statusText ?? "(cleared)"}`,
			);
			app.requestRender();
			break;

		case "setWidget": {
			const lines = req.widgetLines;
			if (lines && lines.length > 0) {
				app.output.append(
					`${MAGENTA}${BOLD}Notification:${RESET} ${DIM}[widget: ${req.widgetKey}]${RESET}`,
				);
				for (const wl of lines) {
					app.output.append(`  ${DIM}${wl}${RESET}`);
				}
				app.requestRender();
			}
			break;
		}

		case "set_editor_text":
			app.prompt.editor.setText(req.text ?? "");
			app.requestRender();
			break;
	}
}
