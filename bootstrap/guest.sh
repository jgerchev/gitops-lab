#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Internal entrypoint, invoked over SSH by bootstrap.sh. Never run on the host.
set -Eeuo pipefail
umask 077
trap 'printf "bootstrap: stopped at guest line %s (no automatic reinstall).\n" "$LINENO" >&2' ERR
die() { printf 'bootstrap: %s\n' "$*" >&2; exit 1; }
[[ $EUID == 0 && $# == 1 ]] || die 'internal entrypoint requires root and its bundle directory'
cd -- "$1"
# shellcheck source=versions.env
source ./versions.env
[[ $(hostname -s) == gitops-lab ]] || die 'refusing a machine not named gitops-lab'
[[ $(uname -m) == x86_64 ]] || die 'only the contract amd64 guest is supported'
[[ -r /etc/os-release ]] || die 'missing OS identification'
# shellcheck source=/dev/null
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 24.04 ]] || die 'requires Ubuntu 24.04 guest'
systemd-detect-virt --vm --quiet || die 'requires a VM, not a physical host/container'
for tool in flock timeout systemctl sha256sum python3 install cmp stat; do
  command -v "$tool" >/dev/null || die "missing guest prerequisite: $tool (no automatic apt changes)"
done
exec 9>/run/lock/gitops-lab-bootstrap.lock
flock -w 10 9 || die 'another bootstrap owns the guest lock'
if command -v cloud-init >/dev/null; then
  timeout --kill-after=10s 300 cloud-init status --wait >/dev/null
fi
printf '%s  %s\n' "$K3S_SHA256" k3s "$ARGO_SHA256" argocd-install.yaml | sha256sum --check --status \
  || die 'bundle checksum mismatch'
state=/var/lib/gitops-lab-bootstrap
marker=$state/versions.env
if [[ -f $marker ]]; then
  cmp -s versions.env "$marker" || die 'version/checksum/ownership mismatch; review explicitly, never auto-upgrade'
else
  # Refuse to adopt an existing cluster, including an interrupted foreign install.
  for path in /usr/local/bin/k3s /etc/systemd/system/k3s.service /lib/systemd/system/k3s.service \
    /etc/rancher/k3s /var/lib/rancher/k3s; do
    [[ ! -e $path ]] || die "unowned K3s installation: $path; inspect manually or recreate ONLY the lab VM"
  done
  command -v k3s >/dev/null && die 'unowned k3s on PATH'
  install -d -m 0700 "$state"
  install -m 0600 versions.env "$marker"
fi
ensure_file() {
  local source=$1 destination=$2 mode=$3
  if [[ -e $destination ]]; then
    cmp -s "$source" "$destination" || die "configuration drift: $destination; inspect explicitly"
  else
    install -m "$mode" "$source" "$destination"
  fi
  chown root:root "$destination"
  chmod "$mode" "$destination"
}
if [[ -e /usr/local/bin/k3s ]]; then
  printf '%s  %s\n' "$K3S_SHA256" /usr/local/bin/k3s | sha256sum --check --status \
    || die 'installed K3s bytes differ; refusing replacement'
else
  install -m 0755 k3s /usr/local/bin/k3s
fi
chown root:root /usr/local/bin/k3s
chmod 0755 /usr/local/bin/k3s
installed_version=$(/usr/local/bin/k3s --version)
[[ ${installed_version%%$'\n'*} == "k3s version $K3S_VERSION "* ]] \
  || die 'installed K3s version mismatch'
install -d -o root -g root -m 0700 /etc/rancher/k3s
ensure_file k3s-config.yaml /etc/rancher/k3s/config.yaml 0600
ensure_file k3s.service /etc/systemd/system/k3s.service 0644
[[ ! -d /etc/systemd/system/k3s.service.d && ! -d /etc/rancher/k3s/config.yaml.d ]] \
  || die 'unexpected systemd/K3s config drop-ins; inspect explicitly'
systemctl daemon-reload
timeout --kill-after=10s 330 systemctl enable --now k3s
k() { /usr/local/bin/k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml --request-timeout=30s "$@"; }
deadline=$((SECONDS + 300))
until k get --raw=/readyz >/dev/null 2>&1; do
  ((SECONDS < deadline)) || die 'Kubernetes API did not become ready in 300s'
  sleep 5
