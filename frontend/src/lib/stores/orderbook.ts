/**
 * Orderbook store fed by WebSocket updates.
 */

import { writable, derived } from 'svelte/store';
import { selectedMarketTicker } from './markets';

export type BookLevel = [number, number];  // [price_cents, quantity]

export type BookData = {
	ticker: string;
	yes_bids: BookLevel[];
	no_bids: BookLevel[];
	best_yes_bid: number | null;
	best_yes_ask: number | null;
	spread: number | null;
	midpoint: number | null;
	ts: number;
};

// All books keyed by ticker
export const books = writable<Record<string, BookData>>({});

// Current selected market's book
export const currentBook = derived(
	[books, selectedMarketTicker],
	([$books, $ticker]) => $books[$ticker] ?? null
);

export function updateBook(ticker: string, data: BookData) {
	books.update((b) => {
		b[ticker] = data;
		return b;
	});
}
