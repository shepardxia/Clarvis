/**
 * Message text extraction and context stripping utilities.
 *
 * Handles extracting display text from Pi API messages and removing
 * injected context (memory grounding, ambient) from user messages.
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

/** Strip injected context (memory grounding, ambient) from user messages */
export function stripContext(text: string): string {
	let stripped = text;
	// Remove <memory_context>...</memory_context> blocks
	stripped = stripped.replace(/<memory_context>[\s\S]*?<\/memory_context>/g, "");
	// Remove ambient context lines (date/time, weather/location)
	stripped = stripped.replace(/^\s*\w+day,\s+\w+\s+\d+,\s+\d+:\d+[ap]m\s*/im, "");
	stripped = stripped.replace(/^\s*[\d.]+°?F\s+.*?\(.*?\)\s*/im, "");
	return stripped.trim();
}

/** Render message history into the output log */
export function renderHistory(output: OutputLog, messages: unknown[]): void {
	output.clear();
	for (const msg of messages) {
		const m = msg as Record<string, unknown>;
		const role = m.role as string;
		const raw = extractText(m);
		if (!raw) continue;
		const text = role === "user" ? stripContext(raw) : raw;
		if (!text) continue;
		if (role === "user") {
			output.appendUserMessage(text);
		} else if (role === "assistant") {
			output.appendMarkdown(text);
		}
	}
	output.append("");
}
