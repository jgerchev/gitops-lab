"""Update only the deployment image after a release has been published."""

import argparse
from pathlib import Path
import re


def update_image(text, version, digest):
    if version not in ("v1", "v2") or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("expected v1/v2 and sha256:<64 lowercase hex characters>")
    image = f"ghcr.io/jgerchev/gitops-lab-app:{version}@{digest}"
    updated, count = re.subn(
        r"(?m)^(\s*image: )ghcr\.io/jgerchev/gitops-lab-app:v[12](?:@sha256:[0-9a-f]{64})?$",
        lambda match: match[1] + image,
        text,
    )
    if count != 1:
        raise ValueError("expected exactly one known application image; no file written")
    return updated.replace(
        "# Pending publication: coordinator must pin tag@sha256 using app/set-image.py.",
        "# Published digest pinned with app/set-image.py; see app/README.md.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", choices=("v1", "v2"))
    parser.add_argument("digest", help="verified published sha256 digest (not a placeholder)")
    args = parser.parse_args()
    deployment = Path(__file__).resolve().parent.parent / "gitops" / "deployment.yaml"
    deployment.write_text(update_image(deployment.read_text(), args.version, args.digest))
