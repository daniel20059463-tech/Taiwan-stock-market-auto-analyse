"""
Strict pytest acceptance tests for the State Store module.

Test matrix
───────────────────────────────────────────────────────────────
test_concurrent_buys_two_succeed_one_fails
    • 100 balance, 3 concurrent asyncio.gather buys @ 40 each
    • Assert: exactly 2 success, 1 InsufficientBalanceError
    • Assert: balance == 20, position.quantity == 2, len(txns) == 2

test_idempotency_duplicate_request_blocked
    • Same request_id sent twice
    • Assert: second call raises DuplicateRequestError
    • Assert: balance decremented exactly once (200 → 160)
    • Assert: exactly 1 ledger record

test_balance_invariant_prevents_overdraft
    • Single buy that would exceed balance
    • Assert: InsufficientBalanceError, balance unchanged, no ledger record

Running
───────
    # self-contained (uses embedded PostgreSQL via pgserver — no install needed)
    .venv/Scripts/pip install sqlalchemy[asyncio] asyncpg pytest pytest-asyncio pgserver
    .venv/Scripts/pytest test_db.py -v
"""
from __future__ import annotations

import asyncio
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pgserver = pytest.importorskip(
    "pgserver",
    reason="test_db.py requires the optional embedded PostgreSQL dependency 'pgserver'.",
)

from models import (
    Base,
    DuplicateRequestError,
    InsufficientBalanceError,
    Position,
    Transaction,
    User,
    execute_buy,
)

# ──────────────────────────────────────────────────────────────────────────────
# Embedded PostgreSQL (pgserver)
# pgserver downloads pre-compiled binaries and starts a local server in a
# temporary directory — no PostgreSQL installation required.
#
# Session-scoped engine: create schema once, destroy after all tests finish.
# Function-scoped TRUNCATE keeps individual tests isolated without the overhead
# of rebuilding the schema on every test.
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def pg_server(tmp_path_factory):
    """Start an embedded PostgreSQL in a temp dir; stop it after the session."""
    pg_dir = tmp_path_factory.mktemp("pgdata")
    server = pgserver.get_server(pg_dir, cleanup_mode="delete")
    yield server


