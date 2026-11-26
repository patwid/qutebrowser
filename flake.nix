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

          # The test suite needs a full graphical session.
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

      # Run straight from the working tree: `nix develop -c python3 -m qutebrowser`
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (
              ps:
              pythonDeps ps
              ++ (with ps; [
                pytest
                pytest-qt
                pytest-mock
                pytest-bdd
                hypothesis
              ])
            ))
            pkgs.asciidoc
          ];

          QTWEBENGINE_RESOURCES_PATH = "${pkgs.qt6.qtwebengine}/resources";

          # Qt from nixpkgs only finds its plugins through this variable.
          QT_PLUGIN_PATH = pkgs.lib.makeSearchPath pkgs.qt6.qtbase.qtPluginPrefix [
            pkgs.qt6.qtbase
            pkgs.qt6.qtwayland
            pkgs.qt6.qtsvg
          ];
        };
      });
    };
}
