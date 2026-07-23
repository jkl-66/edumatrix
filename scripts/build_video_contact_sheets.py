from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FRAME_NUMBER = re.compile(r"(\d+)$")


def frame_number(path: Path) -> int:
    match = FRAME_NUMBER.search(path.stem)
    return int(match.group(1)) if match else 0


def format_timestamp(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


def build_sheets(
    source: Path,
    output_dir: Path,
    interval_seconds: float,
    chunk_size: int,
    columns: int,
) -> list[Path]:
    files = sorted(
        (path for path in source.iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg"}),
        key=frame_number,
    )
    if not files:
        raise SystemExit(f"No frames found in {source}")

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    font = ImageFont.load_default()
    cell_width = 480
    image_height = 300
    label_height = 30
    cell_height = image_height + label_height

    for chunk_index in range(math.ceil(len(files) / chunk_size)):
        chunk = files[chunk_index * chunk_size : (chunk_index + 1) * chunk_size]
        rows = math.ceil(len(chunk) / columns)
        sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "#f3f4f6")
        draw = ImageDraw.Draw(sheet)

        for index, path in enumerate(chunk):
            image = Image.open(path).convert("RGB")
            image.thumbnail((cell_width - 12, image_height - 12), Image.Resampling.LANCZOS)
            col = index % columns
            row = index // columns
            left = col * cell_width
            top = row * cell_height
            x = left + (cell_width - image.width) // 2
            y = top + label_height + (image_height - image.height) // 2
            sheet.paste(image, (x, y))
            draw.rectangle(
                (left, top, left + cell_width - 1, top + cell_height - 1),
                outline="#9ca3af",
                width=1,
            )
            seconds = (frame_number(path) - 1) * interval_seconds
            draw.text(
                (left + 10, top + 9),
                f"{path.stem} | {format_timestamp(seconds)}",
                fill="#111827",
                font=font,
            )

        start_seconds = (frame_number(chunk[0]) - 1) * interval_seconds
        end_seconds = (frame_number(chunk[-1]) - 1) * interval_seconds
        output = output_dir / (
            f"sheet-{chunk_index + 1:02d}-{format_timestamp(start_seconds).replace(':', '')}"
            f"-{format_timestamp(end_seconds).replace(':', '')}.jpg"
        )
        sheet.save(output, quality=94)
        outputs.append(output)

    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--chunk-size", type=int, default=12)
    parser.add_argument("--columns", type=int, default=3)
    args = parser.parse_args()

    for output in build_sheets(
        args.source,
        args.output_dir,
        args.interval_seconds,
        args.chunk_size,
        args.columns,
    ):
        print(output.resolve())


if __name__ == "__main__":
    main()
