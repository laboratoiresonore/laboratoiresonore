"""Tk-based card-grid GUI for the universal installer.

Polished surface that lists visible apps as hero-image cards with
per-card install buttons. Prefers customtkinter for a modern flat
look; falls back to plain tkinter.ttk if customtkinter isn't
installed. PIL is used to scale hero images when present, with a
canvas-rendered fallback so the GUI stays usable on a fresh Python.

Both customtkinter and PIL are OPTIONAL -- the module imports cleanly
without them, the helpers stay testable headlessly, and ``launch()``
returns False on any environment failure so the caller can drop back
to CLI mode.
"""

from __future__ import annotations

import colorsys
import hashlib
import threading
from pathlib import Path
from typing import Callable, Optional

from . import __version__, manifest


# ---------------------------------------------------------------------------
# Optional imports. Each block sets a ``_HAS_*`` flag and binds the relevant
# symbol to a module-level name (or None) so the rest of the file can branch
# on availability without re-importing.
# ---------------------------------------------------------------------------

try:
    import customtkinter as _ctk  # type: ignore
    _HAS_CTK = True
except Exception:  # noqa: BLE001 -- any import-time failure = fall back
    _ctk = None
    _HAS_CTK = False

try:
    from PIL import Image as _PILImage, ImageTk as _PILImageTk  # type: ignore
    _HAS_PIL = True
except Exception:  # noqa: BLE001
    _PILImage = None
    _PILImageTk = None
    _HAS_PIL = False


# Card visual constants -- duplicated here rather than scattered through the
# layout code so the visual contract is auditable in one place.
HERO_W = 360
HERO_H = 180
SUMMARY_MAX_LINES = 3
SUMMARY_LINE_WIDTH = 52   # rough char count per line at the card width
GRID_COLUMNS = 2

HEADER_BG = "#13131a"
HEADER_FG = "#f4f4f8"
CARD_BG = "#1e1e26"
CARD_FG = "#e8e8ee"
SUBTLE_FG = "#9a9aa6"


# ---------------------------------------------------------------------------
# Pure helpers -- no Tk imports needed, exercised in unit tests.
# ---------------------------------------------------------------------------

def accent_color_for(app: dict) -> str:
    """Pick a stable brand accent for an app entry.

    Honour the manifest's optional ``accent_color`` field if it's a
    well-formed ``#RRGGBB`` string. Otherwise hash the app id into HSL
    space and convert back to hex -- same id always lands on the same
    colour, but distinct ids land far enough apart to be visually
    distinguishable on the card grid.
    """
    explicit = app.get("accent_color")
    if isinstance(explicit, str) and _is_valid_hex_color(explicit):
        return explicit.lower()

    app_id = str(app.get("id", ""))
    digest = hashlib.sha256(app_id.encode("utf-8")).digest()
    # Map the first 3 bytes to (hue, saturation, lightness) bands tuned
    # for readable button backgrounds: hue is full range, saturation
    # stays in the 55–85% band so colours don't go grey or neon, and
    # lightness sits in 40–55% so white text on top reads cleanly.
    hue = digest[0] / 255.0
    saturation = 0.55 + (digest[1] / 255.0) * 0.30
    lightness = 0.40 + (digest[2] / 255.0) * 0.15
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
    return "#{:02x}{:02x}{:02x}".format(
        int(r * 255), int(g * 255), int(b * 255)
    )


def _is_valid_hex_color(value: str) -> bool:
    if not value.startswith("#") or len(value) != 7:
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


def truncate_summary(text: str, max_lines: int = SUMMARY_MAX_LINES,
                     line_width: int = SUMMARY_LINE_WIDTH) -> str:
    """Word-wrap ``text`` to ``line_width`` chars; if the result is more
    than ``max_lines`` lines, keep the first ``max_lines`` and end the
    last one with ``...`` (replacing trailing chars to fit if needed).

    A summary that already fits returns unchanged -- the caller can
    cheaply check identity to decide whether to render a tooltip with
    the full text.
    """
    if not text:
        return ""

    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else current + " " + word
        if len(candidate) <= line_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        # A single word longer than the line width gets hard-broken.
        while len(word) > line_width:
            lines.append(word[:line_width])
            word = word[line_width:]
        current = word
    if current:
        lines.append(current)

    if len(lines) <= max_lines:
        return "\n".join(lines)

    kept = lines[:max_lines]
    last = kept[-1]
    if len(last) + 3 > line_width:
        last = last[: line_width - 3].rstrip()
    kept[-1] = last + "..."
    return "\n".join(kept)


