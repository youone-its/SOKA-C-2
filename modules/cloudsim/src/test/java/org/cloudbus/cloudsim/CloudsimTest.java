package org.cloudbus.cloudsim;

import org.cloudbus.cloudsim.core.CloudActionTags;
import org.cloudbus.cloudsim.core.CloudSim;
import org.cloudbus.cloudsim.core.SimEvent;
import org.cloudbus.cloudsim.core.predicates.Predicate;
import org.cloudbus.cloudsim.util.DummyEntity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.*;

class CloudsimTest {

	private DummyEntity sender;
	private DummyEntity receiver;

	@BeforeEach
	void setup() {
		CloudSim.init(2, null, false, 0.1);
		sender = new DummyEntity("Sender");
		receiver = new DummyEntity("Receiver");
	}

	@Test
	void testSimGet() {
		assertEquals(2 + 2, CloudSim.getNumEntities());
		assertTrue(CloudSim.getEntityList().containsAll(Arrays.asList(sender, receiver)));
		assertNotNull(CloudSim.getSimulationCalendar());

		assertEquals(sender, CloudSim.getEntity(sender.getId()));
		assertEquals(sender, CloudSim.getEntity(sender.getName()));
		assertEquals(sender.getId(), CloudSim.getEntityId(sender.getName()));
		assertEquals(sender.getName(), CloudSim.getEntityName(sender.getId()));
		assertEquals(sender.getName(), CloudSim.getEntityName(Integer.valueOf(sender.getId())));

		assertEquals(receiver, CloudSim.getEntity(receiver.getId()));
		assertEquals(receiver, CloudSim.getEntity(receiver.getName()));
		assertEquals(receiver.getId(), CloudSim.getEntityId(receiver.getName()));
		assertEquals(receiver.getName(), CloudSim.getEntityName(receiver.getId()));
		assertEquals(receiver.getName(), CloudSim.getEntityName(Integer.valueOf(receiver.getId())));

		assertThrows(IndexOutOfBoundsException.class, () -> CloudSim.getEntity(-1));
		assertNull(CloudSim.getEntity("unknown"));
		assertEquals(CloudSim.NOT_FOUND, CloudSim.getEntityId("unknown"));
		assertNull(CloudSim.getEntityName(-1));
		assertNull(CloudSim.getEntityName(Integer.valueOf(-1)));
	}

	@Test
	void testSimAdd() {
		CloudSim.runStart();

		// This auto-registers.
		final var dynamic = new DummyEntity("Dynamic");
		dynamic.onStart = () -> dynamic.schedule(receiver.getId(), 5, null, "from dynamic");

		final var last = CloudSim.run();

		assertEquals(1, receiver.receivedEvents().size());
		assertEquals(5, last);
	}

	@Test
	void testSimAddNull() {
		assertThrows(NullPointerException.class, () -> CloudSim.addEntity(null));
	}

	@Test
	void testScheduleSingleEvent() {
		final var DATA = "Hello";
		final var DELAY = 1.0;

		sender.onStart = () -> {
			sender.schedule(receiver.getId(), DELAY, null, DATA);
		};
		final var last = CloudSim.run();

		assertEquals(1, receiver.receivedEvents().size());
		assertEquals(DATA, receiver.receivedEvents().getFirst().data());
		assertEquals(DELAY, last);
	}

	@Test
	void testScheduleMultipleEventsInOrder() {
		final var DATA_1 = "First";
		final var DATA_2 = "Second";

		sender.onStart = () -> {
			sender.schedule(receiver.getId(), 2.0, null, DATA_2);
			sender.schedule(receiver.getId(), 1.0, null, DATA_1);
		};
		CloudSim.run();

		var received = receiver.receivedEvents();
		assertEquals(2, received.size());
		assertEquals(DATA_1, received.get(0).data());
		assertEquals(DATA_2, received.get(1).data());
	}

	@Test
	void testScheduleFirst() {
		final var DATA_1 = "First";
		final var DATA_2 = "Second";

		sender.onStart = () -> {
			sender.schedule(receiver.getId(), 1.0, null, DATA_2);
			sender.scheduleFirst(receiver.getId(), 1.0, null, DATA_1);
		};
		CloudSim.run();

		var received = receiver.receivedEvents();
		assertEquals(2, received.size());
		assertEquals(DATA_1, received.get(0).data());
		assertEquals(DATA_2, received.get(1).data());
	}


	@Test
	void testScheduleFirstNow() {
		final var DATA_NOW = "Immediate";
		final var DATA_LATER = "Later";

		sender.onStart = () -> {
			sender.scheduleNow(receiver.getId(), null, DATA_LATER);
			sender.scheduleFirstNow(receiver.getId(), null, DATA_NOW);
		};
		CloudSim.run();

		var received = receiver.receivedEvents();
		assertEquals(2, received.size());
		assertEquals(DATA_NOW, received.get(0).data());
		assertEquals(DATA_LATER, received.get(1).data());
	}

