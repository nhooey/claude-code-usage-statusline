#!/usr/bin/env bash
# Measure this terminal's CURSOR ADVANCE for each glyph, by asking it.
#
# For every codepoint: park the cursor at column 1, draw the glyph, then send
# DSR (ESC[6n). The terminal replies with the cursor position, and the column
# it reports minus one is how many cells it advanced. That is the number this
# terminal actually lays out with — no table, no inference.
#
# Run it in a REAL terminal tab — Claude Code has no controlling terminal, so
# the DSR handshake has nothing to answer it there. The handshake uses
# /dev/tty; the report goes to stdout, so it can be redirected to a file.
export LC_ALL=en_US.UTF-8

# The program under measurement. Beside this script, the way
# compaction-once.py finds it, since this probe lives in the program's own
# repo now: it parses the E_* constants and EAW_WIDE out of that file, so it
# is coupled to it and a wrong path is a silent wrong answer. Overridable so a
# candidate can be probed without touching the checked-in one.
#
# This read statusline.sh until 2026-08-25, and that was wrong in a way no run
# of this probe could report: statusline.sh is a test reference that
# settings.json does not run, so the probe measured the glyph set of a file
# nothing draws with. Four glyphs live only in the Python — E_COSTLINE and the
# three E_ROW_* — and this probe had never measured one of them.
DIR="$(cd "$(dirname "$0")" && pwd)"
LIVE="${PROBE_PROG:-$DIR/../claude-code-usage-statusline.py}"
PY=/usr/bin/python3

exec 3<>/dev/tty || { echo "no controlling terminal"; exit 1; }

old=$(stty -g <&3)
trap 'stty "$old" <&3' EXIT
stty raw -echo min 0 time 2 <&3

advance() {                       # $1 = glyph -> columns advanced
  local col
  printf '\r%s\033[6n' "$1" >&3
  IFS='[;' read -r -s -d R -t 2 _ _ col <&3
  printf '\r\033[K' >&3
  printf '%s' "$(( ${col:-1} - 1 ))"
}

# Every measurement is recorded as "codepoint measured", so the classifier
# below can compare it against what the EAW table claims without anyone
# retyping a codepoint. That retyping is where this goes wrong silently: one
# transposed digit produces a table wrong by a column in a single glyph, which
# looks exactly like the bug being chased.
# Only glyphs the status line actually renders may enter the tables. Two other
# kinds are measured and reported, and both must stay out:
#
#   Sequences (skin tone, ZWJ, flag, keycap) measure as a whole, but a table
#   entry is per codepoint, so recording one would file the measurement under
#   its BASE. The keycap 1️⃣ is U+0031 U+FE0F U+20E3, and doing this put 49 —
#   ASCII "1" — into EAW_ICONS, where it would have made every literal 1 in
#   the row count two columns: 📏1M, ⟳ 51m, ⏱ 13s, every clock reading. A
#   width that moves with the digits in the data, which is far worse than the
#   drift being hunted.
#
#   Block samples are representatives, and the blocks are not uniform — 🤀
#   measures 1 beside 🌀 😀 🚀 measuring 2. Generalising from them is unsound.
#
# So report() takes a class, and only USED entries reach the classifier.
MEASURED=""
report() {                        # $1 label, $2 glyph, $3 class (used|sample|seq)
  local g="$2" a cp
  a=$(advance "$g")
  printf -v cp '%d' "'$g"
  case "${3:-used}" in
    used) [ "$cp" -ge 128 ] && MEASURED="$MEASURED $cp:$a" ;;
  esac
  printf '%-9s %-4s advance=%s\n' "$1" "$g" "$a"
}

# ── reading the live program ────────────────────────────────────────────────
#
# Both extractions PARSE the Python. They do not eval it and they do not
# import it. The bash constants this probe used to read were single-quoted
# literals a shell could eval straight; the Python's are double-quoted, three
# of them are written as \U0001F4AC escapes, and EAW_WIDE is a tuple of pairs
# — none of which a shell can read. Importing the module would read all of it
# perfectly and also run a status line as a side effect. ast does neither.
glyph_constants() {   # -> "U+XXXX<TAB>glyph" per codepoint, first use wins
  "$PY" - "$LIVE" <<'PYEOF'
import ast, re, sys
src = open(sys.argv[1], encoding="utf-8").read()
seen = set()
for node in ast.parse(src).body:
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        continue
    t = node.targets[0]
    if not isinstance(t, ast.Name) or not re.fullmatch(r"E_[A-Z0-9_]+", t.id):
        continue
    v = node.value
    if not isinstance(v, ast.Constant) or not isinstance(v.value, str):
        continue
    for ch in v.value:
        cp = ord(ch)
        if cp < 128 or cp in seen:      # spaces and ASCII; already emitted
            continue
        seen.add(cp)
        print("U+%04X\t%s" % (cp, ch))
PYEOF
}