def hero_path_for(app_id: str, assets_root: Optional[Path] = None) -> Path:
    """Where the per-app hero PNG is expected to live."""
    if assets_root is None:
        assets_root = Path(__file__).resolve().parent / "assets" / "heroes"
    return assets_root / f"{app_id}.png"


def load_hero(app: dict, *, parent=None,
              assets_root: Optional[Path] = None) -> tuple:
    """Resolve a hero asset for ``app``.

    Returns ``(image_or_factory, source)`` where:
      - ``source == "file"`` -- a real PNG was loaded; the first element
        is a PIL Image (caller wraps with ImageTk) sized to HERO_W×HERO_H.
      - ``source == "fallback"`` -- no file was found OR PIL isn't
        available; the first element is a dict spec the renderer turns
        into a flat-coloured Canvas with the app's first letter.

    The split lets the function stay pure and testable -- it never
    touches Tk itself, which is what makes it safe to import in
    headless test environments.
    """
    app_id = str(app.get("id", "?"))
    path = hero_path_for(app_id, assets_root=assets_root)
    if _HAS_PIL and path.is_file():
        try:
            img = _PILImage.open(path).convert("RGBA")
            img = img.resize((HERO_W, HERO_H), _PILImage.LANCZOS)
            return img, "file"
        except Exception:  # noqa: BLE001 -- any PIL failure -> fallback
            pass

    name = str(app.get("name") or app_id or "?")
    letter = name.strip()[:1].upper() or "?"
    spec = {
        "letter": letter,
        "color": accent_color_for(app),
        "width": HERO_W,
        "height": HERO_H,
    }
    return spec, "fallback"


def footer_count_text(apps: list[dict]) -> str:
    """Footer line: ``(n apps)``. Pure helper so it can be unit
    tested without a Tk root."""
    return f"({len(apps)} apps)"


# ---------------------------------------------------------------------------
# Lazy import of the per-app installer actions. The actions module may
# not exist yet (it's a v0.2 deliverable). Importing lazily means a
# missing module only matters when the user actually clicks Install,
# at which point we surface a clean error in the card's status line
# instead of crashing the whole GUI.
# ---------------------------------------------------------------------------

def _default_run_install(app: dict) -> None:
    """Default installer entry point. Imports ``actions`` lazily so the
    GUI module loads even when the actions package hasn't shipped yet."""
    try:
        from . import actions  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"installer actions module unavailable: {exc}")
    actions.run_install(app)


# ---------------------------------------------------------------------------
# GUI surface. Everything below this line touches Tk and is only
# exercised manually -- the test suite mocks the Tk root to verify
# error handling without ever opening a window.
# ---------------------------------------------------------------------------

class _CardController:
    """Per-card state container -- owns the row's status label + button
    and serialises updates back onto the Tk main thread via ``after``."""

    def __init__(self, root, app: dict, button, status_label,
                 run_install_fn: Callable[[dict], None]):
        self._root = root
        self._app = app
        self._button = button
        self._status = status_label
        self._run_install = run_install_fn
        self._busy = False

    def install(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self._button.configure(state="disabled")
        except Exception:  # noqa: BLE001
            pass
        self._set_status("Installing…", SUBTLE_FG)

        def worker() -> None:
            try:
                self._run_install(self._app)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc) or exc.__class__.__name__
                self._root.after(0, self._on_done, False, msg)
                return
            self._root.after(0, self._on_done, True, None)

        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, ok: bool, msg: Optional[str]) -> None:
        self._busy = False
        if ok:
            self._set_status("Installed ✓", "#7ddc7d")
        else:
            text = f"Failed: {msg}" if msg else "Failed"
            self._set_status(text, "#e07b7b")
        try:
            self._button.configure(state="normal")
        except Exception:  # noqa: BLE001
            pass

    def _set_status(self, text: str, color: str) -> None:
        try:
            self._status.configure(text=text, text_color=color)
        except Exception:  # noqa: BLE001 -- ttk uses ``foreground``
            try:
                self._status.configure(text=text, foreground=color)
            except Exception:  # noqa: BLE001
                pass


