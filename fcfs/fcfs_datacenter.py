"""Infrastruktur datacenter sesuai spesifikasi VM dari config.json.

File ini juga dapat dijalankan langsung dengan argumen CLI scheduler yang sama.
"""

from __future__ import annotations

from collections import Counter
from math import ceil
from typing import TYPE_CHECKING, List, Sequence

if TYPE_CHECKING:
    from PyCloudSim.entity import vContainer, vHost
    from fcfs_scheduler import Vm


def create_datacenter(
    name: str, vm_count: int, vm_spec: Vm
) -> vHost:
    """Sediakan kapasitas satu host untuk seluruh VM pada datacenter ini."""
    from PyCloudSim.entity import vHost

    spec = vm_spec
    host = vHost(
        ipc=1,
        frequency=spec.mips,
        num_cores=vm_count * spec.pes_number,
        cpu_tdps=150,
        cpu_mode=1,
        ram=max(1, ceil(vm_count * spec.ram / 1024)),
        rom=max(1, ceil(vm_count * spec.size / 1024)),
        label=name,
        create_at=0,
    )
    host.power_on(0)
    return host


def create_vm_containers(vm_list: List[Vm]) -> List[vContainer]:
    from PyCloudSim.entity import vContainer

    containers = []
    for vm in vm_list:
        # PyCloudSim memakai millicore: 1000 = satu core penuh.
        cpu_millicores = 1000 * vm.pes_number
        container = vContainer(
            cpu=cpu_millicores,
            cpu_limit=cpu_millicores,
            ram=vm.ram,
            ram_limit=vm.ram,
            image_size=vm.size,
            label=f"VM_{vm.id}",
            create_at=0,
        )
        containers.append(container)
    return containers


def allocate_infrastructure(vm_list: List[Vm], datacenter_count: int) -> None:
    from PyCloudSim import simulation
    from PyCloudSim.scheduler import DefaultContainerScheduler

    # Satu host mewakili kapasitas tiap datacenter pada model sederhana ini.
    vm_counts = Counter(vm.datacenter_id for vm in vm_list)
    hosts = []
    for datacenter_id in range(datacenter_count):
        host = create_datacenter(
            name=f"Datacenter_{datacenter_id}",
            vm_count=vm_counts[datacenter_id],
            vm_spec=vm_list[0],
        )
        hosts.append(host)
    placement = {f"VM_{vm.id}": hosts[vm.datacenter_id] for vm in vm_list}

    class DatacenterScheduler(DefaultContainerScheduler):
        def find_host(self, container):
            host = placement[container.label]
            if (
                host.powered_on
                and host.cpu_reservoir.amount >= container.cpu
                and host.ram_reservoir.amount >= container.ram
                and host.rom_reservoir.amount >= container.image_size
            ):
                return host
            return None

    DatacenterScheduler()
    containers = create_vm_containers(vm_list)
    simulation.debug(False)
    simulation.simulate(until=0)
    if not all(container.scheduled for container in containers):
        raise RuntimeError("Tidak semua VM container berhasil dialokasikan.")
    for vm, container in zip(vm_list, containers):
        if container.host is not hosts[vm.datacenter_id]:
            raise RuntimeError("Penempatan VM tidak sesuai datacenter yang ditentukan.")


def main(argv: Sequence[str] | None = None) -> None:
    from fcfs_scheduler import main as run_scheduler

    run_scheduler(argv)


if __name__ == "__main__":
    main()
