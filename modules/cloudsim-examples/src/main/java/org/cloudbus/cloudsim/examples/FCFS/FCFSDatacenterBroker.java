package org.cloudbus.cloudsim.examples.FCFS;

import java.util.List;
import org.cloudbus.cloudsim.Cloudlet;
import org.cloudbus.cloudsim.DatacenterBroker;
import org.cloudbus.cloudsim.Vm;

/** Static FCFS for simultaneous arrivals, single-PE tasks and dedicated VM CPUs. */
public class FCFSDatacenterBroker extends DatacenterBroker {
    public FCFSDatacenterBroker(String name) throws Exception {
        super(name);
    }

    public void scheduleTasksToVms(List<Cloudlet> tasks, List<Vm> vms, boolean roundRobin) {
        if (vms.isEmpty()) throw new IllegalArgumentException("At least one VM is required");
        double[] available = new double[vms.size()];
        for (int i = 0; i < tasks.size(); i++) {
            int selected = roundRobin ? i % vms.size() : 0;
            if (!roundRobin) { 
                for (int j = 1; j < vms.size(); j++) {
                    if (available[j] < available[selected]) 
                    selected = j;
                }
            }
            Cloudlet task = tasks.get(i);
            Vm vm = vms.get(selected);
            bindCloudletToVm(task.getCloudletId(), vm.getId());
            available[selected] += task.getCloudletLength() / vm.getMips();
        }
    }
}
