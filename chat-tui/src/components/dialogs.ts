/**
 * Dialog components for handling extension_ui_request events and rewind.
 * Rendered as pi-tui overlays that float over the output log.
 */

import {
	type Component,
	Input,
	isKeyRelease,
	matchesKey,
	type SelectItem,
	SelectList,
	truncateToWidth,
} from "@mariozechner/pi-tui";
import { BOLD, DIM, MAGENTA, RESET, selectListTheme } from "../theme.js";

// ============================================================================
// SelectDialog — for select/confirm extension UI requests
// ============================================================================

export class SelectDialog implements Component {
	private list: SelectList;
	private title: string;
	onSelect?: (value: string) => void;
	onCancel?: () => void;

	constructor(title: string, options: string[]) {
		this.title = title;
		const items: SelectItem[] = options.map((o) => ({ value: o, label: o }));
		this.list = new SelectList(items, Math.min(items.length, 8), selectListTheme);
		this.list.onSelect = (item) => this.onSelect?.(item.value);
		this.list.onCancel = () => this.onCancel?.();
	}

	handleInput(data: string): void {
		this.list.handleInput(data);
	}

	invalidate(): void {
		this.list.invalidate();
	}

	render(width: number): string[] {
		return [
			`${MAGENTA}${BOLD}${this.title}${RESET}`,
			...this.list.render(width),
			`${DIM}Up/Down, Enter to select, Esc to cancel${RESET}`,
		];
	}
}

// ============================================================================
// FilterSelectDialog — select with type-to-filter
// ============================================================================

export class FilterSelectDialog implements Component {
	private list: SelectList;
	private filterInput: Input;
	private title: string;
	onSelect?: (value: string) => void;
	onCancel?: () => void;

	constructor(title: string, options: string[]) {
		this.title = title;
		const items: SelectItem[] = options.map((o) => ({ value: o, label: o }));
		this.list = new SelectList(items, Math.min(items.length, 12), selectListTheme);
		this.list.onSelect = (item) => this.onSelect?.(item.value);
		this.list.onCancel = () => this.onCancel?.();
		this.filterInput = new Input();
		this.filterInput.onSubmit = () => {
			const selected = this.list.getSelectedItem();
			if (selected) this.onSelect?.(selected.value);
		};
		this.filterInput.onEscape = () => this.onCancel?.();
	}

	private lastFilter = "";
	private syncFilter(): void {
		const current = this.filterInput.getValue();
		if (current !== this.lastFilter) {
			this.lastFilter = current;
			this.list.setFilter(current);
		}
	}

	get focused(): boolean { return this.filterInput.focused; }
	set focused(value: boolean) { this.filterInput.focused = value; }

	handleInput(data: string): void {
		// Arrow keys go to the list for navigation
		if (matchesKey(data, "up") || matchesKey(data, "down")) {
			this.list.handleInput(data);
			return;
		}
		// Everything else goes to the filter input, then sync filter to list
		this.filterInput.handleInput(data);
		this.syncFilter();
	}

	invalidate(): void {
		this.filterInput.invalidate();
		this.list.invalidate();
	}

	render(width: number): string[] {
		return [
			`${MAGENTA}${BOLD}${this.title}${RESET}`,
			...this.filterInput.render(width),
			...this.list.render(width),
			`${DIM}Type to filter, Up/Down to navigate, Enter to select, Esc to cancel${RESET}`,
		];
	}
}

// ============================================================================
// InputDialog — for input/editor extension UI requests
// ============================================================================

export class InputDialog implements Component {
	private dialogInput: Input;
	private title: string;
	onCtrlD?: () => void;

	constructor(title: string, prefill?: string) {
		this.title = title;
		this.dialogInput = new Input();
		if (prefill) this.dialogInput.setValue(prefill);
	}

	/** Focusable — propagate to inner Input so cursor renders */
	get focused(): boolean {
		return this.dialogInput.focused;
	}

	set focused(value: boolean) {
		this.dialogInput.focused = value;
	}

	set onSubmit(fn: ((value: string) => void) | undefined) {
		this.dialogInput.onSubmit = fn;
	}

