import csv
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stderr
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from fcfs_scheduler import (
    Cloudlet, calculate_makespan, create_cloudlets, create_vms,
    fcfs_schedule, parse_arguments,
)
from workload import TaskProfile, generate_lengths, load_lengths, save_lengths


class WorkloadTest(unittest.TestCase):
    def test_proportions_and_same_prefix_for_1000_and_2000(self):
        smaller = generate_lengths(1000)
        larger = generate_lengths(2000)
        self.assertEqual(Counter(smaller), {10000: 500, 50000: 300, 100000: 200})
        self.assertEqual(Counter(larger), {10000: 1000, 50000: 600, 100000: 400})
        self.assertEqual(smaller, larger[:1000])
        self.assertEqual(smaller, generate_lengths(1000))

    def test_rounding_preserves_total_for_small_counts(self):
        self.assertEqual(Counter(generate_lengths(7)), {10000: 4, 50000: 2, 100000: 1})
        self.assertEqual(generate_lengths(0), [])
        for count in range(1, 101):
            self.assertEqual(len(generate_lengths(count)), count)

    def test_custom_profile(self):
        profiles = (TaskProfile("a", 2000, 25), TaskProfile("b", 8000, 75))
        self.assertEqual(Counter(generate_lengths(1000, profiles)), {2000: 250, 8000: 750})

    def test_invalid_profiles_and_counts(self):
        invalid_profiles = (
            (), (TaskProfile("a", 100, 99),),
            (TaskProfile("a", 0, 100),), (TaskProfile("a", 10, "100"),),
            (TaskProfile("", 10, 100),),
            (TaskProfile("a", 10, 50), TaskProfile("a", 20, 50)),
            (TaskProfile("a", 10, 101), TaskProfile("b", 20, -1)),
        )
        for profiles in invalid_profiles:
            with self.subTest(profiles=profiles), self.assertRaises(ValueError):
                generate_lengths(10, profiles)
        for count in (-1, 1.5, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                generate_lengths(count)

    def test_csv_roundtrip_and_manual_lengths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.csv"
            save_lengths(path, [12345, 67890, 22222])
            self.assertEqual(load_lengths(path), [12345, 67890, 22222])

    def test_invalid_csv(self):
        invalid = (
            "task_id,length_mi\n", "id,length\n1,100\n",
            "task_id,length_mi\n2,100\n", "task_id,length_mi\n1,0\n",
            "task_id,length_mi\n1,abc\n", "task_id,length_mi\n1,100,extra\n",
            "task_id,length_mi\n1,100\n1,200\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.csv"
            for contents in invalid:
                with self.subTest(contents=contents):
                    path.write_text(contents)
                    with self.assertRaises(ValueError):
                        load_lengths(path)


class FCFSSchedulerTest(unittest.TestCase):
    def test_vms_identical_and_distributed_to_datacenters(self):
        vms = create_vms(10, 2, mips=500, ram=1024)
        specs = [{key: value for key, value in asdict(vm).items()
                  if key not in ("id", "datacenter_id")} for vm in vms]
        self.assertTrue(all(spec == specs[0] for spec in specs))
        self.assertEqual(Counter(vm.datacenter_id for vm in vms), {0: 5, 1: 5})
        self.assertEqual([vm.datacenter_id for vm in create_vms(5, 2)], [0, 1, 0, 1, 0])

    def test_fcfs_queue_timing_and_datacenter_mapping(self):
        tasks = [Cloudlet(id=i, length=length) for i, length in
                 enumerate((1000, 2000, 3000), start=1)]
        fcfs_schedule(tasks, create_vms(2, 2))
        self.assertEqual([task.vm_id for task in tasks], [0, 1, 0])
        self.assertEqual([task.resource_id for task in tasks], [0, 1, 0])
        self.assertEqual([task.start_time for task in tasks], [0, 0, 4])
        self.assertEqual([task.finish_time for task in tasks], [4, 8, 16])
        self.assertEqual(tasks[-1].waiting_time, 4)
        self.assertEqual(calculate_makespan(tasks), 16)

    def test_cloudlet_ids_start_at_one(self):
        self.assertEqual([task.id for task in create_cloudlets(3)], [1, 2, 3])

    def test_invalid_vm_specs(self):
        for spec in ({"mips": 0}, {"ram": -1}, {"pes_number": True}, {"vmm": ""}):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                create_vms(2, 2, **spec)
        with self.assertRaises(ValueError):
            create_vms(1, 2)
        with self.assertRaises(ValueError):
            fcfs_schedule([], [])


class UserInputTest(unittest.TestCase):
    def test_cli_override(self):
        _, config, vms, tasks = parse_arguments(["--tasks", "2000", "--vms", "10"])
        self.assertEqual((len(tasks), len(vms), config["datacenters"]), (2000, 10, 2))

    def test_interactive_input(self):
        with patch("builtins.input", side_effect=["2000", "10", "2"]):
            _, config, vms, tasks = parse_arguments(["--interactive"])
        self.assertEqual((len(tasks), len(vms), config["datacenters"]), (2000, 10, 2))

    def test_cli_rejects_invalid_input(self):
        for args in (["--tasks", "0"], ["--datacenters", "1"], ["--vms", "1"],
                     ["--tasks", "1000", "--dataset", "any.csv"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    parse_arguments(args)
                self.assertEqual(raised.exception.code, 2)

    def test_csv_count_overrides_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.csv"
            save_lengths(path, [100, 200, 300])
            _, config, _, tasks = parse_arguments(["--dataset", str(path)])
        self.assertEqual(config["tasks"], 3)
        self.assertEqual([task.length for task in tasks], [100, 200, 300])

    def test_invalid_config_profiles(self):
        config = json.loads(Path(__file__).with_name("config.json").read_text())
        config["workload"][0]["percentage"] = 20
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config))
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parse_arguments(["--config", str(path)])


@unittest.skipUnless(importlib.util.find_spec("PyCloudSim"), "PyCloudSim belum terpasang")
class InfrastructureIntegrationTest(unittest.TestCase):
    def test_actual_allocation_export_and_dataset_reuse(self):
        script = Path(__file__).with_name("fcfs_scheduler.py")
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first", Path(directory) / "second"
            for output, input_args in (
                (first, ["--tasks", "1000"]),
                (second, ["--dataset", str(first / "dataset.csv")]),
            ):
                result = subprocess.run(
                    [sys.executable, str(script), *input_args, "--output", str(output)],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                summary = json.loads((output / "summary.json").read_text())
                self.assertEqual(summary["completed"], 1000)
                self.assertEqual(summary["vm_distribution"], {"0": 4, "1": 4})
                with (output / "results.csv").open() as source:
                    rows = list(csv.DictReader(source))
                self.assertEqual({row["resource_id"] for row in rows}, {"0", "1"})
                self.assertEqual(len(rows), 1000)
            self.assertEqual(
                (first / "dataset.csv").read_bytes(),
                (second / "dataset.csv").read_bytes(),
            )
            self.assertEqual(
                (first / "results.csv").read_bytes(),
                (second / "results.csv").read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
