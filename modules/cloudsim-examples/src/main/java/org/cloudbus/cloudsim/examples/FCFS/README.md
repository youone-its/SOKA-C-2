# Baseline FCFS dan Round Robin

Dari root repository, Java 21 dan Maven:

```bash
bash run-fcfs.sh
bash run-fcfs.sh 500 10 42 FCFS results/fcfs-500
bash run-fcfs.sh 200 8 42 RR results/rr-200
```

Argumen: jumlah task (200–500), jumlah VM (8–10), seed, FCFS/RR,
folder output. Default: 200, 8, 42, FCFS, results/fcfs.
File output dengan nama yang sama di folder tujuan akan ditimpa.
Di IDE jalankan `org.cloudbus.cloudsim.examples.FCFS.FCFS_Scheduler`.

## Model

- Satu datacenter, empat host, masing-masing empat PE, RAM 8192 MB,
  bandwidth 10000, storage 1000000 MB.
- MIPS per PE host: 1000, 1500, 2000, 2500. Ini kapasitas compute,
  bukan konsumsi daya listrik.
- VM i ditempatkan di host kelas i % 4, dengan MIPS sesuai host,
  satu PE, RAM 1024 MB, bandwidth 1000, image 10000 MB.
  VmSchedulerSpaceShared mencegah oversubscription CPU.
- Task satu PE, length uniform integer 10000–100000 MI, file dan output
  masing-masing 100–1000 KiB (disimpan sebagai byte). Random seed tetap;
  urutan 200 task pertama sama pada workload 500 task dengan seed sama.
- Semua task tersedia bersamaan; ID menentukan urutan kedatangan.
  FCFS memetakan task berikutnya ke VM paling awal tersedia, tie dipecahkan
  berdasarkan indeks VM. Ini static list scheduling dengan urutan FCFS,
  bukan pemilihan task terpendek atau VM dengan finish time terkecil.
  RR memakai indeks task modulo jumlah VM.
- CloudletSchedulerSpaceShared menjalankan antrean tiap VM secara serial.
- Estimasi durasi = MI / MIPS. Binding dilakukan sebelum simulasi.
  Model ini mengasumsikan kapasitas tetap, tanpa migrasi maupun transfer
  jaringan; file/output size hanya metadata workload.
- Resolusi event 0.000001 detik untuk mengurangi pembulatan durasi.

## Output dan validasi

`mapping.csv` mencatat task → VM, workload, MIPS, tarif, waktu mulai/selesai,
waktu CPU aktual, dan biaya. `summary.csv` mencatat makespan aktual
(max finish minus min submission), estimasi makespan, jumlah task berhasil,
dan biaya komputasi. Tarif eksperimen per detik CPU sibuk untuk empat kelas
VM adalah 0.001, 0.0013, 0.0017, 0.0022 satuan uang. Biaya tidak mencakup
idle VM, RAM, storage, jaringan, atau pembulatan billing penyedia cloud.

Program gagal dengan exit nonzero jika task tidak seluruhnya sukses,
eksekusi task satu VM bertumpuk, durasi menyimpang dari MI/MIPS, atau
makespan menyimpang dari estimasi antrean serial. Untuk smoke check jalankan
200/8, 200/9, 500/10 pada FCFS serta 200/8 dan 500/10 pada RR.

FCFS tidak memiliki populasi, iterasi, best solution, maupun convergence
curve. Hasil mapping ini merupakan baseline untuk HHO. Implementasi HHO
20 hawks/100 iterasi dan convergence curve belum termasuk modul FCFS ini.
Saat menambah HHO, gunakan workload, kapasitas, tarif, dan seed yang sama;
binding mapping hasil optimasi ke broker sebelum CloudSim.startSimulation().
