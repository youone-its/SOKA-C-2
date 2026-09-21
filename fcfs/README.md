# FCFS Scheduler dengan PyCloudSim

Implementasi algoritma First Come First Served (FCFS) dalam Python berdasarkan
contoh CloudSim versi Java. Infrastruktur host dan VM container dibuat dengan
PyCloudSim, sedangkan waktu eksekusi cloudlet dihitung sesuai urutan kedatangan.

## Konfigurasi Simulasi

- 1 data center (`Datacenter_0`)
- 6 VM, masing-masing memiliki 250 MIPS, 1 PE, RAM 512 MB, bandwidth 1000,
  dan image size 10000 MB
- 15 cloudlet dengan ukuran yang sama seperti implementasi Java
- Penempatan cloudlet ke VM dilakukan secara round-robin dalam urutan FCFS
- Scheduler VM menggunakan model space-shared: satu cloudlet berjalan pada
  satu VM dalam satu waktu

Waktu cloudlet dihitung dengan rumus:

```text
execution_time = cloudlet_length / (vm_mips * vm_pes)
start_time     = max(submission_time, vm_available_time)
finish_time    = start_time + execution_time
makespan       = max(finish_time seluruh cloudlet)
```

## Persiapan

Implementasi ini telah diuji menggunakan Python 3.14, PyCloudSim 1.0.7, dan
Matplotlib 3.11.2.

```bash
cd fcfs
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Menjalankan Simulasi

```bash
python fcfs_scheduler.py
```

PyCloudSim akan menampilkan log pembuatan dan alokasi enam container sebelum
tabel hasil FCFS.

## Contoh Output

```text
========== OUTPUT ==========
Cloudlet ID  STATUS   Length     Data center ID  VM ID   Time       Start Time   Finish Time   Waiting Time  Response Time  Execution Time
0            SUCCESS  100000     0               0       400.00     0.00         400.00        0.00          400.00         400.00
1            SUCCESS  70000      0               1       280.00     0.00         280.00        0.00          280.00         280.00
2            SUCCESS  5000       0               2       20.00      0.00         20.00         0.00          20.00          20.00
3            SUCCESS  1000       0               3       4.00       0.00         4.00          0.00          4.00           4.00
4            SUCCESS  3000       0               4       12.00      0.00         12.00         0.00          12.00          12.00
5            SUCCESS  10000      0               5       40.00      0.00         40.00         0.00          40.00          40.00
6            SUCCESS  90000      0               0       360.00     400.00       760.00        400.00        760.00         360.00
7            SUCCESS  100000     0               1       400.00     280.00       680.00        280.00        680.00         400.00
8            SUCCESS  15000      0               2       60.00      20.00        80.00         20.00         80.00          60.00
9            SUCCESS  1000       0               3       4.00       4.00         8.00          4.00          8.00           4.00
10           SUCCESS  2000       0               4       8.00       12.00        20.00         12.00         20.00          8.00
11           SUCCESS  4000       0               5       16.00      40.00        56.00         40.00         56.00          16.00
12           SUCCESS  20000      0               0       80.00      760.00       840.00        760.00        840.00         80.00
13           SUCCESS  25000      0               1       100.00     680.00       780.00        680.00        780.00         100.00
14           SUCCESS  80000      0               2       320.00     80.00        400.00        80.00         400.00         320.00
Makespan using FCFS: 840.00
FCFS_Scheduler finished!
```

## Pengujian

```bash
python -m unittest -v test_fcfs_scheduler.py
```

Tes memverifikasi urutan panjang cloudlet dari kode Java, distribusi cloudlet
ke VM, waktu tunggu, dan nilai makespan.

## Struktur File

```text
fcfs/
|-- fcfs_scheduler.py       # Implementasi utama dan entry point
|-- fcfs_datacenter.py      # Versi awal pemodelan data center
|-- test_fcfs_scheduler.py  # Unit test penjadwalan
|-- requirements.txt        # Dependensi Python
`-- README.md               # Dokumentasi
```