wide_table() {        # -> "lo-hi lo-hi ..." from EAW_WIDE
  "$PY" - "$LIVE" <<'PYEOF'
import ast, sys
src = open(sys.argv[1], encoding="utf-8").read()
for node in ast.parse(src).body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 \
            and isinstance(node.targets[0], ast.Name) \
            and node.targets[0].id == "EAW_WIDE":
        print(" ".join("%d-%d" % (lo, hi)
                       for lo, hi in ast.literal_eval(node.value)))
        break
PYEOF
}

printf '\r\033[K' >&3; printf -- '--- glyphs this status line uses ---\n'
printf -- '(derived from the E_* constants in claude-code-usage-statusline.py,\n'
printf -- ' not a list kept here: a list kept here drifts the moment a glyph\n'
printf -- ' changes)\n'

# Read the layout's own glyph constants and measure exactly those. Nothing to
# keep in sync — a retired glyph drops out by itself, and a new one is
# measured the first time this runs. Three separate drifts in one evening came
# from maintaining this list by hand, the last of which left 🎯 sitting on
# every cache row without ever having been measured.
GLYPHS=$(glyph_constants) || GLYPHS=""
# Checked rather than assumed. The eval this replaced left the shell noisy
# when it failed; a heredoc that fails is silent, and an empty list here would
# print a clean report measuring nothing at all — which reads exactly like a
# clean result.
[ -n "$GLYPHS" ] || { echo "FATAL: no E_* constants read from $LIVE" >&2; exit 2; }

report U+0058 'X'                 # narrow reference
report U+1F9E9 '🧩'                # wide reference

# The wide reference is E_TOK, and the derivation would measure it a second
# time — glyph_constants dedups within itself, but knows nothing of what was
# reported before it ran.
while IFS=$'\t' read -r label ch; do
  [ "$label" = 'U+1F9E9' ] && continue
  report "$label" "$ch"
done <<EOF
$GLYPHS
EOF

printf -- '--- one sample per block, to catch whole ranges ---\n'
report U+2190 '←' sample;    report U+2300 '⌀' sample;   report U+2600 '☀' sample
report U+2700 '✀' sample;    report U+2B00 '⬀' sample;   report U+1F300 '🌀' sample
report U+1F600 '😀' sample;   report U+1F680 '🚀' sample;  report U+1F900 '🤀' sample
report U+1FA70 '🩰' sample;   report U+1FA90 '🪐' sample;  report U+1FAA3 '🪣' sample
report U+1FAE0 '🫠' sample
printf -- '--- sequences ---\n'
report skin '👍🏽' seq;  report ZWJ '👨‍💻' seq;  report flag '🇺🇸' seq
report keycap '1️⃣' seq

# ── the paste-ready block ───────────────────────────────────────────────────
#
# What the status line's own table claims for each codepoint, so measurements
# can be classified rather than eyeballed: measured 1 where the table says 2
# belongs in EAW_NARROW, measured 2 where it says 1 belongs in EAW_ICONS, and
# agreement belongs in neither.
#
# The table is read from the live program rather than copied, so the two
# cannot drift apart.
EAW_WIDE=$(wide_table) || EAW_WIDE=""
# An empty table would answer "narrow" for every codepoint, so every glyph
# measured at 2 would come out as an EAW_ICONS disagreement — a paste block
# that is entirely wrong and entirely plausible.
[ -n "$EAW_WIDE" ] || { echo "FATAL: no EAW_WIDE read from $LIVE" >&2; exit 2; }

table_says() {                    # $1 = codepoint -> 1 or 2
  local cp="$1" r lo hi
  for r in $EAW_WIDE; do
    lo=${r%%-*}; hi=${r#*-}
    [ "$cp" -lt "$lo" ] && break
    [ "$cp" -le "$hi" ] && { printf 2; return; }
  done
  printf 1
}

narrow=""; icons=""
for m in $MEASURED; do
  cp=${m%%:*}; got=${m#*:}
  # Sequences measure more than 2 and classify as neither; they are reported
  # in the human table above and read by a person.
  [ "$got" = 1 ] || [ "$got" = 2 ] || continue
  says=$(table_says "$cp")
  [ "$got" = 1 ] && [ "$says" = 2 ] && narrow="$narrow $cp"
  [ "$got" = 2 ] && [ "$says" = 1 ] && icons="$icons $cp"
done

printf -- '\n--- paste into widths_for() in claude-code-usage-statusline.py ---\n'
printf '# probed %s\n' "$(date '+%Y-%m-%d %H:%M')"
printf '#   TERM_PROGRAM=%s TERM=%s TMUX=%s%s\n' \
  "${TERM_PROGRAM:-unset}" "${TERM:-unset}" \
  "${TMUX:+set}${TMUX:-unset}" \
  "${TMUX:+ ($(tmux -V 2>/dev/null || echo 'tmux -V failed'))}"
printf '#   TERMINAL_EMULATOR=%s\n' "${TERMINAL_EMULATOR:-unset}"
printf 'EAW_NARROW="%s"\n' "${narrow# }"
printf 'EAW_ICONS="%s"\n'  "${icons# }"
printf '# TERM_CLUSTERS=1 if the sequences above measured 2 columns or fewer\n'
printf '#   (skin tone, ZWJ, flag, keycap); 0 if any measured more.\n'
