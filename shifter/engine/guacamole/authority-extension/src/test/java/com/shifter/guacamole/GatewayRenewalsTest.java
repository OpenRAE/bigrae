package com.shifter.guacamole;

import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class GatewayRenewalsTest {
    @Test void blockedControlWorkersCannotBlockLocalExpiryForTheAdmittedLoad() throws Exception {
        AtomicLong clock = new AtomicLong();
        AtomicBoolean unavailable = new AtomicBoolean();
        CountDownLatch blocked = new CountDownLatch(4);
        CountDownLatch unblock = new CountDownLatch(1);
        java.util.List<AuthorityLease> leases = new java.util.ArrayList<>();
        try (GatewayRenewals renewals = new GatewayRenewals(id -> {
            if (unavailable.get()) {
                blocked.countDown();
                try { unblock.await(5, TimeUnit.SECONDS); }
                catch (InterruptedException interrupted) { throw new java.io.IOException(); }
                throw new java.io.IOException("Synthetic outage");
            }
            return true;
        }, clock::get, Duration.ofNanos(100), 512, Duration.ofNanos(10))) {
            for (int session = 0; session < 512; session++) leases.add(renewals.admit(UUID.randomUUID()));
            unavailable.set(true);
            clock.set(10);
            renewals.renew();
            assertTrue(blocked.await(2, TimeUnit.SECONDS));
            clock.set(100);
            for (AuthorityLease lease : leases) {
                assertFalse(lease.isValid());
                assertFalse(lease.renew());
            }
            unblock.countDown();
        }
    }
    @Test void everyAdmittedSessionGetsABoundedRenewalSlotUnderConcurrentLoad() throws Exception {
        AtomicLong clock = new AtomicLong();
        AtomicBoolean renewing = new AtomicBoolean();
        CountDownLatch unblock = new CountDownLatch(1);
        CountDownLatch renewed = new CountDownLatch(512);
        try (GatewayRenewals renewals = new GatewayRenewals(id -> {
            if (renewing.get()) {
                try { unblock.await(5, TimeUnit.SECONDS); }
                catch (InterruptedException interrupted) { throw new java.io.IOException(); }
                renewed.countDown();
            }
            return true;
        }, clock::get, Duration.ofSeconds(90), 512)) {
            for (int session = 0; session < 512; session++) renewals.admit(UUID.randomUUID());
            renewing.set(true);
            clock.set(GatewayRenewals.RENEWAL_INTERVAL.toNanos());
            renewals.renew();
            unblock.countDown();
            assertTrue(renewed.await(5, TimeUnit.SECONDS), "Admitted sessions must not be skipped by queue saturation");
        }
    }
    @Test void capacityAcceptsTheEventLoadAndRejectsAnythingAboveTheBound() {
        GatewayRenewals.Control allow = id -> true;
        assertThrows(IllegalArgumentException.class,
            () -> new GatewayRenewals(allow, () -> 0, Duration.ofSeconds(90), GatewayRenewals.MAX_CAPACITY + 1));
        assertThrows(IllegalArgumentException.class, () -> new GatewayRenewals(allow, () -> 0, Duration.ofSeconds(90), 0));
        new GatewayRenewals(allow, () -> 0, Duration.ofSeconds(90), GatewayRenewals.MAX_CAPACITY).close();
    }

    @Test void renewalsRunInParallelUpToTheWorkerBound() throws Exception {
        AtomicLong clock = new AtomicLong();
        AtomicBoolean renewing = new AtomicBoolean();
        CountDownLatch concurrent = new CountDownLatch(GatewayRenewals.RENEWAL_WORKERS);
        CountDownLatch unblock = new CountDownLatch(1);
        try (GatewayRenewals renewals = new GatewayRenewals(id -> {
            if (renewing.get()) {
                concurrent.countDown();
                try { unblock.await(5, TimeUnit.SECONDS); }
                catch (InterruptedException interrupted) { throw new java.io.IOException(); }
            }
            return true;
        }, clock::get, Duration.ofSeconds(90), GatewayRenewals.MAX_CAPACITY)) {
            for (int session = 0; session < GatewayRenewals.RENEWAL_WORKERS * 2; session++) renewals.admit(UUID.randomUUID());
            renewing.set(true);
            clock.set(GatewayRenewals.RENEWAL_INTERVAL.toNanos());
            renewals.renew();
            assertTrue(concurrent.await(2, TimeUnit.SECONDS), "Slow control calls must not serialize renewals");
            unblock.countDown();
        }
    }

    /** Counts renewal calls (calls after admission) per bootstrap. */
    private static final class CountingControl implements GatewayRenewals.Control {
        final java.util.Set<UUID> admitted = java.util.concurrent.ConcurrentHashMap.newKeySet();
        final java.util.concurrent.ConcurrentMap<UUID, java.util.concurrent.atomic.AtomicInteger> renewals =
            new java.util.concurrent.ConcurrentHashMap<>();
        public boolean authorize(UUID bootstrap) {
            if (admitted.add(bootstrap)) return true;
            renewals.computeIfAbsent(bootstrap, id -> new java.util.concurrent.atomic.AtomicInteger()).incrementAndGet();
            return true;
        }
        int count(UUID bootstrap) {
            java.util.concurrent.atomic.AtomicInteger value = renewals.get(bootstrap);
            return value == null ? 0 : value.get();
        }
    }

    private static void awaitCount(CountingControl control, UUID bootstrap, int expected) throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (control.count(bootstrap) < expected && System.nanoTime() < deadline) Thread.sleep(5);
        assertEquals(expected, control.count(bootstrap));
    }

    @Test void leasesAdmittedAtDifferentTimesRenewOnDifferentTicks() throws Exception {
        AtomicLong clock = new AtomicLong();
        CountingControl control = new CountingControl();
        long interval = GatewayRenewals.RENEWAL_INTERVAL.toNanos();
        long second = TimeUnit.SECONDS.toNanos(1);
        try (GatewayRenewals renewals = new GatewayRenewals(control, clock::get, Duration.ofSeconds(90), 16)) {
            UUID early = UUID.randomUUID();
            UUID late = UUID.randomUUID();
            renewals.admit(early);
            clock.set(5 * second);
            renewals.admit(late);
            clock.set(interval);
            renewals.renew();
            awaitCount(control, early, 1);
            Thread.sleep(50);
            assertEquals(0, control.count(late), "A lease admitted later must not renew in the same tick");
            clock.set(interval + 5 * second);
            renewals.renew();
            awaitCount(control, late, 1);
            assertEquals(1, control.count(early), "The early lease must not renew again before its interval");
        }
    }

    @Test void aLeaseRenewsAgainOnlyAfterTheIntervalSinceItsLastAttempt() throws Exception {
        AtomicLong clock = new AtomicLong();
        CountingControl control = new CountingControl();
        long interval = GatewayRenewals.RENEWAL_INTERVAL.toNanos();
        try (GatewayRenewals renewals = new GatewayRenewals(control, clock::get, Duration.ofSeconds(90), 16)) {
            UUID session = UUID.randomUUID();
            AuthorityLease lease = renewals.admit(session);
            clock.set(interval - 1);
            renewals.renew();
            Thread.sleep(50);
            assertEquals(0, control.count(session), "A new lease must wait one interval before its first renewal");
            clock.set(interval);
            renewals.renew();
            awaitCount(control, session, 1);
            clock.set(interval + TimeUnit.SECONDS.toNanos(1));
            renewals.renew();
            Thread.sleep(50);
            assertEquals(1, control.count(session), "Ticks inside the interval must not renew again");
            clock.set(2 * interval);
            renewals.renew();
            awaitCount(control, session, 2);
            assertTrue(lease.isValid());
        }
    }

    @Test void deniedRenewalEndsTheLease() throws Exception {
        AtomicLong clock = new AtomicLong();
        AtomicBoolean deny = new AtomicBoolean();
        try (GatewayRenewals renewals = new GatewayRenewals(id -> !deny.get(), clock::get, Duration.ofSeconds(90), 1)) {
            AuthorityLease lease = renewals.admit(UUID.randomUUID());
            deny.set(true);
            clock.set(GatewayRenewals.RENEWAL_INTERVAL.toNanos());
            renewals.renew();
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (lease.isValid() && System.nanoTime() < deadline) Thread.sleep(5);
            assertFalse(lease.isValid());
        }
    }

    @Test void renewalIntervalMustBePositive() {
        GatewayRenewals.Control allow = id -> true;
        assertThrows(IllegalArgumentException.class,
            () -> new GatewayRenewals(allow, () -> 0, Duration.ofSeconds(90), 1, Duration.ZERO));
    }

    @Test void deniedInitialAuthorityCannotCreateASession() throws Exception {
        try (GatewayRenewals renewals = new GatewayRenewals(id -> false, () -> 0, Duration.ofSeconds(90), 1)) {
            assertThrows(Exception.class, () -> renewals.admit(UUID.randomUUID()));
        }
    }

    @Test void admissionIsBoundedAndInvalidationReleasesCapacity() throws Exception {
        try (GatewayRenewals renewals = new GatewayRenewals(id -> true, () -> 0, Duration.ofSeconds(90), 1)) {
            AuthorityLease first = renewals.admit(UUID.randomUUID());
            assertThrows(Exception.class, () -> renewals.admit(UUID.randomUUID()));
            renewals.release(first);
            renewals.release(first);
            assertFalse(first.isValid());
            assertNotNull(renewals.admit(UUID.randomUUID()));
            assertThrows(Exception.class, () -> renewals.admit(UUID.randomUUID()));
        }
    }

    @Test void gatewayShutdownInvalidatesEveryRegisteredSession() throws Exception {
        GatewayRenewals renewals = new GatewayRenewals(id -> true, () -> 0, Duration.ofSeconds(90), 1);
        AuthorityLease lease = renewals.admit(UUID.randomUUID());
        renewals.close();
        assertFalse(lease.isValid());
        assertThrows(Exception.class, () -> renewals.admit(UUID.randomUUID()));
    }

    @Test void slowInitialControlCannotInstallAnAlreadyExpiredLease() throws Exception {
        AtomicLong clock = new AtomicLong();
        try (GatewayRenewals renewals = new GatewayRenewals(id -> { clock.set(100); return true; }, clock::get, Duration.ofNanos(100), 1)) {
            assertThrows(Exception.class, () -> renewals.admit(UUID.randomUUID()));
        }
    }
}