	set onEscape(fn: (() => void) | undefined) {
		this.dialogInput.onEscape = fn;
	}

	handleInput(data: string): void {
		if (matchesKey(data, "ctrl+d")) {
			this.onCtrlD?.();
			return;
		}
		this.dialogInput.handleInput(data);
	}

	invalidate(): void {
		this.dialogInput.invalidate();
	}

	render(width: number): string[] {
		return [
			`${MAGENTA}${BOLD}${this.title}${RESET}`,
			...this.dialogInput.render(width),
			`${DIM}Enter to submit, Esc to cancel${RESET}`,
		];
	}
}

// ============================================================================
// RewindDialog — for /rewind fork selection
// ============================================================================

export interface RewindEntry {
	entryId: string;
	role: string;
	text: string;
}

export class RewindDialog implements Component {
	private entries: RewindEntry[];
	private selectedIndex = 0;
	private maxVisible = 8;
	onSelect?: (entry: RewindEntry) => void;
	onCancel?: () => void;

	constructor(entries: RewindEntry[]) {
		// Most recent first
		this.entries = [...entries].reverse();
	}

	handleInput(data: string): void {
		if (isKeyRelease(data)) return;
		if (matchesKey(data, "up")) {
			this.selectedIndex = this.selectedIndex === 0
				? this.entries.length - 1
				: this.selectedIndex - 1;
		} else if (matchesKey(data, "down")) {
			this.selectedIndex = this.selectedIndex === this.entries.length - 1
				? 0
				: this.selectedIndex + 1;
		} else if (matchesKey(data, "enter")) {
			const entry = this.entries[this.selectedIndex];
			if (entry) this.onSelect?.(entry);
		} else if (matchesKey(data, "escape")) {
			this.onCancel?.();
		}
	}

	invalidate(): void {}

	render(width: number): string[] {
		const lines: string[] = [];
		lines.push(`${MAGENTA}${BOLD} Rewind${RESET}`);
		lines.push("");
		lines.push(` ${DIM}Restore the conversation to the point before…${RESET}`);
		lines.push("");

		// Scrolling window
		const half = Math.floor(this.maxVisible / 2);
		let start = Math.max(0, Math.min(
			this.selectedIndex - half,
			this.entries.length - this.maxVisible,
		));
		if (start < 0) start = 0;
		const end = Math.min(start + this.maxVisible, this.entries.length);

		for (let i = start; i < end; i++) {
			const entry = this.entries[i];
			const isSelected = i === this.selectedIndex;
			const isCurrent = i === 0;
			const maxTextWidth = width - 6;

			// Show up to 3 lines of the message
			const textLines = entry.text.split("\n").filter((l) => l.trim());
			const shown = textLines.slice(0, 3);

			for (let j = 0; j < shown.length; j++) {
				const lineText = truncateToWidth(shown[j], maxTextWidth, "");
				if (j === 0) {
					const prefix = isSelected ? ` ${BOLD}❯${RESET} ` : `   `;
					lines.push(`${prefix}${isSelected ? BOLD : ""}${lineText}${RESET}`);
				} else {
					lines.push(`   ${isSelected ? BOLD : DIM}${lineText}${RESET}`);
				}
			}
			if (textLines.length > 3) {
				lines.push(`   ${DIM}…${textLines.length - 3} more lines${RESET}`);
			}

			if (isCurrent) {
				lines.push(`   ${DIM}(current)${RESET}`);
			}

			lines.push(""); // breathing room
		}

		if (this.entries.length > this.maxVisible) {
			lines.push(` ${DIM}(${this.selectedIndex + 1}/${this.entries.length})${RESET}`);
			lines.push("");
		}

		lines.push(` ${DIM}Enter to select · Esc to cancel${RESET}`);
		return lines;
	}
}

// ============================================================================
// Extension UI request type
// ============================================================================

export interface ExtensionUIRequest {
	type: "extension_ui_request";
	id: string;
	method: string;
	title?: string;
	options?: string[];
	message?: string;
	placeholder?: string;
	prefill?: string;
	notifyType?: "info" | "warning" | "error";
	statusKey?: string;
	statusText?: string;
	widgetKey?: string;
	widgetLines?: string[];
	text?: string;
}