def _make_root():
    """Build a top-level window using customtkinter when available,
    falling back to plain Tk. Raises whatever the underlying
    constructor raises so ``launch()`` can convert it into a False
    return value."""
    if _HAS_CTK:
        _ctk.set_appearance_mode("dark")
        _ctk.set_default_color_theme("blue")
        return _ctk.CTk()
    import tkinter as tk
    return tk.Tk()


def _hero_widget(parent, image_or_spec, source: str):
    """Render whatever ``load_hero`` returned into a Tk widget. Kept
    out of the controller so the path can be swapped for a mock in
    visual smoke tests later."""
    import tkinter as tk

    if source == "file" and _HAS_PIL:
        photo = _PILImageTk.PhotoImage(image_or_spec)
        label = tk.Label(parent, image=photo, bd=0, highlightthickness=0)
        label.image = photo  # keep a reference so GC doesn't reap it
        return label

    spec = image_or_spec
    canvas = tk.Canvas(
        parent, width=spec["width"], height=spec["height"],
        bg=spec["color"], highlightthickness=0, bd=0,
    )
    canvas.create_text(
        spec["width"] // 2, spec["height"] // 2,
        text=spec["letter"], fill="white",
        font=("Helvetica", 64, "bold"),
    )
    return canvas


def _build_card(parent, app: dict, run_install_fn: Callable[[dict], None],
                root) -> "_CardController":
    """Compose one app card into ``parent`` and wire up its controller."""
    accent = accent_color_for(app)

    if _HAS_CTK:
        frame = _ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=12)
    else:
        import tkinter as tk
        frame = tk.Frame(parent, bg=CARD_BG, bd=0, highlightthickness=0)
    frame.pack_propagate(False)
    frame.configure(width=HERO_W + 32, height=HERO_H + 180)

    image_or_spec, source = load_hero(app)
    hero = _hero_widget(frame, image_or_spec, source)
    hero.pack(padx=12, pady=(12, 8))

    name_text = str(app.get("name", app.get("id", "?")))
    summary_text = truncate_summary(str(app.get("summary", "")))

    if _HAS_CTK:
        name_label = _ctk.CTkLabel(
            frame, text=name_text,
            font=("Helvetica", 18, "bold"),
            text_color=CARD_FG, anchor="w",
        )
        summary_label = _ctk.CTkLabel(
            frame, text=summary_text,
            font=("Helvetica", 12),
            text_color=SUBTLE_FG, justify="left", anchor="w",
        )
        button = _ctk.CTkButton(
            frame, text="Install",
            fg_color=accent, hover_color=accent,
            text_color="white", corner_radius=8,
        )
        status_label = _ctk.CTkLabel(
            frame, text="", font=("Helvetica", 11),
            text_color=SUBTLE_FG, anchor="w",
        )
    else:
        import tkinter as tk
        name_label = tk.Label(
            frame, text=name_text, fg=CARD_FG, bg=CARD_BG,
            font=("Helvetica", 14, "bold"), anchor="w",
        )
        summary_label = tk.Label(
            frame, text=summary_text, fg=SUBTLE_FG, bg=CARD_BG,
            font=("Helvetica", 10), justify="left", anchor="w",
        )
        button = tk.Button(
            frame, text="Install", bg=accent, fg="white",
            activebackground=accent, activeforeground="white",
            relief="flat", padx=14, pady=4, bd=0,
        )
        status_label = tk.Label(
            frame, text="", fg=SUBTLE_FG, bg=CARD_BG,
            font=("Helvetica", 9), anchor="w",
        )

    name_label.pack(fill="x", padx=14, pady=(0, 4))
    summary_label.pack(fill="x", padx=14, pady=(0, 8))
    button.pack(side="right", padx=14, pady=(0, 4))
    status_label.pack(side="left", fill="x", expand=True, padx=14, pady=(0, 4))

    controller = _CardController(
        root, app, button, status_label, run_install_fn,
    )
    button.configure(command=controller.install)
    return controller


