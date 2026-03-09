/** ANSI color constants and shared theme objects for TUI styling */

import type { SelectListTheme } from "@mariozechner/pi-tui";

export const GREEN = "\x1b[32m";
export const YELLOW = "\x1b[33m";
export const BLUE = "\x1b[34m";
export const MAGENTA = "\x1b[35m";
export const CYAN = "\x1b[36m";
export const RED = "\x1b[31m";
export const DIM = "\x1b[2m";
export const BOLD = "\x1b[1m";
export const ITALIC = "\x1b[3m";
export const UNDERLINE = "\x1b[4m";
export const STRIKETHROUGH = "\x1b[9m";
export const RESET = "\x1b[0m";

export const selectListTheme: SelectListTheme = {
	selectedPrefix: (t) => `${MAGENTA}${t}${RESET}`,
	selectedText: (t) => `${MAGENTA}${t}${RESET}`,
	description: (t) => `${DIM}${t}${RESET}`,
	scrollInfo: (t) => `${DIM}${t}${RESET}`,
	noMatch: (t) => `${YELLOW}${t}${RESET}`,
};
