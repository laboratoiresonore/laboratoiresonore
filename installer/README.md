# LaboratoireSonore Universal Installer

One installer for the LaboratoireSonore ecosystem. Pick an app, pick
your platform, click Install.

```bash
python install.py             # GUI
python install.py --list      # CLI: list apps
python install.py --install <app_id>
```

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
