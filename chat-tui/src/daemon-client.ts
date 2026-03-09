/**
 * Unix socket clients for daemon communication.
 *
 * ChatClient: persistent streaming connection to /tmp/clarvis-chat.sock (NDJSON bidirectional)
 * DaemonClient: ephemeral request/response to /tmp/clarvis-daemon.sock (for ctools commands)
 */

import * as net from "node:net";
import * as readline from "node:readline";

const CHAT_SOCKET = "/tmp/clarvis-chat.sock";
const DAEMON_SOCKET = "/tmp/clarvis-daemon.sock";

// ============================================================================
// ChatClient — persistent streaming NDJSON connection
// ============================================================================

export type ChatEvent = Record<string, unknown>;
export type ChatEventHandler = (event: ChatEvent) => void;

let reqCounter = 0;

export class ChatClient {
	private socket: net.Socket | null = null;
	private rl: readline.Interface | null = null;
	private onEvent: ChatEventHandler;
	private onDisconnect: () => void;
	private reconnecting = false;
	private pendingRequests = new Map<string, {
		resolve: (event: ChatEvent) => void;
		timeout: NodeJS.Timeout;
	}>();

	constructor(onEvent: ChatEventHandler, onDisconnect: () => void) {
		this.onEvent = onEvent;
		this.onDisconnect = onDisconnect;
	}

	connect(): Promise<void> {
		return new Promise((resolve, reject) => {
			const socket = net.createConnection(CHAT_SOCKET);

			socket.on("connect", () => {
				this.socket = socket;
				this.rl = readline.createInterface({ input: socket, terminal: false });
				this.rl.on("line", (line) => {
					try {
						const event = JSON.parse(line) as ChatEvent;
						// Check if this event matches a pending request by ID
						const eventId = event.id as string | undefined;
						if (eventId) {
							const pending = this.pendingRequests.get(eventId);
							if (pending) {
								this.pendingRequests.delete(eventId);
								clearTimeout(pending.timeout);
								pending.resolve(event);
								return;
							}
						}
						this.onEvent(event);
					} catch {
						// ignore malformed JSON
					}
				});
				resolve();
			});

			socket.on("error", (err) => {
				if (!this.socket) {
					reject(err);
				}
			});

			socket.on("close", () => {
				this.rejectPending("Socket closed");
				this.cleanup();
				if (!this.reconnecting) {
					this.onDisconnect();
				}
			});
		});
	}

	send(obj: Record<string, unknown>): void {
		if (this.socket && !this.socket.destroyed) {
			this.socket.write(JSON.stringify(obj) + "\n");
		}
	}

	/**
	 * Send a command and wait for its response, matched by request ID.
	 * Attaches an `id` field to the command; the bridge echoes it back.
	 */
	request(command: Record<string, unknown>, timeoutMs = 5000): Promise<ChatEvent> {
		const id = `req_${++reqCounter}`;
		return new Promise((resolve, reject) => {
			const timeout = setTimeout(() => {
				this.pendingRequests.delete(id);
				reject(new Error(`Timeout waiting for response to ${command.type}`));
			}, timeoutMs);

			this.pendingRequests.set(id, { resolve, timeout });
			this.send({ ...command, id });
		});
	}

	disconnect(): void {
		this.reconnecting = true;
		for (const [, pending] of this.pendingRequests) {
			clearTimeout(pending.timeout);
		}
		this.pendingRequests.clear();
		this.cleanup();
		this.reconnecting = false;
	}

	get connected(): boolean {
		return this.socket !== null && !this.socket.destroyed;
	}

	private rejectPending(reason: string): void {
		for (const [id, pending] of this.pendingRequests) {
			clearTimeout(pending.timeout);
			pending.resolve({ type: "error", message: reason, id });
		}
		this.pendingRequests.clear();
	}

	private cleanup(): void {
		if (this.rl) {
			this.rl.close();
			this.rl = null;
		}
		if (this.socket) {
			this.socket.destroy();
			this.socket = null;
		}
	}
}

// ============================================================================
// DaemonClient — ephemeral request/response for ctools commands
// ============================================================================

export class DaemonClient {
	/**
	 * Send a JSON-RPC request to the daemon and return the result.
	 * Creates a new connection for each request (matches ctools behavior).
	 */
	static async send(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
		return new Promise((resolve, reject) => {
			const socket = net.createConnection(DAEMON_SOCKET);
			let data = "";

			socket.on("connect", () => {
				socket.write(JSON.stringify({ method, params }) + "\n");
			});

			socket.on("data", (chunk) => {
				data += chunk.toString();
			});

			socket.on("end", () => {
				try {
					const result = JSON.parse(data);
					if (result.error) {
						reject(new Error(result.error));
					} else {
						resolve(result.result ?? result);
					}
				} catch {
					reject(new Error(`Invalid response: ${data}`));
				}
			});

			socket.on("error", (err) => {
				reject(err);
			});

			// Timeout after 10s
			socket.setTimeout(10000, () => {
				socket.destroy();
				reject(new Error("Daemon request timed out"));
			});
		});
	}
}
