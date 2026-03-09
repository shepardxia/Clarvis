/**
 * Clarvis Chat TUI — Entry point.
 *
 * Parses CLI args and boots the App.
 */

import { ProcessTerminal, TUI } from "@mariozechner/pi-tui";
import { App } from "./app.js";

function parseArgs(): { agent?: string } {
	const args = process.argv.slice(2);
	for (let i = 0; i < args.length; i++) {
		if (args[i] === "--agent" && i + 1 < args.length) {
			return { agent: args[i + 1] };
		}
	}
	return {};
}

async function main() {
	const { agent } = parseArgs();
	const terminal = new ProcessTerminal();
	const tui = new TUI(terminal);
	const app = new App(tui);
	await app.start(agent);
}

main().catch((err) => {
	console.error(err);
	process.exit(1);
});
