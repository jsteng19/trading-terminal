<script lang="ts">
	import { selectedMarketTicker, selectedMarket, selectedEvent, selectedEventTicker } from '$lib/stores/markets';
	import { currentBook } from '$lib/stores/orderbook';
	import { placeOrder, estimateCost, fetchEventStartTime } from '$lib/api/client';

	let {
		defaultSize = 100,
		sizeIncrement = 100,
		maxContracts = 500,
	}: {
		defaultSize?: number;
		sizeIncrement?: number;
		maxContracts?: number;
	} = $props();

	let side = $state<'yes' | 'no'>('yes');
	let price = $state(50);
	let count = $state(defaultSize);
	let postOnly = $state(true);
	let submitting = $state(false);
	let lastResult = $state<{ ok: boolean; message: string } | null>(null);

	// Expiration
	type ExpirationMode = 'none' | '10min' | 'eod' | 'event_start' | 'custom';
	let expirationMode = $state<ExpirationMode>('none');
	let customExpirationMinutes = $state(30);

	// Event start time (fetched from backend, uses cutoff_resolver)
	let eventStartUtc = $state<string | null>(null);
	let eventStartAvailable = $state(false);

	$effect(() => {
		const eventTicker = $selectedEventTicker;
		if (!eventTicker) {
			eventStartUtc = null;
			eventStartAvailable = false;
			return;
		}
		fetchEventStartTime(eventTicker).then((res) => {
			eventStartUtc = res.event_start_utc;
			eventStartAvailable = res.event_start_utc != null;
		}).catch(() => {
			eventStartUtc = null;
			eventStartAvailable = false;
		});
	});

	// Compute expiration timestamp
	let expirationTs = $derived.by((): number | null => {
		if (expirationMode === 'none') return null;
		if (expirationMode === '10min') {
			return Math.floor(Date.now() / 1000) + 10 * 60;
		}
		if (expirationMode === 'eod') {
			// End of day 4:00 PM ET (Eastern)
			const now = new Date();
			// Build today at 4pm ET using Intl to handle DST
			const etFormatter = new Intl.DateTimeFormat('en-US', {
				timeZone: 'America/New_York',
				year: 'numeric', month: '2-digit', day: '2-digit',
			});
			const parts = etFormatter.formatToParts(now);
			const y = parts.find(p => p.type === 'year')!.value;
			const m = parts.find(p => p.type === 'month')!.value;
			const d = parts.find(p => p.type === 'day')!.value;
			// 4:00 PM ET = 16:00
			const eodEt = new Date(`${y}-${m}-${d}T16:00:00`);
			// Convert ET to UTC by finding the offset
			const etNow = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));
			const offsetMs = now.getTime() - etNow.getTime();
			const eodUtc = new Date(eodEt.getTime() + offsetMs);
			const ts = Math.floor(eodUtc.getTime() / 1000);
			if (ts <= Date.now() / 1000) return null; // Already past EOD
			return ts;
		}
		if (expirationMode === 'event_start') {
			if (!eventStartUtc) return null;
			const ts = Math.floor(new Date(eventStartUtc).getTime() / 1000);
			if (isNaN(ts) || ts <= Date.now() / 1000) return null;
			return ts;
		}
		if (expirationMode === 'custom') {
			return Math.floor(Date.now() / 1000) + customExpirationMinutes * 60;
		}
		return null;
	});

	// Format time in local timezone, always showing clock time
	function formatLocalTime(ts: number): string {
		const d = new Date(ts * 1000);
		return d.toLocaleString(undefined, {
			month: 'short', day: 'numeric',
			hour: 'numeric', minute: '2-digit',
			hour12: true,
		});
	}

	// Human-readable expiration label — always local time
	let expirationLabel = $derived.by((): string => {
		if (expirationMode === 'none') return '';
		if (expirationTs == null) {
			if (expirationMode === 'event_start') return '(no start time)';
			if (expirationMode === 'eod') return '(past EOD)';
			return '';
		}
		return formatLocalTime(expirationTs);
	});

	// Cost estimate
	let costEstimate = $state<{ total: string; fee: string; label: string } | null>(null);

	$effect(() => {
		const _side = side;
		const _price = price;
		const _count = count;
		const _postOnly = postOnly;
		if (_price >= 1 && _price <= 99 && _count >= 1) {
			estimateCost(_side, _price, _count, _postOnly).then((res) => {
				if (res.ok) {
					costEstimate = {
						total: `$${res.total_cost!.toFixed(2)}`,
						fee: res.is_taker ? `${res.fee_cents}c fee` : 'no fee',
						label: res.is_taker ? 'TAKER' : 'MAKER',
					};
				}
			}).catch(() => {});
		}
	});

	async function handlePlace() {
		const ticker = $selectedMarketTicker;
		if (!ticker) return;
		if (count > maxContracts) {
			lastResult = { ok: false, message: `Max ${maxContracts} contracts per order` };
			return;
		}
		submitting = true;
		lastResult = null;
		try {
			const res = await placeOrder({
				ticker,
				side,
				price,
				count,
				post_only: postOnly,
				expiration_ts: expirationTs ?? undefined,
			});
			if (res.ok) {
				lastResult = { ok: true, message: `${side.toUpperCase()} ${count}@${price}c placed` };
			} else {
				lastResult = { ok: false, message: res.error ?? 'Failed' };
			}
		} catch (e: any) {
			lastResult = { ok: false, message: e.message };
		} finally {
			submitting = false;
		}
	}

	// Exposed methods for keyboard shortcuts and orderbook clicks
	export function setSide(s: 'yes' | 'no') { side = s; }
	export function adjustPrice(delta: number) { price = Math.max(1, Math.min(99, price + delta)); }
	export function adjustCount(delta: number) { count = Math.max(1, Math.min(maxContracts, count + delta)); }
	export function submit() { handlePlace(); }
	export function setPrice(p: number) { price = Math.max(1, Math.min(99, p)); }
	export function setCount(c: number) { count = Math.max(1, Math.min(maxContracts, c)); }
	export function setPostOnly(v: boolean) { postOnly = v; }

	/** Populate the ticket from an orderbook click */
	export function populateFromBook(p: number, c: number, s: 'yes' | 'no', po: boolean) {
		side = s;
		price = Math.max(1, Math.min(99, p));
		count = Math.max(1, Math.min(maxContracts, c));
		postOnly = po;
		lastResult = null;
	}
