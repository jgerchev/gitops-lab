#!/usr/bin/env python3
"""Restricted Terraform entry point; intentionally accepts no raw CLI flags."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
from runtime import IMAGE_NAME, INFRA, external, runtime


def main():
    if len(sys.argv) != 2:
        raise ValueError("Usage: tf.py fmt|init|validate|schema|plan|destroy-plan|show|show-destroy|apply|apply-destroy|output")
    command = sys.argv[1]
    if any(k.startswith("TF_CLI_ARGS") for k in os.environ):
        raise ValueError("Unset TF_CLI_ARGS*; hidden CLI flags are forbidden")
    if os.environ.get("TF_WORKSPACE", "default") != "default":
        raise ValueError("Only the default workspace is allowed")
    root = runtime()
    data = external(os.environ["TF_DATA_DIR"])
    if root not in data.parents:
        raise ValueError("TF_DATA_DIR must be inside LAB_RUNTIME_DIR")
    for directory in [data, root / "state", root / "plans", root / "tmp"]:
        if root not in external(str(directory)).parents:
            raise ValueError("Runtime subdirectories must remain inside runtime")
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    env = os.environ.copy()
    env.update(TF_DATA_DIR=str(data), TF_WORKSPACE="default", TF_IN_AUTOMATION="1",
               TMPDIR=str(root / "tmp"), TF_LOG_PATH=str(root / "terraform.log"),
               TF_VAR_image_path=str(root / "images" / IMAGE_NAME))
    terraform = env.get("TERRAFORM", "terraform")
    version = json.loads(subprocess.check_output([terraform, "version", "-json"], env=env))
    if version["terraform_version"] != "1.17.2":
        raise ValueError("Terraform must be exactly 1.17.2")
    plan = root / "plans" / "apply.tfplan"
    destroy = root / "plans" / "destroy.tfplan"
    for path in [plan, destroy, root / "state" / "terraform.tfstate", root / "run.lock"]:
        if path.is_symlink():
            raise ValueError("Runtime output files must not be symbolic links")
    commands = {
        "fmt": ["fmt", "-check", "-recursive"],
        "init": ["init", "-input=false", "-reconfigure", "-lockfile=readonly",
                 f"-backend-config=path={root / 'state' / 'terraform.tfstate'}",
                 f"-backend-config=workspace_dir={root / 'state' / 'workspaces'}"],
        "validate": ["validate"],
        "schema": ["providers", "schema", "-json"],
        "plan": ["plan", "-input=false", "-lock-timeout=30s", f"-out={plan}"],
        "destroy-plan": ["plan", "-destroy", "-input=false", "-lock-timeout=30s", f"-out={destroy}"],
        "show": ["show", str(plan)],
        "show-destroy": ["show", str(destroy)],
        "apply": ["apply", "-input=false", "-lock-timeout=30s", str(plan)],
        "apply-destroy": ["apply", "-input=false", "-lock-timeout=30s", str(destroy)],
        "output": ["output", "-json"],
    }
    if command not in commands:
        raise ValueError("Unsupported command")
    if command.startswith("apply") and env.get("LAB_APPROVE") != command:
        raise ValueError(f"Review saved plan, obtain approval, then set LAB_APPROVE={command}")
    if command in {"plan", "destroy-plan", "show", "show-destroy", "apply", "apply-destroy", "output"}:
        metadata = json.loads((data / "terraform.tfstate").read_text())
        backend = metadata.get("backend", {})
        config = backend.get("config", {})
        if (backend.get("type") != "local" or
                config.get("path") != str(root / "state" / "terraform.tfstate") or
                config.get("workspace_dir") != str(root / "state" / "workspaces")):
            raise ValueError("Backend does not match guarded runtime; run wrapper init")
    # Serialize even plan/init; retain Terraform's own backend locking as well.
    with (root / "run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run([terraform, f"-chdir={INFRA}", *commands[command]], env=env)
        # Never chmod provider binaries in TF_DATA_DIR (they need execute bits).
        for directory in [root / "state", root / "plans", root / "tmp"]:
            for path in directory.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    path.chmod(0o600)
        return result.returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, ValueError, OSError) as error:
        sys.exit(f"Refusing Terraform operation: {error}")
