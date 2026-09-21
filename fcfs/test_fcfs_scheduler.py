import unittest

from fcfs_scheduler import (
    calculate_makespan,
    create_cloudlets,
    create_vms,
    fcfs_schedule,
)


class FCFSSchedulerTest(unittest.TestCase):
    def test_cloudlet_lengths_follow_java_sequence(self) -> None:
        cloudlets = create_cloudlets(15)

        self.assertEqual(
            [cloudlet.length for cloudlet in cloudlets],
            [
                100000,
                70000,
                5000,
                1000,
                3000,
                10000,
                90000,
                100000,
                15000,
                1000,
                2000,
                4000,
                20000,
                25000,
                80000,
            ],
        )

    def test_fcfs_schedules_cloudlets_in_submission_order(self) -> None:
        cloudlets = fcfs_schedule(create_cloudlets(15), create_vms(6))

        self.assertEqual(
            [cloudlet.vm_id for cloudlet in cloudlets],
            [0, 1, 2, 3, 4, 5, 0, 1, 2, 3, 4, 5, 0, 1, 2],
        )
        self.assertEqual(cloudlets[6].start_time, 400.0)
        self.assertEqual(cloudlets[6].waiting_time, 400.0)

    def test_makespan_matches_fcfs_result(self) -> None:
        cloudlets = fcfs_schedule(create_cloudlets(15), create_vms(6))

        self.assertEqual(calculate_makespan(cloudlets), 840.0)


if __name__ == "__main__":
    unittest.main()
