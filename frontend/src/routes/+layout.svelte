<script lang="ts">
	import '../app.css';

	let { children } = $props();
</script>

<div class="h-screen flex flex-col overflow-hidden bg-[var(--bg-primary)]">
	{@render children()}
</div>
