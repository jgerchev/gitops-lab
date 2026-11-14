#!/usr/bin/env python3
"""Acquire the immutable Ubuntu image, checking pinned SHA256 before rename."""
import hashlib
import os
import tempfile
import urllib.request

from runtime import IMAGE_NAME, IMAGE_SHA256, IMAGE_URL, external, runtime


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    root = runtime()
    directory = external(str(root / "images"))
    directory.mkdir(mode=0o700, exist_ok=True)
    destination = directory / IMAGE_NAME
    if destination.exists():
        if destination.is_symlink() or digest(destination) != IMAGE_SHA256:
            raise ValueError("Existing image is unsafe/corrupt; investigate, do not overwrite")
        print(destination)
        return
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
            name = output.name
            with urllib.request.urlopen(IMAGE_URL, timeout=120) as response:
                if not response.url.startswith("https://cloud-images.ubuntu.com/"):
                    raise ValueError("Unexpected image redirect")
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        from pathlib import Path
        if digest(Path(name)) != IMAGE_SHA256:
            raise ValueError("Ubuntu image SHA256 mismatch; refusing image")
        # Atomic no-clobber publication; concurrent downloads cannot replace it.
        os.link(name, destination)
        print(destination)
    finally:
        if name is not None:
            os.unlink(name)


if __name__ == "__main__":
    main()
