{
  description = "qutebrowser - a keyboard-driven, vim-like browser based on Python and Qt";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      # Runtime Python dependencies, shared by the package and the dev shell.
      pythonDeps =
        ps: with ps; [
          jinja2
          pyyaml
          pyqt6
          pyqt6-webengine
          # Optional
          pygments
          adblock
        ];

      # What the test suite and the linters need on top of pythonDeps.
      devDeps =
        ps: with ps; [
          pytest
          pytest-qt
          pytest-mock
          pytest-bdd
          pytest-benchmark
          pytest-instafail
          pytest-rerunfailures
          pytest-xdist
          pytest-xvfb
          hypothesis
          beautifulsoup4
          cheroot
          flask
          pillow
          tldextract
          flake8
          vulture
          pylint
        ];

      devPython = pkgs: pkgs.python3.withPackages (ps: pythonDeps ps ++ devDeps ps);

      # Qt from nixpkgs only finds its plugins through this variable.
      qtPluginPath =
        pkgs:
        pkgs.lib.makeSearchPath pkgs.qt6.qtbase.qtPluginPrefix [
          pkgs.qt6.qtbase
          pkgs.qt6.qtwayland
          pkgs.qt6.qtsvg
        ];

      # A check which runs a command in a copy of the source tree.
      mkCheck =
        pkgs: name: command:
        pkgs.stdenvNoCC.mkDerivation {
          name = "qutebrowser-${name}";
          src = self;
          nativeBuildInputs = [
            (devPython pkgs)
            pkgs.dbus
            pkgs.git
          ];
          dontConfigure = true;
          QTWEBENGINE_RESOURCES_PATH = "${pkgs.qt6.qtwebengine}/resources";
          QT_PLUGIN_PATH = qtPluginPath pkgs;
          buildPhase = ''
            runHook preBuild
            export HOME=$TMPDIR/home XDG_RUNTIME_DIR=$TMPDIR/runtime
            mkdir -p "$HOME" "$XDG_RUNTIME_DIR"
            chmod 700 "$XDG_RUNTIME_DIR"
            ${command}
            runHook postBuild
          '';
          installPhase = "touch $out";
        };

      version =
        pkgs:
        let
          init = builtins.readFile ./qutebrowser/__init__.py;
          match = builtins.match ".*__version__ = \"([^\"]+)\".*" init;
        in
        "${builtins.head match}+${self.shortRev or self.dirtyShortRev or "dirty"}";
    in
    {
      packages = forAllSystems (pkgs: {
        default = self.packages.${pkgs.stdenv.hostPlatform.system}.qutebrowser;

        qutebrowser = pkgs.python3.pkgs.buildPythonApplication {
          pname = "qutebrowser";
          version = version pkgs;
          pyproject = true;

          src = self;

          build-system = [ pkgs.python3.pkgs.setuptools ];
          dependencies = pythonDeps pkgs.python3.pkgs;

          nativeBuildInputs = [
            pkgs.qt6.wrapQtAppsHook
            pkgs.asciidoc
          ];

          buildInputs = [
            pkgs.qt6.qtbase
            pkgs.qt6.qtwayland
            pkgs.qt6.qtsvg
          ];

          postPatch = ''
            # Let qutebrowser find the userscripts installed below.
            substituteInPlace qutebrowser/utils/standarddir.py \
              --replace-fail "'/usr'" "'$out'"
          '';

          # In-app documentation for :help
          preBuild = ''
            python3 scripts/asciidoc2html.py
          '';

          postInstall = ''
            install -Dm644 misc/org.qutebrowser.qutebrowser.desktop \
              -t "$out/share/applications"
            install -Dm644 misc/org.qutebrowser.qutebrowser.appdata.xml \
              -t "$out/share/metainfo"
            for i in 16 24 32 48 64 128 256 512; do
              install -Dm644 "qutebrowser/icons/qutebrowser-''${i}x$i.png" \
                "$out/share/icons/hicolor/''${i}x$i/apps/qutebrowser.png"
            done
            install -Dm644 qutebrowser/icons/qutebrowser.svg \
              "$out/share/icons/hicolor/scalable/apps/qutebrowser.svg"

            rm -rf misc/userscripts/__pycache__
            install -Dm755 -t "$out/share/qutebrowser/userscripts" misc/userscripts/*
          '';


          # Wrap only once, via the Python wrapper.
          dontWrapQtApps = true;
          preFixup = ''
            makeWrapperArgs+=(
              "''${qtWrapperArgs[@]}"
              # qutebrowser can't locate these inside the Nix store by itself.
              --set-default QTWEBENGINE_RESOURCES_PATH "${pkgs.qt6.qtwebengine}/resources"
            )
          '';

          # The tests are run by the "tests" check below instead.
          doCheck = false;
          pythonImportsCheck = [ "qutebrowser" ];

          meta = {
            description = "Keyboard-focused browser with a minimal GUI";
            homepage = "https://www.qutebrowser.org/";
            license = pkgs.lib.licenses.gpl3Plus;
            mainProgram = "qutebrowser";
            platforms = systems;
          };
        };
      });

      apps = forAllSystems (pkgs: {
        default = {
          type = "app";
          program = pkgs.lib.getExe self.packages.${pkgs.stdenv.hostPlatform.system}.qutebrowser;
        };
      });

      # `nix flake check` runs the unit tests and the linters.
      checks = forAllSystems (pkgs: {
        # Not using pytest-xdist, as some tests depend on running in order.
        tests = mkCheck pkgs "tests" ''
          export QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software
          dbus-run-session --config-file=${pkgs.dbus}/share/dbus-1/session.conf -- \
            python3 -m pytest -p no:cacheprovider tests/unit
        '';
        flake8 = mkCheck pkgs "flake8" "python3 -m flake8 qutebrowser tests scripts";
        pylint = mkCheck pkgs "pylint" ''
          export PYTHONPATH=$PWD/scripts/dev/pylint_checkers
          python3 -m pylint scripts qutebrowser --reports=no
          python3 scripts/dev/run_pylint_on_tests.py "$PWD" --reports=no
        '';
        vulture = mkCheck pkgs "vulture" ''
          QT_QPA_PLATFORM=offscreen PYTHONPATH=$PWD python3 scripts/dev/run_vulture.py
        '';
        misc = mkCheck pkgs "misc" ''
          # misc_checks.py lists the files to check via git.
          git init --quiet && git add --all
          for check in vcs spelling pyqt-imports userscript-descriptions \
              userscript-shebangs vim-modelines; do
            python3 scripts/dev/misc_checks.py "$check"
          done
        '';
      });

      # Run straight from the working tree: `nix develop -c python3 -m qutebrowser`
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (devPython pkgs)
            pkgs.asciidoc
            pkgs.dbus
          ];

          QTWEBENGINE_RESOURCES_PATH = "${pkgs.qt6.qtwebengine}/resources";
          QT_PLUGIN_PATH = qtPluginPath pkgs;
        };
      });
    };
}
