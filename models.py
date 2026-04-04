"""
State Store – ORM models and transactional business logic.

Architecture decisions
──────────────────────
• Invariants   : CHECK constraints on balance >= 0 and quantity >= 0 are
                 enforced at the DB level, so they hold even for raw SQL
                 clients that bypass this application layer.
• Idempotency  : transactions.request_id is UNIQUE. Duplicate submissions
                 (e.g. Telegram retries) are detected and rejected before
                 any money moves.
• Locking      : SELECT … FOR UPDATE (pessimistic) on the user row.
                 See execute_buy() docstring for the rationale.
• Atomicity    : all three mutations (balance ↓, position ↑, ledger insert)
                 happen inside a single DB transaction; partial success is
                 impossible.
"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import AsyncGenerator

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ──────────────────────────────────────────────────────────────────────────────
# Custom domain exceptions
# ──────────────────────────────────────────────────────────────────────────────

class InsufficientBalanceError(Exception):
    """User balance is too low to cover the requested order amount."""


class DuplicateRequestError(Exception):
    """
    request_id has already been processed (idempotency violation).
    The caller should treat this as a success (the operation was already done),
    not as an error that should trigger a retry.
    """


# ──────────────────────────────────────────────────────────────────────────────
# ORM models
# ──────────────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class User(Base):
    """
    Represents a trading account.

    Invariant (DB-level CHECK):
        balance >= 0  — prevents overdrafts even from direct SQL access.
    """

    __tablename__ = "users"
    __table_args__ = (
        # Invariant #1: balance must never go negative.
        CheckConstraint("balance >= 0", name="ck_users_balance_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False, default=Decimal("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    positions: Mapped[list[Position]] = relationship(
        "Position", back_populates="user", cascade="all, delete-orphan"
    )
    transactions: Mapped[list[Transaction]] = relationship(
        "Transaction", back_populates="user", cascade="all, delete-orphan"
    )


class Position(Base):
    """
    Tracks a user's net holding of a given symbol (all lots merged into one row).

    Invariant (DB-level CHECK):
        quantity >= 0  — prevents short positions unless explicitly allowed.

    The (user_id, symbol) unique constraint ensures one row per asset per user.
    """

    __tablename__ = "positions"
    __table_args__ = (
        # Invariant #2: position quantity must never go negative.
        CheckConstraint("quantity >= 0", name="ck_positions_quantity_non_negative"),
        UniqueConstraint("user_id", "symbol", name="uq_positions_user_symbol"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False, default=Decimal("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="positions")


class Transaction(Base):
    """
    Immutable ledger entry for every executed trade.

    Idempotency guard:
        request_id carries a UNIQUE constraint — the database itself rejects
        a second INSERT with the same key, so no two writes can race past the
        application-level check.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        # Idempotency: every external call must carry a unique request_id.
        UniqueConstraint("request_id", name="uq_transactions_request_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Idempotency key supplied by the caller (e.g. Telegram update_id, UUID).
    request_id: Mapped[str] = mapped_column(String(255), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    # amount = quantity * price, stored for fast reporting without recomputation.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="transactions")


class PaperTrade(Base):
    """
    模擬交易紀錄（Paper Trade）。

    每筆買入/賣出均寫入此表，供策略績效分析與回測使用。
    不涉及真實資金，無 FK 至 users 表。

    session_id：用於將同一次程式啟動的交易歸為一組。
    trade_ts_ms：交易發生時的 Exchange timestamp（ms），與 created_at 不同。
    stop_price / target_price：買入時計算的停損/停利價，供事後分析用。
    """

    __tablename__ = "paper_trades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)         # BUY | SELL
    price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(30), nullable=False)         # SIGNAL | STOP_LOSS | TRAIL_STOP | TAKE_PROFIT | EOD
    pnl: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )                                                          # 淨損益（已扣交易成本）
    gross_pnl: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )                                                          # 毛損益（未扣成本，供成本分析）
    # ATR 動態停損/停利價（買入時記錄，賣出時為 0）
    stop_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, default=Decimal("0")
    )
    target_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, default=Decimal("0")
    )
    trade_ts_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)    # Exchange ts (ms)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


async def save_paper_trade(
    session: AsyncSession,
    *,
    session_id: str,
    symbol: str,
    action: str,
    price: float,
    shares: int,
    reason: str,
    pnl: float,
    trade_ts_ms: int,
    stop_price: float = 0.0,
    target_price: float = 0.0,
    gross_pnl: float = 0.0,
) -> PaperTrade:
    """
    將一筆模擬交易寫入 paper_trades 表。
    pnl      = 淨損益（已扣手續費+證交稅）
    gross_pnl = 毛損益（未扣成本，供事後分析交易成本佔比）
    呼叫者應在外部 session.begin() 的 context 內呼叫此函式。
    """
    record = PaperTrade(
        session_id=session_id,
        symbol=symbol,
        action=action,
        price=Decimal(str(round(price, 4))),
        shares=shares,
        reason=reason,
        pnl=Decimal(str(round(pnl, 2))),
        gross_pnl=Decimal(str(round(gross_pnl, 2))),
        stop_price=Decimal(str(round(stop_price, 4))),
        target_price=Decimal(str(round(target_price, 4))),
        trade_ts_ms=trade_ts_ms,
    )
    session.add(record)
    await session.flush()
    return record


