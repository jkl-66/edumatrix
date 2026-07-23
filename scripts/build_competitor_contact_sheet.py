from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def build(source: Path, output: Path, columns: int = 3) -> None:
    files = sorted(
        path for path in source.iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )
    if not files:
        raise SystemExit(f"No images found in {source}")

    cell_width = 640
    cell_height = 430
    label_height = 42
    rows = math.ceil(len(files) / columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "#f4f4f1")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for index, path in enumerate(files):
        image = Image.open(path).convert("RGB")
        image.thumbnail((cell_width - 24, cell_height - label_height - 20), Image.Resampling.LANCZOS)
        col = index % columns
        row = index // columns
        left = col * cell_width
        top = row * cell_height
        x = left + (cell_width - image.width) // 2
        y = top + label_height + (cell_height - label_height - image.height) // 2
        sheet.paste(image, (x, y))
        draw.rectangle((left, top, left + cell_width - 1, top + cell_height - 1), outline="#c8ccc7", width=1)
        draw.text((left + 12, top + 12), path.stem, fill="#20251f", font=font)

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92)
    print(output.resolve())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--columns", type=int, default=3)
    args = parser.parse_args()
    build(args.source, args.output, args.columns)


if __name__ == "__main__":
    main()
