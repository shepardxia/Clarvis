/**
 * Message text extraction and history rendering utilities.
 *
 * Handles extracting display text from Pi API messages and rendering
 * conversation history with full tool context into the output log.
 */

import type { OutputLog } from "./components/output-log.js";

/** Extract display text from a Pi API message (handles string and content array formats) */
export function extractText(msg: Record<string, unknown>): string {
	const content = msg.content;
	if (typeof content === "string") return content;
	if (Array.isArray(content)) {
		return content
			.filter((c: Record<string, unknown>) => c.type === "text")
			.map((c: Record<string, unknown>) => c.text as string)
			.join("");
	}
	return (msg.text as string) ?? "";
}

/** Render message history into the output log, including tool context */
export function renderHistory(output: OutputLog, messages: unknown[]): void {
	output.clear();
	for (const msg of messages) {
		const m = msg as Record<string, unknown>;
		const role = m.role as string;
		const content = m.content;

		if (role === "assistant" && Array.isArray(content)) {
			// Process content blocks: text blocks and tool_use blocks
			let firstText = true;
			for (const block of content) {
				const b = block as Record<string, unknown>;
				if (b.type === "text") {
					const text = (b.text as string) ?? "";
					if (!text) continue;
					if (firstText) {
						output.appendMarkdown(text);
						firstText = false;
					} else {
						output.appendMarkdownContinuation(text);
					}
				} else if (b.type === "tool_use") {
					const name = (b.name as string) ?? "tool";
					const input = b.input as Record<string, unknown> | undefined;
					output.handleToolStart(name, input);
				}
			}
		} else if (role === "user" && Array.isArray(content)) {
			// Process content blocks: text blocks and tool_result blocks
			for (const block of content) {
				const b = block as Record<string, unknown>;
				if (b.type === "text") {
					const text = (b.text as string) ?? "";
					if (!text) continue;
					output.appendUserMessage(text);
				} else if (b.type === "tool_result") {
					const name = (b.tool_name ?? b.name ?? "tool") as string;
					const resultContent = b.content;
					output.handleToolEnd(name, resultContent);
				}
			}
		} else {
			// Non-array content: simple text extraction
			const raw = extractText(m);
			if (!raw) continue;
			if (role === "user") {
				output.appendUserMessage(raw);
			} else if (role === "assistant") {
				output.appendMarkdown(raw);
			}
		}
	}
	output.append("");
}
