/**
 * Dialog components for handling extension_ui_request events and rewind.
 * Rendered as pi-tui overlays that float over the output log.
 */

import {
	type Component,
	Input,
	matchesKey,
	type SelectItem,
	SelectList,
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

export class RewindDialog implements Component {
	private list: SelectList;
	onSelect?: (item: SelectItem) => void;
	onCancel?: () => void;

	constructor(items: SelectItem[]) {
		this.list = new SelectList(items, Math.min(items.length, 12), selectListTheme);
		this.list.onSelect = (item) => this.onSelect?.(item);
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
			`${MAGENTA}${BOLD}Rewind to:${RESET}`,
			...this.list.render(width),
			`${DIM}Up/Down, Enter to select, Esc to cancel${RESET}`,
		];
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
