/**
 * REST API client for the trading terminal backend.
 */

const BASE = '';  // Same origin in production; proxied in dev

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
	const res = await fetch(`${BASE}${path}`, {
		...options,
		headers: {
			'Content-Type': 'application/json',
			...options?.headers,
		},
	});
	if (!res.ok) {
		const text = await res.text();
		throw new Error(`API error ${res.status}: ${text}`);
	}
	return res.json();
}

export async function fetchEvents(seriesTicker?: string, status = 'open') {
	const params = new URLSearchParams({ status });
	if (seriesTicker) params.set('series_ticker', seriesTicker);
	return apiFetch<{ events: any[] }>(`/api/markets/events?${params}`);
}

export async function fetchEventMarkets(eventTicker: string) {
	return apiFetch<{ markets: any[] }>(`/api/markets/event/${eventTicker}/markets`);
}

export async function fetchEventStartTime(eventTicker: string) {
	return apiFetch<{ event_start_utc: string | null; source: string }>(`/api/markets/event/${eventTicker}/start-time`);
}

export async function fetchMarket(ticker: string) {
	return apiFetch<{ market: any }>(`/api/markets/market/${ticker}`);
}

export async function fetchOrderbook(ticker: string, depth = 20) {
	return apiFetch<{ orderbook: any }>(`/api/markets/market/${ticker}/orderbook?depth=${depth}`);
}

export async function fetchTrades(ticker: string, limit = 200) {
	return apiFetch<{ trades: any[] }>(`/api/markets/market/${ticker}/trades?limit=${limit}`);
}

export async function fetchPositions(eventTicker?: string, subaccount?: number) {
	const params = new URLSearchParams();
	if (eventTicker) params.set('event_ticker', eventTicker);
	if (subaccount !== undefined) params.set('subaccount', String(subaccount));
	return apiFetch<{ positions: any[]; subaccount: number }>(`/api/positions/?${params}`);
}

export async function fetchOrders(eventTicker?: string, status = 'resting', subaccount?: number) {
	const params = new URLSearchParams({ status });
	if (eventTicker) params.set('event_ticker', eventTicker);
	if (subaccount !== undefined) params.set('subaccount', String(subaccount));
	return apiFetch<{ orders: any[]; subaccount: number }>(`/api/positions/orders?${params}`);
}

// ── Order management (requires token) ──

let _token = '';
export function setToken(token: string) { _token = token; }

function authHeaders(): Record<string, string> {
	return _token ? { Authorization: `Bearer ${_token}` } : {};
}

export async function placeOrder(params: {
	ticker: string;
	side: string;
	price: number;
	count: number;
	post_only?: boolean;
	expiration_ts?: number;
}) {
	return apiFetch<{ ok: boolean; order?: any; error?: string }>('/api/orders/place', {
		method: 'POST',
		headers: authHeaders(),
		body: JSON.stringify({
			ticker: params.ticker,
			side: params.side,
			price: params.price,
			count: params.count,
			post_only: params.post_only ?? true,
			expiration_ts: params.expiration_ts ?? null,
		}),
	});
}

export async function cancelOrder(orderId: string) {
	return apiFetch<{ ok: boolean; status?: string; error?: string }>('/api/orders/cancel', {
		method: 'POST',
		headers: authHeaders(),
		body: JSON.stringify({ order_id: orderId }),
	});
}

export async function cancelAllOrders(ticker?: string, eventTicker?: string) {
	return apiFetch<{ ok: boolean; cancelled?: number; errors?: number; error?: string }>('/api/orders/cancel-all', {
		method: 'POST',
		headers: authHeaders(),
		body: JSON.stringify({ ticker: ticker ?? null, event_ticker: eventTicker ?? null }),
	});
}

export async function estimateCost(side: string, price: number, count: number, postOnly = true) {
	return apiFetch<{
		ok: boolean;
		gross_cost?: number;
		fee_cents?: number;
		fee_dollars?: number;
		total_cost?: number;
		effective_price?: number;
		is_taker?: boolean;
		role?: string;
		error?: string;
	}>('/api/orders/estimate', {
		method: 'POST',
		body: JSON.stringify({ side, price, count, post_only: postOnly }),
	});
}
