from dataclasses import dataclass
from typing import List

from PyCloudSim import simulation
from PyCloudSim.entity import vContainer, vHost
from PyCloudSim.scheduler import DefaultContainerScheduler


CLOUDLET_LENGTH_DELTAS = (
    0,
    -30000,
    -65000,
    -4000,
    2000,
    7000,
    80000,
    10000,
    -85000,
    -14000,
    1000,
    2000,
    16000,
    5000,
    55000,
)


@dataclass
class Vm:
    id: int
    mips: int = 250
    pes_number: int = 1
    ram: int = 512
    bandwidth: int = 1000
    size: int = 10000
    vmm: str = "Xen"
    available_at: float = 0.0


@dataclass
class Cloudlet:
    id: int
    length: int
    pes_number: int = 1
    file_size: int = 3000
    output_size: int = 300
    submission_time: float = 0.0
    resource_id: int = 0
    vm_id: int = -1
    status: str = "CREATED"
    start_time: float = 0.0
    finish_time: float = 0.0

    @property
    def actual_cpu_time(self) -> float:
        return self.finish_time - self.start_time

    @property
    def waiting_time(self) -> float:
        return self.start_time - self.submission_time

    @property
    def response_time(self) -> float:
        return self.finish_time - self.submission_time

    @property
    def execution_time(self) -> float:
        return self.finish_time - self.start_time


def create_datacenter(name: str, vm_count: int) -> vHost:
    datacenter = vHost(
        ipc=1,
        frequency=250,
        num_cores=vm_count,
        cpu_tdps=150,
        cpu_mode=1,
        ram=8,
        rom=64,
        label=name,
        create_at=0,
    )
    datacenter.power_on(0)
    return datacenter


def create_vms(vm_count: int) -> List[Vm]:
    if vm_count <= 0:
        raise ValueError("Jumlah VM harus lebih dari 0.")
    return [Vm(id=vm_id) for vm_id in range(vm_count)]


def create_vm_containers(vm_list: List[Vm]) -> List[vContainer]:
    return [
        vContainer(
            cpu=vm.mips,
            cpu_limit=vm.mips,
            ram=vm.ram,
            ram_limit=vm.ram,
            image_size=vm.size,
            label=f"VM_{vm.id}",
            create_at=0,
        )
        for vm in vm_list
    ]


def create_cloudlets(cloudlet_count: int) -> List[Cloudlet]:
    if cloudlet_count < 0:
        raise ValueError("Jumlah cloudlet tidak boleh negatif.")
    if cloudlet_count > len(CLOUDLET_LENGTH_DELTAS):
        raise ValueError(
            f"Data panjang hanya tersedia untuk {len(CLOUDLET_LENGTH_DELTAS)} cloudlet."
        )

    length = 100000
    cloudlets = []
    for cloudlet_id, delta in enumerate(
        CLOUDLET_LENGTH_DELTAS[:cloudlet_count]
    ):
        length += delta
        cloudlets.append(Cloudlet(id=cloudlet_id, length=length))
    return cloudlets


def fcfs_schedule(
    cloudlets: List[Cloudlet], vm_list: List[Vm]
) -> List[Cloudlet]:
    if not vm_list:
        raise ValueError("FCFS membutuhkan minimal satu VM.")

    for index, cloudlet in enumerate(cloudlets):
        # Cloudlets are accepted in submission order and VMs are chosen round-robin.
        vm = vm_list[index % len(vm_list)]
        cloudlet.vm_id = vm.id
        cloudlet.resource_id = 0
        cloudlet.status = "SUCCESS"
        cloudlet.start_time = max(cloudlet.submission_time, vm.available_at)
        cloudlet.finish_time = cloudlet.start_time + (
            cloudlet.length / (vm.mips * vm.pes_number)
        )
        vm.available_at = cloudlet.finish_time

    return cloudlets


def calculate_makespan(cloudlets: List[Cloudlet]) -> float:
    return max((cloudlet.finish_time for cloudlet in cloudlets), default=0.0)


def print_cloudlet_list(cloudlets: List[Cloudlet]) -> None:
    headers = (
        "Cloudlet ID",
        "STATUS",
        "Length",
        "Data center ID",
        "VM ID",
        "Time",
        "Start Time",
        "Finish Time",
        "Waiting Time",
        "Response Time",
        "Execution Time",
    )
    row_format = (
        "{:<12} {:<8} {:<10} {:<15} {:<7} {:<10} "
        "{:<12} {:<13} {:<13} {:<14} {:<14}"
    )

    print("\n========== OUTPUT ==========")
    print(row_format.format(*headers))
    for cloudlet in cloudlets:
        if cloudlet.status != "SUCCESS":
            continue
        print(
            row_format.format(
                cloudlet.id,
                cloudlet.status,
                cloudlet.length,
                cloudlet.resource_id,
                cloudlet.vm_id,
                f"{cloudlet.actual_cpu_time:.2f}",
                f"{cloudlet.start_time:.2f}",
                f"{cloudlet.finish_time:.2f}",
                f"{cloudlet.waiting_time:.2f}",
                f"{cloudlet.response_time:.2f}",
                f"{cloudlet.execution_time:.2f}",
            )
        )

    print(f"Makespan using FCFS: {calculate_makespan(cloudlets):.2f}")


def main() -> None:
    print("Starting FCFS Scheduler...", flush=True)

    vm_count = 6
    cloudlet_count = 15

    create_datacenter("Datacenter_0", vm_count)
    vm_list = create_vms(vm_count)
    for vm in vm_list:
        print(vm.size)

    DefaultContainerScheduler()
    containers = create_vm_containers(vm_list)

    simulation.debug(False)
    simulation.simulate(until=0)
    if not all(container.scheduled for container in containers):
        raise RuntimeError("Tidak semua VM container berhasil dialokasikan.")

    cloudlets = fcfs_schedule(create_cloudlets(cloudlet_count), vm_list)
    print_cloudlet_list(cloudlets)
    print("FCFS_Scheduler finished!")


if __name__ == "__main__":
    main()
