#!/usr/bin/env bash
# Otomasi stack Kubernetes FCFS di kind. Setiap langkah dijelaskan di k8s/README.md.
# Seluruh alokasi (node datacenter, VM, task) berasal dari satu file: $CONFIG.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CLUSTER=${CLUSTER:-soka-fcfs}
CONTEXT=${KUBE_CONTEXT:-kind-$CLUSTER}
CONFIG=$(realpath "${CONFIG:-$ROOT/fcfs/config.json}")
IMAGE=fcfs-k8s:dev
MANIFESTS=$ROOT/k8s/manifests

kc() { kubectl --context "$CONTEXT" -n fcfs "$@"; }
render() { python3 "$ROOT/k8s/render.py" "$1" "$CONFIG"; }

usage() {
  cat <<EOF
Pemakaian: k8s/fcfs-k8s.sh <perintah> [opsi broker]

  up        Buat cluster kind: 1 control-plane + 1 worker per datacenter di config
  build     Build image $IMAGE dan muat ke node kind
  deploy    Pasang ConfigMap, PVC, dan pod VM yang dirender dari config
  run       deploy + Job broker FCFS + salin hasil ke results/
            opsi broker yang boleh: --work-per-mi N, --timeout S, --show-tasks
  collect   Salin ulang hasil terakhir dari PVC ke results/
  render    Tampilkan manifest kind dan VM hasil render config
  status    Tampilkan node, pod VM, Job, dan PVC
  down      Hapus cluster kind
  all       up + build + run

Config: $CONFIG (ubah dengan CONFIG=path/config.json)
EOF
}

sync_config() {
  kc create configmap fcfs-config --from-file=config.json="$CONFIG" \
    --dry-run=client -o yaml | kc apply -f -
}

check_nodes() {
  local datacenters=$1 dc
  for ((dc = 0; dc < datacenters; dc++)); do
    if [ -z "$(kubectl --context "$CONTEXT" get nodes -o name \
      -l "topology.kubernetes.io/zone=dc-$dc")" ]; then
      echo "Tidak ada node untuk datacenter $dc (zone dc-$dc). Jumlah datacenter di" \
        "config berubah? Buat ulang cluster: k8s/fcfs-k8s.sh down && k8s/fcfs-k8s.sh up" >&2
      exit 1
    fi
  done
}

cmd_up() {
  if kind get clusters | grep -qx "$CLUSTER"; then
    echo "Cluster $CLUSTER sudah ada."
  else
    local cluster_config
    cluster_config=$(mktemp --suffix=.yaml)
    render kind >"$cluster_config"
    kind create cluster --name "$CLUSTER" --config "$cluster_config"
    rm -f "$cluster_config"
  fi
  kubectl --context "$CONTEXT" get nodes -L topology.kubernetes.io/zone
}

cmd_build() {
  docker build -t "$IMAGE" -f "$ROOT/k8s/Dockerfile" "$ROOT/fcfs"
  kind load docker-image "$IMAGE" --name "$CLUSTER"
}

cmd_deploy() {
  local tasks vms datacenters dc
  read -r tasks vms datacenters < <(render shape)
  echo "Config: $tasks task, $vms VM, $datacenters datacenter ($CONFIG)"
  check_nodes "$datacenters"
  kubectl --context "$CONTEXT" apply -f "$MANIFESTS/namespace.yaml"
  sync_config
  kc apply -f "$MANIFESTS/results-pvc.yaml"
  render vms | kc apply -f -
  # Hapus VM datacenter yang tidak lagi ada di config.
  kc delete statefulset,service --ignore-not-found -l "app.kubernetes.io/name=fcfs-vm,\
fcfs.soka/datacenter notin ($(seq -s, 0 $((datacenters - 1))))"
  for ((dc = 0; dc < datacenters; dc++)); do
    kc rollout status "statefulset/fcfs-vm-dc$dc" --timeout=180s
  done
  kc get pods -l app.kubernetes.io/name=fcfs-vm -o wide
}

cmd_collect() {
  local tasks vms datacenters destination
  read -r tasks vms datacenters < <(render shape)
  destination="$ROOT/results/k8s-fcfs-${tasks}task-${vms}vm-${datacenters}dc-$(date +%Y%m%d-%H%M%S)"
  kc delete pod fcfs-results-reader --ignore-not-found
  kc apply -f "$MANIFESTS/results-reader.yaml"
  kc wait --for=condition=Ready pod/fcfs-results-reader --timeout=120s
  kc cp fcfs-results-reader:/results/fcfs-k8s "$destination"
  kc delete pod fcfs-results-reader --wait=false
  echo "Hasil disalin ke: $destination"
}

cmd_run() {
  local arg
  for arg in "$@"; do
    case "$arg" in
      --config* | --tasks* | --vms* | --datacenters* | --dataset* | --interactive | \
        --output* | --endpoints*)
        echo "Opsi $arg ditolak: task, VM, dan datacenter hanya diatur lewat $CONFIG" \
          "(ConfigMap fcfs-config)." >&2
        exit 1
        ;;
    esac
  done
  cmd_deploy
  kc delete job fcfs-broker --ignore-not-found
  # Opsi broker tambahan (mis. --work-per-mi 50) ditambahkan ke args container.
  kc create --dry-run=client -o json -f "$MANIFESTS/broker-job.yaml" \
    | python3 -c 'import json, sys
job = json.load(sys.stdin)
job["spec"]["template"]["spec"]["containers"][0]["args"] += sys.argv[1:]
json.dump(job, sys.stdout)' "$@" \
    | kc create -f -

  local phase=""
  for _ in $(seq 150); do
    phase=$(kc get pods -l job-name=fcfs-broker -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)
    [ -n "$phase" ] && [ "$phase" != Pending ] && break
    sleep 2
  done
  if [ -z "$phase" ] || [ "$phase" = Pending ]; then
    kc describe pods -l job-name=fcfs-broker >&2
    echo "Pod broker tidak kunjung berjalan." >&2
    exit 1
  fi
  kc logs -f job/fcfs-broker

  local counts=""
  for _ in $(seq 30); do
    counts=$(kc get job fcfs-broker -o jsonpath='{.status.succeeded}/{.status.failed}')
    [ "$counts" != / ] && break
    sleep 2
  done
  if [ "${counts%%/*}" != 1 ]; then
    echo "Job broker gagal; lihat: kubectl -n fcfs describe job fcfs-broker" >&2
    exit 1
  fi
  cmd_collect
}

cmd_render() {
  echo "# ===== kind cluster ($CONFIG) ====="
  render kind
  echo "# ===== VM ($CONFIG) ====="
  render vms
}

cmd_status() {
  kubectl --context "$CONTEXT" get nodes -L topology.kubernetes.io/zone
  kc get statefulsets,pods,jobs,pvc -o wide
}

cmd_down() {
  kind delete cluster --name "$CLUSTER"
}

command=${1:-}
[ $# -gt 0 ] && shift
case "$command" in
  up | build | deploy | collect | render | status | down) "cmd_$command" ;;
  run) cmd_run "$@" ;;
  all) cmd_up && cmd_build && cmd_run "$@" ;;
  *) usage; [ -z "$command" ] || exit 1 ;;
esac