	@Test
	void testScheduleInvalid() {
		double[] invalidDelays = {-1.0, Double.NEGATIVE_INFINITY, Double.MAX_VALUE, Double.POSITIVE_INFINITY};

		for (double invalidDelay : invalidDelays) {
			this.setup();
			sender.onStart = () -> {
				assertThrows(IllegalArgumentException.class, () -> sender.schedule(receiver.getId(), invalidDelay, null, "InvalidDelay"));
			};
			CloudSim.run();
		}
	}

	@Test
	void testScheduleFirstInvalid() {
		double[] invalidDelays = {-1.0, Double.NEGATIVE_INFINITY, Double.MAX_VALUE, Double.POSITIVE_INFINITY};

		for (double invalidDelay : invalidDelays) {
			this.setup();
			sender.onStart = () -> {
				assertThrows(IllegalArgumentException.class, () -> sender.scheduleFirst(receiver.getId(), invalidDelay, null, "InvalidDelay"));
			};
			CloudSim.run();
		}
	}

	@Test
	void testEntityPause() {
		final var EVENT_DELAY = 5;
		final var RECEIVER_PAUSE = 10;

		sender.onStart = () -> {
			receiver.pause(RECEIVER_PAUSE);
			sender.schedule(receiver.getId(), EVENT_DELAY, null, "delayed by pause");
		};
		final var last = CloudSim.run();
		assertEquals(RECEIVER_PAUSE, receiver.receivedEvents().getFirst().time());
		assertEquals(RECEIVER_PAUSE, last);
	}

	@Test
	void testEntityCancelEvent() {
		sender.onStart = () -> {
			sender.schedule(receiver.getId(), 2, null, "delivered");
			sender.schedule(receiver.getId(), 1, null, "canceled");
			sender.cancelEvent(CloudSim.SIM_ANY);
		};
		final var last = CloudSim.run();
		assertEquals(1, receiver.receivedEvents().size());
		assertEquals(2, receiver.receivedEvents().getFirst().time());
		assertEquals(2, last);
	}

	@Test
	void testEntityCancelEventEmpty() {
		sender.onStart = () -> {
			sender.cancelEvent(CloudSim.SIM_ANY);
			sender.schedule(receiver.getId(), 1, null, "delivered");
			sender.schedule(receiver.getId(), 2, null, "delivered");
		};
		final var last = CloudSim.run();
		assertEquals(2, receiver.receivedEvents().size());
		assertEquals(2, last);
	}


	@Test
	void testCancelAllEvent() {
		sender.onStart = () -> {
			sender.schedule(receiver.getId(), 2, null, "delivered");
			sender.schedule(receiver.getId(), 1, null, "canceled");
			CloudSim.cancelAll(sender.getId(), CloudSim.SIM_ANY);
		};
		final var last = CloudSim.run();
		assertEquals(0, receiver.receivedEvents().size());
		assertEquals(0, last);
	}

	@Test
	void testCancelAllEventEmpty() {
		sender.onStart = () -> {
			CloudSim.cancelAll(sender.getId(), CloudSim.SIM_ANY);
			sender.schedule(receiver.getId(), 1, null, "delivered");
			sender.schedule(receiver.getId(), 2, null, "delivered");
		};
		final var last = CloudSim.run();
		assertEquals(2, receiver.receivedEvents().size());
		assertEquals(2, last);
	}


	@Test
	void testEntityWaitFor() {
		final var EVENT_DELAY_1 = 1;
		final var EVENT_DELAY_2 = 2;
		final var EVENT_DELAY_3 = 3;

		sender.onStart = () -> {
			receiver.waitForEvent(new Predicate() {
				int counter = 0;

				@Override
				public boolean match(SimEvent event) {
					counter += 1;
					return counter == 2;
				}
			});
			sender.schedule(receiver.getId(), EVENT_DELAY_1, null, "ignored");
			sender.schedule(receiver.getId(), EVENT_DELAY_2, null, "wakes up");
			sender.schedule(receiver.getId(), EVENT_DELAY_3, null, "standard");
		};
		final var last = CloudSim.run();
		assertEquals(3, receiver.receivedEvents().size());
		assertEquals(EVENT_DELAY_2, receiver.receivedEvents().get(0).time());
		assertEquals(EVENT_DELAY_2, receiver.receivedEvents().get(1).time());
		assertEquals(EVENT_DELAY_3, receiver.receivedEvents().get(2).time());
		assertEquals(EVENT_DELAY_3, last);
	}

	@Test
	void testSimPause() {
		sender.onStart = () -> {
			sender.schedule(receiver.getId(), 1, null, "before pause");
			sender.schedule(receiver.getId(), 2, null, "after pause");

			new Thread(() -> {
				try {
					Thread.sleep(1000);
				} catch (InterruptedException e) {
					// ignore.
				}
				assertTrue(CloudSim.isPaused());
				// Clock is 1 (instead of 0) because the sim loop runs the first event before checking for pauses.
				assertEquals(1, CloudSim.clock());
				CloudSim.resumeSimulation();
			}).start();
			CloudSim.pauseSimulation();
		};
		final var last = CloudSim.run();

		assertEquals(2, receiver.receivedEvents().size());
		assertEquals(2, last);
	}

