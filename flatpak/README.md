# Flatpak bundle

This directory contains the Flatpak manifest, desktop metadata, icon, and the one-time x86_64 bundle at `dist/Screenshot-Markierer.flatpak`.

Build from the project folder with:

```sh
flatpak-builder --jobs=1 --disable-rofiles-fuse --default-branch=stable --force-clean --state-dir=/tmp/screenshot-marker-state --repo=/tmp/screenshot-marker-repo /tmp/screenshot-marker-build flatpak/org.kelra.ScreenshotMarker.yml
flatpak build-bundle /tmp/screenshot-marker-repo flatpak/dist/Screenshot-Markierer.flatpak org.kelra.ScreenshotMarker stable --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo
```

Install for the current user with:

```sh
flatpak install --user --bundle flatpak/dist/Screenshot-Markierer.flatpak
```

The bundle contains the application. Flatpak downloads the GNOME 50 runtime from the configured remote during installation. No Flathub submission or update feed is part of this release.

The application source is licensed under 0BSD. The bundled Papirus icon is a third-party GPL-3.0 asset; see the project root's `THIRD-PARTY-NOTICES.md` and <https://github.com/PapirusDevelopmentTeam/papirus-icon-theme>.
