from dataclasses import dataclass
from typing import List
from PyCloudSim import simulation
from PyCloudSim.entity import vContainer, vHost
from PyCloudSim.scheduler import DefaultContainerScheduler

@dataclass
class Vm:
    id: int
    mips: int = 250
    pes_number: int =1
    ram: int = 512
    bw: int=1000
    size: int=10000
    vmm:str="Xen"
    available_at:float =0.0

@dataclass
class Cloudlet:
    id:int
    length: int
    pes_number: int=1
    file_size:int = 3000
    output_size: int=300
    submission_time: float=0.0 # By default setup 0
    resource_id: int=0
    vm_id:int =-1
    status:str="Created"
    start_time:float = 0.0
    finish_time:float =0.0
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

def create_datacenter(name: str,vm_count:int) -> vHost:
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

def create_vms(vms: int) -> List[Vm]:
    vm_list = []
    for i in range(vms):
        vm = Vm(id=i)
        vm_list.append(vm)
        print(vm.size)
    return vm_list

def create_vm_containers(vm_list: List[Vm]) -> List[vContainer]:
    containers = []
    for vm in vm_list:
        container= vContainer(
            cpu=vm.mips,
            cpu_limit=vm.mips,
            ram=vm.ram,
            ram_limit=vm.ram,
            image_size=vm.size,
            label=f"VM_{vm.id}",
            create_at=0,
        )
        containers.append(container)
    return containers

def create_cloudlets(cloudlets: int) -> List[Cloudlet]:
    length = 100000
    deltas = {
        0: 0,
        1: -30000,
        2: -65000,
        3: -4000,
        4: 2000,
        5: 7000,
        6: 80000,
        7: 10000,
        8: -85000,
        9: -14000,
        10: 1000,
        11: 2000,
        12: 16000,
        13: 5000,
        14: 55000,
    }
    cloudlet_list = []
    for i in range(cloudlets):
        length+= deltas.get(i,0)
        cloudlet_list.append(Cloudlet(id=i,length=length))
    return cloudlet_list


def fcfs_schedule(cloudlets: List[Cloudlet], vm_list: List[Vm]) -> List[Cloudlet]:
    for i, cloudlet in enumerate(cloudlets):
        # FCFS in submit order; distribute tasks to VM 0..5 repeatedly.
        vm = vm_list[i % len(vm_list)]

        cloudlet.vm_id = vm.id
        cloudlet.resource_id = 0
        cloudlet.status = "SUCCESS"
        cloudlet.start_time = max(cloudlet.submission_time, vm.available_at)

        runtime = cloudlet.length / (vm.mips * vm.pes_number)
        cloudlet.finish_time = cloudlet.start_time + runtime

        vm.available_at = cloudlet.finish_time

    return cloudlets


def fmt(value: float) -> str:
    return f"{value:05.2f}"


def print_cloudlet_list(cloudlets: List[Cloudlet]) -> None:
    indent = "    "
    print()
    print("========== Output ==========")
    print(
        "Cloudlet ID" + indent +
        "STATUS" + indent +
        "Length" + indent +
        "Data center ID" + indent +
        "VM ID" + indent + indent +
        "Time" + indent +
        "Start Time" + indent +
        "Finish Time" + indent +
        "Waiting Time" + indent +
        "Response Time" + indent +
        "Execution Time"
    )

    for cloudlet in cloudlets:
        if cloudlet.status == "SUCCESS":
            print(
                indent + fmt(cloudlet.id) + indent + indent +
                "SUCCESS" +
                indent + indent + fmt(cloudlet.length) +
                indent + indent + fmt(cloudlet.resource_id) +
                indent + indent + indent + fmt(cloudlet.vm_id) +
                indent + indent + fmt(cloudlet.actual_cpu_time) +
                indent + indent + fmt(cloudlet.start_time) +
                indent + indent + indent + fmt(cloudlet.finish_time) +
                indent + indent + indent + fmt(cloudlet.waiting_time) +
                indent + indent + indent + fmt(cloudlet.response_time) +
                indent + indent + indent + fmt(cloudlet.execution_time)
            )

    makespan = max(c.finish_time for c in cloudlets)
    print(f"Makespan using FCFS: {makespan}")


def main() -> None:
    print("Starting FCFS Scheduler...")

    vm_count = 6
    cloudlet_count = 15

    datacenter = create_datacenter("Datacenter_0", vm_count)
    vm_list = create_vms(vm_count)
    DefaultContainerScheduler()
    containers = create_vm_containers(vm_list)

    # Process entity creation and let PyCloudSim allocate each container.
    simulation.debug(False)
    simulation.simulate(until=0)
    if not all(container.scheduled for container in containers):
        raise RuntimeError("Tidak semua VM container berhasil dialokasikan.")

    cloudlet_list = create_cloudlets(cloudlet_count)
    finished_cloudlets = fcfs_schedule(cloudlet_list, vm_list)

    print_cloudlet_list(finished_cloudlets)
    print("FCFS_Scheduler finished!")


if __name__ == "__main__":
    main()
