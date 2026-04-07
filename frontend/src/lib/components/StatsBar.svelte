<script lang="ts">
	import { currentBook } from '$lib/stores/orderbook';
	import { selectedMarket } from '$lib/stores/markets';
</script>

<div class="flex items-center gap-4 px-3 py-1.5 text-[11px] border-t border-[var(--border)] bg-[var(--bg-secondary)]">
	{#if $currentBook}
		<span>
			<span class="text-[var(--text-muted)]">Bid</span>
			<span class="text-bid font-medium">{$currentBook.best_yes_bid ?? '—'}</span>
		</span>
		<span>
			<span class="text-[var(--text-muted)]">Ask</span>
			<span class="text-ask font-medium">{$currentBook.best_yes_ask ?? '—'}</span>
		</span>
		<span>
			<span class="text-[var(--text-muted)]">Spread</span>
			<span class="text-[var(--text-primary)]">{$currentBook.spread ?? '—'}c</span>
		</span>
		<span>
			<span class="text-[var(--text-muted)]">Mid</span>
			<span class="text-[var(--text-primary)]">{$currentBook.midpoint?.toFixed(1) ?? '—'}</span>
		</span>
	{/if}
	{#if $selectedMarket}
		<span>
			<span class="text-[var(--text-muted)]">Vol</span>
			<span class="text-[var(--text-primary)]">
				{$selectedMarket.volume != null ? ($selectedMarket.volume > 1000 ? (($selectedMarket.volume) / 1000).toFixed(1) + 'K' : $selectedMarket.volume) : '—'}
			</span>
		</span>
		<span>
			<span class="text-[var(--text-muted)]">OI</span>
			<span class="text-[var(--text-primary)]">
				{$selectedMarket.open_interest ?? '—'}
			</span>
		</span>
		<span>
			<span class="text-[var(--text-muted)]">Last</span>
			<span class="text-[var(--text-primary)]">{$selectedMarket.last_price ?? '—'}</span>
		</span>
	{/if}
</div>
