#!/usr/bin/env python3
"""
Token Composer — pick a portrait, drag to position, tint the frame, save to Assets/Combatants/.

Usage (standalone):
    python3 Tools/token_composer.py

Usage (called from run_dnd_py.py):
    python3 Tools/token_composer.py --color "#FFD700" --lock-color --assets-dir /path/to/Assets
"""
import argparse
import os
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox

import numpy as np
from PIL import Image, ImageTk
from scipy import ndimage

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")

PREVIEW_SIZE = 360
THUMB_SIZE = 80
THUMB_COLS = 4
OUTPUT_SIZE = 512
DM_COLOR = "#FFD700"

PRESETS = [
    ("Gold",   "#FFD700"),
    ("Silver", "#C0C0C0"),
    ("Red",    "#CC2200"),
    ("Blue",   "#2266CC"),
    ("Green",  "#228822"),
    ("Purple", "#882299"),
]


def _load_frame(path: str) -> tuple[Image.Image, np.ndarray]:
    """Return (frame_rgba, outer_mask).
    outer_mask is True for corner pixels that must stay transparent in the final token."""
    img = Image.open(path).convert("RGBA")
    arr = np.array(img)
    h, w = arr.shape[:2]
    transparent = (arr[:, :, 3] == 0).astype(np.uint8)
    labeled, _ = ndimage.label(transparent)
    corner_labels = (
        {int(labeled[0, 0]), int(labeled[0, w - 1]), int(labeled[h - 1, 0]), int(labeled[h - 1, w - 1])} - {0}
    )
    outer_mask = np.isin(labeled, list(corner_labels))
    return img, outer_mask


