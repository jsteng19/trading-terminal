<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import MarketSelector from '$lib/components/MarketSelector.svelte';
	import OrderBook from '$lib/components/OrderBook.svelte';
	import TradeTape from '$lib/components/TradeTape.svelte';
	import StatsBar from '$lib/components/StatsBar.svelte';
	import OrderEntry from '$lib/components/OrderEntry.svelte';
	import RestingOrders from '$lib/components/RestingOrders.svelte';
	import { selectedEventTicker, selectedMarketTicker, selectedMarket, markets } from '$lib/stores/markets';
	import { updateBook, currentBook } from '$lib/stores/orderbook';
	import { addTrade } from '$lib/stores/trades';
	import { wsClient, type WsMessage } from '$lib/ws/client';
	import { fetchOrderbook, fetchTrades, setToken, cancelAllOrders } from '$lib/api/client';

	let token = $state('');
	let wsConnected = $state(false);
	let mode = $state('');
	let subaccount = $state(1);
	let maxContracts = $state(500);
	let defaultSize = $state(100);
	let sizeIncrement = $state(100);

	// Component refs for keyboard shortcuts
	let orderEntry: OrderEntry;
	let restingOrdersRef: RestingOrders;
	let orderBookRef: OrderBook;

	// Auto-fetch session token + config from backend (local-only, safe)
	onMount(async () => {
		try {
			const [tokenRes, configRes] = await Promise.all([
				fetch('/api/auth/token'),
				fetch('/api/config'),
			]);
			const tokenData = await tokenRes.json();
			const configData = await configRes.json();
			token = tokenData.token;
			mode = configData.mode ?? '';
			subaccount = configData.subaccount ?? 1;
			maxContracts = configData.max_order_contracts ?? 500;
			defaultSize = configData.default_order_size ?? 100;
			sizeIncrement = configData.size_increment ?? 100;
			setToken(token);
		} catch (e) {
			console.error('Failed to fetch config:', e);
		}
	});

	// Handle WS messages — register handler once
	let wsHandlerRegistered = false;

	function ensureWsHandler() {
		if (wsHandlerRegistered) return;
		wsClient.onMessage((msg: WsMessage) => {
			if (msg.type === 'book' && msg.ticker) {
				updateBook(msg.ticker, msg.data);
			} else if (msg.type === 'trade' && msg.ticker) {
				addTrade({ ...msg.data, ticker: msg.ticker });
			}
		});
		wsHandlerRegistered = true;
	}

	// Track which event we're connected to, avoid redundant reconnects
	let connectedEvent = '';

	// Connect WS when event changes
	$effect(() => {
		const eventTicker = $selectedEventTicker;
		const t = token;
		if (eventTicker && t && eventTicker !== connectedEvent) {
			ensureWsHandler();
			connectedEvent = eventTicker;
			wsClient.connect(eventTicker, t);
		} else if (!eventTicker) {
			connectedEvent = '';
			wsClient.disconnect();
		}
	});

	// Load initial orderbook + trades via REST when market changes
	$effect(() => {
		const ticker = $selectedMarketTicker;
		if (!ticker) return;
		fetchOrderbook(ticker).then((res) => {
			const ob = res.orderbook;
			updateBook(ticker, {
				ticker,
				yes_bids: ob.yes || [],
				no_bids: ob.no || [],
				best_yes_bid: null,
				best_yes_ask: null,
				spread: null,
				midpoint: null,
				ts: Date.now() / 1000,
			});
		}).catch((e) => console.error('Failed to fetch orderbook:', e));
		fetchTrades(ticker, 100).then((res) => {
			for (const t of res.trades.reverse()) {
				addTrade({
					ticker,
					side: t.taker_side ?? (t.yes_price && t.yes_price > 50 ? 'yes' : 'no'),
					yes_price: t.yes_price,
					no_price: t.no_price,
					count: t.count,
					ts: t.created_time ? new Date(t.created_time).getTime() / 1000 : Date.now() / 1000,
				});
			}
		}).catch((e) => console.error('Failed to fetch trades:', e));
	});

	// Track connection status
	let connectionPoll: ReturnType<typeof setInterval>;
	onMount(() => {
		connectionPoll = setInterval(() => {
			wsConnected = wsClient.connected;
		}, 1000);
	});

	onDestroy(() => {
		clearInterval(connectionPoll);
		unsubWs?.();
		wsClient.disconnect();
	});

	// ── Keyboard shortcuts ──
	function handleKeydown(e: KeyboardEvent) {
		// Don't capture when typing in input fields
		const target = e.target as HTMLElement;
		if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
			// Allow Enter to submit from input fields in OrderEntry
			if (e.key === 'Enter' && target.closest('[data-order-entry]')) {
				e.preventDefault();
				orderEntry?.submit();
			}
			return;
		}

		switch (e.key) {
			case 'y':
			case 'Y':
				e.preventDefault();
				orderEntry?.setSide('yes');
				break;
			case 'n':
			case 'N':
				e.preventDefault();
				orderEntry?.setSide('no');
				break;
			case 'ArrowUp':
				e.preventDefault();
				orderEntry?.adjustPrice(e.shiftKey ? 5 : 1);
				break;
			case 'ArrowDown':
				e.preventDefault();
				orderEntry?.adjustPrice(e.shiftKey ? -5 : -1);
				break;
			case ']':
			case '+':
			case '=':
				e.preventDefault();
				orderEntry?.adjustCount(sizeIncrement);
				break;
			case '[':
			case '-':
				e.preventDefault();
				orderEntry?.adjustCount(-sizeIncrement);
				break;
			case 'p':
			case 'P':
				// Toggle post_only handled inside component
				break;
			case 'Enter':
				e.preventDefault();
				orderEntry?.submit();
				break;
			case 'Escape':
				e.preventDefault();
				if (e.shiftKey) {
					// Cancel all orders across all markets in event
					const eventTicker = $selectedEventTicker;
					if (eventTicker) cancelAllOrders(undefined, eventTicker).then(() => restingOrdersRef?.refreshOrders());
				} else {
					restingOrdersRef?.handleCancelAll();
				}
				break;
			case 'Tab':
				e.preventDefault();
				cycleMarket(e.shiftKey ? -1 : 1);
				break;
			case '?':
				e.preventDefault();
				showShortcutHelp = !showShortcutHelp;
				break;
		}

		// Number keys 1-9: quick select market
		if (e.key >= '1' && e.key <= '9' && !e.ctrlKey && !e.metaKey) {
			const idx = parseInt(e.key) - 1;
			const mktList = $markets;
			if (idx < mktList.length) {
				e.preventDefault();
				selectedMarketTicker.set(mktList[idx].ticker);
			}
		}
	}

	function cycleMarket(delta: number) {
		const mktList = $markets;
		if (mktList.length === 0) return;
		const currentIdx = mktList.findIndex((m) => m.ticker === $selectedMarketTicker);
		const nextIdx = ((currentIdx + delta) % mktList.length + mktList.length) % mktList.length;
		selectedMarketTicker.set(mktList[nextIdx].ticker);
	}

	// Click on orderbook level → populate order entry
	function handleLevelClick(price: number, count: number, side: 'yes' | 'no', postOnly: boolean) {
		orderEntry?.populateFromBook(price, count, side, postOnly);
	}

	let showShortcutHelp = $state(false);
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- Header -->
<header class="flex items-center justify-between px-3 py-1.5 border-b border-[var(--border)] bg-[var(--bg-secondary)]">
	<div class="flex items-center gap-3">
		<span class="text-[var(--blue)] font-bold text-sm tracking-wider">TERMINAL</span>
		<span class="text-[var(--text-muted)] text-[10px]">
			{#if wsConnected}
				<span class="text-[var(--green)]">&#9679;</span> CONNECTED
			{:else}
				<span class="text-[var(--red)]">&#9679;</span> DISCONNECTED
			{/if}
		</span>
	</div>
	<div class="flex items-center gap-3 text-[10px]">
		{#if $selectedMarket}
			<span class="text-[var(--text-secondary)]">{$selectedMarketTicker}</span>
		{/if}
		<span class="text-[var(--text-muted)]">Sub: {subaccount}</span>
		{#if mode === 'demo'}
			<span class="text-[var(--blue)] font-bold">DEMO</span>
		{:else}
			<span class="text-[var(--yellow)] font-bold">LIVE</span>
		{/if}
		<button
			class="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
			onclick={() => showShortcutHelp = !showShortcutHelp}
			title="Keyboard shortcuts"
		>?</button>
	</div>
</header>

<!-- Main content -->
<div class="flex-1 flex overflow-hidden">
	<!-- Left: Market selector -->
	<div class="w-56 border-r border-[var(--border)] flex-shrink-0 overflow-hidden">
		<MarketSelector />
	</div>

	<!-- Center: Orderbook -->
	<div class="flex-1 flex flex-col overflow-hidden border-r border-[var(--border)]">
		<div class="flex-1 overflow-hidden">
			<OrderBook bind:this={orderBookRef} onlevelclick={handleLevelClick} defaultCount={defaultSize} />
		</div>
	</div>

	<!-- Right panel: Trade tape + Order entry + Resting orders -->
	<div class="w-64 flex-shrink-0 overflow-hidden flex flex-col border-l border-[var(--border)]">
		<!-- Order Entry -->
		<div class="border-b border-[var(--border)]" data-order-entry>
			<OrderEntry bind:this={orderEntry} {defaultSize} {sizeIncrement} maxContracts={maxContracts} />
		</div>

		<!-- Resting Orders -->
		<div class="border-b border-[var(--border)]">
			<RestingOrders bind:this={restingOrdersRef} />
		</div>

		<!-- Trade Tape (fills remaining space) -->
		<div class="flex-1 overflow-hidden">
			<TradeTape />
		</div>
	</div>
</div>

<!-- Bottom: Stats bar -->
<StatsBar />

<!-- Keyboard shortcut help modal -->
{#if showShortcutHelp}
	<div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onclick={() => showShortcutHelp = false}>
		<div class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg p-4 max-w-sm" onclick={(e) => e.stopPropagation()}>
			<div class="text-sm font-bold mb-3 text-[var(--blue)]">Keyboard Shortcuts</div>
			<div class="grid grid-cols-[80px_1fr] gap-1 text-xs">
				<span class="text-[var(--text-muted)]">Y / N</span><span>Set side YES / NO</span>
				<span class="text-[var(--text-muted)]">Up / Down</span><span>Price +/- 1c</span>
				<span class="text-[var(--text-muted)]">Shift+Up/Dn</span><span>Price +/- 5c</span>
				<span class="text-[var(--text-muted)]">] / [</span><span>Size +/- 10</span>
				<span class="text-[var(--text-muted)]">Enter</span><span>Place order</span>
				<span class="text-[var(--text-muted)]">Escape</span><span>Cancel all (ticker)</span>
				<span class="text-[var(--text-muted)]">Shift+Esc</span><span>Cancel all (event)</span>
				<span class="text-[var(--text-muted)]">Tab</span><span>Next market</span>
				<span class="text-[var(--text-muted)]">Shift+Tab</span><span>Prev market</span>
				<span class="text-[var(--text-muted)]">1-9</span><span>Select market #</span>
				<span class="text-[var(--text-muted)]">?</span><span>Toggle this help</span>
			</div>
			<button class="mt-3 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)]" onclick={() => showShortcutHelp = false}>
				Close (? or click outside)
			</button>
		</div>
	</div>
{/if}
