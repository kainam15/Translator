"""Download pinned formula models, checking bytes before atomic replacement."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import os
import tempfile
import time
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORIES = {
    "mfd": (
        "breezedeus/pix2text-mfd-1.5",
        "f470a885e0fca1d3d2bfa2a54991db7ae01f1861",
    ),
    "mfr": (
        "breezedeus/pix2text-mfr-1.5",
        "1cef9f0bdcd6a4c63df7de1311fb0894593340cc",
    ),
}


@dataclass(frozen=True)
class ModelFile:
    group: str
    name: str
    size: int
    sha256: str

    @property
    def relative_path(self) -> Path:
        return Path(self.group) / self.name

    @property
    def url(self) -> str:
        repository, revision = REPOSITORIES[self.group]
        return f"https://huggingface.co/{repository}/resolve/{revision}/{self.name}"


# ONNX digests match the official repository's Git LFS SHA-256 metadata.
# Small-file bytes also matched the official Git blob IDs before pinning.
MODEL_FILES = (
    ModelFile("mfd", "README.md", 855,
              "20405a1967627ca2496c6f05e5e7d054d305e9deb155010e48df57de5b327194"),
    ModelFile("mfd", "config.yaml", 23,
              "2768256f4e0ae82e1e0b4e0844c19be37b5875a5794ce63051bd999a32288df7"),
    ModelFile("mfd", "pix2text-mfd-1.5.onnx", 80311115,
              "40d4fc852d99bcbf25a9478897d2f49fbbb8f7fdd6569c088cd1c31386293bd7"),
    ModelFile("mfr", "README.md", 9441,
              "7ae7136c49c64378ff09a86b750ef9c2007ad8e91e148be391e3480bfd9dce97"),
    ModelFile("mfr", "config.json", 1573,
              "fe4076f08f6ca75940f6af9268d51928b834979a69bc2145dacee62633a5d53d"),
    ModelFile("mfr", "decoder_model.onnx", 32026253,
              "917deb98e91a0453c5f234f58a0f32f9fb037de8527c7eb4ed394daf9e692f2a"),
    ModelFile("mfr", "encoder_model.onnx", 87510770,
              "080a3f660f08bc9ebcacdd96e34be6b6400f8c7e62d7cd0dd8251badc37f610b"),
    ModelFile("mfr", "generation_config.json", 211,
              "7363c031c6142d35a276815b0e285cc289dfb9f51d0b7c63de8f3ed65cc8d8ad"),
    ModelFile("mfr", "preprocessor_config.json", 450,
              "36a945a7cc645688b9ef64dabae16979cf5f7c1c448569cc306694edc0598b9b"),
    ModelFile("mfr", "special_tokens_map.json", 964,
              "8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835"),
    ModelFile("mfr", "tokenizer.json", 113168,
              "4ffbeb2143e6a38324bb6111b7a8109530d38a076a8439aa5777535f0a32758a"),
    ModelFile("mfr", "tokenizer_config.json", 1244,
              "f5cc321e8545940295fba11e9a59f4f2a208a23af3d63cc8c355c78593645b99"),
)


def verify_file(path: Path, specification: ModelFile) -> bool:
    if not path.is_file() or path.stat().st_size != specification.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == specification.sha256


def download_file(path: Path, specification: ModelFile) -> None:
    """Retain any existing file until the replacement is completely verified."""
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        specification.url,
        headers={"User-Agent": "TranslatorLite-model-setup/1", "Accept-Encoding": "identity"},
    )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=path.name + ".", suffix=".part", delete=False
        ) as output:
            temporary_path = Path(output.name)
            digest = hashlib.sha256()
            received = 0
            with urllib.request.urlopen(request, timeout=30) as response:
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > specification.size:
                        raise ValueError(f"Downloaded file is too large: {specification.relative_path}")
                    output.write(chunk)
                    digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        if received != specification.size or digest.hexdigest() != specification.sha256:
            raise ValueError(f"Model checksum mismatch: {specification.relative_path}")
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models-dir", type=Path, default=PROJECT_ROOT / ".artifacts" / "ocr-models"
    )
    parser.add_argument("--verify-only", action="store_true", help="Do not download or modify files")
    args = parser.parse_args(argv)
    destination = args.models_dir.resolve()
    failures: list[str] = []
    for specification in MODEL_FILES:
        path = destination / specification.relative_path
        if verify_file(path, specification):
            print(f"Verified {specification.relative_path}", flush=True)
            continue
        if args.verify_only:
            failures.append(str(specification.relative_path))
            continue
        for attempt in range(3):
            try:
                print(f"Downloading {specification.relative_path}", flush=True)
                download_file(path, specification)
                break
            except (OSError, ValueError) as error:
                if attempt == 2:
                    raise RuntimeError(
                        f"Unable to download {specification.relative_path}: {error}"
                    ) from error
                time.sleep(2 * (attempt + 1))
    if failures:
        parser.exit(1, "Missing or invalid models: " + ", ".join(failures) + "\n")
    print(f"All {len(MODEL_FILES)} model files verified: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
