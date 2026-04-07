<script lang="ts">
	import { events, selectedEventTicker, markets, selectedMarketTicker, type MarketSummary } from '$lib/stores/markets';
	import { fetchEvents, fetchEventMarkets } from '$lib/api/client';
	import { books } from '$lib/stores/orderbook';
	import { onMount } from 'svelte';

	let loading = $state(false);

	async function loadEvents() {
		loading = true;
		try {
			const res = await fetchEvents();
			events.set(res.events.map((e: any) => ({
				event_ticker: e.event_ticker ?? e.ticker,
				title: e.title ?? e.event_ticker,
				series_ticker: e.series_ticker ?? '',
				category: e.category ?? '',
			})));
		} catch (e) {
			console.error('Failed to load events:', e);
		} finally {
			loading = false;
		}
	}

	async function selectEvent(eventTicker: string) {
		selectedEventTicker.set(eventTicker);
		selectedMarketTicker.set('');
		loading = true;
		try {
			const res = await fetchEventMarkets(eventTicker);
			const sorted = res.markets
				.filter((m: any) => m.status !== 'finalized')
				.map((m: any): MarketSummary => ({
					ticker: m.ticker,
					subtitle: m.yes_sub_title ?? m.subtitle ?? m.title ?? m.ticker,
					yes_bid: m.yes_bid,
					yes_ask: m.yes_ask,
					last_price: m.last_price,
					volume: m.volume,
					open_interest: m.open_interest,
					status: m.status,
				}))
				.sort((a: MarketSummary, b: MarketSummary) => (b.volume ?? 0) - (a.volume ?? 0));
			markets.set(sorted);
			if (sorted.length > 0) {
				selectedMarketTicker.set(sorted[0].ticker);
			}
		} catch (e) {
			console.error('Failed to load markets:', e);
		} finally {
			loading = false;
		}
	}

	function selectMarket(ticker: string) {
		selectedMarketTicker.set(ticker);
	}

	onMount(() => {
		loadEvents();
	});
</script>

<div class="h-full flex flex-col overflow-hidden">
	<!-- Event selector -->
	<div class="px-2 py-1.5 border-b border-[var(--border)]">
		<select
			class="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] px-2 py-1 rounded text-xs"
			value={$selectedEventTicker}
			onchange={(e) => selectEvent((e.target as HTMLSelectElement).value)}
		>
			<option value="">Select Event...</option>
			{#each $events as event}
				<option value={event.event_ticker}>
					{event.title}
				</option>
			{/each}
		</select>
		{#if loading}
			<div class="text-[var(--text-muted)] text-[10px] mt-0.5">loading...</div>
		{/if}
	</div>

	<!-- Market list -->
	<div class="flex-1 overflow-y-auto">
		{#each $markets as market, i}
			{@const book = $books[market.ticker]}
			{@const bid = book?.best_yes_bid ?? market.yes_bid}
			{@const ask = book?.best_yes_ask ?? market.yes_ask}
			<button
				class="w-full text-left px-2 py-1.5 border-b border-[var(--border)] hover:bg-[var(--bg-tertiary)] transition-colors
					{market.ticker === $selectedMarketTicker ? 'bg-[var(--bg-tertiary)] border-l-2 border-l-[var(--blue)]' : ''}"
				onclick={() => selectMarket(market.ticker)}
			>
				<div class="flex items-center justify-between">
					<div class="flex items-center gap-1.5 min-w-0">
						<span class="text-[var(--text-muted)] text-[10px] w-4 text-right shrink-0">{i + 1}</span>
						<span class="text-xs truncate">{market.subtitle}</span>
					</div>
					<div class="flex items-center gap-2 shrink-0 text-[10px]">
						{#if bid != null}
							<span class="text-bid">{bid}</span>
						{/if}
						{#if ask != null}
							<span class="text-ask">{ask}</span>
						{/if}
					</div>
				</div>
				{#if market.volume}
					<div class="text-[var(--text-muted)] text-[10px] ml-5">
						vol {(market.volume / 1000).toFixed(1)}K
					</div>
				{/if}
			</button>
		{/each}
	</div>
</div>
