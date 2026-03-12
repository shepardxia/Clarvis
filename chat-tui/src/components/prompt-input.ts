/**
 * Prompt input component wrapping Editor with slash command autocomplete.
 */

import {
	type AutocompleteProvider,
	type Component,
	Editor,
	type EditorTheme,
	matchesKey,
	truncateToWidth,
	type TUI,
} from "@mariozechner/pi-tui";
import { BOLD, DIM, GREEN, RESET, selectListTheme } from "../theme.js";

const editorTheme: EditorTheme = {
	borderColor: (s) => `${DIM}${s}${RESET}`,
	selectList: selectListTheme,
};

export class PromptInput implements Component {
	readonly editor: Editor;
	onCtrlD?: () => void;
	userLabel = "You";

	constructor(tui: TUI, autocompleteProvider?: AutocompleteProvider) {
		this.editor = new Editor(tui, editorTheme, { paddingX: 0, autocompleteMaxVisible: 15 });
		if (autocompleteProvider) {
			this.editor.setAutocompleteProvider(autocompleteProvider);
		}
	}

	set onSubmit(fn: ((text: string) => void) | undefined) {
		this.editor.onSubmit = fn;
	}

	handleInput(data: string): void {
		if (matchesKey(data, "ctrl+d")) {
			this.onCtrlD?.();
			return;
		}
		this.editor.handleInput(data);
	}

	invalidate(): void {
		this.editor.invalidate();
	}

	render(width: number): string[] {
		// Render editor at reduced width to leave room for ❯ prefix
		const contentWidth = width - 2;
		const editorLines = this.editor.render(contentWidth);
		const prompt = `${GREEN}${BOLD}>${RESET} `;
		const indent = "  ";
		return editorLines.map((line, i) => {
			// Replace block cursor with underscore cursor
			const cursored = line.replace(/\x1b\[7m(.)\x1b\[0m/, (_, ch) =>
				ch === " " ? "_" : `${ch}\x1b[0m_`,
			);
			// Lines 0 and last are borders — replace ─ with = for retro look
			if (i === 0 || i === editorLines.length - 1) {
				return truncateToWidth(indent + cursored.replace(/─/g, "="), width);
			}
			// First content line gets the prompt symbol
			if (i === 1) return truncateToWidth(prompt + cursored, width);
			// Continuation lines get 2-space indent
			return truncateToWidth(indent + cursored, width);
		});
	}
}
