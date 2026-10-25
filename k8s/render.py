"""Render manifest Kubernetes dari fcfs/config.json, sumber tunggal alokasi.

    python3 k8s/render.py kind  fcfs/config.json   # cluster kind: 1 node per datacenter
    python3 k8s/render.py vms   fcfs/config.json   # Service + StatefulSet per datacenter
    python3 k8s/render.py shape fcfs/config.json   # "tasks vms datacenters"

Validasi config dan pembagian VM ke datacenter memakai kode yang sama dengan
simulasi (parse_arguments dan create_vms di fcfs_scheduler.py).
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from string import Template

K8S = Path(__file__).resolve().parent
sys.path.insert(0, str(K8S.parent / "fcfs"))

from fcfs_scheduler import parse_arguments  # noqa: E402


def render_kind(config: dict) -> str:
    """Node worker = host datacenter; label zone dipakai nodeSelector VM."""
    lines = [
        "# Dibuat oleh k8s/render.py dari config.json: satu node worker per datacenter.",
        "kind: Cluster",
        "apiVersion: kind.x-k8s.io/v1alpha4",
        "nodes:",
        "  - role: control-plane",
    ]
    for datacenter_id in range(config["datacenters"]):
        lines += [
            "  - role: worker",
            "    labels:",
            f"      topology.kubernetes.io/zone: dc-{datacenter_id}",
        ]
    return "\n".join(lines) + "\n"


def render_vms(config: dict, vms: list) -> str:
    template = Template((K8S / "templates" / "vm-datacenter.yaml").read_text(encoding="utf-8"))
    counts = Counter(vm.datacenter_id for vm in vms)
    spec = config["vm"]
    return "---\n".join(
        template.substitute(
            DATACENTER_ID=datacenter_id,
            DATACENTERS=config["datacenters"],
            REPLICAS=counts[datacenter_id],
            CPU_MILLICORES=spec["mips"] * spec["pes_number"],
            MEMORY_MIB=spec["ram"],
        )
        for datacenter_id in range(config["datacenters"])
    )


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] not in ("kind", "vms", "shape"):
        sys.exit("Pemakaian: render.py kind|vms|shape <config.json>")
    command, path = argv
    _, config, vms, _ = parse_arguments(["--config", path])
    if command == "kind":
        print(render_kind(config), end="")
    elif command == "vms":
        print(render_vms(config, vms), end="")
    else:
        print(config["tasks"], len(vms), config["datacenters"])


if __name__ == "__main__":
    main()
