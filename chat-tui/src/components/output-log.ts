/**
 * Scrolling output log for agent responses, tool executions, and system messages.
 *
 * Agent text responses are rendered via pi-tui's Markdown component for styled
 * output (code blocks, headings, lists, etc.). Other lines (tool output, errors,
 * info messages) are rendered as raw ANSI-styled text.
 *
 * Tool executions are stored as collapsible segments. Toggle detail mode with
 * /detail to expand tool output (compact: 5 lines, detail: up to 200 lines).
 */

import { type Component, Markdown, type MarkdownTheme, truncateToWidth } from "@mariozechner/pi-tui";
import {
	BLUE, BOLD, CYAN, DIM, GREEN, ITALIC, MAGENTA, RED, RESET, STRIKETHROUGH,
	UNDERLINE, YELLOW,
} from "../theme.js";

const markdownTheme: MarkdownTheme = {
	heading: (t) => `${BOLD}${BLUE}${t}${RESET}`,
	link: (t) => `${CYAN}${t}${RESET}`,
	linkUrl: (t) => `${DIM}${t}${RESET}`,
	code: (t) => `${YELLOW}${t}${RESET}`,
	codeBlock: (t) => `${t}`,
	codeBlockBorder: (t) => `${DIM}${t}${RESET}`,
	quote: (t) => `${DIM}${ITALIC}${t}${RESET}`,
	quoteBorder: (t) => `${DIM}${t}${RESET}`,
	hr: (t) => `${DIM}${t}${RESET}`,
	listBullet: (t) => `${CYAN}${t}${RESET}`,
	bold: (t) => `${BOLD}${t}${RESET}`,
	italic: (t) => `${ITALIC}${t}${RESET}`,
	strikethrough: (t) => `${STRIKETHROUGH}${t}${RESET}`,
	underline: (t) => `${UNDERLINE}${t}${RESET}`,
};

/** Compact mode: max lines of tool output body to show */
const COMPACT_LINES = 5;
/** Detail mode: max lines of tool output body to show */
const DETAIL_LINES = 200;

/**
 * A segment in the output log — raw line, Markdown block, or collapsible tool output.
 */
type Segment =
	| { kind: "line"; text: string }
	| { kind: "markdown"; component: Markdown; buffer: string }
	| { kind: "tool"; header: string; lines: string[] }
	| { kind: "thinking"; buffer: string };

export class OutputLog implements Component {
	private segments: Segment[] = [];
	private maxSegments = 2000;
	agentLabel = "Clarvis";
	userLabel = "You";
	detailMode = false;

	/** Append a raw styled line */
	append(line: string): void {
		this.segments.push({ kind: "line", text: line });
		this.trimSegments();
	}

	/** Append a user message with styled prefix */
	appendUserMessage(text: string): void {
		this.append("");
		this.append(`${GREEN}${BOLD}${this.userLabel}:${RESET}`);
		this.addMarkdownSegment(text);
	}

	/** Append a complete Markdown block (for history replay) */
	appendMarkdown(text: string): void {
		this.append("");
		this.append(`${BLUE}${BOLD}${this.agentLabel}:${RESET}`);
		this.addMarkdownSegment(text);
	}

	/** Clear all output */
	clear(): void {
		this.segments = [];
	}

	/** Toggle between compact and detail mode for tool output */
	toggleDetail(): boolean {
		this.detailMode = !this.detailMode;
		return this.detailMode;
	}

	invalidate(): void {
		for (const seg of this.segments) {
			if (seg.kind === "markdown") seg.component.invalidate();
		}
	}

