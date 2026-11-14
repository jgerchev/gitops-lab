"""Shared external-runtime guard; standard-library only, no host mutations."""
import os
from pathlib import Path


INFRA = Path(__file__).resolve().parents[1]
CHECKOUT = INFRA.parent


def external(value):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("Runtime paths must be absolute")
    path = path.resolve()
    if path == CHECKOUT or CHECKOUT in path.parents or path in CHECKOUT.parents:
        raise ValueError("Runtime must be outside (and not contain) the checkout")
    return path


def runtime():
    os.umask(0o077)
    root = external(os.environ["LAB_RUNTIME_DIR"])
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.stat().st_uid != os.getuid():
        raise ValueError("Runtime must belong to current user")
    root.chmod(0o700)
    return root


IMAGE_NAME = "ubuntu-24.04-server-cloudimg-amd64.img"
IMAGE_SHA256 = "04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94"
IMAGE_URL = "https://cloud-images.ubuntu.com/releases/noble/release-20261017/" + IMAGE_NAME