# ──────────────────────────────────────────────────────────────────────────────
# Engine & session factory
# ──────────────────────────────────────────────────────────────────────────────

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/trading",
)

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,       # flip to True to print every SQL statement for debugging
    pool_size=10,
    max_overflow=20,
)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep ORM objects usable after commit
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager that yields a transactional AsyncSession.
    Commits on clean exit; rolls back on any exception.
    """
    async with AsyncSessionFactory() as session:
        async with session.begin():
            yield session


# ──────────────────────────────────────────────────────────────────────────────
# Business logic
# ──────────────────────────────────────────────────────────────────────────────

async def execute_buy(
    session: AsyncSession,
    user_id: uuid.UUID,
    symbol: str,
    quantity: Decimal,
    price: Decimal,
    request_id: str,
) -> Transaction:
    """
    Atomically execute a market buy order.

    All three mutations — (1) balance deduction, (2) position update,
    (3) transaction ledger insert — occur inside the *caller's* DB transaction.
    Either all three succeed together, or none of them persist.

    Why pessimistic locking (SELECT … FOR UPDATE) instead of optimistic?
    ────────────────────────────────────────────────────────────────────
    In a high-frequency deduction workload (e.g. a Telegram bot receiving
    rapid-fire buy commands for the same user), optimistic locking requires
    each concurrent writer to *read a version stamp, attempt a write, detect a
    conflict, and retry*.  Under heavy contention every writer except the first
    will fail and re-execute its entire business logic path, multiplying DB
    round-trips and holding connections open longer.

    SELECT … FOR UPDATE serialises access at the database level: the first
    writer acquires the lock, completes its work atomically, then releases it.
    The second writer then proceeds immediately with a guaranteed-fresh view of
    the row — no retry loop, no wasted round-trips.  This makes pessimistic
    locking the correct choice whenever:
      • The same row is modified by many concurrent requests (high contention).
      • The work following the read is cheap (balance check + two writes).
      • Stale reads have business consequences (overdrafts, double-sells).

    Parameters
    ----------
    session     : The active AsyncSession (caller owns commit/rollback).
    user_id     : UUID of the buying user.
    symbol      : Asset ticker (e.g. "BTC").
    quantity    : Number of units to purchase.
    price       : Price per unit.
    request_id  : Caller-supplied idempotency key (e.g. Telegram update_id).

    Returns
    -------
    Transaction : The newly inserted ledger record.

    Raises
    ------
    ValueError              – user_id does not exist.
    DuplicateRequestError   – request_id was already committed.
    InsufficientBalanceError – balance < quantity * price.
    """

    # ── Step 1: Pessimistic row lock ─────────────────────────────────────────
    # SELECT … FOR UPDATE blocks every other transaction that tries to lock
    # or UPDATE this user row until we COMMIT or ROLLBACK.  This is the
    # serialisation point that makes all subsequent checks race-free.
    result = await session.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f"User {user_id!r} not found")

    # ── Step 2: Idempotency check ────────────────────────────────────────────
    # Because we hold FOR UPDATE on the user row, two concurrent transactions
    # for the same user are serialised here — only one can pass this check
    # at a time.  The UNIQUE constraint on transactions.request_id is a
    # belt-and-suspenders guard for cross-user duplicate submissions.
    dup = await session.execute(
        select(Transaction).where(Transaction.request_id == request_id)
    )
    if dup.scalar_one_or_none() is not None:
        raise DuplicateRequestError(
            f"request_id {request_id!r} has already been processed — "
            "no funds were moved"
        )

    # ── Step 3: Balance invariant ────────────────────────────────────────────
    amount: Decimal = quantity * price
    if user.balance < amount:
        raise InsufficientBalanceError(
            f"Insufficient balance: have {user.balance}, need {amount} "
            f"({quantity} × {price})"
        )

    # ── Step 4: Atomic triple-write ──────────────────────────────────────────

    # 4a. Deduct balance (CHECK constraint prevents it going < 0 at commit).
    user.balance -= amount

    # 4b. Upsert position — also locked to guard against concurrent sells.
    pos_result = await session.execute(
        select(Position)
        .where(Position.user_id == user_id, Position.symbol == symbol)
        .with_for_update()
    )
    position = pos_result.scalar_one_or_none()
    if position is None:
        position = Position(user_id=user_id, symbol=symbol, quantity=quantity)
        session.add(position)
    else:
        position.quantity += quantity

    # 4c. Immutable ledger entry.
    transaction = Transaction(
        user_id=user_id,
        request_id=request_id,
        symbol=symbol,
        quantity=quantity,
        price=price,
        amount=amount,
        status="completed",
    )
    session.add(transaction)

    # ── Step 5: Flush ────────────────────────────────────────────────────────
    # Sends all pending SQL to the DB within the open transaction without
    # committing.  Any CHECK or UNIQUE violation surfaces here as an
    # IntegrityError so the caller can handle it before the commit point.
    await session.flush()

    return transaction
