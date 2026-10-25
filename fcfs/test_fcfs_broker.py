import csv
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fcfs_broker import DEFAULT_ENDPOINT, main as run_broker, vm_endpoints
from fcfs_scheduler import calculate_makespan, create_vms, fcfs_schedule, parse_arguments
from fcfs_worker import VmHandler, create_server, identity_from_environment, read_cgroup_limits

VM_SPEC = {"mips": 250, "pes_number": 1, "ram": 512,
           "bandwidth": 1000, "size": 10000, "vmm": "Xen"}
RENDER = Path(__file__).resolve().parent.parent / "k8s" / "render.py"


def setUpModule():
    # Log akses worker tidak relevan untuk output pengujian.
    patcher = patch.object(VmHandler, "log_message")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def start_worker(vm_id, datacenter_id):
    server = create_server("127.0.0.1", 0, vm_id, datacenter_id)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.server, self.url = start_worker(5, 1)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, body):
        request = urllib.request.Request(f"{self.url}/execute", data=json.dumps(body).encode())
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def test_health_info_and_execute(self):
        with urllib.request.urlopen(f"{self.url}/healthz") as response:
            self.assertEqual(json.load(response), {"status": "ok"})
        with urllib.request.urlopen(f"{self.url}/info") as response:
            info = json.load(response)
        self.assertEqual((info["vm_id"], info["datacenter_id"]), (5, 1))
        reply = self.post({"task_id": 3, "length_mi": 100, "iterations": 1000})
        self.assertEqual((reply["task_id"], reply["vm_id"]), (3, 5))
        self.assertGreaterEqual(reply["exec_time_s"], 0)
        self.assertGreaterEqual(reply["cpu_time_s"], 0)

    def test_invalid_requests(self):
        for body in ({}, {"task_id": 1, "length_mi": 1, "iterations": -1},
                     {"task_id": 1, "length_mi": 1, "iterations": 1.5}, [1]):
            with self.subTest(body=body), self.assertRaises(urllib.error.HTTPError) as error:
                self.post(body)
            error.exception.close()
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f"{self.url}/unknown")
        error.exception.close()
        self.assertEqual(error.exception.code, 404)

    def test_identity_follows_simulation_mapping(self):
        environ = {"POD_NAME": "fcfs-vm-dc1-3", "DATACENTER_ID": "1", "DATACENTERS": "2"}
        self.assertEqual(identity_from_environment(environ), (7, 1))
        environ = {"POD_NAME": "fcfs-vm-dc0-0", "DATACENTER_ID": "0", "DATACENTERS": "2"}
        self.assertEqual(identity_from_environment(environ), (0, 0))

    def test_cgroup_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(read_cgroup_limits(root),
                             {"cpu_limit_millicores": None, "memory_limit_mib": None})
            (root / "cpu.max").write_text("25000 100000\n")
            (root / "memory.max").write_text(f"{512 * 1024 * 1024}\n")
            self.assertEqual(read_cgroup_limits(root),
                             {"cpu_limit_millicores": 250, "memory_limit_mib": 512})
            (root / "cpu.max").write_text("max 100000\n")
            (root / "memory.max").write_text("max\n")
            self.assertEqual(read_cgroup_limits(root),
                             {"cpu_limit_millicores": None, "memory_limit_mib": None})


