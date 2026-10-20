{
  description = "coding-agent-usage-line: Claude Code's usage status line, and the usage-band mod";

  inputs = {
    # Rolling, for a current Node: the mod's tests run TypeScript straight
    # through `node --test`, and its TypeScript 7 wants a recent runtime.
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts = {
      url = "github:hercules-ci/flake-parts";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };
    systems.url = "github:nix-systems/default";
    # The dev-shell skills wiring (flakeModules.devshellSkills), which
    # bundles numtide/devshell.  The skill sources are not inputs here: they
    # live only in skills-devshell/'s lock, which the dev shell runs on
    # entry, so this flake stays a leaf with no skill inputs.
    agent-skill-flake = {
      url = "github:nhooey/agent-skill-flake";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      nixpkgs,
      flake-parts,
      systems,
      ...
    }@inputs:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = import systems;
      imports = [
        # Bundles numtide/devshell, the skills startup that installs
        # skills-devshell/'s skills into .claude/skills, and the check, fmt,
        # update-flake, reap-skills and update-skills-devshell commands.
        inputs.agent-skill-flake.flakeModules.devshellSkills
        inputs.treefmt-nix.flakeModule
      ];

      agent-skill-flake.devshellSkills = {
        name = "coding-agent-usage-line";
        motd = ''
          {bold}{14}📊 Entering the coding-agent-usage-line dev shell{reset}
          Run {bold}menu{reset} to list available commands.
        '';
      };

      perSystem =
        { pkgs, ... }:
        let
          # The one Node: the mod's node_modules are built with it, and the
          # dev shell runs it.
          nodejs = pkgs.nodejs_26;

          # mod/'s npm dependencies (TypeScript, Node's types), each fetched
          # by the integrity hash its package-lock.json records: no
          # `npm ci`, and no hash to keep beside the lock.  Built from the
          # two files alone, so an edit elsewhere in mod/ rebuilds nothing.
          modNodeModules = pkgs.importNpmLock.buildNodeModules {
            package = builtins.fromJSON (builtins.readFile ./mod/package.json);
            packageLock = builtins.fromJSON (builtins.readFile ./mod/package-lock.json);
            inherit nodejs;
          };
        in
        {
          # Repo-specific packages and commands, merged onto the module's.
          devshells.default = {
            packages = [
              nodejs
              pkgs.git
              pkgs.python3
            ];
            env = [
              {
                name = "MOD_NODE_MODULES";
                value = "${modNodeModules}/node_modules";
              }
            ];
            devshell.startup.link-node-modules.text = builtins.readFile ./nix/link-node-modules.sh;
            commands = [
              # dev
              {
                category = "dev";
                name = "diff-grid-fixtures";
                help = "say how tests/fixtures/grid changed since a commit (HEAD)";
                command = ''python3 "$PRJ_ROOT/tools/diff-grid-fixtures.py" "$@"'';
              }
              {
                category = "dev";
                name = "draw-panel";
                help = "draw the agent panel for a payload at a width";
                command = ''python3 "$PRJ_ROOT/tools/draw-panel.py" "$@"'';
              }
              {
                category = "dev";
                name = "regen-spec";
                help = "regenerate spec.py and spec.ts from spec/layout.jsonc";
                command = ''python3 "$PRJ_ROOT/tools/gen-spec.py" "$@"'';
              }

              # test
              {
                category = "test";
                name = "check-folds";
                help = "break the transcript folds over ~/.claude/projects in both ports; [--largest N] [--seed S] [FILE...]";
                command = ''python3 "$PRJ_ROOT/tests/fold_real.py" "$@" && node "$PRJ_ROOT/mod/tools/check-fold.ts" "$@"'';
              }
              {
                category = "test";
                name = "tests";
                help = "run every suite, or the ones named; --repeat N to catch a flake (tests/all.sh)";
                command = ''bash "$PRJ_ROOT/tests/all.sh" "$@"'';
              }
              {
                category = "test";
                name = "time-panel";
                help = "time the agent panel's read of the session with the most agents, cold and off its saved folds; [--runs N] [TRANSCRIPT]";
                command = ''python3 "$PRJ_ROOT/tools/time-panel.py" "$@"'';
              }
              {
                category = "test";
                name = "time-window-costs";
                help = "time the window-cost scan over ~/.claude/projects, cold and cached, in both ports; [--runs N]";
                command = ''python3 "$PRJ_ROOT/tools/time-window-costs.py" "$@" && node "$PRJ_ROOT/mod/tools/time-window-costs.ts" "$@"'';
              }
              {
                category = "test";
                name = "typecheck";
                help = "type-check the TypeScript port and the mod";
                command = ''cd "$PRJ_ROOT/mod" && npm run -s typecheck'';
              }

              # update
              {
                category = "update";
                name = "update-npm-lock";
                help = "re-resolve mod/package-lock.json from mod/package.json";
                command = ''cd "$PRJ_ROOT/mod" && npm install --package-lock-only --ignore-scripts "$@"'';
              }
            ];
          };

          treefmt = {
            projectRootFile = "flake.nix";
            programs.nixfmt.enable = true;
          };
        };
    };
}
