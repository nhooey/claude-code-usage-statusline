// The repository's address on GitHub, from its git remote: what the band
// tree's 📦 🌿 🔀 link under (band_tree.ts, workspaceLinks).

/** The `https://github.com/<owner>/<repo>` a remote's URL names, in any
 * of the forms git takes it (`git@github.com:o/r.git`,
 * `ssh://git@github.com/o/r`, `https://github.com/o/r.git`, with a user or
 * a port or not), or null for a remote on any other host. */
export function githubRepo(remote: string): string | null {
  const url = remote.trim();
  const m =
    /^(?:[a-z+]+:\/\/)?(?:[^@/]+@)?github\.com(?::\d+)?[:/]([^/\s]+)\/([^/\s]+?)(?:\.git)?\/?$/i
      .exec(url);
  if (!m) return null;
  return "https://github.com/" + m[1] + "/" + m[2];
}
