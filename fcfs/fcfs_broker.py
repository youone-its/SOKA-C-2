"""Broker FCFS untuk VM nyata: task dikirim lewat HTTP ke pod Kubernetes.

Config, dataset, pembagian task ke VM, dan format hasil sama dengan
fcfs_scheduler.py, sehingga hasil simulasi dan hasil cluster dapat dibandingkan.
Waktu start/finish diukur oleh broker; waktu eksekusi murni dan CPU time
dilaporkan oleh VM.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import List, Sequence

from fcfs_scheduler import (
    Cloudlet,
    Vm,
    _build_summary,
    _create_argument_parser,
    _write_csv,
    calculate_makespan,
    fcfs_schedule,
    parse_arguments,
    print_cloudlet_list,
    save_results,
)

# Pod StatefulSet fcfs-vm-dc<D>-<i> di balik headless Service fcfs-vm-dc<D>.
DEFAULT_ENDPOINT = "http://fcfs-vm-dc{datacenter_id}-{index}.fcfs-vm-dc{datacenter_id}:8080"

# Prediksi simulasi dalam detik nyata: waktu dibagi speedup, throughput dikali.
COMPARED_METRICS = (
    ("makespan_s", "Makespan", -1),
    ("mean_waiting_time_s", "Rata-rata waiting", -1),
    ("mean_response_time_s", "Rata-rata response", -1),
    ("mean_execution_time_s", "Rata-rata eksekusi", -1),
    ("throughput_tasks_per_s", "Throughput", 1),
    ("utilization_pct", "Utilisasi", 0),
)

# Token warna grafik (palet tervalidasi skill dataviz, mode terang).
SURFACE, INK, INK_2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE = "#e1e0d9", "#c3c2b7"
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100",
          "#e87ba4", "#008300", "#6250d6", "#e34948")
# Ramp ordinal biru (terang = task pendek, gelap = task panjang).
LENGTH_STEPS = {
    1: ("#2a78d6",),
    2: ("#86b6ef", "#184f95"),
    3: ("#86b6ef", "#2a78d6", "#104281"),
    4: ("#86b6ef", "#3987e5", "#1c5cab", "#0d366b"),
}


def vm_endpoints(
    vms: List[Vm],
    datacenter_count: int,
    template: str = DEFAULT_ENDPOINT,
    explicit: Sequence[str] | None = None,
) -> List[str]:
    if explicit:
        if len(explicit) != len(vms):
            raise ValueError(f"--endpoints memuat {len(explicit)} URL untuk {len(vms)} VM.")
        return [url.rstrip("/") for url in explicit]
    return [
        template.format(
            vm_id=vm.id, datacenter_id=vm.datacenter_id, index=vm.id // datacenter_count
        )
        for vm in vms
    ]


def request_json(url: str, payload: dict | None = None, timeout: float = 30,
                 retries: int = 3) -> dict:
    """Request JSON dengan retry untuk gangguan jaringan sementara."""
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"{url}: HTTP {error.code} {error.read().decode()}") from error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if attempt == retries - 1:
                raise ConnectionError(f"{url}: {error}") from error
            time.sleep(1 + attempt)
    raise AssertionError("unreachable")


def check_vms(vms: List[Vm], endpoints: List[str], timeout: float) -> List[dict]:
    """Pastikan setiap endpoint adalah VM yang dimaksud sebelum eksperimen dimulai."""
    placement = []
    for vm, url in zip(vms, endpoints):
        try:
            info = request_json(f"{url}/info", timeout=timeout, retries=5)
        except ConnectionError as error:
            raise ConnectionError(
                f"{error}. Pastikan VM {vm.id} berjalan: jumlah pod VM harus sama "
                "dengan `vms` di config (k8s/fcfs-k8s.sh deploy)."
            ) from error
        if (info["vm_id"], info["datacenter_id"]) != (vm.id, vm.datacenter_id):
            raise RuntimeError(
                f"{url} adalah VM {info['vm_id']} DC {info['datacenter_id']}, "
                f"seharusnya VM {vm.id} DC {vm.datacenter_id}."
            )
        # Pod dirender dari config yang sama (1 MIPS = 1 millicore), jadi harus cocok.
        limit = info["cpu_limit_millicores"]
        if limit is not None and limit != vm.mips * vm.pes_number:
            raise RuntimeError(
                f"VM {vm.id} dibatasi {limit}m CPU, config mengharapkan "
                f"{vm.mips * vm.pes_number}m. Jalankan ulang k8s/fcfs-k8s.sh deploy."
            )
        memory = info["memory_limit_mib"]
        if memory is not None and memory != vm.ram:
            raise RuntimeError(
                f"VM {vm.id} dibatasi {memory} MiB memori, config mengharapkan "
                f"{vm.ram} MiB. Jalankan ulang k8s/fcfs-k8s.sh deploy."
            )
        placement.append({
            "vm_id": vm.id,
            "datacenter_id": vm.datacenter_id,
            "endpoint": url,
            "pod": info["pod"],
            "node": info["node"],
            "cpu_limit_millicores": limit,
            "memory_limit_mib": info["memory_limit_mib"],
        })
    return placement


def run_fcfs(
    tasks: List[Cloudlet],
    vms: List[Vm],
    endpoints: List[str],
    work_per_mi: int,
    timeout: float,
) -> List[dict]:
    """Eksekusi FCFS di VM nyata dengan pembagian task yang sama seperti fcfs_schedule."""
    queues = {vm.id: [] for vm in vms}
    for index, task in enumerate(tasks):
        queues[vms[index % len(vms)].id].append(task)

    stop = threading.Event()
    origin = time.perf_counter()

    def serve(vm: Vm, url: str) -> List[dict]:
        records = []
        try:
            for task in queues[vm.id]:
                if stop.is_set():
                    break
                delay = task.submission_time - (time.perf_counter() - origin)
                if delay > 0:
                    time.sleep(delay)
                # Antrean VM dilayani satu per satu: task berikut dikirim setelah selesai.
                start = time.perf_counter() - origin
                reply = request_json(f"{url}/execute", {
                    "task_id": task.id,
                    "length_mi": task.length,
                    "iterations": task.length * work_per_mi,
                }, timeout=timeout)
                task.finish_time = time.perf_counter() - origin
                task.start_time = start
                task.vm_id, task.resource_id, task.status = vm.id, vm.datacenter_id, "SUCCESS"
                vm.available_at = task.finish_time
                records.append({
                    "task_id": task.id,
                    "vm_id": vm.id,
                    "length_mi": task.length,
                    "worker_exec_time_s": reply["exec_time_s"],
                    "worker_cpu_time_s": reply["cpu_time_s"],
                    "overhead_s": task.execution_time - reply["exec_time_s"],
                })
        except Exception:
            stop.set()
            raise
        return records

    with ThreadPoolExecutor(max_workers=len(vms)) as pool:
        futures = [pool.submit(serve, vm, url) for vm, url in zip(vms, endpoints)]
        records = [record for future in futures for record in future.result()]
    return sorted(records, key=lambda record: record["task_id"])


def summarize_cluster(vms: List[Vm], placement: List[dict], records: List[dict],
                      work_per_mi: int) -> dict:
    """Metrik yang hanya ada di eksekusi nyata: MIPS efektif, overhead, CPU share."""
    for row in placement:
        own = [record for record in records if record["vm_id"] == row["vm_id"]]
        exec_time = sum(record["worker_exec_time_s"] for record in own)
        row["effective_mips"] = sum(r["length_mi"] for r in own) / exec_time if exec_time else 0.0
    total_exec = sum(record["worker_exec_time_s"] for record in records)
    effective_mips = sum(record["length_mi"] for record in records) / total_exec
    configured_mips = vms[0].mips * vms[0].pes_number
    return {
        "work_per_mi": work_per_mi,
        "configured_mips": configured_mips,
        "effective_mips": effective_mips,
        # Waktu simulasi dibagi angka ini kira-kira sama dengan waktu nyata.
        "speedup_vs_simulation": effective_mips / configured_mips,
        "mean_worker_exec_time_s": total_exec / len(records),
        "mean_overhead_s": sum(record["overhead_s"] for record in records) / len(records),
        "cpu_share_pct": 100 * sum(r["worker_cpu_time_s"] for r in records) / total_exec,
        "nodes": sorted({row["node"] for row in placement if row["node"]}),
    }


def compare_with_simulation(config: dict, tasks: List[Cloudlet], vms: List[Vm],
                            speedup: float) -> List[dict]:
    """Simulasi dataset yang sama, diskalakan ke detik nyata, lalu dibandingkan."""
    simulated_vms = [replace(vm) for vm in vms]
    simulated_tasks = fcfs_schedule([replace(task) for task in tasks], simulated_vms)
    simulated = _build_summary(config, simulated_vms, simulated_tasks, None)
    measured = _build_summary(config, vms, tasks, None)
    rows = []
    for key, label, exponent in COMPARED_METRICS:
        predicted = simulated[key] * speedup ** exponent
        rows.append({
            "metric": key,
            "label": label,
            "simulation": simulated[key],
            "predicted": predicted,
            "measured": measured[key],
            "ratio_pct": 100 * measured[key] / predicted if predicted else None,
        })
    return rows


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def _style_axis(axis, title: str) -> None:
    axis.set_facecolor(SURFACE)
    axis.set_title(title, loc="left", fontsize=12, color=INK, pad=12)
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color(BASELINE)
    axis.tick_params(colors=BASELINE, labelcolor=INK_2, labelsize=9)
    axis.xaxis.label.set_color(INK_2)
    axis.yaxis.label.set_color(INK_2)
    axis.set_axisbelow(True)


def plot_cluster_metrics(output: Path, tasks: List[Cloudlet], placement: List[dict],
                         records: List[dict], cluster: dict) -> None:
    """Grafik khusus eksekusi nyata; disimpan sebagai k8s_metrics.png."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

    makespan = calculate_makespan(tasks)
    datacenters = sorted({row["datacenter_id"] for row in placement})
    figure = Figure(figsize=(16, 10), facecolor=SURFACE, layout="constrained")
    FigureCanvasAgg(figure)
    figure.get_layout_engine().set(rect=(0, 0, 1, 0.9), h_pad=0.15, w_pad=0.15)
    figure.text(0.012, 0.975, f"FCFS di Kubernetes · {len(tasks):,} task · "
                f"{len(placement)} VM · {len(datacenters)} datacenter",
                fontsize=17, color=INK, weight="bold", va="top")
    figure.text(0.012, 0.935, f"Makespan terukur {makespan:,.2f} s   ·   MIPS efektif "
                f"{cluster['effective_mips']:,.0f} (config {cluster['configured_mips']})   ·   "
                f"overhead rata-rata {1000 * cluster['mean_overhead_s']:.1f} ms/task   ·   "
                f"CPU share {cluster['cpu_share_pct']:.1f}%",
                fontsize=11.5, color=INK_2, va="top")
    (gantt, ratio), (mips, overhead) = figure.subplots(
        2, 2, gridspec_kw={"width_ratios": (1.4, 1), "height_ratios": (1.25, 1)}
    )

    # 1. Timeline: setiap baris adalah antrean FCFS satu VM.
    lengths = sorted({task.length for task in tasks})
    if len(lengths) in LENGTH_STEPS:
        palette = dict(zip(lengths, LENGTH_STEPS[len(lengths)]))
        color_of = palette.__getitem__
    else:
        ramp = LinearSegmentedColormap.from_list("panjang", LENGTH_STEPS[4])
        scale = Normalize(lengths[0], lengths[-1])
        color_of = lambda length: ramp(scale(length))  # noqa: E731
    for row_index, row in enumerate(placement):
        own = [task for task in tasks if task.vm_id == row["vm_id"]]
        gantt.broken_barh(
            [(task.start_time, task.execution_time) for task in own], (row_index - 0.34, 0.68),
            facecolors=[color_of(task.length) for task in own], edgecolor=SURFACE, linewidth=0.4,
        )
    gantt.set_yticks(range(len(placement)),
                     [f"VM {row['vm_id']} · DC {row['datacenter_id']}" for row in placement])
    gantt.set_ylim(len(placement) - 0.5, -0.5)
    gantt.set_xlim(0, makespan * 1.02)
    gantt.axvline(makespan, color=INK_2, linewidth=1)
    gantt.grid(axis="x", color=GRID, linewidth=0.8)
    gantt.set_xlabel(f"Waktu sejak broker mulai (s) · garis vertikal = makespan {makespan:,.2f} s")
    _style_axis(gantt, "Timeline eksekusi per VM")
    if len(lengths) in LENGTH_STEPS:
        gantt.legend(
            handles=[Patch(color=palette[length], label=f"{length:,} MI") for length in lengths],
            loc="lower right", bbox_to_anchor=(1, 1.0), ncol=len(lengths), frameon=False,
            fontsize=9, labelcolor=INK_2, handlelength=1.2, borderaxespad=0.3,
        )
    else:
        colorbar = figure.colorbar(ScalarMappable(norm=scale, cmap=ramp), ax=gantt,
                                   pad=0.01, fraction=0.03)
        colorbar.set_label("Panjang task (MI)", color=INK_2)
        colorbar.ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))

    # 2. Deviasi dari model: terukur dibagi prediksi simulasi (100% = sesuai model).
    rows = [row for row in cluster["comparison"]
            if row["ratio_pct"] is not None and row["metric"] != "throughput_tasks_per_s"]
    positions = range(len(rows))
    values = [row["ratio_pct"] for row in rows]
    ratio.barh(positions, values, height=0.46, color=SERIES[0])
    ratio.axvline(100, color=INK_2, linewidth=1)
    limit = max(160, max(values) * 1.6)
    ratio.set_xlim(0, limit)
    for position, row in zip(positions, rows):
        unit = "%" if row["metric"] == "utilization_pct" else " s"
        ratio.text(max(row["ratio_pct"], 100) + limit * 0.015, position,
                   f"{row['ratio_pct']:.1f}%   ({row['measured']:,.2f}{unit} vs "
                   f"{row['predicted']:,.2f}{unit})",
                   va="center", fontsize=9, color=INK_2)
    ratio.set_yticks(list(positions), [row["label"] for row in rows])
    ratio.set_ylim(len(rows) - 0.5, -0.5)
    ratio.text(100 + limit * 0.01, -0.48, "100% = prediksi simulasi", ha="left", va="top",
               fontsize=8.5, color=INK_2)
    ratio.grid(axis="x", color=GRID, linewidth=0.8)
    ratio.set_xlabel("Terukur ÷ prediksi simulasi (%) · label: terukur vs prediksi")
    _style_axis(ratio, "Hasil nyata dibanding model simulasi")

    # 3. VM berspesifikasi sama, tetapi kecepatan nyatanya tidak persis sama.
    for datacenter_id in datacenters:
        own = [row for row in placement if row["datacenter_id"] == datacenter_id]
        color = SERIES[datacenter_id] if len(datacenters) <= len(SERIES) else SERIES[0]
        mips.scatter([row["vm_id"] for row in own], [row["effective_mips"] for row in own],
                     s=80, color=color, edgecolors=SURFACE, linewidths=2, zorder=3,
                     label=f"DC {datacenter_id}")
    speeds = [row["effective_mips"] for row in placement]
    mean_speed = sum(speeds) / len(speeds)
    spread = 100 * (max(speeds) - min(speeds)) / mean_speed
    padding = max(max(speeds) - min(speeds), 0.02 * mean_speed)
    mips.set_ylim(min(speeds) - padding, max(speeds) + padding)
    mips.axhline(mean_speed, color=INK_2, linewidth=1, zorder=2)
    mips.set_xticks([row["vm_id"] for row in placement],
                    [f"VM {row['vm_id']}" for row in placement])
    mips.set_xlim(-0.6, len(placement) - 0.4)
    mips.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
    mips.grid(axis="y", color=GRID, linewidth=0.8)
    mips.set_ylabel("MIPS efektif (MI/s)")
    mips.set_xlabel(f"Spesifikasi VM sama · selisih tercepat–terlambat {spread:.1f}%")
    _style_axis(mips, "MIPS efektif per VM")
    handles = mips.get_legend_handles_labels()[0] if 1 < len(datacenters) <= len(SERIES) else []
    handles.append(Line2D([], [], color=INK_2, linewidth=1, label=f"rata-rata {mean_speed:,.0f}"))
    mips.legend(handles=handles, loc="lower right", bbox_to_anchor=(1, 1.0), ncol=len(handles),
                frameon=False, fontsize=9, labelcolor=INK_2, borderaxespad=0.3,
                handletextpad=0.4, handlelength=1.4)

    # 4. Overhead per task: waktu di broker dikurangi waktu eksekusi di VM.
    delays = [1000 * record["overhead_s"] for record in records]
    median, p95 = _percentile(delays, 0.5), _percentile(delays, 0.95)
    # Sumbu log: kelompok ~ms (jaringan) dan puluhan ms (throttling CPU) sama-sama terlihat.
    low, high = max(min(delays), 0.05), max(max(delays), 0.1)
    bins = [low * (high * 1.05 / low) ** (step / 50) for step in range(51)]
    overhead.hist(delays, bins=bins, color=SERIES[0], rwidth=0.85)
    overhead.set_xscale("log")
    overhead.xaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5)))
    overhead.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    overhead.xaxis.set_minor_formatter(NullFormatter())
    for value, label, align in ((median, "median", "right"), (p95, "p95", "left")):
        overhead.axvline(value, color=INK_2, linewidth=1)
        overhead.text(value, 0.98, f" {label} {value:.2f} ms ", ha=align, va="top",
                      transform=overhead.get_xaxis_transform(), fontsize=9, color=INK_2)
    overhead.grid(axis="y", color=GRID, linewidth=0.8)
    overhead.set_xlabel("Overhead per task (ms, skala log)")
    overhead.set_ylabel("Jumlah task")
    _style_axis(overhead, "Overhead jaringan + HTTP per task")
    figure.savefig(output / "k8s_metrics.png", dpi=160, facecolor=SURFACE)


