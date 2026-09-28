# FCFS Python: dataset konsisten dan VM seragam

Simulator menerima jumlah task, jumlah VM, dan jumlah datacenter dari pengguna.
Dataset dibuat dari profil panjang task dan persentase yang eksplisit, tanpa random.
Setiap task memiliki ID mulai 1 dan panjang yang bisa diperiksa di `dataset.csv`.

## Mulai dari root proyek

Virtual environment `cloudsim` yang sudah ada dapat digunakan:

```bash
cloudsim/bin/python fcfs/fcfs_scheduler.py --interactive
```

Isi jumlah task, VM, dan datacenter pada prompt. Tekan Enter untuk memakai
nilai default: **1000 task, 8 VM total, 2 datacenter**.

Untuk membuat environment baru:

```bash
python -m venv fcfs/.venv
source fcfs/.venv/bin/activate
python -m pip install -r fcfs/requirements.txt
python fcfs/fcfs_scheduler.py --interactive
```

## Percobaan 1000 dan 2000 task

```bash
cloudsim/bin/python fcfs/fcfs_scheduler.py --tasks 1000 --vms 8 --datacenters 2 --output results/python-fcfs-1000
cloudsim/bin/python fcfs/fcfs_scheduler.py --tasks 2000 --vms 8 --datacenters 2 --output results/python-fcfs-2000
```

Gunakan jumlah dan spesifikasi VM yang sama untuk membandingkan pengaruh jumlah
task. Jumlah task tidak dibatasi pada 200–500; setiap bilangan bulat positif diterima.
Jumlah VM minimal sama dengan jumlah datacenter. Jumlah datacenter minimal 2.
VM dibagi secara bergantian ke datacenter: VM 0 ke DC 0, VM 1 ke DC 1, dan seterusnya.
Untuk 8 VM dan 2 DC, setiap DC mendapat 4 VM; untuk 10 VM, setiap DC mendapat 5 VM.

## Profil dataset

Edit `fcfs/config.json` untuk mengubah parameter default dan profil workload:

```json
{
  "tasks": 1000,
  "vms": 8,
  "datacenters": 2,
  "vm": {
    "mips": 250,
    "pes_number": 1,
    "ram": 512,
    "bandwidth": 1000,
    "size": 10000,
    "vmm": "Xen"
  },
  "workload": [
    {"name": "pendek", "length": 10000, "percentage": 50},
    {"name": "sedang", "length": 50000, "percentage": 30},
    {"name": "panjang", "length": 100000, "percentage": 20}
  ]
}
```

Semua VM memakai satu blok `vm` yang sama. `length` memakai satuan MI
(Million Instructions); `mips` adalah MI per detik; RAM dan image size memakai MiB.
Bandwidth dan VMM dicatat sebagai spesifikasi; keduanya tidak memengaruhi rumus
waktu eksekusi pada model ini. Input/output task tetap 3000/300 byte.

| Profil | Panjang (MI) | Persentase | 1000 task | 2000 task |
|---|---:|---:|---:|---:|
| Pendek | 10.000 | 50% | 500 | 1000 |
| Sedang | 50.000 | 30% | 300 | 600 |
| Panjang | 100.000 | 20% | 200 | 400 |

Persentase harus bilangan bulat, totalnya tepat 100%, dan nama profil harus unik.
Profil dapat ditambah atau dihapus. Jika jumlah task menghasilkan kuota pecahan,
kuota dibulatkan ke bawah lalu sisa task diberikan ke profil dengan sisa pecahan
terbesar. Jika seri, urutan profil dalam config menentukan prioritas.

Task diselingkan secara deterministik sesuai kuota, sehingga task panjang tidak
semuanya diletakkan di belakang. Konfigurasi dan jumlah task yang sama selalu
menghasilkan urutan task yang sama. Dengan profil default, 1000 task pertama
pada dataset 2000 identik dengan dataset 1000; untuk jumlah yang memerlukan
pembulatan, urutan dapat berubah sesuai kuota yang baru.

Untuk memakai konfigurasi terpisah:

```bash
cloudsim/bin/python fcfs/fcfs_scheduler.py --config fcfs/config.json --tasks 2000 --output results/percobaan
```