def _tint(frame_rgba: Image.Image, hex_color: str) -> Image.Image:
    rt = int(hex_color[1:3], 16)
    gt = int(hex_color[3:5], 16)
    bt = int(hex_color[5:7], 16)
    r, g, b, a = frame_rgba.split()
    r = r.point(lambda x: x * rt // 255)
    g = g.point(lambda x: x * gt // 255)
    b = b.point(lambda x: x * bt // 255)
    return Image.merge("RGBA", (r, g, b, a))


def _scale_mask(mask: np.ndarray, size: int) -> np.ndarray:
    img = Image.fromarray(mask.astype(np.uint8) * 255, "L")
    return np.array(img.resize((size, size), Image.NEAREST)) > 127


def _composite(
    portrait: Image.Image,
    tinted_frame: Image.Image,
    outer_mask: np.ndarray,
    port_x: float,
    port_y: float,
    port_scale: float,
    preview_size: int,
    out_size: int,
) -> Image.Image:
    """
    port_x, port_y  — portrait top-left in preview-pixel coordinates
    port_scale      — portrait.width * port_scale = portrait's displayed width in preview pixels
    """
    ratio = out_size / preview_size
    pw = max(1, int(portrait.width * port_scale * ratio))
    ph = max(1, int(portrait.height * port_scale * ratio))
    portrait_sized = portrait.resize((pw, ph), Image.LANCZOS)

    ox = int(port_x * ratio)
    oy = int(port_y * ratio)

    canvas = Image.new("RGBA", (out_size, out_size), (0, 0, 0, 0))
    canvas.paste(portrait_sized, (ox, oy))

    frame = tinted_frame.resize((out_size, out_size), Image.LANCZOS)
    canvas.paste(frame, (0, 0), mask=frame)

    outer = _scale_mask(outer_mask, out_size)
    arr = np.array(canvas)
    arr[outer, 3] = 0
    return Image.fromarray(arr, "RGBA")


class TokenComposer(tk.Tk):
    def __init__(self, preset_color: str, lock_color: bool, assets_dir: str, output_dir: str):
        super().__init__()
        self.title("Token Composer")
        self.resizable(False, False)

        self._output_dir = output_dir
        self._portraits_dir = os.path.join(assets_dir, "Portraits")
        self._frame_base, self._outer_mask = _load_frame(
            os.path.join(assets_dir, "Frames", "Grey_frame.png")
        )

        self._color = preset_color
        self._lock_color = lock_color
        self._portrait: Image.Image | None = None
        self._portrait_path: str | None = None
        self._thumbs: dict[str, ImageTk.PhotoImage] = {}

        # Portrait position/scale in preview-pixel space
        self._port_x: float = 0.0
        self._port_y: float = 0.0
        self._port_scale: float = 1.0  # portrait.width * scale = preview pixels

        self._drag_start: tuple[int, int] | None = None
        self._drag_origin: tuple[float, float] | None = None

        self._build_ui()
        self._load_portrait_grid()
        self._refresh_preview()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Portrait browser
        port_panel = tk.LabelFrame(self, text="Portrait", padx=6, pady=6)
        port_panel.pack(padx=12, pady=(12, 6), fill="x")

        grid_w = THUMB_COLS * (THUMB_SIZE + 6) + 20
        scroll_canvas = tk.Canvas(port_panel, height=THUMB_SIZE * 2 + 20, width=grid_w)
        sb = tk.Scrollbar(port_panel, orient="vertical", command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        scroll_canvas.pack(side="left")
        self._grid_inner = tk.Frame(scroll_canvas)
        scroll_canvas.create_window((0, 0), window=self._grid_inner, anchor="nw")
        self._grid_inner.bind(
            "<Configure>",
            lambda e: scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all")),
        )
        tk.Button(port_panel, text="Browse…", command=self._browse_portrait).pack(pady=4)

        # Preview + color
        mid = tk.Frame(self)
        mid.pack(padx=12, pady=6)

        preview_wrap = tk.LabelFrame(mid, text="Drag to position  ·  scroll wheel to zoom", padx=0, pady=0)
        preview_wrap.pack(side="left", padx=(0, 12))
        self._canvas = tk.Canvas(
            preview_wrap, width=PREVIEW_SIZE, height=PREVIEW_SIZE, bg="#1a1a1a", cursor="fleur",
        )
        self._canvas.pack()
        self._canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<MouseWheel>", self._on_scroll)   # Windows / Mac
        self._canvas.bind("<Button-4>", self._on_scroll)     # Linux scroll up
        self._canvas.bind("<Button-5>", self._on_scroll)     # Linux scroll down

        color_col = tk.Frame(mid)
        color_col.pack(side="left", anchor="n")
        tk.Label(color_col, text="Frame color", font=("", 10, "bold")).pack(pady=(0, 4))
        self._swatch = tk.Label(color_col, width=10, height=2, bg=self._color, relief="solid")
        self._swatch.pack()
        if not self._lock_color:
            tk.Button(color_col, text="Pick color…", command=self._pick_color).pack(pady=(6, 2))
            tk.Label(color_col, text="Presets:").pack(pady=(10, 2))
            for name, hex_c in PRESETS:
                tk.Button(
                    color_col, text=name,
                    bg=hex_c, fg="black" if name == "Gold" else "white",
                    width=9, command=lambda h=hex_c: self._set_color(h),
                ).pack(pady=1)

        # Name + save
        bot = tk.Frame(self)
        bot.pack(padx=12, pady=12, fill="x")
        tk.Label(bot, text="Name:").pack(side="left")
        self._name_var = tk.StringVar()
        tk.Entry(bot, textvariable=self._name_var, width=22).pack(side="left", padx=5)
        tk.Label(bot, text=".png").pack(side="left")
        tk.Button(bot, text="Save token", command=self._save, width=10).pack(side="right")

    # ── Portrait grid ─────────────────────────────────────────────────────

    def _load_portrait_grid(self):
        os.makedirs(self._portraits_dir, exist_ok=True)
        portraits = sorted(
            f for f in os.listdir(self._portraits_dir)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        )
        if not portraits:
            tk.Label(
                self._grid_inner,
                text="No portraits in Assets/Portraits/ yet.\nUse Browse… to pick any image.",
                justify="left", fg="#555",
            ).grid(row=0, column=0, padx=6, pady=6)
            return
        for i, fname in enumerate(portraits):
            path = os.path.join(self._portraits_dir, fname)
            img = Image.open(path).convert("RGBA").resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._thumbs[path] = photo
            row, col = divmod(i, THUMB_COLS)
            tk.Button(
                self._grid_inner, image=photo, relief="flat", bd=2,
                command=lambda p=path, n=os.path.splitext(fname)[0]: self._select_portrait(p, n),
            ).grid(row=row, column=col, padx=2, pady=2)

    def _select_portrait(self, path: str, name: str):
        self._portrait_path = path
        self._portrait = Image.open(path).convert("RGBA")
        self._name_var.set(name)
        self._reset_position()
        self._refresh_preview()

    def _browse_portrait(self):
        path = filedialog.askopenfilename(
            title="Select portrait",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")],
        )
        if path:
            self._portrait_path = path
            self._portrait = Image.open(path).convert("RGBA")
            self._name_var.set(os.path.splitext(os.path.basename(path))[0])
            self._reset_position()
            self._refresh_preview()

    def _reset_position(self):
        if self._portrait is None:
            return
        # Fill the preview width; center vertically
        self._port_scale = PREVIEW_SIZE / self._portrait.width
        ph = self._portrait.height * self._port_scale
        self._port_x = 0.0
        self._port_y = (PREVIEW_SIZE - ph) / 2

    # ── Color ─────────────────────────────────────────────────────────────

    def _pick_color(self):
        result = colorchooser.askcolor(color=self._color, title="Frame color")
        if result[1]:
            self._set_color(result[1])

    @staticmethod
    def _is_too_bright(hex_color: str) -> bool:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return luminance > 0.75

    def _set_color(self, hex_color: str):
        if self._is_too_bright(hex_color):
            messagebox.showwarning(
                "Color too bright",
                "That color is too light to be visible in the tracker.\n"
                "Please choose a darker color.",
            )
            return
        self._color = hex_color
        self._swatch.configure(bg=hex_color)
        self._refresh_preview()

    # ── Drag & scroll ─────────────────────────────────────────────────────

    def _on_drag_start(self, event):
        self._drag_start = (event.x, event.y)
        self._drag_origin = (self._port_x, self._port_y)

    def _on_drag(self, event):
        if self._drag_start is None or self._portrait is None:
            return
        self._port_x = self._drag_origin[0] + (event.x - self._drag_start[0])
        self._port_y = self._drag_origin[1] + (event.y - self._drag_start[1])
        self._refresh_preview()

    def _on_scroll(self, event):
        if self._portrait is None:
            return
        factor = 1.06 if (event.num == 4 or event.delta > 0) else 1 / 1.06
        # Zoom centered on the frame center
        cx = cy = PREVIEW_SIZE / 2
        self._port_x = cx + (self._port_x - cx) * factor
        self._port_y = cy + (self._port_y - cy) * factor
        self._port_scale *= factor
        self._refresh_preview()

    # ── Preview ───────────────────────────────────────────────────────────

    def _refresh_preview(self):
        tinted = _tint(self._frame_base, self._color)

        if self._portrait is not None:
            img = _composite(
                self._portrait, tinted, self._outer_mask,
                self._port_x, self._port_y, self._port_scale,
                PREVIEW_SIZE, PREVIEW_SIZE,
            )
        else:
            frame_prev = tinted.resize((PREVIEW_SIZE, PREVIEW_SIZE), Image.LANCZOS)
            outer = _scale_mask(self._outer_mask, PREVIEW_SIZE)
            arr = np.array(frame_prev)
            arr[outer, 3] = 0
            img = Image.fromarray(arr, "RGBA")

        # Composite onto dark background for display
        bg = Image.new("RGBA", (PREVIEW_SIZE, PREVIEW_SIZE), (26, 26, 26, 255))
        bg.paste(img, (0, 0), mask=img)
        self._preview_photo = ImageTk.PhotoImage(bg)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._preview_photo)

    # ── Save ──────────────────────────────────────────────────────────────

    def _save(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showerror("Error", "Enter a name for the token.")
            return
        if self._portrait is None:
            messagebox.showerror("Error", "Select a portrait first.")
            return
        if self._is_too_bright(self._color):
            messagebox.showerror(
                "Color too bright",
                "The selected color is too light to be visible in the tracker.\n"
                "Please choose a darker color.",
            )
            return
        tinted = _tint(self._frame_base, self._color)
        token = _composite(
            self._portrait, tinted, self._outer_mask,
            self._port_x, self._port_y, self._port_scale,
            PREVIEW_SIZE, OUTPUT_SIZE,
        )
        os.makedirs(self._output_dir, exist_ok=True)
        out_path = os.path.join(self._output_dir, f"{name}.png")
        token.save(out_path)
        import json as _json
        print(_json.dumps({
            "path": out_path,
            "icon": f"{name}.png",
            "color": self._color,
            "portrait_source": os.path.basename(self._portrait_path),
        }), flush=True)
        messagebox.showinfo("Saved", f"Token saved:\n{out_path}")
        self.destroy()


def main():
    ap = argparse.ArgumentParser(description="DungeonPy token composer")
    ap.add_argument("--color", default=DM_COLOR)
    ap.add_argument("--lock-color", action="store_true")
    ap.add_argument("--assets-dir", default=None)
    ap.add_argument("--output-dir", default=None)
    args = ap.parse_args()

    assets_dir = args.assets_dir or os.path.join(_ROOT, "Assets")
    output_dir = args.output_dir or os.path.join(assets_dir, "Combatants")

    TokenComposer(
        preset_color=args.color,
        lock_color=args.lock_color,
        assets_dir=assets_dir,
        output_dir=output_dir,
    ).mainloop()


if __name__ == "__main__":
    main()