def launch(visible_apps_fn: Optional[Callable[[], list[dict]]] = None,
           run_install_fn: Optional[Callable[[dict], None]] = None) -> bool:
    """Open the installer GUI. Returns True on a clean shutdown,
    False if the GUI couldn't start (no display, missing tkinter,
    headless CI). The caller is expected to fall back to CLI mode on
    False -- this function never raises out to the user.

    Both injected functions are optional; defaults read from the
    real manifest and the (lazy) actions module.
    """
    if visible_apps_fn is None:
        visible_apps_fn = manifest.visible_apps
    if run_install_fn is None:
        run_install_fn = _default_run_install

    try:
        root = _make_root()
    except Exception:  # noqa: BLE001 -- Tk import failure, no DISPLAY, etc.
        return False

    try:
        root.title("LaboratoireSonore -- Universal Installer")
        try:
            root.geometry("840x720")
        except Exception:  # noqa: BLE001
            pass

        _build_header(root)

        body = _make_scrollable_body(root)

        try:
            apps = list(visible_apps_fn())
        except Exception:  # noqa: BLE001
            apps = []

        for index, app in enumerate(apps):
            row, col = divmod(index, GRID_COLUMNS)
            cell = _make_cell(body, row, col)
            _build_card(cell, app, run_install_fn, root)

        _build_footer(root, apps)

        root.mainloop()
        return True
    except Exception:  # noqa: BLE001 -- never bubble GUI errors to the user
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass
        return False


def _build_header(root) -> None:
    if _HAS_CTK:
        bar = _ctk.CTkFrame(root, fg_color=HEADER_BG, corner_radius=0,
                             height=92)
        title = _ctk.CTkLabel(
            bar, text="LaboratoireSonore",
            font=("Helvetica", 26, "bold"), text_color=HEADER_FG,
        )
        subtitle = _ctk.CTkLabel(
            bar, text=f"Universal Installer · v{__version__}",
            font=("Helvetica", 12), text_color=SUBTLE_FG,
        )
    else:
        import tkinter as tk
        bar = tk.Frame(root, bg=HEADER_BG, height=92)
        title = tk.Label(
            bar, text="LaboratoireSonore",
            font=("Helvetica", 22, "bold"),
            fg=HEADER_FG, bg=HEADER_BG,
        )
        subtitle = tk.Label(
            bar, text=f"Universal Installer · v{__version__}",
            font=("Helvetica", 10),
            fg=SUBTLE_FG, bg=HEADER_BG,
        )
    bar.pack(fill="x", side="top")
    bar.pack_propagate(False)
    title.pack(anchor="w", padx=22, pady=(18, 0))
    subtitle.pack(anchor="w", padx=22, pady=(0, 12))


def _make_scrollable_body(root):
    if _HAS_CTK:
        body = _ctk.CTkScrollableFrame(root, fg_color="#0f0f14")
        body.pack(fill="both", expand=True, padx=18, pady=12)
        return body
    import tkinter as tk
    body = tk.Frame(root, bg="#0f0f14")
    body.pack(fill="both", expand=True, padx=18, pady=12)
    return body


def _make_cell(body, row: int, col: int):
    if _HAS_CTK:
        cell = _ctk.CTkFrame(body, fg_color="transparent")
    else:
        import tkinter as tk
        cell = tk.Frame(body, bg="#0f0f14")
    cell.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
    return cell


def _build_footer(root, apps: list[dict]) -> None:
    text = f"Status: ready  {footer_count_text(apps)}"
    if _HAS_CTK:
        footer = _ctk.CTkLabel(
            root, text=text, font=("Helvetica", 11),
            text_color=SUBTLE_FG, anchor="w",
        )
    else:
        import tkinter as tk
        footer = tk.Label(
            root, text=text, fg=SUBTLE_FG, bg=HEADER_BG,
            font=("Helvetica", 9), anchor="w",
        )
    footer.pack(fill="x", side="bottom", padx=18, pady=(4, 8))
