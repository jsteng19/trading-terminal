<script lang="ts">
	import { currentBook, type BookLevel } from '$lib/stores/orderbook';
	import { selectedMarketTicker, selectedMarket } from '$lib/stores/markets';
	import { currentOrders } from '$lib/stores/orders';
	import { tick } from 'svelte';

	/**
	 * Click callback: (price, count, side, postOnly) => void
	 * - Clicking an ask level = TAKE: side matches view, count = cumulative to clear, postOnly = false
	 * - Clicking a bid level = JOIN: side matches view, count = level qty or default, postOnly = true
	 * - Clicking an empty level = new order at that price, postOnly = true
	 */
	type BookClickHandler = (price: number, count: number, side: 'yes' | 'no', postOnly: boolean) => void;
	let { onlevelclick, defaultCount = 100 }: { onlevelclick?: BookClickHandler; defaultCount?: number } = $props();

	// YES/NO view toggle
	let viewSide = $state<'yes' | 'no'>('yes');

	// Ref for the ladder container (for auto-scroll)
	let ladderEl: HTMLDivElement | undefined = $state();

	type LadderRow = {
		price: number;        // in terms of the viewed side
		bidQty: number;       // resting bids (same side as view)
		askQty: number;       // resting asks (opposite side)
		bidCumul: number;
		askCumul: number;
		isSpread: boolean;
		myBidQty: number;     // user's resting bid quantity at this price
		myAskQty: number;     // user's resting ask quantity at this price
	};

	// Build a map of user's resting orders by price for the current view side
	let myOrderMap = $derived.by(() => {
		const orders = $currentOrders;
		const bidMap = new Map<number, number>();
		const askMap = new Map<number, number>();
		for (const o of orders) {
			if (viewSide === 'yes') {
				if (o.side === 'yes') {
					bidMap.set(o.price, (bidMap.get(o.price) ?? 0) + o.remaining);
				} else {
					// NO order appears as ask at 100 - price
					const askPrice = 100 - o.price;
					askMap.set(askPrice, (askMap.get(askPrice) ?? 0) + o.remaining);
				}
			} else {
				if (o.side === 'no') {
					bidMap.set(o.price, (bidMap.get(o.price) ?? 0) + o.remaining);
				} else {
					const askPrice = 100 - o.price;
					askMap.set(askPrice, (askMap.get(askPrice) ?? 0) + o.remaining);
				}
			}
		}
		return { bidMap, askMap };
	});

	let ladder = $derived.by(() => {
		const book = $currentBook;
		if (!book) return [];

		// In YES view: bids = yes_bids, asks = derived from no_bids (ask = 100 - no_bid)
		// In NO view: bids = no_bids, asks = derived from yes_bids (ask = 100 - yes_bid)
		const bidMap = new Map<number, number>();
		const askMap = new Map<number, number>();

		if (viewSide === 'yes') {
			for (const [price, qty] of book.yes_bids) {
				bidMap.set(price, (bidMap.get(price) ?? 0) + qty);
			}
			for (const [price, qty] of book.no_bids) {
				const askPrice = 100 - price;
				askMap.set(askPrice, (askMap.get(askPrice) ?? 0) + qty);
			}
		} else {
			for (const [price, qty] of book.no_bids) {
				bidMap.set(price, (bidMap.get(price) ?? 0) + qty);
			}
			for (const [price, qty] of book.yes_bids) {
				const askPrice = 100 - price;
				askMap.set(askPrice, (askMap.get(askPrice) ?? 0) + qty);
			}
		}

		// Build visible prices
		const bidPrices = [...bidMap.keys()];
		const askPrices = [...askMap.keys()];
		if (bidPrices.length === 0 && askPrices.length === 0) return [];

		const PADDING = 3;
		const MAX_SPREAD_ROWS = 2;
		const visiblePrices = new Set<number>();

		for (const p of bidPrices) {
			for (let i = 0; i <= PADDING; i++) {
				if (p + i <= 99) visiblePrices.add(p + i);
				if (p - i >= 1) visiblePrices.add(p - i);
			}
		}
		for (const p of askPrices) {
			for (let i = 0; i <= PADDING; i++) {
				if (p + i <= 99) visiblePrices.add(p + i);
				if (p - i >= 1) visiblePrices.add(p - i);
			}
		}

		const highestBid = bidPrices.length > 0 ? Math.max(...bidPrices) : null;
		const lowestAsk = askPrices.length > 0 ? Math.min(...askPrices) : null;
		if (highestBid != null && lowestAsk != null && lowestAsk - highestBid > MAX_SPREAD_ROWS + 1) {
			for (let p = highestBid + 1; p < lowestAsk; p++) visiblePrices.delete(p);
			for (let i = 1; i <= Math.min(MAX_SPREAD_ROWS, lowestAsk - highestBid - 1); i++) {
				visiblePrices.add(highestBid + i);
			}
		}

		const sortedPrices = [...visiblePrices].sort((a, b) => a - b);
		const minPrice = sortedPrices[0];
		const maxPrice = sortedPrices[sortedPrices.length - 1];

		// Cumulative asks ascending (from lowest ask upward)
		const askCumulMap = new Map<number, number>();
		let runningAsk = 0;
		for (let p = minPrice; p <= maxPrice; p++) {
			runningAsk += askMap.get(p) ?? 0;
			askCumulMap.set(p, runningAsk);
		}

		// Cumulative bids descending (from highest bid downward)
		const bidCumulMap = new Map<number, number>();
		let runningBid = 0;
		for (let p = maxPrice; p >= minPrice; p--) {
			runningBid += bidMap.get(p) ?? 0;
			bidCumulMap.set(p, runningBid);
		}

		const { bidMap: myBids, askMap: myAsks } = myOrderMap;

		const rows: LadderRow[] = [];
		for (let i = sortedPrices.length - 1; i >= 0; i--) {
			const p = sortedPrices[i];
			const isSpread = highestBid != null && lowestAsk != null && p > highestBid && p < lowestAsk;
			rows.push({
				price: p,
				bidQty: bidMap.get(p) ?? 0,
				askQty: askMap.get(p) ?? 0,
				bidCumul: bidCumulMap.get(p) ?? 0,
				askCumul: askCumulMap.get(p) ?? 0,
				isSpread,
				myBidQty: myBids.get(p) ?? 0,
				myAskQty: myAsks.get(p) ?? 0,
			});
		}
		return rows;
	});

	let maxQty = $derived(Math.max(1, ...ladder.map((r) => Math.max(r.bidQty, r.askQty))));

	// Spread/mid in terms of current view
	let spread = $derived.by(() => {
		const book = $currentBook;
		if (!book) return null;
		if (viewSide === 'yes') return book.spread;
		const noBid = book.best_no_bid;
		const noAsk = book.best_no_ask;
		if (noBid == null || noAsk == null) return null;
		return noAsk - noBid;
	});

	let midpoint = $derived.by(() => {
		const book = $currentBook;
		if (!book) return null;
		if (viewSide === 'yes') return book.midpoint;
		const noBid = book.best_no_bid;
		const noAsk = book.best_no_ask;
		if (noBid == null || noAsk == null) return null;
		return (noBid + noAsk) / 2;
	});

	// Last price from market data
	let lastPrice = $derived($selectedMarket?.last_price ?? null);

	function handleBidClick(row: LadderRow) {
		// Click on bid = JOIN this level (post_only = true, maker)
		const qty = row.bidQty > 0 ? row.bidQty : defaultCount;
		onlevelclick?.(row.price, qty, viewSide, true);
	}

	function handleAskClick(row: LadderRow) {
		// Click on ask = TAKE through this level (post_only = false, taker)
		const qty = row.askCumul > 0 ? row.askCumul : defaultCount;
		onlevelclick?.(row.price, qty, viewSide, false);
	}

	function handlePriceClick(row: LadderRow) {
		// Click on price = create new order at this price (post_only = true, maker)
		onlevelclick?.(row.price, defaultCount, viewSide, true);
	}

	export function toggleView() {
		viewSide = viewSide === 'yes' ? 'no' : 'yes';
	}

	// Auto-center on spread when market changes
	let lastCenteredTicker = '';
	$effect(() => {
		const ticker = $selectedMarketTicker;
		const rows = ladder;
		if (!ticker || rows.length === 0) return;
		if (ticker === lastCenteredTicker) return;
		lastCenteredTicker = ticker;
		// Wait for DOM to render
		tick().then(() => {
			scrollToSpread();
		});
	});

	function scrollToSpread() {
		if (!ladderEl) return;
		const spreadRow = ladderEl.querySelector('[data-spread]');
		if (spreadRow) {
			spreadRow.scrollIntoView({ block: 'center', behavior: 'instant' });
		} else {
			// No spread rows — center on the middle of the ladder
			const rows = ladderEl.querySelectorAll('[data-row]');
			if (rows.length > 0) {
				const mid = rows[Math.floor(rows.length / 2)];
				mid.scrollIntoView({ block: 'center', behavior: 'instant' });
			}
		}
	}
