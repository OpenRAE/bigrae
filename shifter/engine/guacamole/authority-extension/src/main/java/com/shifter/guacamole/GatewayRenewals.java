package com.shifter.guacamole;

import java.time.Duration;
import java.util.UUID;
import java.util.function.LongSupplier;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.io.IOException;

final class GatewayRenewals implements AutoCloseable {
    /** Largest number of concurrent sessions one gateway admits. */
    static final int MAX_CAPACITY = 2048;
    /** Parallel control calls; each call can take most of a second under event load. */
    static final int RENEWAL_WORKERS = 16;
    /** Time from one renewal attempt of a lease to its next attempt. */
    static final Duration RENEWAL_INTERVAL = Duration.ofSeconds(15);
    interface Control extends AutoCloseable {
        boolean authorize(UUID bootstrap) throws IOException;
        default void close() {}
    }
    private final Control control;
    private final LongSupplier clock;
    private final Duration lifetime;
    private final long intervalNanos;
    private final Semaphore capacity;
    private final ConcurrentMap<AuthorityLease, Registration> registrations = new ConcurrentHashMap<>();
    private final ThreadPoolExecutor workers;
    private boolean closed;

    private static final class Registration {
        final UUID bootstrap;
        final AtomicBoolean pending = new AtomicBoolean();
        /** Clock reading of the last renewal attempt, or of admission. */
        volatile long lastAttempt;
        Registration(UUID bootstrap, long admitted) { this.bootstrap = bootstrap; this.lastAttempt = admitted; }
    }

    GatewayRenewals(Control control, LongSupplier clock, Duration lifetime, int capacity) {
        this(control, clock, lifetime, capacity, RENEWAL_INTERVAL);
    }

    GatewayRenewals(Control control, LongSupplier clock, Duration lifetime, int capacity, Duration interval) {
        if (capacity < 1 || capacity > MAX_CAPACITY) throw new IllegalArgumentException("Invalid gateway capacity");
        if (interval.isZero() || interval.isNegative()) throw new IllegalArgumentException("Invalid renewal interval");
        this.intervalNanos = interval.toNanos();
        this.control = control;
        this.clock = clock;
        this.lifetime = lifetime;
        this.capacity = new Semaphore(capacity);
        workers = new ThreadPoolExecutor(RENEWAL_WORKERS, RENEWAL_WORKERS, 0, TimeUnit.SECONDS, new ArrayBlockingQueue<>(capacity), task -> {
            Thread thread = new Thread(task, "shifter-guacamole-renewal");
            thread.setDaemon(true);
            return thread;
        }, new ThreadPoolExecutor.AbortPolicy());
    }

    AuthorityLease admit(UUID bootstrap) throws IOException {
        if (!capacity.tryAcquire()) throw new IllegalStateException("Gateway authority capacity exhausted");
        AuthorityLease lease = new AuthorityLease(clock, lifetime);
        boolean installed = false;
        try {
            if (!control.authorize(bootstrap) || !lease.isValid())
                throw new IllegalStateException("Gateway authority refused");
            synchronized (this) {
                if (closed) throw new IllegalStateException("Gateway authority unavailable");
                registrations.put(lease, new Registration(bootstrap, clock.getAsLong()));
                installed = true;
            }
            return lease;
        }
        finally {
            if (!installed) { lease.deny(); capacity.release(); }
        }
    }

    void release(AuthorityLease lease) {
        lease.deny();
        if (registrations.remove(lease) != null) capacity.release();
    }

    /**
     * Submit each lease whose last attempt is at least one interval old. Call
     * this often (for example every second). Each lease then renews on its own
     * schedule, so renewals spread out by admission time instead of arriving
     * at the control endpoint in one burst.
     */
    void renew() {
        long now = clock.getAsLong();
        registrations.forEach((lease, registration) -> {
            if (!lease.isValid()) { release(lease); return; }
            long previous = registration.lastAttempt;
            // Subtraction remains valid when System.nanoTime() wraps.
            if (now - previous < intervalNanos) return;
            if (!registration.pending.compareAndSet(false, true)) return;
            registration.lastAttempt = now;
            try {
                workers.execute(() -> renewLease(lease, registration));
            }
            catch (RejectedExecutionException saturated) {
                // A full bounded queue cannot extend a lease. Retry on the next tick.
                registration.lastAttempt = previous;
                registration.pending.set(false);
            }
        });
    }

    private void renewLease(AuthorityLease lease, Registration registration) {
        try {
            if (!lease.isValid()) return;
            if (control.authorize(registration.bootstrap)) lease.renew();
            else lease.deny();
        }
        catch (Exception unavailable) {
            // Failure retains the existing deadline without logging proof or response data.
        }
        finally { registration.pending.set(false); }
    }

    public synchronized void close() {
        closed = true;
        registrations.keySet().forEach(this::release);
        workers.shutdownNow();
        control.close();
    }
}