done
chown root:root /etc/rancher/k3s/k3s.yaml
chmod 0600 /etc/rancher/k3s/k3s.yaml
[[ $(stat -c '%a:%U:%G' /etc/rancher/k3s/k3s.yaml) == 600:root:root ]] || die 'unsafe kubeconfig permissions'
[[ $(k get nodes -o name | wc -l) == 1 ]] || die 'expected exactly one lab node'
k wait --for=condition=Ready node --all --timeout=300s
[[ $(k get --raw=/version | python3 -c 'import json,sys; print(json.load(sys.stdin)["gitVersion"])') == "$K3S_VERSION" ]] \
  || die 'running API version mismatch; no automatic restart/upgrade'
deadline=$((SECONDS + 300))
until k -n kube-system get deployment traefik >/dev/null 2>&1; do
  ((SECONDS < deadline)) || die 'default Traefik deployment not found in 300s'
  sleep 5
done
k -n kube-system rollout status deployment/traefik --timeout=300s
# Persist ownership before creating Argo resources so interrupted first runs can
# resume, but never silently adopt a pre-existing installation/namespace.
if [[ ! -f $state/argocd-owned ]]; then
  existing=$(k get namespace argocd --ignore-not-found -o name)
  if [[ -n $existing ]]; then
    die 'unowned argocd namespace; explicit migration or lab recreation required'
  fi
  existing=$(k get crd applications.argoproj.io --ignore-not-found -o name)
  if [[ -n $existing ]]; then
    die 'unowned Argo CRDs; explicit migration or lab recreation required'
  fi
  install -m 0600 /dev/null "$state/argocd-owned"
fi
# Detect live version drift before apply can turn it into an unintended downgrade.
k -n argocd get deployment,statefulset -o json > "$state/argocd-workloads.json"
python3 - "$state/argocd-workloads.json" "$ARGO_VERSION" <<'PY'
import json, sys
argo_containers = {'argocd-applicationset-controller', 'copyutil',
                   'argocd-notifications-controller', 'secret-init',
                   'argocd-repo-server', 'argocd-server', 'argocd-application-controller'}
for item in json.load(open(sys.argv[1]))['items']:
    if not item['metadata']['name'].startswith('argocd-'):
        continue
    pod = item['spec']['template']['spec']
    if pod.get('hostNetwork'):
        sys.exit('bootstrap: Argo hostNetwork exposure detected; inspect manually')
    for container in pod.get('containers', []) + pod.get('initContainers', []):
        if any(port.get('hostPort') for port in container.get('ports', [])):
            sys.exit('bootstrap: Argo hostPort exposure detected; inspect manually')
        image = container['image']
        if (container['name'] in argo_containers or 'argoproj/argocd' in image) and image != 'quay.io/argoproj/argocd:' + sys.argv[2]:
            sys.exit('bootstrap: Argo image version/digest drift; refusing automatic replacement')
PY
rm -f "$state/argocd-workloads.json"
k apply --server-side --field-manager=gitops-lab-bootstrap -f namespaces.yaml
# SSA avoids the 262144-byte last-applied annotation limit on Argo CRDs.
# Do NOT add --force-conflicts: foreign field ownership requires investigation.
k -n argocd apply --server-side --field-manager=gitops-lab-bootstrap -f argocd-install.yaml
k wait --for=condition=Established --timeout=120s \
  crd/applications.argoproj.io crd/appprojects.argoproj.io crd/applicationsets.argoproj.io
k -n argocd get service,ingress -o json > "$state/argocd-exposure.json"
python3 - "$state/argocd-exposure.json" <<'PY'
import json, sys
for item in json.load(open(sys.argv[1]))['items']:
    if item['kind'] == 'Ingress':
        sys.exit('bootstrap: unexpected Ingress in Argo namespace; inspect manually')
    spec = item['spec']
    if spec.get('type', 'ClusterIP') != 'ClusterIP' or spec.get('externalIPs') or spec.get('loadBalancerIP'):
        sys.exit('bootstrap: Argo services must remain internal ClusterIP without external IPs')
PY
rm -f "$state/argocd-exposure.json"
# A fixed non-HA workload list avoids accidentally accepting an empty selector.
for workload in deployment/argocd-applicationset-controller deployment/argocd-dex-server \
  deployment/argocd-notifications-controller deployment/argocd-redis \
  deployment/argocd-repo-server deployment/argocd-server statefulset/argocd-application-controller; do
  k -n argocd rollout status "$workload" --timeout=300s
done
k apply --server-side --field-manager=gitops-lab-bootstrap -f project.yaml
k apply --server-side --field-manager=gitops-lab-bootstrap -f application.yaml
printf 'Bootstrap ready: K3s %s, Argo CD %s; Application created (sync/health NOT yet asserted).\n' "$K3S_VERSION" "$ARGO_VERSION"
