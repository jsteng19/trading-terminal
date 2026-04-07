/**
 * Trade tape store.
 */

import { writable, derived } from 'svelte/store';
import { selectedMarketTicker } from './markets';

export type Trade = {
	ticker: string;
	side: string;
	yes_price: number;
	no_price: number;
	count: number;
	ts: number;
};

const MAX_TRADES = 200;

// All trades keyed by ticker (most recent first)
export const tradesByTicker = writable<Record<string, Trade[]>>({});

export const currentTrades = derived(
	[tradesByTicker, selectedMarketTicker],
	([$trades, $ticker]) => $trades[$ticker] ?? []
);

export function addTrade(trade: Trade) {
	tradesByTicker.update((all) => {
		const list = all[trade.ticker] ?? [];
		list.unshift(trade);
		if (list.length > MAX_TRADES) list.length = MAX_TRADES;
		all[trade.ticker] = list;
		return all;
	});
}
