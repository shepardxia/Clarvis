/**
 * Scrolling output log for agent responses, tool executions, and system messages.
 *
 * All output is composed of Block elements — a single configurable type that
 * handles rich/raw rendering, collapsibility, streaming deltas, and per-line
 * styling through properties rather than subclasses.
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

const stripAnsi = (s: string) => s.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, "");

/** Compact mode: max lines of collapsible body to show */
const COMPACT_LINES = 12;
/** Detail mode: max lines of collapsible body to show */
const DETAIL_LINES = 200;
/** Trailing cursor shown during streaming responses */
const STREAM_CURSOR = "_";

// ============================================================================
// Block — unified output element
// ============================================================================

interface BlockOptions {
	header?: string;
	collapsible?: boolean;
	rich?: boolean;
	style?: (line: string) => string;
	indent?: boolean;
}

/**
 * A single output element. Configuration determines behavior:
 *
 * - `rich`: render body via Markdown component (for agent responses)
 * - `collapsible`: truncate body in compact mode with expand hint
 * - `style`: per-line styling function for raw body lines
 * - `header`: optional header line rendered above the body
 *
 * Content is either streamed via `write()` into a buffer, or set
 * as pre-formatted lines via `setLines()` (for tool results).
 */
class Block {
	readonly header: string | null;
	readonly collapsible: boolean;
	readonly rich: boolean;
	readonly style: ((line: string) => string) | null;
	readonly indent: boolean;

	private md: Markdown | null = null;
	private buffer = "";
	private lines: string[] | null = null;

	constructor(opts: BlockOptions = {}) {
		this.header = opts.header ?? null;
		this.collapsible = opts.collapsible ?? false;
		this.rich = opts.rich ?? false;
		this.style = opts.style ?? null;
		this.indent = opts.indent ?? false;
		if (this.rich) {
			this.md = new Markdown("", 0, 0, markdownTheme);
		}
	}

	/** Append streaming text to the buffer */
	write(text: string): void {
		this.buffer += text;
		this.md?.setText(this.buffer + STREAM_CURSOR);
	}

	/** Remove the trailing stream cursor after streaming ends */
	finalize(): void {
		this.md?.setText(this.buffer);
	}

	/** Set pre-formatted body lines (for tool results filled after creation) */
	setLines(value: string[]): void {
		this.lines = value;
	}

	get linesEmpty(): boolean {
		return this.lines === null || this.lines.length === 0;
	}

	invalidate(): void {
		this.md?.invalidate();
	}

	private get bodyLines(): string[] {
		return this.lines ?? (this.buffer ? this.buffer.split("\n") : []);
	}

	render(width: number, detailMode: boolean): string[] {
		const result: string[] = [];
		const prefix = this.indent ? "  " : "";
		const contentWidth = this.indent ? width - 2 : width;

		if (this.header !== null) {
			result.push(prefix + truncateToWidth(this.header, contentWidth));
		}

		if (this.md) {
			for (const line of this.md.render(contentWidth)) {
				result.push(prefix + line);
			}
		} else {
			const body = this.bodyLines;
			if (body.length > 0) {
				const cap = this.collapsible
					? (detailMode ? DETAIL_LINES : COMPACT_LINES)
					: body.length;
				const max = Math.min(body.length, cap);
				for (let i = 0; i < max; i++) {
					const styled = this.style ? this.style(body[i]) : body[i];
					result.push(prefix + truncateToWidth(styled, contentWidth));
				}
				const remaining = body.length - max;
				if (remaining > 0) {
					result.push(`${prefix}${DIM}[+${remaining} lines — Ctrl+L to expand]${RESET}`);
				}
			}
		}

		return result;
	}