class BrokerTest(unittest.TestCase):
    def setUp(self):
        self.servers, self.urls = [], []
        for vm_id in range(4):
            server, url = start_worker(vm_id, vm_id % 2)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            self.servers.append(server)
            self.urls.append(url)

    def run_broker(self, output, urls):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            run_broker(["--tasks", "12", "--vms", "4", "--datacenters", "2",
                        "--work-per-mi", "1", "--endpoints", ",".join(urls),
                        "--output", str(output)])

    def test_default_endpoints_use_statefulset_dns(self):
        vms = create_vms(8, 2, **VM_SPEC)
        endpoints = vm_endpoints(vms, 2)
        self.assertEqual(endpoints[0], DEFAULT_ENDPOINT.format(datacenter_id=0, index=0))
        self.assertEqual(endpoints[5], "http://fcfs-vm-dc1-2.fcfs-vm-dc1:8080")
        self.assertEqual(endpoints[6], "http://fcfs-vm-dc0-3.fcfs-vm-dc0:8080")
        with self.assertRaises(ValueError):
            vm_endpoints(vms, 2, explicit=["http://a", "http://b"])

    def test_real_execution_matches_simulation_assignment(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self.run_broker(output, self.urls)
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["completed"], 12)
            self.assertEqual(summary["vm_distribution"], {"0": 2, "1": 2})
            self.assertEqual((output / "metrics.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            with (output / "results.csv").open() as source:
                rows = list(csv.DictReader(source))
            self.assertEqual([int(row["vm_id"]) for row in rows], [i % 4 for i in range(12)])
            self.assertEqual([int(row["resource_id"]) for row in rows], [i % 2 for i in range(12)])
            for vm_id in range(4):
                own = [row for row in rows if int(row["vm_id"]) == vm_id]
                for before, after in zip(own, own[1:]):
                    # Task berikut di VM yang sama baru mulai setelah task sebelumnya selesai.
                    self.assertGreaterEqual(float(after["start_time"]), float(before["finish_time"]))
            with (output / "k8s_tasks.csv").open() as source:
                self.assertEqual(len(list(csv.DictReader(source))), 12)
            with (output / "k8s_vms.csv").open() as source:
                placement = list(csv.DictReader(source))
            self.assertEqual([row["endpoint"] for row in placement], self.urls)
            cluster = json.loads((output / "k8s_summary.json").read_text())
            self.assertEqual((cluster["work_per_mi"], cluster["configured_mips"]), (1, 250))
            self.assertGreater(cluster["effective_mips"], 0)
            comparison = {row["metric"]: row for row in cluster["comparison"]}
            # Prediksi = simulasi dataset yang sama, diskalakan dengan speedup terukur.
            self.assertEqual(comparison["makespan_s"]["simulation"], summary_of_simulation())
            self.assertAlmostEqual(
                comparison["makespan_s"]["predicted"] * cluster["speedup_vs_simulation"],
                comparison["makespan_s"]["simulation"],
            )
            self.assertEqual(comparison["makespan_s"]["measured"], summary["makespan_s"])
            with (output / "k8s_comparison.csv").open() as source:
                self.assertEqual(len(list(csv.DictReader(source))), len(comparison))
            self.assertEqual((output / "k8s_metrics.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_wrong_vm_identity_aborts_before_execution(self):
        swapped = [self.urls[1], self.urls[0], *self.urls[2:]]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            with self.assertRaises(SystemExit) as error:
                self.run_broker(output, swapped)
            self.assertIn("seharusnya VM 0", str(error.exception.code))
            self.assertFalse(output.exists())

    def test_resource_limits_must_match_config(self):
        for key, value, message in (("cpu_limit_millicores", 500, "500m CPU"),
                                    ("memory_limit_mib", 256, "256 MiB")):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                original = self.servers[2].info[key]
                self.servers[2].info[key] = value
                try:
                    with self.assertRaises(SystemExit) as error:
                        self.run_broker(Path(directory) / "run", self.urls)
                finally:
                    self.servers[2].info[key] = original
                self.assertIn(f"VM 2 dibatasi {message}", str(error.exception.code))
        with tempfile.TemporaryDirectory() as directory:
            self.servers[2].info.update(cpu_limit_millicores=250, memory_limit_mib=512)
            self.run_broker(Path(directory), self.urls)
            self.assertTrue((Path(directory) / "summary.json").exists())

    def test_invalid_broker_options(self):
        for extra in (["--work-per-mi", "0"], ["--timeout", "-1"],
                      ["--endpoints", "http://a"]):
            with self.subTest(extra=extra), redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit):
                run_broker(["--tasks", "4", "--vms", "4", "--datacenters", "2", *extra])


def summary_of_simulation():
    # Simulasi independen dengan config dan jumlah yang sama seperti run_broker.
    _, _, vms, tasks = parse_arguments(["--tasks", "12", "--vms", "4", "--datacenters", "2"])
    return calculate_makespan(fcfs_schedule(tasks, vms))


class RenderTest(unittest.TestCase):
    def render(self, command, config):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config))
            return subprocess.run([sys.executable, str(RENDER), command, str(path)],
                                  capture_output=True, text=True, timeout=30)

    def config(self, **changes):
        config = {
            "tasks": 20, "vms": 5, "datacenters": 3,
            "vm": {"mips": 500, "pes_number": 2, "ram": 1024,
                   "bandwidth": 1000, "size": 10000, "vmm": "Xen"},
            "cloudlet": {"pes_number": 1, "file_size": 0,
                         "output_size": 0, "submission_time": 0.0},
            "workload": [{"name": "a", "length": 1000, "percentage": 100}],
        }
        config.update(changes)
        return config

    def test_vms_follow_config_allocation(self):
        result = self.render("vms", self.config())
        self.assertEqual(result.returncode, 0, result.stderr)
        documents = result.stdout.split("---\n")
        self.assertEqual(len(documents), 6)
        # create_vms: VM v -> DC v mod 3, jadi 5 VM terbagi 2, 2, 1.
        for datacenter_id, replicas in enumerate((2, 2, 1)):
            statefulset = documents[2 * datacenter_id + 1]
            self.assertIn(f"name: fcfs-vm-dc{datacenter_id}\n", statefulset)
            self.assertIn(f"replicas: {replicas}\n", statefulset)
            self.assertIn(f"topology.kubernetes.io/zone: dc-{datacenter_id}\n", statefulset)
            self.assertEqual(statefulset.count("cpu: 1000m"), 2)
            self.assertEqual(statefulset.count("memory: 1024Mi"), 2)
            self.assertIn('name: DATACENTERS\n              value: "3"', statefulset)
        self.assertNotIn("$", result.stdout)

    def test_kind_nodes_and_shape_follow_config(self):
        result = self.render("kind", self.config())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("role: worker"), 3)
        self.assertIn("zone: dc-2\n", result.stdout)
        self.assertEqual(self.render("shape", self.config()).stdout, "20 5 3\n")

    def test_invalid_config_is_rejected(self):
        for changes in ({"datacenters": 1}, {"vms": 2}, {"tasks": 0}):
            with self.subTest(changes=changes):
                result = self.render("vms", self.config(**changes))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