</script>

<div class="flex flex-col gap-1.5 p-2">
	<div class="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Order Entry</div>

	<!-- Side toggle -->
	<div class="flex gap-1">
		<button
			class="flex-1 py-1 text-xs font-bold rounded transition-colors
				{side === 'yes' ? 'bg-[var(--green)] text-black' : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'}"
			onclick={() => side = 'yes'}
		>YES <span class="text-[10px] opacity-60">Y</span></button>
		<button
			class="flex-1 py-1 text-xs font-bold rounded transition-colors
				{side === 'no' ? 'bg-[var(--red)] text-white' : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'}"
			onclick={() => side = 'no'}
		>NO <span class="text-[10px] opacity-60">N</span></button>
	</div>

	<!-- Price -->
	<div class="flex items-center gap-1">
		<span class="text-[10px] text-[var(--text-muted)] w-10">Price</span>
		<button class="px-1.5 py-0.5 bg-[var(--bg-tertiary)] rounded text-xs" onclick={() => adjustPrice(-5)}>-5</button>
		<button class="px-1.5 py-0.5 bg-[var(--bg-tertiary)] rounded text-xs" onclick={() => adjustPrice(-1)}>-</button>
		<input
			type="number"
			bind:value={price}
			min="1" max="99"
			class="w-12 text-center bg-[var(--bg-tertiary)] border border-[var(--border)] rounded text-xs py-0.5"
		/>
		<button class="px-1.5 py-0.5 bg-[var(--bg-tertiary)] rounded text-xs" onclick={() => adjustPrice(1)}>+</button>
		<button class="px-1.5 py-0.5 bg-[var(--bg-tertiary)] rounded text-xs" onclick={() => adjustPrice(5)}>+5</button>
		<span class="text-[10px] text-[var(--text-muted)]">c</span>
	</div>

	<!-- Size -->
	<div class="flex items-center gap-1">
		<span class="text-[10px] text-[var(--text-muted)] w-10">Size</span>
		<input
			type="number"
			bind:value={count}
			min="1" max={maxContracts}
			class="w-16 text-center bg-[var(--bg-tertiary)] border border-[var(--border)] rounded text-xs py-0.5"
		/>
		<span class="text-[10px] text-[var(--text-muted)]">/ {maxContracts}</span>
	</div>

	<!-- Post Only toggle -->
	<label class="flex items-center gap-1.5 text-[10px]">
		<input type="checkbox" bind:checked={postOnly} class="accent-[var(--blue)]" />
		<span class="text-[var(--text-secondary)]">Post Only (maker, no fee)</span>
	</label>

	<!-- Expiration -->
	<div class="flex items-center gap-1 flex-wrap">
		<span class="text-[10px] text-[var(--text-muted)] w-10">Exp</span>
		<select
			bind:value={expirationMode}
			class="bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-primary)] rounded text-[10px] py-0.5 px-1"
		>
			<option value="none">None (GTC)</option>
			<option value="10min">10 min</option>
			<option value="eod">EOD (4pm ET)</option>
			{#if eventStartAvailable}
				<option value="event_start">Event Start</option>
			{/if}
			<option value="custom">Custom</option>
		</select>
		{#if expirationMode === 'custom'}
			<input
				type="number"
				bind:value={customExpirationMinutes}
				min="1" max="10080"
				class="w-12 text-center bg-[var(--bg-tertiary)] border border-[var(--border)] rounded text-[10px] py-0.5"
			/>
			<span class="text-[10px] text-[var(--text-muted)]">min</span>
		{/if}
		{#if expirationMode !== 'none' && expirationLabel}
			<span class="text-[10px] text-[var(--text-secondary)]">{expirationLabel}</span>
		{/if}
	</div>

	<!-- Cost estimate -->
	{#if costEstimate}
		<div class="text-[10px] text-[var(--text-muted)] flex gap-2">
			<span>Cost: <span class="text-[var(--text-primary)]">{costEstimate.total}</span></span>
			<span class="{costEstimate.label === 'TAKER' ? 'text-[var(--yellow)]' : 'text-[var(--green)]'}">{costEstimate.fee}</span>
			<span class="uppercase text-[var(--text-muted)]">{costEstimate.label}</span>
		</div>
	{/if}

	<!-- Place button -->
	<button
		class="w-full py-1.5 rounded font-bold text-xs transition-colors
			{side === 'yes' ? 'bg-[var(--green)] text-black hover:brightness-110' : 'bg-[var(--red)] text-white hover:brightness-110'}
			{submitting ? 'opacity-50 cursor-wait' : ''}"
		onclick={handlePlace}
		disabled={submitting || !$selectedMarketTicker}
	>
		{submitting ? 'PLACING...' : `BUY ${side.toUpperCase()} ${count} @ ${price}c`}
		{#if !postOnly}<span class="text-[10px] opacity-60 ml-1">(IOC)</span>{/if}
		<span class="text-[10px] opacity-60 ml-1">Enter</span>
	</button>

	<!-- Result message -->
	{#if lastResult}
		<div class="text-[10px] {lastResult.ok ? 'text-[var(--green)]' : 'text-[var(--red)]'}">
			{lastResult.message}
		</div>
	{/if}
</div>
