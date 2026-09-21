package org.cloudbus.cloudsim.examples.FCFS;

import java.io.PrintWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import org.cloudbus.cloudsim.*;
import org.cloudbus.cloudsim.core.CloudSim;
import org.cloudbus.cloudsim.core.GuestEntity;
import org.cloudbus.cloudsim.provisioners.*;

/** Reproducible FCFS/RR baseline. Arguments: tasks vms seed FCFS|RR outputDirectory. */
public class FCFS_Scheduler {
    private static final int[] MIPS = {1000, 1500, 2000, 2500};
    // Experimental currency units per busy CPU second, not a provider price quote.
    private static final double[] RATE = {0.001, 0.0013, 0.0017, 0.0022};

    public static void main(String[] args) throws Exception {
        int taskCount = args.length > 0 ? Integer.parseInt(args[0]) : 200;
        int vmCount = args.length > 1 ? Integer.parseInt(args[1]) : 8;
        long seed = args.length > 2 ? Long.parseLong(args[2]) : 42;
        String algorithm = args.length > 3 ? args[3].toUpperCase(Locale.ROOT) : "FCFS";
        Path output = Path.of(args.length > 4 ? args[4] : "results/" + algorithm.toLowerCase(Locale.ROOT));
        if (args.length > 5 || taskCount < 200 || taskCount > 500 || vmCount < 8 || vmCount > 10
                || !(algorithm.equals("FCFS") || algorithm.equals("RR"))) {
            throw new IllegalArgumentException("Usage: 200..500 8..10 seed FCFS|RR outputDirectory");
        }
        CloudSim.init(1, Calendar.getInstance(), false, 0.000001);
        List<Host> hosts = new ArrayList<>();
        for (int mips : MIPS) {
            List<Pe> pes = new ArrayList<>();
            for (int p = 0; p < 4; p++) pes.add(new Pe(p, new PeProvisionerSimple(mips)));
            hosts.add(new Host(new RamProvisionerSimple(8192), new BwProvisionerSimple(10000),
                    1000000, pes, new VmSchedulerSpaceShared(pes)));
        }
        DatacenterCharacteristics characteristics = new DatacenterCharacteristics(
                "x86", "Linux", "Xen", hosts, 7.0, 0, 0, 0, 0);
        new Datacenter("Datacenter", characteristics, new VmAllocationPolicySimple(hosts) {
            @Override
            public boolean allocateHostForGuest(GuestEntity guest) {
                return allocateHostForGuest(guest, hosts.get(guest.getId() % MIPS.length));
            }
        },
                new LinkedList<Storage>(), 0);
        FCFSDatacenterBroker broker = new FCFSDatacenterBroker("Broker");
        List<Vm> vms = new ArrayList<>();
        for (int i = 0; i < vmCount; i++) {
            vms.add(new Vm(i, broker.getId(), MIPS[i % 4], 1, 1024, 1000, 10000,
                    "Xen", new CloudletSchedulerSpaceShared()));
        }
        Random random = new Random(seed);
        List<Cloudlet> tasks = new ArrayList<>();
        UtilizationModel full = new UtilizationModelFull();
        for (int i = 0; i < taskCount; i++) {
            Cloudlet task = new Cloudlet(i, 10000 + random.nextInt(90001), 1,
                    (100 + random.nextInt(901)) * 1024L,
                    (100 + random.nextInt(901)) * 1024L, full, full, full);
            task.setUserId(broker.getId());
            tasks.add(task);
        }
        broker.submitGuestList(vms);
        broker.submitCloudletList(tasks);
        broker.scheduleTasksToVms(tasks, vms, algorithm.equals("RR"));
        CloudSim.startSimulation();
        List<Cloudlet> completed = broker.getCloudletReceivedList();
        CloudSim.stopSimulation();
        if (completed.size() != taskCount || completed.stream().anyMatch(
                t -> t.getStatus() != Cloudlet.CloudletStatus.SUCCESS)) {
            throw new IllegalStateException("Not all tasks completed successfully: " + completed.size());
        }
        completed.sort(Comparator.comparingInt(Cloudlet::getCloudletId));
        double arrival = completed.stream().mapToDouble(Cloudlet::getSubmissionTime).min().orElseThrow();
        double makespan = completed.stream().mapToDouble(Cloudlet::getExecFinishTime).max().orElseThrow() - arrival;
        double cost = 0;
        double[] finish = new double[vmCount];
        double[] estimatedLoad = new double[vmCount];
        Files.createDirectories(output);
        try (PrintWriter csv = new PrintWriter(Files.newBufferedWriter(output.resolve("mapping.csv")))) {
            csv.println("task_id,length_mi,file_bytes,output_bytes,vm_id,vm_mips,rate_per_second,start_s,finish_s,cpu_s,cost");
            for (Cloudlet task : completed) {
                int vm = task.getGuestId();
                double duration = task.getCloudletLength() / vms.get(vm).getMips();
                // Runnable checks: serial service, correct compute capacity, no lost tasks.
                if (task.getExecStartTime() + 1e-6 < finish[vm]
                        || Math.abs(task.getActualCPUTime() - duration) > 0.01) {
                    throw new IllegalStateException("Unexpected execution timing for task " + task.getCloudletId());
                }
                finish[vm] = task.getExecFinishTime();
                estimatedLoad[vm] += duration;
                double taskCost = task.getActualCPUTime() * RATE[vm % 4];
                cost += taskCost;
                csv.printf(Locale.ROOT, "%d,%d,%d,%d,%d,%.0f,%.6f,%.6f,%.6f,%.6f,%.6f%n",
                        task.getCloudletId(), task.getCloudletLength(), task.getCloudletFileSize(),
                        task.getCloudletOutputSize(), vm, vms.get(vm).getMips(), RATE[vm % 4],
                        task.getExecStartTime(), task.getExecFinishTime(), task.getActualCPUTime(), taskCost);
            }
        }
        double estimate = Arrays.stream(estimatedLoad).max().orElseThrow();
        if (Math.abs(makespan - estimate) > 0.1) throw new IllegalStateException("Makespan differs from serial estimate");
        try (PrintWriter csv = new PrintWriter(Files.newBufferedWriter(output.resolve("summary.csv")))) {
            csv.println("algorithm,hosts,vms,tasks,seed,completed,makespan_s,estimated_makespan_s,compute_cost");
            csv.printf(Locale.ROOT, "%s,4,%d,%d,%d,%d,%.6f,%.6f,%.6f%n",
                    algorithm, vmCount, taskCount, seed, completed.size(), makespan, estimate, cost);
        }
        System.out.printf(Locale.ROOT, "%s: %d/%d tasks, makespan=%.3f s, cost=%.6f; output=%s%n",
                algorithm, completed.size(), taskCount, makespan, cost, output.toAbsolutePath());
    }
}