def main(argv: Sequence[str] | None = None) -> None:
    parser = _create_argument_parser()
    parser.description = "FCFS di VM nyata (pod Kubernetes atau worker HTTP lain)."
    parser.set_defaults(output=Path("results/k8s-fcfs"))
    parser.add_argument("--endpoint-template", default=DEFAULT_ENDPOINT,
                        help="Pola URL VM; tersedia {vm_id}, {datacenter_id}, {index}.")
    parser.add_argument("--endpoints", help="URL VM dipisah koma, urut ID VM.")
    parser.add_argument("--work-per-mi", type=int, default=20,
                        help="Iterasi CPU per MI; mengatur lama task nyata.")
    parser.add_argument("--timeout", type=float, default=300,
                        help="Batas waktu satu request ke VM (detik).")
    args, config, vms, tasks = parse_arguments(argv, parser)
    if args.work_per_mi <= 0 or args.timeout <= 0:
        parser.error("--work-per-mi dan --timeout harus positif.")
    try:
        endpoints = vm_endpoints(
            vms, config["datacenters"], args.endpoint_template,
            args.endpoints.split(",") if args.endpoints else None,
        )
    except (ValueError, KeyError, IndexError) as error:
        parser.error(f"Endpoint VM tidak valid: {error}")

    print(f"FCFS nyata: {len(tasks)} task, {len(vms)} VM, "
          f"{config['datacenters']} datacenter.", flush=True)
    try:
        placement = check_vms(vms, endpoints, args.timeout)
        for row in placement:
            limit = row["cpu_limit_millicores"]
            print(f"VM {row['vm_id']} DC {row['datacenter_id']}: {row['pod']} "
                  f"@ {row['node'] or '-'} "
                  f"({f'{limit}m' if limit is not None else 'tanpa limit'} CPU)", flush=True)
        records = run_fcfs(tasks, vms, endpoints, args.work_per_mi, args.timeout)
    except (ConnectionError, RuntimeError) as error:
        sys.exit(f"Eksperimen dibatalkan: {error}")

    save_results(args.output, config, vms, tasks, args.dataset)
    cluster = summarize_cluster(vms, placement, records, args.work_per_mi)
    cluster["comparison"] = compare_with_simulation(
        config, tasks, vms, cluster["speedup_vs_simulation"]
    )
    (args.output / "k8s_summary.json").write_text(
        json.dumps(cluster, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(args.output / "k8s_vms.csv", placement)
    _write_csv(args.output / "k8s_tasks.csv", records)
    _write_csv(args.output / "k8s_comparison.csv", cluster["comparison"])
    plot_cluster_metrics(args.output, tasks, placement, records, cluster)

    if args.show_tasks:
        print_cloudlet_list(tasks)
    print(f"MIPS efektif: {cluster['effective_mips']:,.0f} "
          f"(config {cluster['configured_mips']}, {cluster['speedup_vs_simulation']:.1f}x "
          f"lebih cepat dari simulasi)")
    print(f"Overhead jaringan rata-rata: {1000 * cluster['mean_overhead_s']:.1f} ms/task; "
          f"CPU share: {cluster['cpu_share_pct']:.1f}%")
    print(f"{'Metrik':<20} {'Simulasi':>12} {'Prediksi':>12} {'Terukur':>12} {'Rasio':>8}")
    for row in cluster["comparison"]:
        ratio = f"{row['ratio_pct']:.1f}%" if row["ratio_pct"] is not None else "-"
        print(f"{row['label']:<20} {row['simulation']:>12,.4f} {row['predicted']:>12,.4f} "
              f"{row['measured']:>12,.4f} {ratio:>8}")
    print(f"Hasil dan grafik (metrics.png, k8s_metrics.png) tersimpan di: "
          f"{args.output.resolve()}")


if __name__ == "__main__":
    main()