	renderPlain(width: number): string[] {
		const result: string[] = [];
		const prefix = this.indent ? "  " : "";
		const contentWidth = this.indent ? width - 2 : width;

		if (this.header !== null) {
			result.push(prefix + stripAnsi(this.header));
		}

		if (this.md) {
			for (const line of this.md.render(contentWidth)) {
				result.push(prefix + stripAnsi(line));
			}
		} else {
			for (const line of this.bodyLines) {
				result.push(prefix + stripAnsi(line));
			}
		}

		return result;
	}
}

// ============================================================================
// OutputLog
// ============================================================================

export class OutputLog implements Component {
	private blocks: Block[] = [];
	private streaming: Block | null = null;
	private pendingTools: Block[] = [];
	private maxBlocks = 2000;

	agentLabel = "Clarvis";
	userLabel = "You";
	detailMode = false;

	/** Append a raw styled line */
	append(line: string): void {
		this.streaming?.finalize();
		this.streaming = null;
		const block = new Block();
		block.setLines([line]);
		this.push(block);
	}

	/** Append a user message with styled prefix */
	appendUserMessage(text: string): void {
		this.append("");
		this.append(`${GREEN}${BOLD}${this.userLabel.toUpperCase()}:${RESET}`);
		this.pushRich(text);
	}

	/** Append a complete Markdown block (for history replay) */
	appendMarkdown(text: string): void {
		this.append("");
		this.append(`${BLUE}${BOLD}${this.agentLabel.toUpperCase()}:${RESET}`);
		this.pushRich(text);
	}

	/** Append a continuation Markdown block without agent label (for history replay) */
	appendMarkdownContinuation(text: string): void {
		this.pushRich(text);
	}

	/** Clear all output */
	clear(): void {
		this.blocks = [];
		this.streaming?.finalize();
		this.streaming = null;
		this.pendingTools = [];
	}

	/** Toggle between compact and detail mode for collapsible output */
	toggleDetail(): boolean {
		this.detailMode = !this.detailMode;
		return this.detailMode;
	}

	invalidate(): void {
		for (const block of this.blocks) block.invalidate();
	}

	render(width: number): string[] {
		const result: string[] = [];
		for (const block of this.blocks) {
			result.push(...block.render(width, this.detailMode));
		}
		return result.length === 0 ? [""] : result;
	}

	/** Render all output fully expanded, ANSI stripped. For pager. */
	getAllText(width: number): string {
		const lines: string[] = [];
		for (const block of this.blocks) {
			lines.push(...block.renderPlain(width));
		}
		return lines.join("\n");
	}

	// -- Event handlers for Pi RPC events --

	/** Whether a streaming response block is active (for first-delta detection) */
	get hasActiveResponse(): boolean {
		return this.streaming?.rich === true;
	}

	/** Start a new agent response block — creates a streaming Markdown block */
	startResponseBlock(): void {
		this.append("");
		this.append(`${BLUE}${BOLD}${this.agentLabel.toUpperCase()}:${RESET}`);
		this.streaming = new Block({ rich: true, indent: true });
		this.push(this.streaming);
	}

	/** Append streaming text delta to the current Markdown block */
	handleTextDelta(delta: string): void {
		if (this.streaming?.rich) {
			this.streaming.write(delta);
		} else {
			// After tool output — start a new markdown block (continuation, no header)
			this.streaming = new Block({ rich: true, indent: true });
			this.streaming.write(delta);
			this.push(this.streaming);
		}
	}

	/** Append streaming thinking delta */
	handleThinkingDelta(delta: string): void {
		if (this.streaming?.collapsible) {
			this.streaming.write(delta);
		} else {
			this.streaming = new Block({
				header: `${DIM}${ITALIC}[thinking]${RESET}`,
				collapsible: true,
				style: (l) => `${DIM}${ITALIC}${l}${RESET}`,
				indent: true,
			});
			this.streaming.write(delta);
			this.push(this.streaming);
		}
	}

