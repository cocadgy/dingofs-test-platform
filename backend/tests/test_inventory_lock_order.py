import os
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue

from sqlalchemy import create_engine, text

from dingofs_platform.auth.users import lock_accounts
from dingofs_platform.inventory.service import lock_inventory


def test_inventory_lock_also_protects_accounts_until_transaction_ends():
    """An inventory-first request must not let an account-first request overtake it."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        with engine.connect() as first, engine.connect() as second:
            with first.begin():
                lock_inventory(first)
                # Mirrors owned()/actor_in_transaction() after lock_inventory.
                lock_accounts(first)
            with second.begin():
                assert second.scalar(text("SELECT pg_try_advisory_xact_lock(7412082)"))
            with first.begin():
                lock_inventory(first)
                with second.begin():
                    assert not second.scalar(text("SELECT pg_try_advisory_xact_lock(7412082)"))
    finally:
        engine.dispose()


def test_inventory_waiter_does_not_block_account_owner():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    pid = Queue()

    def inventory_request():
        with engine.begin() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            pid.put(db.scalar(text("SELECT pg_backend_pid()")))
            lock_inventory(db)
            lock_accounts(db)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with engine.begin() as account_request:
                lock_accounts(account_request)
                future = pool.submit(inventory_request)
                worker_pid = pid.get(timeout=5)
                deadline = time.monotonic() + 3
                with engine.connect() as observer:
                    while time.monotonic() < deadline:
                        waiting = observer.scalar(text(
                            "SELECT count(*) FROM pg_locks WHERE pid = :pid "
                            "AND locktype = 'advisory' AND NOT granted"
                        ), {"pid": worker_pid})
                        observer.rollback()
                        if waiting:
                            break
                        time.sleep(0.01)
                    assert waiting, "request did not reach the contested lock"
                # A waiter must not hold inventory while waiting for accounts.
                assert account_request.scalar(text(
                    "SELECT pg_try_advisory_xact_lock(7412081)"
                ))
            future.result(timeout=5)
    finally:
        engine.dispose()