@pytest_asyncio.fixture(scope="session")
async def test_engine(pg_server):
    """Build tables once per test session; drop them on teardown."""
    # pgserver returns a postgresql:// URI; swap in the asyncpg driver prefix.
    raw_uri = pg_server.get_uri()
    async_url = raw_uri.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(async_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(test_engine):
    """Return an async session factory bound to the test engine."""
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(test_engine):
    """
    Truncate all data before every test.
    RESTART IDENTITY resets sequences; CASCADE handles FK ordering.
    """
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE transactions, positions, users "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


async def create_user(
    session_factory: async_sessionmaker,
    username: str,
    balance: Decimal,
) -> uuid.UUID:
    """Insert a user and return their UUID."""
    async with session_factory() as session:
        async with session.begin():
            user = User(username=username, balance=balance)
            session.add(user)
            await session.flush()
            return user.id


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 – Concurrent buys
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_buys_two_succeed_one_fails(session_factory):
    """
    Acceptance criteria (strict)
    ────────────────────────────
    Setup : balance = 100 | symbol = BTC | unit_price = 40 | quantity = 1

    3 concurrent buy orders are fired with asyncio.gather.
    Because each session uses SELECT … FOR UPDATE, the DB serialises the
    three writes.  The first two deplete the balance (100→60→20); the third
    can no longer afford 40 and is rejected.

    Assertions
        outcomes    : exactly 2 "success", exactly 1 "failed"
        balance     : Decimal("20")   (100 - 40 - 40)
        position    : quantity == Decimal("2")   (2 successful lots)
        transactions: len == 2   (immutable ledger matches successes)
        total_amount: Decimal("80")  (sanity: 2 × 40)
    """
    user_id = await create_user(session_factory, "trader_concurrent", Decimal("100"))

    outcomes: list[str] = []
    outcomes_lock = asyncio.Lock()  # protect the shared Python list only

    async def attempt_buy(req_id: str) -> None:
        """Each coroutine opens its own session — they compete for FOR UPDATE."""
        async with session_factory() as session:
            async with session.begin():
                try:
                    await execute_buy(
                        session,
                        user_id=user_id,
                        symbol="BTC",
                        quantity=Decimal("1"),
                        price=Decimal("40"),
                        request_id=req_id,
                    )
                    async with outcomes_lock:
                        outcomes.append("success")
                except InsufficientBalanceError:
                    async with outcomes_lock:
                        outcomes.append("failed")

    # Fire all three at once and wait for all to settle.
    await asyncio.gather(
        attempt_buy("concurrent-req-1"),
        attempt_buy("concurrent-req-2"),
        attempt_buy("concurrent-req-3"),
    )

    # ── Outcome assertions ────────────────────────────────────────────────────
    n_success = outcomes.count("success")
    n_failed = outcomes.count("failed")

    assert n_success == 2, (
        f"Expected exactly 2 successes, got {n_success}. "
        f"Full outcomes: {outcomes}"
    )
    assert n_failed == 1, (
        f"Expected exactly 1 failure, got {n_failed}. "
        f"Full outcomes: {outcomes}"
    )

    # ── Final DB state assertions ─────────────────────────────────────────────
    async with session_factory() as session:

        # Balance: 100 − 40 − 40 = 20
        user = await session.get(User, user_id)
        assert user.balance == Decimal("20"), (
            f"Expected balance Decimal('20'), got {user.balance!r}"
        )

        # Position: 2 successful lots of 1 unit each
        pos_result = await session.execute(
            select(Position).where(
                Position.user_id == user_id,
                Position.symbol == "BTC",
            )
        )
        position = pos_result.scalar_one()
        assert position.quantity == Decimal("2"), (
            f"Expected position.quantity Decimal('2'), got {position.quantity!r}"
        )

        # Ledger: exactly 2 records, total amount = 80
        txn_result = await session.execute(
            select(Transaction).where(Transaction.user_id == user_id)
        )
        transactions = txn_result.scalars().all()
        assert len(transactions) == 2, (
            f"Expected 2 transaction records, got {len(transactions)}"
        )

        total_amount = sum(t.amount for t in transactions)
        assert total_amount == Decimal("80"), (
            f"Expected total debited Decimal('80'), got {total_amount!r}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Test 2 – Idempotency
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_duplicate_request_blocked(session_factory):
    """
    Acceptance criteria (strict)
    ────────────────────────────
    Setup : balance = 200 | same request_id submitted twice sequentially

    First call  : succeeds → balance = 160, 1 ledger record
    Second call : raises DuplicateRequestError → balance still 160,
                  still only 1 ledger record (no double-deduction)

    This simulates a Telegram retry or network-level at-least-once delivery.
    """
    IDEMPOTENCY_KEY = "idem-key-abc-123"
    user_id = await create_user(
        session_factory, "trader_idempotent", Decimal("200")
    )

    # ── First request: must succeed ───────────────────────────────────────────
    async with session_factory() as session:
        async with session.begin():
            txn = await execute_buy(
                session,
                user_id=user_id,
                symbol="ETH",
                quantity=Decimal("1"),
                price=Decimal("40"),
                request_id=IDEMPOTENCY_KEY,
            )
    assert txn is not None, "First call should return a Transaction object"
    assert txn.amount == Decimal("40")

    # ── Second request with the SAME key: must be rejected ────────────────────
    with pytest.raises(DuplicateRequestError) as exc_info:
        async with session_factory() as session:
            async with session.begin():
                await execute_buy(
                    session,
                    user_id=user_id,
                    symbol="ETH",
                    quantity=Decimal("1"),
                    price=Decimal("40"),
                    request_id=IDEMPOTENCY_KEY,
                )

    # Error message must reference the offending key for debuggability.
    assert IDEMPOTENCY_KEY in str(exc_info.value), (
        f"DuplicateRequestError message should contain the request_id. "
        f"Got: {exc_info.value}"
    )

    # ── Final DB state: exactly one deduction ─────────────────────────────────
    async with session_factory() as session:

        user = await session.get(User, user_id)
        assert user.balance == Decimal("160"), (
            f"Expected balance Decimal('160') (deducted once), got {user.balance!r}"
        )

        txn_result = await session.execute(
            select(Transaction).where(Transaction.user_id == user_id)
        )
        transactions = txn_result.scalars().all()
        assert len(transactions) == 1, (
            f"Expected exactly 1 ledger record (idempotency breach!), "
            f"got {len(transactions)}"
        )
        assert transactions[0].request_id == IDEMPOTENCY_KEY


# ──────────────────────────────────────────────────────────────────────────────
# Test 3 – Balance invariant / overdraft prevention
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_balance_invariant_prevents_overdraft(session_factory):
    """
    A buy whose amount exceeds the available balance must be rejected cleanly,
    leaving the account and ledger completely unchanged.
    """
    user_id = await create_user(
        session_factory, "trader_broke", Decimal("30")
    )

    with pytest.raises(InsufficientBalanceError):
        async with session_factory() as session:
            async with session.begin():
                await execute_buy(
                    session,
                    user_id=user_id,
                    symbol="BTC",
                    quantity=Decimal("1"),
                    price=Decimal("50"),   # 50 > 30 → must fail
                    request_id="overdraft-req",
                )

    async with session_factory() as session:
        user = await session.get(User, user_id)
        assert user.balance == Decimal("30"), (
            "Balance must be completely unchanged after a failed buy"
        )

        txn_result = await session.execute(
            select(Transaction).where(Transaction.user_id == user_id)
        )
        assert txn_result.scalars().first() is None, (
            "No ledger record should exist after a rejected buy"
        )

        pos_result = await session.execute(
            select(Position).where(Position.user_id == user_id)
        )
        assert pos_result.scalars().first() is None, (
            "No position record should exist after a rejected buy"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Test 4 – Atomicity: partial failure leaves no trace
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomicity_no_partial_success(session_factory):
    """
    Simulate the scenario where two concurrent transactions are running for the
    same user, and confirm the FOR UPDATE lock prevents interleaving.

    We run two sequential buys — after each, the DB state must be perfectly
    consistent (no intermediate states observable between balance and ledger).
    """
    user_id = await create_user(
        session_factory, "trader_atomic", Decimal("100")
    )

    async with session_factory() as session:
        async with session.begin():
            await execute_buy(
                session,
                user_id=user_id,
                symbol="BTC",
                quantity=Decimal("2"),
                price=Decimal("30"),   # cost = 60
                request_id="atomic-req-1",
            )

    # Intermediate state check — balance and position must be coherent.
    async with session_factory() as session:
        user = await session.get(User, user_id)
        pos_result = await session.execute(
            select(Position).where(
                Position.user_id == user_id, Position.symbol == "BTC"
            )
        )
        position = pos_result.scalar_one()
        txn_result = await session.execute(
            select(Transaction).where(Transaction.user_id == user_id)
        )
        txns = txn_result.scalars().all()

    assert user.balance == Decimal("40"),  "Balance must be 40 after first buy"
    assert position.quantity == Decimal("2"), "Position must be 2 after first buy"
    assert len(txns) == 1, "Exactly 1 ledger entry after first buy"

    # Second buy that fails: cost = 50 > 40
    with pytest.raises(InsufficientBalanceError):
        async with session_factory() as session:
            async with session.begin():
                await execute_buy(
                    session,
                    user_id=user_id,
                    symbol="BTC",
                    quantity=Decimal("1"),
                    price=Decimal("50"),
                    request_id="atomic-req-2",
                )

    # Nothing must have changed after the failed second buy.
    async with session_factory() as session:
        user = await session.get(User, user_id)
        pos_result = await session.execute(
            select(Position).where(
                Position.user_id == user_id, Position.symbol == "BTC"
            )
        )
        position = pos_result.scalar_one()
        txn_result = await session.execute(
            select(Transaction).where(Transaction.user_id == user_id)
        )
        txns = txn_result.scalars().all()

    assert user.balance == Decimal("40"),  "Balance must still be 40 after failed second buy"
    assert position.quantity == Decimal("2"), "Position must still be 2 after failed buy"
    assert len(txns) == 1, "Still only 1 ledger entry — no partial record from failed buy"
