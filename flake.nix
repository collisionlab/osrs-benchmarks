{
  description = "Benchmarks for the Shortest Path plugin's Java pathfinders";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      # Gradle and the benchmark JVM run on jdk17; the plugin compiles with a Java 11 toolchain.
      # Both are pinned here, so a JDK change is a commit to this repo and shows up in the
      # recorded harness version.
      runtimeJdk = pkgs.jdk17;
      toolchainJdk = pkgs.jdk11;

      osrs-benchmarks = pkgs.python3Packages.buildPythonApplication {
        pname = "osrs-benchmarks";
        version = "0";
        pyproject = true;
        src = ./.;
        build-system = [ pkgs.python3Packages.setuptools ];
        postPatch = ''
          substituteInPlace src/osrs_benchmarks/_version.py \
            --replace-fail 'VERSION = "dev"' 'VERSION = "${self.rev or "dirty"}"'
        '';
        makeWrapperArgs = [
          "--prefix" "PATH" ":" (pkgs.lib.makeBinPath [ pkgs.git pkgs.gradle runtimeJdk ])
          "--set" "JAVA_HOME" "${runtimeJdk.home}"
          "--set" "OSRS_BENCHMARKS_JDK11" "${toolchainJdk.home}"
        ];
        nativeCheckInputs = [ pkgs.python3Packages.pytestCheckHook ];
        meta.mainProgram = "osrs-benchmarks";
      };
    in
    {
      packages.${system}.default = osrs-benchmarks;

      checks.${system}.default = osrs-benchmarks;

      devShells.${system}.default = pkgs.mkShell {
        packages = [ pkgs.python3 pkgs.python3Packages.pytest pkgs.git pkgs.gradle runtimeJdk ];
        JAVA_HOME = runtimeJdk.home;
        OSRS_BENCHMARKS_JDK11 = toolchainJdk.home;
        shellHook = ''
          export PYTHONPATH=$PWD/src''${PYTHONPATH:+:$PYTHONPATH}
        '';
      };
    };
}
