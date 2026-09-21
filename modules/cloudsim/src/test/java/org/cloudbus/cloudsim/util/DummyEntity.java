package org.cloudbus.cloudsim.util;

import org.cloudbus.cloudsim.core.CloudSim;
import org.cloudbus.cloudsim.core.SimEntity;
import org.cloudbus.cloudsim.core.SimEvent;

import java.util.ArrayList;
import java.util.List;

public class DummyEntity extends SimEntity {

	private final List<TimedSimEvent> receivedEvents = new ArrayList<>();
	public Runnable onStart;
	public boolean shutdown = false;

	public DummyEntity(String name) {
		super(name);
	}

	@Override
	public void startEntity() {
		super.startEntity();
		if (onStart != null) {
			onStart.run();
		}
	}

	@Override
	public void processEvent(SimEvent ev) {
		receivedEvents.add(new TimedSimEvent(ev.getData(), CloudSim.clock()));
	}

	public List<TimedSimEvent> receivedEvents() {
		return receivedEvents;
	}

	@Override
	public void shutdownEntity() {
		super.shutdownEntity();
		shutdown = true;
	}

	public record TimedSimEvent(Object data, double time) {
		//
	}
}
