import argparse
import json
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable

import ddddocr
from PIL import Image, ImageOps


ALLOWED_MATH_CHARS = "0123456789+-*/=?"
MATH_RE = re.compile(r"(?P<left>\d+)\s*(?P<op>[+\-*/])\s*(?P<right>\d+)")
CHAR_REPLACEMENTS = str.maketrans(
    {
        "×": "*",
        "x": "*",
        "X": "*",
        "÷": "/",
        "—": "-",
        "_": "-",
        " ": "",
    }
)


@dataclass(frozen=True)
class SolveResult:
    image_path: str
    raw_candidates: list[str]
    expression: str | None
    answer: str | None


def normalize_candidate(text: str) -> str:
    cleaned = text.translate(CHAR_REPLACEMENTS).strip()
    return "".join(ch for ch in cleaned if ch in ALLOWED_MATH_CHARS)


def choose_expression(candidates: Iterable[str]) -> str | None:
    seen: set[str] = set()
    for candidate in candidates:
        normalized = normalize_candidate(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if MATH_RE.search(normalized):
            return normalized
    return None


def solve_expression_text(text: str) -> str | None:
    match = MATH_RE.search(normalize_candidate(text))
    if not match:
        return None
    left = int(match.group("left"))
    right = int(match.group("right"))
    op = match.group("op")
    if op == "+":
        return str(left + right)
    if op == "-":
        return str(left - right)
    if op == "*":
        return str(left * right)
    if op == "/":
        if right == 0 or left % right != 0:
            return None
        return str(left // right)
    return None


def build_variants(image_bytes: bytes) -> list[bytes]:
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    grayscale = ImageOps.grayscale(image)
    variants = [
        image,
        image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS),
        grayscale.resize(
            (grayscale.width * 4, grayscale.height * 4), Image.Resampling.LANCZOS
        ),
    ]

    binary = grayscale.point(lambda x: 0 if x < 185 else 255, "1").convert("L")
    variants.append(
        binary.resize((binary.width * 4, binary.height * 4), Image.Resampling.NEAREST)
    )

    output: list[bytes] = []
    for variant in variants:
        buffer = BytesIO()
        variant.save(buffer, format="PNG")
        output.append(buffer.getvalue())
    return output


def classify_candidates(image_bytes: bytes) -> list[str]:
    candidates: list[str] = []
    for beta in (False, True):
        ocr = ddddocr.DdddOcr(show_ad=False, beta=beta)
        for variant in build_variants(image_bytes):
            candidates.append(ocr.classification(variant))
            ocr.set_ranges(ALLOWED_MATH_CHARS)
            candidates.append(ocr.classification(variant))
    return [candidate for candidate in candidates if candidate is not None]


def solve_image(image_path: str) -> SolveResult:
    path = Path(image_path)
    image_bytes = path.read_bytes()
    raw_candidates = classify_candidates(image_bytes)
    expression = choose_expression(raw_candidates)
    answer = solve_expression_text(expression or "")
    return SolveResult(
        image_path=str(path),
        raw_candidates=raw_candidates,
        expression=expression,
        answer=answer,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Use ddddocr to read a math captcha and compute the answer."
    )
    parser.add_argument("image_path", help="Path to the captcha image")
    args = parser.parse_args()

    result = solve_image(args.image_path)
    print(
        json.dumps(
            {
                "image_path": result.image_path,
                "raw_candidates": result.raw_candidates,
                "expression": result.expression,
                "answer": result.answer,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
