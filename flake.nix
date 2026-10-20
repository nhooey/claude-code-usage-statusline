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
    devshell = {
      url = "github:numtide/devshell";
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
        inputs.devshell.flakeModule
        inputs.treefmt-nix.flakeModule
      ];

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
          devshells.default = {
            name = "coding-agent-usage-line";
            motd = ''
              {bold}{14}📊 Entering the coding-agent-usage-line dev shell{reset}
              Run {bold}menu{reset} to list available commands.
            '';
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
                name = "regen-spec";
                help = "regenerate spec.py and spec.ts from spec/layout.jsonc";
                command = ''python3 "$PRJ_ROOT/tools/gen-spec.py" "$@"'';
              }

              # test
              {
                category = "test";
                name = "tests";
                help = "run every suite, or the ones named (tests/all.sh)";
                command = ''bash "$PRJ_ROOT/tests/all.sh" "$@"'';
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
                name = "update-flake";
                help = "update the flake's inputs (flake.lock)";
                command = ''nix flake update --flake "$PRJ_ROOT" "$@"'';
              }
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