	handleToolStart(toolName: string, toolInput?: Record<string, unknown>): void {
		this.streaming?.finalize();
		this.streaming = null;
		const block = new Block({
			header: buildToolHeader(toolName, toolInput),
			collapsible: true,
			indent: true,
		});
		this.pendingTools.push(block);
		this.push(block);
	}

	handleToolEnd(toolName: string, result: unknown): void {
		const lines = extractResultLines(toolName, result);
		const pending = this.pendingTools.pop();
		if (pending) {
			pending.setLines(lines);
		} else {
			// Fallback: no matching start, create standalone
			const block = new Block({
				header: `${DIM}[${toolName}]${RESET}`,
				collapsible: true,
				indent: true,
			});
			block.setLines(lines);
			this.push(block);
		}
	}

	handleAgentEnd(): void {
		this.streaming?.finalize();
		this.streaming = null;
		this.append("");
	}

	handleError(message: string): void {
		this.appendIndented(`${RED}${BOLD}Error:${RESET} ${message}`);
	}

	handleInfo(message: string): void {
		this.appendIndented(`${YELLOW}${message}${RESET}`);
	}

	// -- Private helpers --

	private appendIndented(line: string): void {
		this.streaming?.finalize();
		this.streaming = null;
		const block = new Block({ indent: true });
		block.setLines([line]);
		this.push(block);
	}

	private pushRich(text: string): void {
		const block = new Block({ rich: true, indent: true });
		block.write(text);
		block.finalize();
		this.push(block);
	}

	private push(block: Block): void {
		this.blocks.push(block);
		if (this.blocks.length > this.maxBlocks) {
			this.blocks = this.blocks.slice(-this.maxBlocks);
		}
	}
}

// ============================================================================
// Tool formatting (pure functions)
// ============================================================================

function buildToolHeader(toolName: string, toolInput?: Record<string, unknown>): string {
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
						const brief = rawArgs.length > 60 ? rawArgs.slice(0, 60) + "…" : rawArgs;
						return `${DIM}[ctools ${method}] ${brief}${RESET}`;
					}
				}
				return `${DIM}[ctools ${method}]${RESET}`;
			}

			const brief = cmd.length > 120 ? cmd.slice(0, 120) + "…" : cmd;
			return `${CYAN}$${RESET} ${DIM}${brief}${RESET}`;
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
		default: {
			// Show key input params for non-trivial tools
			let detail = "";
			if (toolInput) {
				const keys = Object.keys(toolInput).slice(0, 2);
				const parts = keys.map((k) => {
					const v = toolInput![k];
					const vs = typeof v === "string" ? v : JSON.stringify(v);
					return vs && vs.length > 60 ? vs.slice(0, 60) + "…" : vs;
				}).filter(Boolean);
				if (parts.length > 0) detail = ` ${parts.join(" ")}`;
			}
			return `${DIM}[${toolName}]${detail}${RESET}`;
		}
	}
}

function extractResultLines(_toolName: string, result: unknown): string[] {
	const text = extractResultText(result);
	if (!text) return [];
	return text.split("\n").map((l) => `${DIM}  ${l}${RESET}`);
}

/** Try all known result formats: string, {output}, {content[].text}, JSON fallback. */
function extractResultText(result: unknown): string | null {
	if (typeof result === "string") return result || null;

	if (result && typeof result === "object" && !Array.isArray(result)) {
		const r = result as Record<string, unknown>;

		// Bash format: { output: "..." }
		if (typeof r.output === "string" && r.output) return r.output;

		// Pi/MCP format: { content: [{ type: "text", text: "..." }] }
		if (Array.isArray(r.content)) {
			const texts = (r.content as Array<Record<string, unknown>>)
				.filter((c) => c.type === "text")
				.map((c) => c.text as string);
			if (texts.length > 0) return texts.join("\n");
		}
	}

	// Fallback: JSON pretty-print
	try {
		const json = JSON.stringify(result, null, 2);
		return json;
	} catch {
		return null;
	}
}
