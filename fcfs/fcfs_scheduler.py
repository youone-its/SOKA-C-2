"""Simulasi FCFS dengan VM seragam dan dataset task yang dapat diulang."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from math import isfinite
from pathlib import Path
from typing import List, Sequence

from fcfs_datacenter import allocate_infrastructure, create_datacenter, create_vm_containers
from workload import (
    TaskProfile,
    generate_lengths,
    load_lengths,
    save_lengths,
    validate_profiles,
)


@dataclass
class Vm:
    id: int
    mips: int
    pes_number: int
    ram: int
    bandwidth: int
    size: int
    vmm: str
    datacenter_id: int
    available_at: float = field(default=0.0, init=False)


@dataclass
class Cloudlet:
    id: int
    length: int
    pes_number: int
    file_size: int
    output_size: int
    submission_time: float
    resource_id: int = field(default=-1, init=False)
    vm_id: int = field(default=-1, init=False)
    status: str = field(default="CREATED", init=False)
    start_time: float = field(default=0.0, init=False)
    finish_time: float = field(default=0.0, init=False)

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


def create_vms(vm_count: int, datacenter_count: int, **spec) -> List[Vm]:
    if type(vm_count) is not int or vm_count <= 0:
        raise ValueError("Jumlah VM harus bilangan bulat positif.")
    if type(datacenter_count) is not int or not 1 <= datacenter_count <= vm_count:
        raise ValueError("Setiap datacenter harus mendapat minimal satu VM.")
    template = Vm(id=0, datacenter_id=0, **spec)
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


def create_cloudlets(
    cloudlet_count: int, profiles: Sequence[TaskProfile], **spec
) -> List[Cloudlet]:
    lengths = generate_lengths(cloudlet_count, profiles)
    return [
        Cloudlet(id=task_id, length=length, **spec)
        for task_id, length in enumerate(lengths, start=1)
    ]


def fcfs_schedule(cloudlets: List[Cloudlet], vm_list: List[Vm]) -> List[Cloudlet]:
    if not vm_list:
        raise ValueError("FCFS membutuhkan minimal satu VM.")
    if any(task.pes_number > vm_list[index % len(vm_list)].pes_number
           for index, task in enumerate(cloudlets)):
        raise ValueError("PE task tidak boleh melebihi PE VM yang dituju.")
    for index, cloudlet in enumerate(cloudlets):
        # Urutan input FCFS; antrean tiap VM dilayani satu per satu.
        vm = vm_list[index % len(vm_list)]
        cloudlet.vm_id = vm.id
        cloudlet.resource_id = vm.datacenter_id
        cloudlet.status = "SUCCESS"
        cloudlet.start_time = max(cloudlet.submission_time, vm.available_at)
        execution_time = cloudlet.length / (vm.mips * cloudlet.pes_number)
        cloudlet.finish_time = cloudlet.start_time + execution_time
        vm.available_at = cloudlet.finish_time
    return cloudlets


def calculate_makespan(cloudlets: List[Cloudlet]) -> float:
    return max((task.finish_time for task in cloudlets), default=0.0)


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
    required_keys = {"tasks", "vms", "datacenters", "vm", "cloudlet", "workload"}
    if not isinstance(config, dict) or set(config) != required_keys:
        raise ValueError("Config harus memuat tasks, vms, datacenters, vm, cloudlet, dan workload.")

    vm_keys = {"mips", "pes_number", "ram", "bandwidth", "size", "vmm"}
    if not isinstance(config["vm"], dict) or set(config["vm"]) != vm_keys:
        raise ValueError(
            "Config vm harus memuat mips, pes_number, ram, bandwidth, size, vmm."
        )
    if not isinstance(config["workload"], list):
        raise ValueError("Config workload harus berupa daftar profil task.")

    cloudlet_keys = {"pes_number", "file_size", "output_size", "submission_time"}
    spec = config["cloudlet"]
    if not isinstance(spec, dict) or set(spec) != cloudlet_keys:
        raise ValueError("Config cloudlet harus memuat pes_number, file_size, output_size, submission_time.")
    if type(spec["pes_number"]) is not int or spec["pes_number"] <= 0:
        raise ValueError("PE cloudlet harus bilangan bulat positif.")
    for key in ("file_size", "output_size"):
        if type(spec[key]) is not int or spec[key] < 0:
            raise ValueError(f"Cloudlet {key} harus bilangan bulat nonnegatif.")
    arrival = spec["submission_time"]
    if type(arrival) not in (int, float) or not isfinite(arrival) or arrival < 0:
        raise ValueError("Submission time harus angka nonnegatif dan finite.")

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
        if config["cloudlet"]["pes_number"] > config["vm"]["pes_number"]:
            raise ValueError("PE cloudlet tidak boleh melebihi PE VM.")

        if args.dataset:
            lengths = load_lengths(args.dataset)
            config["tasks"] = len(lengths)
            tasks = [
                Cloudlet(id=task_id, length=length, **config["cloudlet"])
                for task_id, length in enumerate(lengths, start=1)
            ]
        else:
            task_count = config["tasks"]
            if type(task_count) is not int or task_count <= 0:
                raise ValueError("Jumlah task harus bilangan bulat positif.")
            tasks = create_cloudlets(task_count, profiles, **config["cloudlet"])
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
    makespan = calculate_makespan(tasks)
    busy_times = Counter()
    task_counts = Counter()
    for task in tasks:
        busy_times[task.vm_id] += task.execution_time
        task_counts[task.vm_id] += 1
    vm_metrics = [
        {
            "vm_id": vm.id,
            "datacenter_id": vm.datacenter_id,
            "tasks": task_counts[vm.id],
            "busy_time_s": busy_times[vm.id],
            "idle_time_s": makespan - busy_times[vm.id],
            "utilization_pct": 100 * busy_times[vm.id] / makespan,
        }
        for vm in vms
    ]
    datacenter_metrics = []
    for datacenter_id in range(config["datacenters"]):
        members = [vm for vm in vm_metrics if vm["datacenter_id"] == datacenter_id]
        count = sum(vm["tasks"] for vm in members)
        datacenter_metrics.append({
            "datacenter_id": datacenter_id,
            "vms": len(members),
            "tasks": count,
            "throughput_tasks_per_s": count / makespan,
            "utilization_pct": sum(vm["utilization_pct"] for vm in members) / len(members),
        })
    return {
        "algorithm": "FCFS",
        "datacenters": config["datacenters"],
        "vms": len(vms),
        "tasks": task_count,
        "completed": sum(task.status == "SUCCESS" for task in tasks),
        "makespan_s": makespan,
        "mean_waiting_time_s": sum(task.waiting_time for task in tasks) / task_count,
        "mean_response_time_s": sum(task.response_time for task in tasks) / task_count,
        "mean_execution_time_s": sum(task.execution_time for task in tasks) / task_count,
        "throughput_tasks_per_s": task_count / makespan,
        "utilization_pct": 100 * sum(busy_times.values()) / (len(vms) * makespan),
        "vm_metrics": vm_metrics,
        "datacenter_metrics": datacenter_metrics,
        "dataset_source": str(dataset_source) if dataset_source else "profile",
        "distribution": distribution,
        "vm_distribution": {
            str(datacenter_id): vm_counts[datacenter_id]
            for datacenter_id in range(config["datacenters"])
        },
    }


def plot_metrics(output: Path, summary: dict, tasks: List[Cloudlet]) -> None:
    """Buat grafik dari hasil run ini; tidak memerlukan jendela GUI."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(14, 9), facecolor="#f5f7fb", layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots(2, 2)
    figure.suptitle(
        f"FCFS | {summary['tasks']:,} task | {summary['vms']} VM | "
        f"{summary['datacenters']} datacenter\n"
        f"Makespan: {summary['makespan_s']:,.2f} s   |   "
        f"Throughput: {summary['throughput_tasks_per_s']:.5f} task/s   |   "
        f"Utilisasi: {summary['utilization_pct']:.2f}%",
        fontsize=15,
    )

    averages = [summary[f"mean_{metric}_time_s"]
                for metric in ("waiting", "response", "execution")]
    bars = axes[0, 0].bar(
        ["Waiting", "Response", "Execution"], averages,
        color=["#d78b26", "#3168ad", "#278578"],
    )
    axes[0, 0].bar_label(bars, labels=[f"{value:,.2f}" for value in averages], padding=4)
    axes[0, 0].set(title="Rata-rata waktu task", ylabel="Waktu (s)")
    axes[0, 0].margins(y=0.15)

    task_ids = [task.id for task in tasks]
    for metric, label, color in (
        ("waiting_time", "Waiting", "#d78b26"),
        ("response_time", "Response", "#3168ad"),
        ("execution_time", "Execution", "#278578"),
    ):
        axes[0, 1].plot(task_ids, [getattr(task, metric) for task in tasks],
                        label=label, color=color, linewidth=1)
    axes[0, 1].set(title="Waktu setiap task (urutan FCFS)", xlabel="Task ID", ylabel="Waktu (s)")
    axes[0, 1].legend()

    vm_metrics = summary["vm_metrics"]
    vm_labels = [f"VM {vm['vm_id']}\nDC {vm['datacenter_id']}" for vm in vm_metrics]
    busy = [vm["busy_time_s"] for vm in vm_metrics]
    axes[1, 0].bar(vm_labels, busy, label="Busy", color="#3168ad")
    axes[1, 0].bar(vm_labels, [vm["idle_time_s"] for vm in vm_metrics],
                   bottom=busy, label="Idle", color="#d8dfe9")
    axes[1, 0].set(title="Waktu busy dan idle per VM", ylabel="Waktu (s)")
    axes[1, 0].legend()
    if len(vm_metrics) > 12:
        axes[1, 0].tick_params(axis="x", labelsize=7, labelrotation=90)

    dc_metrics = summary["datacenter_metrics"]
    bars = axes[1, 1].bar(
        [f"DC {dc['datacenter_id']}" for dc in dc_metrics],
        [dc["utilization_pct"] for dc in dc_metrics], color="#278578",
    )
    axes[1, 1].bar_label(
        bars, labels=[f"{dc['utilization_pct']:.2f}%\n{dc['tasks']:,} task" for dc in dc_metrics],
        padding=4,
    )
    axes[1, 1].set(title="Utilisasi tiap datacenter", ylabel="Utilisasi (%)", ylim=(0, 120))
    for axis in axes.flat:
        axis.set_axisbelow(True)
        axis.grid(axis="y", alpha=0.2)
        axis.spines[["top", "right"]].set_visible(False)
    figure.savefig(output / "metrics.png", dpi=160)


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
    _write_csv(output / "vm_metrics.csv", summary["vm_metrics"])
    _write_csv(output / "datacenter_metrics.csv", summary["datacenter_metrics"])
    plot_metrics(output, summary, tasks)


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
    print(f"Grafik metrik: {(args.output / 'metrics.png').resolve()}")


if __name__ == "__main__":
    main()
