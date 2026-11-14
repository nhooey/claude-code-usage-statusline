#!/usr/bin/env python3
"""Which entry points reach each module of coding_agent_usage_line/.

    python3 tools/python-module-reach.py           # a Markdown table
    python3 tools/python-module-reach.py --json    # the same, as JSON

Reads the imports of every module with `ast`, without running anything,
and follows them from each entry:

- codex: coding-agent-usage-line.py with --agent codex.  cli.py and
  sources.py import claude.py only inside the functions that serve Claude
  (--agent claude, the Claude Usage Tracker source, Claude Code's account
  id), so this is cli.py's closure without any import of claude.py made
  inside a function.
- claude: the same launcher with --agent claude, the agent panel among its
  modes: cli.py's closure with claude.py's added.
- fold: mod/scripts/agent_lines.py, the mod's worker for large folds.
- tests: each Python file under tests/ and tools/ that imports a module.

An import inside a function counts as reached wherever its module is
reached, apart from those imports of claude.py, so a module reached here
may go unused on some runs; one not reached is never loaded by that entry.
"""
import argparse
import ast
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = 'coding_agent_usage_line'
PKG_DIR = os.path.join(ROOT, PKG)


def module_names():
    return sorted(f[:-3] for f in os.listdir(PKG_DIR)
                  if f.endswith('.py') and f != '__init__.py')


def imports_of(path, inside_package):
    """The package's modules `path` imports, as (name, top-level?) pairs."""
    tree = ast.parse(open(path, encoding='utf-8').read(), path)
    top = set(id(n) for n in tree.body)
    out = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.ImportFrom):
            if node.level == 1 and inside_package:
                names = ([node.module] if node.module
                         else [a.name for a in node.names])
            elif node.module == PKG:
                names = [a.name for a in node.names]
            elif node.module and node.module.startswith(PKG + '.'):
                names = [node.module.split('.')[1]]
        elif isinstance(node, ast.Import):
            names = [a.name.split('.')[1] for a in node.names
                     if a.name.startswith(PKG + '.')]
        for n in names:
            out.append((n.split('.')[0], id(node) in top))
    return out


def closure(start, edges):
    seen, todo = set(), list(start)
    while todo:
        m = todo.pop()
        if m in seen or m not in edges:
            continue
        seen.add(m)
        todo.extend(edges[m])
    return seen


def reach():
    mods = module_names()
    edges, codex_edges = {}, {}
    for m in mods:
        pairs = imports_of(os.path.join(PKG_DIR, m + '.py'), True)
        edges[m] = sorted(set(n for n, _ in pairs if n in mods))
        codex_edges[m] = sorted(set(n for n, top in pairs if n in mods
                                    and (top or n != 'claude')))
    entries = {
        'codex': closure(['cli'], codex_edges),
        'claude': closure(['cli', 'claude'], edges),
    }
    fold = os.path.join(ROOT, 'mod', 'scripts', 'agent_lines.py')
    entries['fold'] = closure(
        [n for n, _ in imports_of(fold, False) if n in mods], edges)
    tests = {m: [] for m in mods}
    for d in ('tests', 'tools'):
        for dirpath, dirnames, files in os.walk(os.path.join(ROOT, d)):
            dirnames[:] = [x for x in dirnames if x != '__pycache__']
            for f in files:
                if not f.endswith('.py'):
                    continue
                p = os.path.join(dirpath, f)
                for n in closure([n for n, _ in imports_of(p, False)
                                  if n in mods], edges):
                    tests[n].append(os.path.relpath(p, ROOT))
    rows = []
    for m in mods:
        lines = sum(1 for _ in open(os.path.join(PKG_DIR, m + '.py'),
                                    encoding='utf-8'))
        rows.append({'module': m + '.py', 'lines': lines,
                     'codex': m in entries['codex'],
                     'claude': m in entries['claude'],
                     'fold': m in entries['fold'],
                     'tests': sorted(set(tests[m]))})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--json', action='store_true')
    rows = reach()
    if ap.parse_args().json:
        json.dump(rows, sys.stdout, indent=1)
        print()
        return 0
    yes = lambda b: '✅' if b else '—'
    print('| Module | Lines | Codex | Claude | Fold worker | Test files |')
    print('| --- | ---: | :---: | :---: | :---: | ---: |')
    for r in sorted(rows, key=lambda r: (r['codex'], r['fold'],
                                         -r['lines'])):
        print('| `{}` | {} | {} | {} | {} | {} |'.format(
            r['module'], r['lines'], yes(r['codex']), yes(r['claude']),
            yes(r['fold']), len(r['tests'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
