"""Read-only GHCR gate: only definite manifest/repository absence permits push."""

import base64
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    release = os.environ["RELEASE"]
    if release not in ("v1", "v2"):
        sys.exit("Invalid release")
    credentials = (os.environ["GHCR_USER"] + ":" + os.environ["GHCR_TOKEN"]).encode()
    request = urllib.request.Request(
        "https://ghcr.io/token?service=ghcr.io&scope=repository:jgerchev/gitops-lab-app:pull",
        headers={"Authorization": "Basic " + base64.b64encode(credentials).decode()},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            token = json.load(response)["token"]
        request = urllib.request.Request(
            f"https://ghcr.io/v2/jgerchev/gitops-lab-app/manifests/{release}",
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.oci.image.index.v1+json, "
                "application/vnd.docker.distribution.manifest.list.v2+json, "
                "application/vnd.oci.image.manifest.v1+json, "
                "application/vnd.docker.distribution.manifest.v2+json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30):
                sys.exit("Refusing publication: release tag already exists")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                errors = json.loads(error.read()).get("errors", [])
                if errors and all(
                    item.get("code") in ("MANIFEST_UNKNOWN", "NAME_UNKNOWN") for item in errors
                ):
                    print("Release tag absent; publication permitted")
                    return
            sys.exit("Registry did not confirm tag absence; refusing publication")
    except Exception:
        # Never print exceptions, headers, tokens, or registry response bodies.
        sys.exit("Registry check failed; refusing publication (check package permissions/connectivity)")


if __name__ == "__main__":
    main()
