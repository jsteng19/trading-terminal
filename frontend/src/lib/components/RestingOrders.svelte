<script lang="ts">
	import { currentOrders, restingOrders, removeOrder } from '$lib/stores/orders';
	import { selectedMarketTicker, selectedEventTicker } from '$lib/stores/markets';
	import { cancelOrder, cancelAllOrders, fetchOrders } from '$lib/api/client';
	import { onMount } from 'svelte';

	let cancelling = $state<Set<string>>(new Set());

	async function handleCancel(orderId: string) {
		cancelling.add(orderId);
		cancelling = new Set(cancelling);
		try {
			const res = await cancelOrder(orderId);
			if (res.ok) {
				removeOrder(orderId);
			}
		} catch (e) {
			console.error('Cancel failed:', e);
		} finally {
			cancelling.delete(orderId);
			cancelling = new Set(cancelling);
		}
	}

	async function handleCancelAll() {
		const ticker = $selectedMarketTicker;
		if (!ticker) return;
		try {
			await cancelAllOrders(ticker);
			await refreshOrders();
		} catch (e) {
			console.error('Cancel all failed:', e);
		}
	}

	async function refreshOrders() {
		const eventTicker = $selectedEventTicker;
		if (!eventTicker) return;
		try {
			const res = await fetchOrders(eventTicker, 'resting');
			restingOrders.set(
				res.orders.map((o: any) => ({
					order_id: o.order_id,
					ticker: o.ticker,
					side: o.side ?? (o.yes_price ? 'yes' : 'no'),
					price: o.yes_price ?? o.no_price ?? 0,
					count: o.initial_count ?? o.remaining_count ?? 0,
					remaining: o.remaining_count ?? 0,
					status: o.status ?? 'resting',
				}))
			);
		} catch (e) {
			console.error('Failed to refresh orders:', e);
		}
	}

	// Refresh orders when event or market changes
	$effect(() => {
		const _event = $selectedEventTicker;
		if (_event) refreshOrders();
	});

	// Periodic refresh every 5 seconds
	let interval: ReturnType<typeof setInterval>;
	onMount(() => {
		interval = setInterval(refreshOrders, 5000);
		return () => clearInterval(interval);
	});

	// Expose for keyboard shortcut
	export { handleCancelAll, refreshOrders };
</script>

<div class="flex flex-col gap-0.5 p-2">
	<div class="flex items-center justify-between">
		<span class="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Resting Orders</span>
		{#if $currentOrders.length > 0}
			<button
				class="text-[10px] text-[var(--red)] hover:text-red-300 transition-colors"
				onclick={handleCancelAll}
			>Cancel All <span class="opacity-60">Esc</span></button>
		{/if}
	</div>

	{#each $currentOrders as order}
		<div class="flex items-center justify-between py-0.5 text-[11px]
			{order.side === 'yes' ? 'border-l-2 border-l-[var(--green)] pl-1' : 'border-l-2 border-l-[var(--red)] pl-1'}">
			<div class="flex items-center gap-1.5">
				<span class="{order.side === 'yes' ? 'text-bid' : 'text-ask'} font-medium w-6 text-right">
					{order.price}c
				</span>
				<span class="text-[var(--text-secondary)]">
					{order.side.toUpperCase()} x{order.remaining}
				</span>
			</div>
			<button
				class="text-[var(--text-muted)] hover:text-[var(--red)] text-[10px] px-1 transition-colors"
				onclick={() => handleCancel(order.order_id)}
				disabled={cancelling.has(order.order_id)}
			>
				{cancelling.has(order.order_id) ? '...' : 'X'}
			</button>
		</div>
	{/each}

	{#if $currentOrders.length === 0}
		<div class="text-[10px] text-[var(--text-muted)] py-1">No resting orders</div>
	{/if}

	<!-- Show orders for other markets in this event -->
	{#if $restingOrders.length > $currentOrders.length}
		<div class="text-[10px] text-[var(--text-muted)] mt-1 pt-1 border-t border-[var(--border)]">
			+{$restingOrders.length - $currentOrders.length} orders on other markets
		</div>
	{/if}
</div>