Prioritas parameter: nilai config, lalu argumen CLI, lalu jawaban prompt ketika
`--interactive` dipakai. Setiap simulasi membaca ulang config tanpa mengubah file sumber.

## Panjang task manual atau dataset yang sama

Anda juga bisa menentukan panjang tiap task sendiri dengan CSV:

```csv
task_id,length_mi
1,12000
2,45000
3,80000
```

ID wajib berurutan mulai 1, panjang wajib bilangan bulat positif, dan urutan baris
menjadi urutan kedatangan task. Simpan sebagai `tasks.csv`, lalu jalankan:

```bash
cloudsim/bin/python fcfs/fcfs_scheduler.py --dataset tasks.csv --vms 8 --output results/manual
```

Jumlah task mengikuti jumlah baris CSV. `--tasks` tidak dipakai bersama `--dataset`.
Untuk mengulang dataset hasil percobaan sebelumnya:

```bash
cloudsim/bin/python fcfs/fcfs_scheduler.py --dataset results/python-fcfs-1000/dataset.csv --output results/ulang
```

Distribusi aktual CSV dicatat di `summary.json`; profil `workload` dalam config
hanya digunakan saat membuat dataset baru. Untuk mengulang dataset manual,
selalu gunakan `--dataset` bersama config yang disimpan agar spesifikasi sama.

## Output

Setiap folder output memuat:

- `dataset.csv`: ID dan panjang setiap task sebelum penjadwalan.
- `config.json`: konfigurasi efektif, termasuk jumlah task dan VM.
- `vms.csv`: spesifikasi tiap VM dan ID datacenter.
- `results.csv`: panjang task, VM, datacenter (`resource_id`), waktu mulai,
  waktu selesai, waktu tunggu, dan waktu respons.
- `summary.json`: jumlah task selesai, makespan, rata-rata waktu tunggu,
  distribusi panjang task, dan distribusi VM per datacenter.

Gunakan `--show-tasks` untuk menampilkan seluruh tabel di terminal. Gunakan folder
`--output` berbeda untuk menyimpan beberapa percobaan; menjalankan kembali ke folder
output yang sama akan memperbarui file hasil.

## Model simulasi

PyCloudSim membuat dan mengalokasikan container yang mewakili VM. Pada model
sederhana ini, **satu host mewakili setiap datacenter**, sehingga default 2 DC
memiliki 2 host. Kapasitas CPU, RAM, dan penyimpanan host disesuaikan dengan
jumlah VM dan spesifikasinya agar seluruh VM bisa dialokasikan. Alokasi aktual
container diperiksa sebelum penjadwalan task.

Seluruh task datang pada waktu 0 dan diproses dalam urutan input. Pembagian task
ke VM dilakukan bergantian (round-robin); pada tiap VM, antrean dilayani FCFS,
satu task pada satu waktu. Waktu task dihitung oleh kode Python:

```text
execution_time = task_length / (vm_mips * vm_pes)
start_time     = max(submission_time, vm_available_time)
finish_time    = start_time + execution_time
makespan       = max(finish_time seluruh task)
```

PyCloudSim menangani infrastruktur; jadwal task memakai perhitungan tersebut.
Model ini belum menghitung transfer jaringan atau kompetisi I/O antar datacenter.

## Pengujian

Dari root proyek:

```bash
cloudsim/bin/python -m unittest discover -s fcfs -v
```

Pengujian mencakup dataset 1000/2000, kuota dan pembulatan, input CLI/interaktif,
CSV manual, input tidak valid, VM seragam, waktu FCFS, alokasi PyCloudSim ke
kedua datacenter, serta hasil identik setelah dataset dipakai ulang.
Tes integrasi memerlukan PyCloudSim; tes perhitungan dapat berjalan dengan Python standar.

## File

- `fcfs_scheduler.py`: penjadwalan, input pengguna, infrastruktur, dan output.
- `workload.py`: pembuatan dataset deterministik dan pembacaan/penulisan CSV.
- `config.json`: parameter VM, jumlah task, datacenter, dan profil dataset.
- `fcfs_datacenter.py`: entry point alternatif yang menjalankan scheduler yang sama.
- `test_fcfs_scheduler.py`: pengujian unit dan integrasi.
