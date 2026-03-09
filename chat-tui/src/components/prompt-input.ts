/**
 * Prompt input component wrapping Editor with slash command autocomplete.
 */

import {
	type AutocompleteProvider,
	type Component,
	Editor,
	type EditorTheme,
	matchesKey,
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
		return [`${GREEN}${BOLD}${this.userLabel}:${RESET}`, ...this.editor.render(width)];
	}
}
