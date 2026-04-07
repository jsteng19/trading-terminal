/**
 * Resting orders store.
 */

import { writable, derived } from 'svelte/store';
import { selectedMarketTicker } from './markets';

export type RestingOrder = {
	order_id: string;
	ticker: string;
	side: string;
	price: number;  // cents
	count: number;
	remaining: number;
	status: string;
};

export const restingOrders = writable<RestingOrder[]>([]);

export const currentOrders = derived(
	[restingOrders, selectedMarketTicker],
	([$orders, $ticker]) => $orders.filter((o) => o.ticker === $ticker)
);

export function setRestingOrders(orders: RestingOrder[]) {
	restingOrders.set(orders);
}

export function removeOrder(orderId: string) {
	restingOrders.update((orders) => orders.filter((o) => o.order_id !== orderId));
}
