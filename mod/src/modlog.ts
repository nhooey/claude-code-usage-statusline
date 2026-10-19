// The mod's log file, as a file: its name, how much it keeps, and how a
// line is written.  Pure, so the mod (hooks/log.ts) writes it through `$`
// and Node could write the same file the same way.

/** How many lines the log file keeps, the newest last. */
export const LOG_KEPT = 500;
export const LOG_NAME = "usage-band.log";

/** What was thrown, as one line's tail: the message, and where it was
 * thrown from when the error says. */
export function describe(err: unknown): string {
  if (err instanceof Error) {
    const where = (err.stack ?? "").split("\n").slice(1, 4)
      .map((l) => l.trim()).join(" < ");
    return err.message + (where ? " [" + where + "]" : "");
  }
  try {
    return typeof err === "string" ? err : JSON.stringify(err);
  } catch {
    return String(err);
  }
}

/** A line as the file holds it: when, the first eight characters of the
 * session's id, and what, with the error it is about if there is one. */
export function logLine(atMs: number, session: string, what: string,
  err?: unknown): string {
  const line = what + (err === undefined ? "" : ": " + describe(err));
  return `${new Date(atMs).toISOString()} ${session.slice(0, 8)} ${line}`;
}

/** The file's text with `line` added, cut to the newest LOG_KEPT. */
export function logAppended(old: string, line: string): string {
  const lines = [...old.split("\n").filter((l) => l), line];
  return lines.slice(-LOG_KEPT).join("\n") + "\n";
}
