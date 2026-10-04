# Screenshot Marker

Screenshot Marker is a small Linux desktop editor for annotating screenshots and other images. Open an image or paste one from the clipboard, add clear visual notes, then copy or export the finished image at its original resolution.

It is an image annotation tool; it does not capture the screen itself.

## What you can do

- Draw arrows, free-form ellipses, and perfect circles.
- Add sequentially numbered markers.
- Move annotations, rotate arrows, and resize or reposition a crop.
- Undo and redo edits.
- Paste images from the clipboard and copy the annotated result back.
- Open PNG, JPEG, WEBP, BMP, and TIFF images.
- Save the edited image at full resolution.

The interface is currently in German. Closing the window discards unsaved changes.

## Run from source

Requirements: Python 3, Pillow, Tkinter, and GTK 3 with PyGObject for clipboard integration. `zenity` is recommended for the GTK file chooser; Tkinter file dialogs are used as a fallback when `zenity` is unavailable. On Debian or Ubuntu, the system packages are typically named `python3-tk`, `python3-pil`, `python3-gi`, `gir1.2-gtk-3.0`, and `zenity`. Package names may differ across distributions.

```sh
./start.sh
```

To open an image directly:

```sh
./start.sh /path/to/image.png
```

`requirements.txt` lists Pillow for installation in a Python environment. Some Linux distributions package GTK and PyGObject separately from pip.

## Flatpak bundle

A prebuilt single-file bundle is available in the [GitHub release](https://github.com/K3lr4/screenshot-markierer/releases). It includes the application; the GNOME 50 runtime is downloaded by Flatpak during installation.

```sh
flatpak install --user --bundle Screenshot-Markierer.flatpak
```

The runtime is obtained from the configured Flatpak remote. The published bundle was built for x86_64 Linux.

## Release policy

This project is published as a one-time release. No update channel or future updates are planned. The public source remains available so anyone can use, modify, fork, redistribute, or continue the project under the license below.

## License

The application source code and project documentation are released under the [0BSD license](LICENSE). It grants permission to use, copy, modify, and distribute that material for any purpose, with or without fee.

The included Papirus SVG icon is a third-party asset and remains under its original GPL-3.0 license. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). Dependencies and the GNOME runtime are governed by their respective licenses.
