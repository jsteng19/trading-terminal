/**
 * Market and event selection stores.
 */

import { writable, derived } from 'svelte/store';

export type MarketSummary = {
	ticker: string;
	subtitle: string;
	yes_bid: number | null;
	yes_ask: number | null;
	last_price: number | null;
	volume: number | null;
	open_interest: number | null;
	status: string;
	// enriched by position data
	position?: number;
	pnl?: number;
};

export type EventSummary = {
	event_ticker: string;
	title: string;
	series_ticker: string;
	category: string;
};

export const events = writable<EventSummary[]>([]);
export const selectedEventTicker = writable<string>('');
export const markets = writable<MarketSummary[]>([]);
export const selectedMarketTicker = writable<string>('');

export const selectedMarket = derived(
	[markets, selectedMarketTicker],
	([$markets, $ticker]) => $markets.find((m) => m.ticker === $ticker) ?? null
);

export const selectedEvent = derived(
	[events, selectedEventTicker],
	([$events, $ticker]) => $events.find((e) => e.event_ticker === $ticker) ?? null
);
