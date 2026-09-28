"""Dataset task deterministik berdasarkan panjang (MI) dan persentase."""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence


@dataclass(frozen=True)
class TaskProfile:
    name: str
    length: int
    percentage: int


DEFAULT_PROFILES = (
    TaskProfile("pendek", 10000, 50),
    TaskProfile("sedang", 50000, 30),
    TaskProfile("panjang", 100000, 20),
)


def validate_profiles(profiles: Sequence[TaskProfile]) -> None:
    if not profiles:
        raise ValueError("Profil task tidak boleh kosong.")
    for profile in profiles:
        if not isinstance(profile.name, str) or not profile.name.strip():
            raise ValueError("Nama profil task tidak boleh kosong.")
        if type(profile.length) is not int or profile.length <= 0:
            raise ValueError("Panjang task harus bilangan bulat positif (MI).")
        if type(profile.percentage) is not int or not 0 <= profile.percentage <= 100:
            raise ValueError("Persentase task harus bilangan bulat 0 sampai 100.")
    if sum(profile.percentage for profile in profiles) != 100:
        raise ValueError("Total persentase profil task harus tepat 100%.")
    if len({profile.name for profile in profiles}) != len(profiles):
        raise ValueError("Nama profil task harus unik.")


def generate_lengths(
    task_count: int, profiles: Sequence[TaskProfile] = DEFAULT_PROFILES
) -> List[int]:
    """Bulatkan kuota dengan sisa terbesar; selingkan task tanpa random."""
    if type(task_count) is not int or task_count < 0:
        raise ValueError("Jumlah task harus bilangan bulat nonnegatif.")
    validate_profiles(profiles)
    target_counts = [
        task_count * profile.percentage // 100 for profile in profiles
    ]
    remainder_order = sorted(
        range(len(profiles)),
        key=lambda profile_index: -(
            task_count * profiles[profile_index].percentage % 100
        ),
    )
    remaining_tasks = task_count - sum(target_counts)
    for profile_index in remainder_order[:remaining_tasks]:
        target_counts[profile_index] += 1

    assigned_counts = [0] * len(profiles)
    lengths = []
    for position in range(task_count):
        eligible_profiles = (
            profile_index
            for profile_index in range(len(profiles))
            if assigned_counts[profile_index] < target_counts[profile_index]
        )
        # Defisit terbesar = profil paling tertinggal dari kuota posisi ini.
        # Kalikan dengan task_count agar perbandingan memakai bilangan bulat.
        next_profile = max(
            eligible_profiles,
            key=lambda profile_index: (
                target_counts[profile_index] * (position + 1)
                - assigned_counts[profile_index] * task_count
            ),
        )
        lengths.append(profiles[next_profile].length)
        assigned_counts[next_profile] += 1
    return lengths


def load_lengths(path: Path) -> List[int]:
    """CSV menggunakan ID berurutan mulai 1 agar urutan FCFS eksplisit."""
    lengths = []
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["task_id", "length_mi"]:
            raise ValueError("Header dataset harus task_id,length_mi.")
        for row in reader:
            if None in row:
                raise ValueError(f"Kolom berlebih pada baris {reader.line_num}.")
            try:
                task_id = int(row["task_id"])
                length = int(row["length_mi"])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Data task pada baris {reader.line_num} tidak valid."
                ) from error
            if task_id != len(lengths) + 1 or length <= 0:
                raise ValueError(
                    "ID task harus berurutan mulai 1 dan panjang harus positif."
                )
            lengths.append(length)
    if not lengths:
        raise ValueError("Dataset task tidak boleh kosong.")
    return lengths


def save_lengths(path: Path, lengths: Sequence[int]) -> None:
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.writer(destination, lineterminator="\n")
        writer.writerow(["task_id", "length_mi"])
        writer.writerows(enumerate(lengths, start=1))
