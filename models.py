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
    Text,
    UniqueConstraint,
    delete,
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


class PaperPositionSnapshot(Base):
    """
    活躍模擬持倉快照（Paper Position）。

    每次開倉時 UPSERT、平倉時 DELETE。
    重啟後透過 load_today_positions() 依 trade_date 過濾恢復同日持倉。

    trade_date：格式 YYYYMMDD，用於確保僅恢復同日持倉。
    """

    __tablename__ = "paper_positions"
    __table_args__ = (
        UniqueConstraint("trade_date", "symbol", name="uq_paper_pos_date_symbol"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trade_date: Mapped[str] = mapped_column(String(8), nullable=False, index=True)  # YYYYMMDD
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)                    # long | short
    entry_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_ts: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_change_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    stop_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    target_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    peak_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, default=Decimal("0")
    )
    trail_stop_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, default=Decimal("0")
    )
    entry_atr: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )


async def upsert_paper_position(
    session: AsyncSession,
    *,
    trade_date: str,
    symbol: str,
    side: str,
    entry_price: float,
    shares: int,
    entry_ts: int,
    entry_change_pct: float,
    stop_price: float,
    target_price: float,
    peak_price: float = 0.0,
    trail_stop_price: float = 0.0,
    entry_atr: float | None = None,
) -> PaperPositionSnapshot:
    """
    新增或更新活躍持倉快照。(trade_date, symbol) 唯一。
    呼叫者應在外部 session.begin() context 內呼叫此函式。
    """
    stmt = select(PaperPositionSnapshot).where(
        PaperPositionSnapshot.trade_date == trade_date,
        PaperPositionSnapshot.symbol == symbol,
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.side = side
        existing.entry_price = Decimal(str(round(entry_price, 4)))
        existing.shares = shares
        existing.entry_ts = entry_ts
        existing.entry_change_pct = Decimal(str(round(entry_change_pct, 4)))
        existing.stop_price = Decimal(str(round(stop_price, 4)))
        existing.target_price = Decimal(str(round(target_price, 4)))
        existing.peak_price = Decimal(str(round(peak_price, 4)))
        existing.trail_stop_price = Decimal(str(round(trail_stop_price, 4)))
        existing.entry_atr = Decimal(str(round(entry_atr, 6))) if entry_atr is not None else None
        await session.flush()
        return existing

    snapshot = PaperPositionSnapshot(
        trade_date=trade_date,
        symbol=symbol,
        side=side,
        entry_price=Decimal(str(round(entry_price, 4))),
        shares=shares,
        entry_ts=entry_ts,
        entry_change_pct=Decimal(str(round(entry_change_pct, 4))),
        stop_price=Decimal(str(round(stop_price, 4))),
        target_price=Decimal(str(round(target_price, 4))),
        peak_price=Decimal(str(round(peak_price, 4))),
        trail_stop_price=Decimal(str(round(trail_stop_price, 4))),
        entry_atr=Decimal(str(round(entry_atr, 6))) if entry_atr is not None else None,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def delete_paper_position(
    session: AsyncSession,
    *,
    trade_date: str,
    symbol: str,
) -> None:
    """
    平倉後刪除對應的活躍持倉快照。
    呼叫者應在外部 session.begin() context 內呼叫此函式。
    """
    stmt = delete(PaperPositionSnapshot).where(
        PaperPositionSnapshot.trade_date == trade_date,
        PaperPositionSnapshot.symbol == symbol,
    )
    await session.execute(stmt)


async def load_today_positions(
    session: AsyncSession,
    *,
    trade_date: str,
) -> list[dict]:
    """
    讀取指定交易日的所有活躍持倉快照，回傳 dict 列表供 AutoTrader 重建 PaperPosition。
    """
    stmt = select(PaperPositionSnapshot).where(
        PaperPositionSnapshot.trade_date == trade_date
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "symbol": r.symbol,
            "side": r.side,
            "entry_price": float(r.entry_price),
            "shares": r.shares,
            "entry_ts": r.entry_ts,
            "entry_change_pct": float(r.entry_change_pct),
            "stop_price": float(r.stop_price),
            "target_price": float(r.target_price),
            "peak_price": float(r.peak_price),
            "trail_stop_price": float(r.trail_stop_price),
            "entry_atr": float(r.entry_atr) if r.entry_atr is not None else None,
        }
        for r in rows
    ]


class StrategyParamLog(Base):
    """
    策略參數調整歷史紀錄。

    由 StrategyTuner 每日 EOD 後寫入，記錄每次參數變更的前後值與原因。
    供事後審計與回溯分析使用。
    """

    __tablename__ = "strategy_param_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    param_name: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    new_value: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    trade_count_basis: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


async def save_param_log(
    session: AsyncSession,
    *,
    param_name: str,
    old_value: float,
    new_value: float,
    reason: str,
    trade_count_basis: int = 0,
) -> StrategyParamLog:
    """
    記錄一筆策略參數調整。
    呼叫者應在外部 session.begin() context 內呼叫此函式。
    """
    record = StrategyParamLog(
        param_name=param_name,
        old_value=Decimal(str(round(old_value, 4))),
        new_value=Decimal(str(round(new_value, 4))),
        reason=reason,
        trade_count_basis=trade_count_basis,
    )
    session.add(record)
    await session.flush()
    return record


async def load_closed_trades(
    session: AsyncSession,
    *,
    days: int = 30,
) -> list[dict]:
    """
    讀取近 N 日的已平倉交易紀錄（action IN SELL, COVER），供 StrategyTuner 分析使用。
    """
    from datetime import timedelta
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    stmt = (
        select(PaperTrade)
        .where(
            PaperTrade.action.in_(["SELL", "COVER"]),
            PaperTrade.created_at >= cutoff,
        )
        .order_by(PaperTrade.created_at)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "symbol": r.symbol,
            "action": r.action,
            "price": float(r.price),
            "shares": r.shares,
            "reason": r.reason,
            "pnl": float(r.pnl),
            "gross_pnl": float(r.gross_pnl),
            "stop_price": float(r.stop_price),
            "target_price": float(r.target_price),
            "trade_ts_ms": r.trade_ts_ms,
        }
        for r in rows
    ]


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