	render(width: number): string[] {
		const result: string[] = [];
		for (const seg of this.segments) {
			if (seg.kind === "line") {
				result.push(truncateToWidth(seg.text, width));
			} else if (seg.kind === "markdown") {
				result.push(...seg.component.render(width));
			} else if (seg.kind === "tool") {
				// Tool segment — render header + body based on detail mode
				result.push(truncateToWidth(seg.header, width));
				if (seg.lines.length > 0) {
					const cap = this.detailMode ? DETAIL_LINES : COMPACT_LINES;
					const max = Math.min(seg.lines.length, cap);
					for (let i = 0; i < max; i++) {
						result.push(truncateToWidth(seg.lines[i], width));
					}
					const remaining = seg.lines.length - max;
					if (remaining > 0) {
						result.push(`${DIM}  [+${remaining} lines — Ctrl+L to expand]${RESET}`);
					}
				}
			} else if (seg.kind === "thinking") {
				const lines = seg.buffer.split("\n");
				result.push(`${DIM}${ITALIC}[thinking]${RESET}`);
				const cap = this.detailMode ? DETAIL_LINES : COMPACT_LINES;
				const max = Math.min(lines.length, cap);
				for (let i = 0; i < max; i++) {
					result.push(truncateToWidth(`${DIM}${ITALIC}${lines[i]}${RESET}`, width));
				}
				if (lines.length > max) {
					result.push(`${DIM}  [+${lines.length - max} lines — Ctrl+L to expand]${RESET}`);
				}
			}
		}
		if (result.length === 0) return [""];
		return result;
	}

