// The usage band's values in `$.state`: what its drawings read, so a write
// redraws them.  Each is JSON, as the host keeps it.

/** A figures document, as claude.ts builds it. */
export type FiguresDoc = { readonly [key: string]: unknown };

declare module 'claude-code' {
  interface PluginState {
    'usage-band': {
      /** Bumped by each load, so the timer an earlier load started stops. */
      generation: number;
      /** The band's last status document, or null before the first. */
      status: FiguresDoc | null;
      /** The main thread's 🛫, tokens a second, or null with no slope. */
      rate: number | null;
      /** Bumped when a receipt or a start line is filed in the store, so
       * the rows that look for one draw again. */
      filed: number;
      /** Seconds since the epoch the band and the footer draw their clocks
       * at, moved each second between reads; 0 before the first. */
      now: number;
    }
  }
}
