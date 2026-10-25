"""VM nyata untuk FCFS: HTTP service yang mengeksekusi task CPU-bound.

Satu pod Kubernetes mewakili satu VM. Batas CPU pod (millicore) berperan
sebagai MIPS, sehingga waktu eksekusi diukur dari CPU yang benar-benar tersedia.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping, Sequence

CGROUP = Path("/sys/fs/cgroup")


def burn_cpu(iterations: int) -> int:
    """Beban CPU deterministik; satu iterasi adalah satu langkah LCG."""
    state = 1
    for _ in range(iterations):
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
    return state


def read_cgroup_limits(root: Path = CGROUP) -> dict:
    """Baca kuota CPU dan memori cgroup v2; None berarti tanpa batas."""
    limits = {"cpu_limit_millicores": None, "memory_limit_mib": None}
    try:
        quota, period = (root / "cpu.max").read_text().split()
        if quota != "max":
            limits["cpu_limit_millicores"] = round(1000 * int(quota) / int(period))
    except (OSError, ValueError):
        pass
    try:
        memory = (root / "memory.max").read_text().strip()
        if memory != "max":
            limits["memory_limit_mib"] = int(memory) // (1024 * 1024)
    except (OSError, ValueError):
        pass
    return limits


def identity_from_environment(environ: Mapping[str, str] = os.environ) -> tuple[int, int]:
    """ID VM dari pod StatefulSet: ordinal * jumlah DC + ID DC (sama dengan simulasi)."""
    datacenter_id = int(environ["DATACENTER_ID"])
    ordinal = int(environ["POD_NAME"].rsplit("-", 1)[1])
    return ordinal * int(environ["DATACENTERS"]) + datacenter_id, datacenter_id


class VmHandler(BaseHTTPRequestHandler):
    server_version = "fcfs-vm/1.0"

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._reply(HTTPStatus.OK, {"status": "ok"})
        elif self.path == "/info":
            self._reply(HTTPStatus.OK, self.server.info)
        else:
            self._reply(HTTPStatus.NOT_FOUND, {"error": "Endpoint tidak dikenal."})

    def do_POST(self) -> None:
        if self.path != "/execute":
            self._reply(HTTPStatus.NOT_FOUND, {"error": "Endpoint tidak dikenal."})
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            task_id, length, iterations = body["task_id"], body["length_mi"], body["iterations"]
            if type(iterations) is not int or iterations < 0:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            self._reply(HTTPStatus.BAD_REQUEST,
                        {"error": "Body harus memuat task_id, length_mi, iterations >= 0."})
            return

        # Satu PE: task di VM yang sama dieksekusi bergantian, tidak paralel.
        with self.server.cpu:
            cpu_start, wall_start = time.thread_time(), time.perf_counter()
            burn_cpu(iterations)
            exec_time = time.perf_counter() - wall_start
            cpu_time = time.thread_time() - cpu_start
        self._reply(HTTPStatus.OK, {
            "task_id": task_id,
            "length_mi": length,
            "vm_id": self.server.info["vm_id"],
            "exec_time_s": exec_time,
            "cpu_time_s": cpu_time,
        })

    def _reply(self, status: HTTPStatus, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        # Probe kesehatan Kubernetes terlalu sering untuk dicatat.
        if self.command == "POST":
            super().log_message(format, *args)


def create_server(host: str, port: int, vm_id: int, datacenter_id: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), VmHandler)
    server.cpu = threading.Lock()
    server.info = {
        "vm_id": vm_id,
        "datacenter_id": datacenter_id,
        "pod": os.environ.get("POD_NAME", socket.gethostname()),
        "node": os.environ.get("NODE_NAME"),
        **read_cgroup_limits(),
    }
    return server


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="VM FCFS sebagai HTTP service.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--vm-id", type=int, help="Default: dari POD_NAME dan DATACENTERS.")
    parser.add_argument("--datacenter-id", type=int, help="Default: dari DATACENTER_ID.")
    args = parser.parse_args(argv)

    if args.vm_id is None or args.datacenter_id is None:
        try:
            args.vm_id, args.datacenter_id = identity_from_environment()
        except (KeyError, ValueError, IndexError):
            parser.error("Isi --vm-id dan --datacenter-id, atau env POD_NAME, "
                         "DATACENTER_ID, dan DATACENTERS.")

    server = create_server(args.host, args.port, args.vm_id, args.datacenter_id)
    print(f"VM {args.vm_id} (DC {args.datacenter_id}) siap di port "
          f"{server.server_address[1]}: {json.dumps(server.info)}", flush=True)
    # Python sebagai PID 1 di container mengabaikan SIGTERM tanpa handler.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
