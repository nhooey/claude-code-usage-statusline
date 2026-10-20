# Link mod/node_modules to the flake's build of mod's npm dependencies
# ($MOD_NODE_MODULES), so `npm run typecheck` and `tsc` find TypeScript
# with no `npm ci`.  Run by the dev shell on entry.
#
# Only a link into the Nix store is replaced, or no node_modules at all: a
# node_modules a developer installed by hand is left alone, with a note.
link="$PRJ_ROOT/mod/node_modules"
if [ -L "$link" ]; then
  case "$(readlink "$link")" in
    "$NIX_STORE"/* | /nix/store/*) ln -sfn "$MOD_NODE_MODULES" "$link" ;;
  esac
elif [ ! -e "$link" ]; then
  ln -s "$MOD_NODE_MODULES" "$link"
else
  echo "mod/node_modules is a local install; remove it to use the flake's" >&2
fi
