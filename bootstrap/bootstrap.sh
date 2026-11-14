#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Runs only over SSH, never against the virtualization host's local services.
set -Eeuo pipefail
umask 077
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=versions.env
source "$ROOT/versions.env"
die() { printf 'bootstrap: %s\n' "$*" >&2; exit 1; }
usage() {
  cat <<'EOF'
Usage: bash bootstrap/bootstrap.sh --target lab@VM_IP [options]
  --jump USER@HOME_SERVER  SSH jump host (optional)
  --identity FILE          Private key outside checkout (optional)
  --port PORT              Guest SSH port (default 22)
  --known-hosts FILE       Preverified SSH known_hosts file (optional)
  --ssh-option OPTION     Additional single ssh -o option (repeatable)
  --render                Print bootstrap namespaces/project/Application only
  --help                  Show this message
SSH host keys must be verified in advance. Passwordless guest sudo is required.
No host prerequisites are installed. No credential is fetched or printed.
EOF
}
target=''
ssh_args=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10
  -o ConnectionAttempts=1 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
while (($#)); do
  case "$1" in
    --help) usage; exit 0 ;;
    --render)
      for file in namespaces.yaml project.yaml application.yaml; do
        printf '%s\n' '---'; cat "$ROOT/$file"
      done
      exit 0 ;;
    --target|--jump|--identity|--port|--known-hosts|--ssh-option)
      (($# >= 2)) || die "missing value for $1"
      [[ -n $2 && $2 != -* ]] || die "invalid value for $1"
      case "$1" in
        --target) target=$2 ;;
        --jump) ssh_args+=(-J "$2") ;;
        --identity) ssh_args+=(-i "$2" -o IdentitiesOnly=yes) ;;
        --port) [[ $2 =~ ^[0-9]+$ ]] || die 'invalid port'; ssh_args+=(-p "$2") ;;
        --known-hosts) ssh_args+=(-o "UserKnownHostsFile=$2") ;;
        --ssh-option) ssh_args+=(-o "$2") ;;
      esac
      shift 2 ;;
    *) die "unknown option: $1" ;;
  esac
done
[[ $target =~ ^lab@[A-Za-z0-9][A-Za-z0-9.:-]*$ ]] || die 'supply --target lab@VM_IP (guest only)'
for tool in ssh curl sha256sum tar timeout mktemp; do
  command -v "$tool" >/dev/null || die "missing local prerequisite: $tool"
done
work=$(mktemp -d "${TMPDIR:-/tmp}/gitops-lab-bootstrap.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
fetch() {
  local url=$1 hash=$2 output=$3
  curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    --connect-timeout 10 --max-time 300 --retry 2 --retry-max-time 620 \
    "$url" -o "$output"
  printf '%s  %s\n' "$hash" "$output" | sha256sum --check --status || die "checksum mismatch: ${output##*/}"
}
printf 'Downloading pinned public release artifacts (no installer scripts).\n'
fetch "$K3S_URL" "$K3S_SHA256" "$work/k3s"
fetch "$ARGO_URL" "$ARGO_SHA256" "$work/argocd-install.yaml"
for file in guest.sh versions.env k3s.service k3s-config.yaml namespaces.yaml project.yaml application.yaml; do
  cp -- "$ROOT/$file" "$work/$file"
done
# No secrets in this archive. Remote temporary files are user-private and removed
# on success/failure; privileged persistent state lives outside the checkout.
# Both SSH transport and the privileged guest work have finite deadlines.
printf 'Bootstrapping %s; guest deadline 30 minutes.\n' "$target"
# Variables in the remote program must expand on the guest, not locally.
# shellcheck disable=SC2016
tar -C "$work" -cf - . | timeout --signal=TERM --kill-after=30s 2100 \
  ssh "${ssh_args[@]}" "$target" '
    set -eu
    umask 077
    work=$(mktemp -d /tmp/gitops-lab-bootstrap.XXXXXXXX)
    trap '\''rm -rf -- "$work"'\'' EXIT HUP INT TERM
    tar -xf - -C "$work"
    sudo -n timeout --signal=TERM --kill-after=30s 1800 bash "$work/guest.sh" "$work"
  '
