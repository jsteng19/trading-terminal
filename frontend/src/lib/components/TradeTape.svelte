<script lang="ts">
	import { currentTrades, type Trade } from '$lib/stores/trades';

	function formatTime(ts: number): string {
		const d = new Date(ts * 1000);
		return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
	}
</script>

<div class="h-full flex flex-col overflow-hidden">
	<div class="px-2 py-1 border-b border-[var(--border)] text-[10px] text-[var(--text-muted)]">
		TRADE TAPE
	</div>

	<div class="flex-1 overflow-y-auto">
		{#each $currentTrades.slice(0, 50) as trade}
			{@const isYes = trade.side?.toLowerCase() === 'yes'}
			<div class="flex items-center justify-between px-2 py-px text-[11px] border-b border-[var(--bg-secondary)]">
				<span class="text-[var(--text-muted)] text-[10px] w-14">{formatTime(trade.ts)}</span>
				<span class="{isYes ? 'text-bid' : 'text-ask'} w-6 text-center font-medium">
					{trade.yes_price}
				</span>
				<span class="text-[var(--text-secondary)] w-10 text-right">x{trade.count}</span>
				<span class="{isYes ? 'text-bid' : 'text-ask'} w-5 text-right text-[10px]">
					{isYes ? '\u25B2' : '\u25BC'}
				</span>
			</div>
		{/each}
		{#if $currentTrades.length === 0}
			<div class="text-[var(--text-muted)] text-xs text-center py-4">No trades</div>
		{/if}
	</div>
</div>