	/** Render all output with tool bodies fully expanded, ANSI stripped. For pager. */
	getAllText(width: number): string {
		const strip = (s: string) => s.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, "");
		const lines: string[] = [];
		for (const seg of this.segments) {
			if (seg.kind === "line") {
				lines.push(strip(seg.text));
			} else if (seg.kind === "markdown") {
				for (const ml of seg.component.render(width)) {
					lines.push(strip(ml));
				}
			} else if (seg.kind === "tool") {
				lines.push(strip(seg.header));
				for (const tl of seg.lines) {
					lines.push(strip(tl));
				}
			} else if (seg.kind === "thinking") {
				lines.push("[thinking]");
				for (const tl of seg.buffer.split("\n")) {
					lines.push(tl);
				}
			}
		}
		return lines.join("\n");
	}

	// -- Event handlers for Pi RPC events --

	handleAgentStart(): void {
		// Prepare for new response
	}

	/** Start a new agent response block — creates a Markdown segment */
	startResponseBlock(): void {
		this.append("");
		this.append(`${BLUE}${BOLD}${this.agentLabel}:${RESET}`);
		this.addMarkdownSegment("");
	}

	/** Append streaming text delta to the current Markdown block */
	handleTextDelta(delta: string): void {
		const last = this.segments[this.segments.length - 1];
		if (last?.kind === "markdown") {
			last.buffer += delta;
			last.component.setText(last.buffer);
		} else {
			// After tool output, last segment is a "line" or "tool" — start a new
			// markdown block to continue accumulating text (no header, continuation)
			this.addMarkdownSegment(delta);
		}
	}

	/** Append streaming thinking delta */
	handleThinkingDelta(delta: string): void {
		const last = this.segments[this.segments.length - 1];
		if (last?.kind === "thinking") {
			last.buffer += delta;
		} else {
			this.segments.push({ kind: "thinking", buffer: delta });
			this.trimSegments();
		}
	}

	handleToolStart(toolName: string, toolInput?: Record<string, unknown>): void {
		const header = this.buildToolHeader(toolName, toolInput);
		this.segments.push({ kind: "tool", header, lines: [] });
		this.trimSegments();
	}

	handleToolEnd(toolName: string, result: unknown): void {
		const lines = this.extractResultLines(toolName, result);
		// Fill the last empty tool segment (matches the corresponding start)
		for (let i = this.segments.length - 1; i >= 0; i--) {
			const seg = this.segments[i];
			if (seg.kind === "tool" && seg.lines.length === 0) {
				seg.lines = lines;
				return;
			}
		}
		// Fallback: no matching start, create standalone
		this.segments.push({ kind: "tool", header: `${DIM}[${toolName}]${RESET}`, lines });
	}

	handleAgentEnd(): void {
		this.append("");
	}

	handleError(message: string): void {
		this.append(`${RED}${BOLD}Error:${RESET} ${message}`);
	}

	handleInfo(message: string): void {
		this.append(`${YELLOW}${message}${RESET}`);
	}

	// -- Private helpers --

	private buildToolHeader(toolName: string, toolInput?: Record<string, unknown>): string {
		switch (toolName) {
			case "bash":
			case "Bash": {
				const cmd = toolInput?.command as string | undefined;
				if (!cmd) return `${DIM}[bash]${RESET}`;

				// Parse ctools commands for cleaner display
				const ctoolsMatch = cmd.match(/^ctools\s+(\S+)(?:\s+(.*))?/);
				if (ctoolsMatch) {
					const [, method, rawArgs] = ctoolsMatch;
					if (rawArgs) {
						// Try to extract meaningful params from JSON args
						try {
							const parsed = JSON.parse(rawArgs.replace(/^'|'$/g, ""));
							const brief = Object.entries(parsed)
								.slice(0, 3)
								.map(([k, v]) => {
									const vs = typeof v === "string" ? v : JSON.stringify(v);
									return `${k}=${vs.length > 40 ? vs.slice(0, 40) + "…" : vs}`;
								})
								.join(" ");
							return `${DIM}[ctools ${method}] ${brief}${RESET}`;
						} catch {
							// Not JSON, show raw
							const brief = rawArgs.length > 60 ? rawArgs.slice(0, 60) + "…" : rawArgs;
							return `${DIM}[ctools ${method}] ${brief}${RESET}`;
						}
					}
					return `${DIM}[ctools ${method}]${RESET}`;
				}

				// Regular bash command
				const brief = cmd.length > 80 ? cmd.slice(0, 80) + "…" : cmd;
				return `${DIM}$ ${brief}${RESET}`;
			}
			case "Read":
			case "read": {
				const path = toolInput?.file_path as string | undefined;
				return `${DIM}[reading ${path ?? "file"}]${RESET}`;
			}
			case "Edit":
			case "edit": {
				const path = toolInput?.file_path as string | undefined;
				return `${DIM}[editing ${path ?? "file"}]${RESET}`;
			}
			case "Write":
			case "write": {
				const path = toolInput?.file_path as string | undefined;
				return `${DIM}[writing ${path ?? "file"}]${RESET}`;
			}
			default:
				return `${DIM}[${toolName}]${RESET}`;
		}
	}

	private extractResultLines(toolName: string, result: unknown): string[] {
		// Bash: extract output string
		if (toolName === "bash" || toolName === "Bash") {
			const output = typeof result === "string"
				? result
				: (result as Record<string, unknown>)?.output as string | undefined;
			if (!output) return [];
			return output.split("\n").map((l) => `${DIM}  ${l}${RESET}`);
		}

		// Pi tool result: try content[].text extraction
		if (result && typeof result === "object" && !Array.isArray(result)) {
			const r = result as Record<string, unknown>;
			if (Array.isArray(r.content)) {
				const texts = (r.content as Array<Record<string, unknown>>)
					.filter((c) => c.type === "text")
					.map((c) => c.text as string);
				if (texts.length > 0) {
					return texts
						.join("\n")
						.split("\n")
						.map((l) => `${DIM}  ${l}${RESET}`);
				}
			}
		}

		// String result
		if (typeof result === "string") {
			return result.split("\n").map((l) => `${DIM}  ${l}${RESET}`);
		}

		// Fallback: JSON pretty-print
		try {
			const json = JSON.stringify(result, null, 2);
			return json.split("\n").map((l) => `${DIM}  ${l}${RESET}`);
		} catch {
			return [`${DIM}  [result]${RESET}`];
		}
	}

	private addMarkdownSegment(text: string): void {
		const md = new Markdown(text, 0, 0, markdownTheme);
		this.segments.push({ kind: "markdown", component: md, buffer: text });
		this.trimSegments();
	}

	private trimSegments(): void {
		if (this.segments.length > this.maxSegments) {
			this.segments = this.segments.slice(-this.maxSegments);
		}
	}
}
