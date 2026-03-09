/**
 * Loading indicator shown while the agent is thinking.
 * Wraps CancellableLoader from pi-tui.
 */

import { CancellableLoader, type TUI } from "@mariozechner/pi-tui";
import { BLUE, CYAN, DIM } from "../theme.js";

const spinnerColor = (s: string) => `${CYAN}${s}`;
const messageColor = (s: string) => `${DIM}${s}`;

export function createLoader(tui: TUI): CancellableLoader {
	return new CancellableLoader(tui, spinnerColor, messageColor, "Thinking...");
}
