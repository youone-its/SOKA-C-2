/*
 * Title:        CloudSim Toolkit
 * Description:  CloudSim (Cloud Simulation) Toolkit for Modeling and Simulation of Clouds
 * Licence:      GPL - http://www.gnu.org/copyleft/gpl.html
 *
 * Copyright (c) 2009-2012, The University of Melbourne, Australia
 */

package org.cloudbus.cloudsim.core;

import org.cloudbus.cloudsim.Log;

import java.util.Iterator;
import java.util.PriorityQueue;

/**
 * This class implements the event queue used by {@link CloudSim}.
 *
 * @author Remo Andreoli
 * @since CloudSim Toolkit 7.0
 *
 */
public class EventQueue extends PriorityQueue<SimEvent> {
	/** A incremental number used for event attribute */
	private long serial = 0;
	private long serialFirst = Long.MIN_VALUE;

	/**
	 * Adds a new event to the queue. Adding a new event to the queue preserves the temporal order of
	 * the events in the queue.
	 * 
	 * @param newEvent The event to be put in the queue.
	 */
	public void addEvent(SimEvent newEvent) {
		newEvent.setSerial(serial++);
		this.add(newEvent);
	}

	/**
	 * Adds a new event to the head of the queue.
	 * 
	 * @param newEvent The event to be put in the queue.
	 */
	public void addEventFirst(SimEvent newEvent) {
		newEvent.setSerial(serialFirst++);
		this.add(newEvent);
	}

	@Override
	public SimEvent poll() {
		return !CloudSim.running() ? null : super.poll();
	}

	@Override
	public SimEvent peek() {
		return !CloudSim.running() ? null : super.peek();
	}

	@Override
	public boolean isEmpty() {
		return !CloudSim.running() || super.isEmpty();
	}

	// TODO: There might be other PriorityQueue methods that need to be overridden to check CloudSim::running

	public void print() {
		Iterator<SimEvent> iter = iterator();
		int i = 0;
		while(iter.hasNext()) {
			Log.printlnConcat("[", i, "] -> ", iter.next().toString());
			i++;
		}
	}
}