from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.environment == "development",
    pool_size=5,
    max_overflow=10,
    # Test each pooled connection with a lightweight ping before handing it out,
    # and recycle connections older than 30 min. Safety net so a connection left
    # in a bad state (e.g. interrupted mid-transaction) is discarded rather than
    # poisoning the next request with "cannot use Connection.transaction() ...".
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args={"statement_cache_size": 0},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