</script>

<div class="h-full flex flex-col overflow-hidden">
	<!-- Header with YES/NO switcher -->
	<div class="flex items-center justify-between px-2 py-1 border-b border-[var(--border)] text-[10px]">
		<div class="flex items-center gap-1.5">
			<span class="text-[var(--text-muted)]">BOOK</span>
			<button
				class="px-1.5 py-0.5 rounded font-bold transition-colors
					{viewSide === 'yes' ? 'bg-[var(--green)] text-black' : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'}"
				onclick={() => viewSide = 'yes'}
			>YES</button>
			<button
				class="px-1.5 py-0.5 rounded font-bold transition-colors
					{viewSide === 'no' ? 'bg-[var(--red)] text-white' : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'}"
				onclick={() => viewSide = 'no'}
			>NO</button>
		</div>
		<span class="text-[var(--text-muted)]">
			{#if spread != null}Spd {spread}c{/if}
			{#if midpoint != null} | Mid {midpoint.toFixed(1)}{/if}
		</span>
	</div>

	<!-- Column headers -->
	<div class="grid grid-cols-[40px_50px_16px_36px_16px_50px_40px] gap-0 px-1 py-0.5 border-b border-[var(--border)] text-[10px] text-[var(--text-muted)]">
		<span class="text-right">Cumul</span>
		<span class="text-right">Bid</span>
		<span></span>
		<span class="text-center">Price</span>
		<span></span>
		<span class="text-left">Ask</span>
		<span class="text-left">Cumul</span>
	</div>

	<!-- Ladder -->
	<div class="flex-1 overflow-y-auto" id="orderbook-ladder" bind:this={ladderEl}>
		{#each ladder as row}
			{@const bidWidth = (row.bidQty / maxQty) * 100}
			{@const askWidth = (row.askQty / maxQty) * 100}
			<div
				class="grid grid-cols-[40px_50px_16px_36px_16px_50px_40px] gap-0 px-1 py-px text-xs relative
					{row.isSpread ? 'bg-[var(--bg-secondary)]' : ''}"
				data-row
				data-spread={row.isSpread ? '' : undefined}
			>
				<!-- Bid depth bar -->
				{#if row.bidQty > 0}
					<div
						class="absolute top-0 bottom-0 bg-[var(--green-dim)] opacity-30"
						style="right: calc(50% + 18px); width: {bidWidth * 0.35}%"
					></div>
				{/if}
				<!-- Ask depth bar -->
				{#if row.askQty > 0}
					<div
						class="absolute top-0 bottom-0 bg-[var(--red-dim)] opacity-30"
						style="left: calc(50% + 18px); width: {askWidth * 0.35}%"
					></div>
				{/if}

				<!-- Bid cumulative -->
				<span class="text-right text-[var(--text-muted)] text-[10px] relative z-10">
					{row.bidCumul > 0 ? row.bidCumul.toLocaleString() : ''}
				</span>

				<!-- Bid qty (clickable) -->
				<span
					class="text-right text-bid relative z-10 font-medium cursor-pointer hover:underline"
					role="button" tabindex="-1"
					onclick={() => handleBidClick(row)}
					onkeydown={(e) => { if (e.key === 'Enter') handleBidClick(row); }}
				>
					{row.bidQty > 0 ? row.bidQty.toLocaleString() : ''}
				</span>

				<!-- My bid marker -->
				<span class="text-center relative z-10 text-[10px]">
					{#if row.myBidQty > 0}
						<span class="text-[var(--blue)]" title="My bid: {row.myBidQty}">{row.myBidQty}</span>
					{/if}
				</span>

				<!-- Price (clickable for order creation) -->
				{#if row.isSpread && lastPrice != null}
					<!-- Show last price in the first spread row -->
					{@const isFirstSpread = ladder.filter(r => r.isSpread).indexOf(row) === 0}
					{#if isFirstSpread}
						<span
							class="text-center text-[var(--yellow)] relative z-10 font-medium cursor-pointer hover:underline text-[10px]"
							role="button" tabindex="-1"
							onclick={() => handlePriceClick(row)}
							onkeydown={(e) => { if (e.key === 'Enter') handlePriceClick(row); }}
							title="Last: {lastPrice}c"
						>
							L:{lastPrice}
						</span>
					{:else}
						<span
							class="text-center text-[var(--text-muted)] relative z-10 font-medium cursor-pointer hover:underline"
							role="button" tabindex="-1"
							onclick={() => handlePriceClick(row)}
							onkeydown={(e) => { if (e.key === 'Enter') handlePriceClick(row); }}
						>
							{row.price}
						</span>
					{/if}
				{:else}
					<span
						class="text-center text-[var(--text-secondary)] relative z-10 font-medium cursor-pointer hover:underline"
						role="button" tabindex="-1"
						onclick={() => handlePriceClick(row)}
						onkeydown={(e) => { if (e.key === 'Enter') handlePriceClick(row); }}
					>
						{row.price}
					</span>
				{/if}

				<!-- My ask marker -->
				<span class="text-center relative z-10 text-[10px]">
					{#if row.myAskQty > 0}
						<span class="text-[var(--blue)]" title="My ask: {row.myAskQty}">{row.myAskQty}</span>
					{/if}
				</span>

				<!-- Ask qty (clickable) -->
				<span
					class="text-left text-ask relative z-10 font-medium cursor-pointer hover:underline"
					role="button" tabindex="-1"
					onclick={() => handleAskClick(row)}
					onkeydown={(e) => { if (e.key === 'Enter') handleAskClick(row); }}
				>
					{row.askQty > 0 ? row.askQty.toLocaleString() : ''}
				</span>

				<!-- Ask cumulative -->
				<span class="text-left text-[var(--text-muted)] text-[10px] relative z-10">
					{row.askCumul > 0 ? row.askCumul.toLocaleString() : ''}
				</span>
			</div>
		{/each}
	</div>
</div>