	@Test
	void testSimPauseAt() {
		sender.onStart = () -> {
			sender.schedule(receiver.getId(), 1, null, "before pause");
			sender.schedule(receiver.getId(), 5, null, "after pause");

			new Thread(() -> {
				try {
					Thread.sleep(1000);
				} catch (InterruptedException e) {
					// ignore.
				}
				assertTrue(CloudSim.isPaused());
				assertEquals(2, CloudSim.clock());
				CloudSim.resumeSimulation();
			}).start();
			CloudSim.pauseSimulation(2);
		};
		final var last = CloudSim.run();

		assertEquals(2, receiver.receivedEvents().size());
		assertEquals(5, last);
	}

	@Test
	void testSimTerminate() {
		sender.onStart = () -> {
			sender.schedule(receiver.getId(), 5, null, "ShouldNotBeDelivered");
			sender.schedule(receiver.getId(), 10, null, "ShouldNotBeDelivered");

			CloudSim.terminateSimulation();
		};
		final var last = CloudSim.run();

		assertTrue(receiver.receivedEvents().isEmpty(), "No events should be received because the simulation was terminated");
		assertEquals(0, last);

		assertTrue(sender.shutdown);
		assertTrue(receiver.shutdown);
	}

	@Test
	void testSimTerminateAt() {
		sender.onStart = () -> {
			sender.schedule(receiver.getId(), 5, null, "ShouldNotBeDelivered");
			sender.schedule(receiver.getId(), 10, null, "ShouldNotBeDelivered");

			CloudSim.terminateSimulation(2);
		};
		final var last = CloudSim.run();

		assertTrue(receiver.receivedEvents().isEmpty(), "No events should be received because the simulation was terminated");
		assertEquals(2, last);

		assertTrue(sender.shutdown);
		assertTrue(receiver.shutdown);
	}

	@Test
	void testSimAbruptallyTerminate() {
		sender.onStart = () -> {
			sender.schedule(receiver.getId(), 5, null, "ShouldNotBeDelivered");
			sender.schedule(receiver.getId(), 10, null, "ShouldNotBeDelivered");

			// This will be ignored.
			CloudSim.pauseSimulation(2);

			// This will be ignored.
			CloudSim.terminateSimulation(3);

			// Will stop it after the next tick, so at clock = 5.
			// But with no events delivered on that clock.
			CloudSim.abruptallyTerminate();
		};
		final var last = CloudSim.run();

		assertTrue(receiver.receivedEvents().isEmpty(), "No events should be received because simulation was terminated.");
		assertEquals(5, last);

		assertTrue(sender.shutdown);
		assertTrue(receiver.shutdown);
	}

	@Test
	void testSimAbruptallyTerminateThroughEventTag() {
		sender.onStart = () -> {
			sender.schedule(CloudSim.getEntityId("CloudSimShutdown"), 1, CloudActionTags.ABRUPT_END_OF_SIMULATION, null);
			sender.schedule(receiver.getId(), 5, null, "ShouldNotBeDelivered");
		};
		final var last = CloudSim.run();

		assertTrue(receiver.receivedEvents().isEmpty(), "No events should be received because simulation was terminated.");
		assertEquals(5, last);

		assertTrue(sender.shutdown);
		assertTrue(receiver.shutdown);
	}

	@Test
	void testSimAbruptallyTerminateThroughNoMoreUsers() {
		sender.onStart = () -> {
			sender.schedule(CloudSim.getEntityId("CloudSimShutdown"), 1, null, null);
			receiver.schedule(CloudSim.getEntityId("CloudSimShutdown"), 1, null, null);
			sender.schedule(receiver.getId(), 5, null, "ShouldNotBeDelivered");
		};
		final var last = CloudSim.run();

		assertTrue(receiver.receivedEvents().isEmpty(), "No events should be received because simulation was terminated.");
		assertEquals(5, last);

		assertTrue(sender.shutdown);
		assertTrue(receiver.shutdown);
	}

	@Test
	void testScheduleWithInvalidDestination() {
		sender.onStart = () -> {
			sender.schedule(-99, 1.0, null, "InvalidTarget");
		};
		assertThrows(IndexOutOfBoundsException.class, CloudSim::run);
	}

	@Test
	void testSendFirstConsistentOrder() {
		sender.onStart = () -> {
			sender.scheduleFirst(receiver.getId(), 5, null, "A");
			sender.scheduleFirst(receiver.getId(), 5, null, "B");
			sender.scheduleFirst(receiver.getId(), 5, null, "C");
		};
		final var last = CloudSim.run();

		assertEquals("A", receiver.receivedEvents().get(0).data());
		assertEquals("B", receiver.receivedEvents().get(1).data());
		assertEquals("C", receiver.receivedEvents().get(2).data());
	}
}
