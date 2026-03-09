/**
 * Scrolling output log for agent responses, tool executions, and system messages.
 *
 * Agent text responses are rendered via pi-tui's Markdown component for styled
 * output (code blocks, headings, lists, etc.). Other lines (tool output, errors,
 * info messages) are rendered as raw ANSI-styled text.
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

/**
 * A segment in the output log — either a raw styled line or a Markdown block
 * representing an agent response.
 */
type Segment =
	| { kind: "line"; text: string }
	| { kind: "markdown"; component: Markdown; buffer: string };

export class OutputLog implements Component {
	private segments: Segment[] = [];
	private maxSegments = 2000;

	/** Append a raw styled line */
	append(line: string): void {
		this.segments.push({ kind: "line", text: line });
		this.trimSegments();
	}

	/** Append a user message with styled "You:" prefix */
	appendUserMessage(text: string): void {
		this.append(`${GREEN}${BOLD}You:${RESET} ${text}`);
	}

	/** Append a complete Markdown block (for history replay) */
	appendMarkdown(text: string): void {
		this.append("");
		this.append(`${BLUE}${BOLD}Agent:${RESET}`);
		this.addMarkdownSegment(text);
	}

	/** Clear all output */
	clear(): void {
		this.segments = [];
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
			} else {
				result.push(...seg.component.render(width));
			}
		}
		if (result.length === 0) return [""];
		return result;
	}

	// -- Event handlers for Pi RPC events --

	handleAgentStart(): void {
		// Prepare for new response
	}

	/** Start a new agent response block — creates a Markdown segment */
	startResponseBlock(): void {
		this.append("");
		this.append(`${BLUE}${BOLD}Agent:${RESET}`);
		this.addMarkdownSegment("");
	}

	/** Append streaming text delta to the current Markdown block */
	handleTextDelta(delta: string): void {
		const last = this.segments[this.segments.length - 1];
		if (last?.kind === "markdown") {
			last.buffer += delta;
			last.component.setText(last.buffer);
		} else {
			// Fallback: no active markdown block, append as raw lines
			const parts = delta.split("\n");
			for (let i = 0; i < parts.length; i++) {
				if (parts[i]) this.append(parts[i]);
				else if (i > 0) this.append("");
			}
		}
	}

	handleToolStart(toolName: string, toolInput?: Record<string, unknown>): void {
		switch (toolName) {
			case "bash":
			case "Bash": {
				const cmd = toolInput?.command as string | undefined;
				if (cmd) {
					this.append(`${DIM}$ ${cmd}${RESET}`);
				} else {
					this.append(`${DIM}[bash]${RESET}`);
				}
				break;
			}
			case "Read":
			case "read": {
				const path = toolInput?.file_path as string | undefined;
				this.append(`${DIM}[reading ${path ?? "file"}]${RESET}`);
				break;
			}
			case "Edit":
			case "edit": {
				const path = toolInput?.file_path as string | undefined;
				this.append(`${DIM}[editing ${path ?? "file"}]${RESET}`);
				break;
			}
			case "Write":
			case "write": {
				const path = toolInput?.file_path as string | undefined;
				this.append(`${DIM}[writing ${path ?? "file"}]${RESET}`);
				break;
			}
			default:
				this.append(`${DIM}[tool: ${toolName}]${RESET}`);
		}
	}

	handleToolEnd(toolName: string, result: unknown): void {
		const MAX_LINES = 10;

		if (toolName === "bash" || toolName === "Bash") {
			// Show bash output as multi-line indented text
			const output = typeof result === "string"
				? result
				: (result as Record<string, unknown>)?.output as string | undefined;
			if (output) {
				const lines = output.split("\n");
				const shown = lines.slice(0, MAX_LINES);
				for (const line of shown) {
					this.append(`${DIM}  ${line}${RESET}`);
				}
				if (lines.length > MAX_LINES) {
					this.append(`${DIM}  ... ${lines.length - MAX_LINES} more lines${RESET}`);
				}
			}
			return;
		}

		// Default: truncated single line
		const text = JSON.stringify(result);
		const truncated = text.length > 120 ? text.slice(0, 120) + "..." : text;
		this.append(`${DIM}[result: ${truncated}]${RESET}`);
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
