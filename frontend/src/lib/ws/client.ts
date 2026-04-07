/**
 * WebSocket client with automatic reconnection.
 */

export type WsMessage = {
	type: 'book' | 'trade' | 'markets' | 'order_update' | 'position_update';
	ticker?: string;
	data: any;
};

type MessageHandler = (msg: WsMessage) => void;

export class WsClient {
	private ws: WebSocket | null = null;
	private url: string = '';
	private handlers: Set<MessageHandler> = new Set();
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private _connected = false;

	get connected() {
		return this._connected;
	}

	connect(eventTicker: string, token: string) {
		this.disconnect();

		const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
		const host = window.location.host;
		this.url = `${protocol}//${host}/ws/${eventTicker}?token=${token}`;

		this._doConnect();
	}

	private _doConnect() {
		if (!this.url) return;

		try {
			this.ws = new WebSocket(this.url);

			this.ws.onopen = () => {
				this._connected = true;
				console.log('[WS] Connected');
			};

			this.ws.onmessage = (event) => {
				try {
					const msg: WsMessage = JSON.parse(event.data);
					for (const handler of this.handlers) {
						handler(msg);
					}
				} catch (e) {
					console.error('[WS] Parse error:', e);
				}
			};

			this.ws.onclose = (event) => {
				this._connected = false;
				console.log('[WS] Disconnected:', event.code, event.reason);
				// Auto-reconnect after 2 seconds unless intentionally closed
				if (event.code !== 1000 && event.code !== 4003) {
					this.reconnectTimer = setTimeout(() => this._doConnect(), 2000);
				}
			};

			this.ws.onerror = (event) => {
				console.error('[WS] Error:', event);
			};
		} catch (e) {
			console.error('[WS] Connection failed:', e);
			this.reconnectTimer = setTimeout(() => this._doConnect(), 2000);
		}
	}

	disconnect() {
		if (this.reconnectTimer) {
			clearTimeout(this.reconnectTimer);
			this.reconnectTimer = null;
		}
		if (this.ws) {
			this.ws.onclose = null;  // Prevent auto-reconnect
			this.ws.close(1000);
			this.ws = null;
		}
		this._connected = false;
		this.url = '';
	}

	onMessage(handler: MessageHandler): () => void {
		this.handlers.add(handler);
		return () => this.handlers.delete(handler);
	}
}

export const wsClient = new WsClient();
