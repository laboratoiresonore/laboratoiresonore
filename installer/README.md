# LaboratoireSonore Universal Installer

One installer for the LaboratoireSonore ecosystem. Pick an app, pick
your platform, click Install.

```bash
python install.py             # GUI
python install.py --list      # CLI: list apps
python install.py --install <app_id>
```

## Install (no Python required)

Native bundled installers are published on every release for all three
desktop platforms. Pick the asset that matches your OS, download, run.

| Platform | Asset                                  | How to run                              |
| -------- | -------------------------------------- | --------------------------------------- |
| Windows  | `LaboratoireSonore-Installer.exe`      | Double-click                            |
| macOS    | `LaboratoireSonore-Installer.app.zip`  | Unzip, drag the `.app` into Applications, double-click |
| Linux    | `LaboratoireSonore-Installer`          | `chmod +x` and `./LaboratoireSonore-Installer` |

Technical users can skip the bundle and run `python install.py`
directly against the bootstrap shim instead.

## Layout

```
installer/
├── bootstrap/install.py     Thin shim copied to every repo's root
├── src/
│   ├── lab_installer.py     Entry point
│   ├── manifest.py          Manifest loader
│   ├── crypto.py            Helpers
│   ├── actions/             Per-kind install dispatch
│   ├── gui.py               Tk card grid
│   └── assets/heroes/       App hero images (PNG)
├── lab_installer.spec       PyInstaller spec
└── tests/                   unittest suite
```

## Tests

```bash
python -m unittest discover installer/tests
```

## License

MIT.
