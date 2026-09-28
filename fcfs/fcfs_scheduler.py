"""Simulasi FCFS dengan VM seragam dan dataset task yang dapat diulang."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass
from math import ceil
from pathlib import Path
from typing import TYPE_CHECKING, List, Sequence

from workload import (
    DEFAULT_PROFILES,
    TaskProfile,
    generate_lengths,
    load_lengths,
    save_lengths,
    validate_profiles,
)

if TYPE_CHECKING:
    from PyCloudSim.entity import vContainer, vHost


@dataclass
class Vm:
    id: int
    mips: int = 250
    pes_number: int = 1
    ram: int = 512
    bandwidth: int = 1000
    size: int = 10000
    vmm: str = "Xen"
    datacenter_id: int = 0
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
        return self.actual_cpu_time


def create_datacenter(
    name: str, vm_count: int, vm_spec: Vm | None = None
) -> vHost:
    """Sediakan kapasitas satu host untuk seluruh VM pada datacenter ini."""
    from PyCloudSim.entity import vHost

    spec = vm_spec or Vm(id=0)
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


def create_vms(vm_count: int, datacenter_count: int = 1, **spec) -> List[Vm]:
    if type(vm_count) is not int or vm_count <= 0:
        raise ValueError("Jumlah VM harus bilangan bulat positif.")
    if type(datacenter_count) is not int or not 1 <= datacenter_count <= vm_count:
        raise ValueError("Setiap datacenter harus mendapat minimal satu VM.")
    template = Vm(id=0, **spec)
    for field in ("mips", "pes_number", "ram", "bandwidth", "size"):
        value = getattr(template, field)
        if type(value) is not int or value <= 0:
            raise ValueError(f"Spesifikasi VM {field} harus bilangan bulat positif.")
    if not isinstance(template.vmm, str) or not template.vmm.strip():
        raise ValueError("VMM harus berupa teks tidak kosong.")
    return [
        Vm(id=vm_id, datacenter_id=vm_id % datacenter_count, **spec)
        for vm_id in range(vm_count)
    ]


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


def create_cloudlets(
    cloudlet_count: int, profiles: Sequence[TaskProfile] = DEFAULT_PROFILES
) -> List[Cloudlet]:
    lengths = generate_lengths(cloudlet_count, profiles)
    return [
        Cloudlet(id=task_id, length=length)
        for task_id, length in enumerate(lengths, start=1)
    ]


def fcfs_schedule(cloudlets: List[Cloudlet], vm_list: List[Vm]) -> List[Cloudlet]:
    if not vm_list:
        raise ValueError("FCFS membutuhkan minimal satu VM.")
    for index, cloudlet in enumerate(cloudlets):
        # Urutan input FCFS; antrean tiap VM dilayani satu per satu.
        vm = vm_list[index % len(vm_list)]
        cloudlet.vm_id = vm.id
        cloudlet.resource_id = vm.datacenter_id
        cloudlet.status = "SUCCESS"
        cloudlet.start_time = max(cloudlet.submission_time, vm.available_at)
        execution_time = cloudlet.length / (vm.mips * vm.pes_number)
        cloudlet.finish_time = cloudlet.start_time + execution_time
        vm.available_at = cloudlet.finish_time
    return cloudlets


def calculate_makespan(cloudlets: List[Cloudlet]) -> float:
    return max((task.finish_time for task in cloudlets), default=0.0)


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


def _create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="FCFS: VM seragam, dataset deterministik."
    )
    parser.add_argument(
        "--config", type=Path, default=Path(__file__).with_name("config.json")
    )
    parser.add_argument("--tasks", type=int, help="Jumlah task, misalnya 1000 atau 2000.")
    parser.add_argument("--vms", type=int, help="Jumlah total VM di semua datacenter.")
    parser.add_argument("--datacenters", type=int, help="Jumlah datacenter, minimal 2.")
    parser.add_argument("--dataset", type=Path, help="CSV task; jumlah task mengikuti CSV.")
    parser.add_argument(
        "--interactive", action="store_true", help="Isi jumlah lewat prompt."
    )
    parser.add_argument("--output", type=Path, default=Path("results/python-fcfs"))
    parser.add_argument(
        "--show-tasks", action="store_true", help="Tampilkan seluruh tabel task."
    )
    return parser


def _load_configuration(path: Path) -> tuple[dict, tuple[TaskProfile, ...]]:
    """Validasi struktur konfigurasi sebelum menerima override pengguna."""
    config = json.loads(path.read_text(encoding="utf-8"))
    required_keys = {"tasks", "vms", "datacenters", "vm", "workload"}
    if not isinstance(config, dict) or set(config) != required_keys:
        raise ValueError("Config harus memuat tasks, vms, datacenters, vm, dan workload.")

    vm_keys = {"mips", "pes_number", "ram", "bandwidth", "size", "vmm"}
    if not isinstance(config["vm"], dict) or set(config["vm"]) != vm_keys:
        raise ValueError(
            "Config vm harus memuat mips, pes_number, ram, bandwidth, size, vmm."
        )
    if not isinstance(config["workload"], list):
        raise ValueError("Config workload harus berupa daftar profil task.")

    profiles = tuple(TaskProfile(**profile) for profile in config["workload"])
    validate_profiles(profiles)
    return config, profiles


def _apply_user_input(config: dict, args: argparse.Namespace) -> None:
    """Prioritas nilai: konfigurasi, argumen CLI, kemudian jawaban prompt."""
    for key in ("tasks", "vms", "datacenters"):
        override = getattr(args, key)
        if override is not None:
            config[key] = override

    if args.dataset and args.tasks is not None:
        raise ValueError("Gunakan --dataset atau --tasks; jumlah task mengikuti CSV.")
    if not args.interactive:
        return

    prompts = (("tasks", "task"), ("vms", "VM"), ("datacenters", "datacenter"))
    for key, label in prompts:
        if key == "tasks" and args.dataset:
            continue
        answer = input(f"Jumlah {label} [{config[key]}]: ").strip()
        if answer:
            config[key] = int(answer)


def parse_arguments(argv: Sequence[str] | None = None):
    parser = _create_argument_parser()
    args = parser.parse_args(argv)
    try:
        config, profiles = _load_configuration(args.config)
        _apply_user_input(config, args)

        datacenter_count = config["datacenters"]
        if type(datacenter_count) is not int or datacenter_count < 2:
            raise ValueError("Jumlah datacenter minimal 2.")
        vms = create_vms(config["vms"], datacenter_count, **config["vm"])

        if args.dataset:
            lengths = load_lengths(args.dataset)
            config["tasks"] = len(lengths)
            tasks = [
                Cloudlet(id=task_id, length=length)
                for task_id, length in enumerate(lengths, start=1)
            ]
        else:
            task_count = config["tasks"]
            if type(task_count) is not int or task_count <= 0:
                raise ValueError("Jumlah task harus bilangan bulat positif.")
            tasks = create_cloudlets(task_count, profiles)
    except (OSError, ValueError, TypeError, KeyError, EOFError) as error:
        parser.error(str(error))
    return args, config, vms, tasks


def _write_csv(path: Path, rows: List[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(
            destination, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _build_summary(
    config: dict,
    vms: List[Vm],
    tasks: List[Cloudlet],
    dataset_source: Path | None,
) -> dict:
    task_count = len(tasks)
    length_counts = Counter(task.length for task in tasks)
    vm_counts = Counter(vm.datacenter_id for vm in vms)
    distribution = [
        {
            "length_mi": length,
            "tasks": count,
            "percentage": 100 * count / task_count,
        }
        for length, count in sorted(length_counts.items())
    ]
    return {
        "algorithm": "FCFS",
        "datacenters": config["datacenters"],
        "vms": len(vms),
        "tasks": task_count,
        "completed": sum(task.status == "SUCCESS" for task in tasks),
        "makespan_s": calculate_makespan(tasks),
        "mean_waiting_time_s": sum(task.waiting_time for task in tasks) / task_count,
        "dataset_source": str(dataset_source) if dataset_source else "profile",
        "distribution": distribution,
        "vm_distribution": {
            str(datacenter_id): vm_counts[datacenter_id]
            for datacenter_id in range(config["datacenters"])
        },
    }


def save_results(
    output: Path,
    config: dict,
    vms: List[Vm],
    tasks: List[Cloudlet],
    dataset_source: Path | None,
) -> None:
    """Simpan input efektif dan hasil agar percobaan mudah diperiksa dan diulang."""
    output.mkdir(parents=True, exist_ok=True)
    save_lengths(output / "dataset.csv", [task.length for task in tasks])
    (output / "config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(output / "vms.csv", [asdict(vm) for vm in vms])

    task_rows = []
    for task in tasks:
        row = asdict(task)
        row.update(
            waiting_time=task.waiting_time,
            execution_time=task.execution_time,
            response_time=task.response_time,
        )
        task_rows.append(row)
    _write_csv(output / "results.csv", task_rows)

    summary = _build_summary(config, vms, tasks, dataset_source)
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> None:
    args, config, vms, tasks = parse_arguments(argv)
    print(
        f"FCFS: {len(tasks)} task, {len(vms)} VM seragam, "
        f"{config['datacenters']} datacenter.",
        flush=True,
    )
    allocate_infrastructure(vms, config["datacenters"])
    fcfs_schedule(tasks, vms)
    save_results(args.output, config, vms, tasks, args.dataset)
    for length, count in sorted(Counter(task.length for task in tasks).items()):
        print(f"{length:,} MI: {count} task ({100 * count / len(tasks):.2f}%)")
    if args.show_tasks:
        print_cloudlet_list(tasks)
    print(f"Makespan FCFS: {calculate_makespan(tasks):.2f} s")
    print(f"Dataset, konfigurasi, dan hasil tersimpan di: {args.output.resolve()}")


if __name__ == "__main__":
    main()
