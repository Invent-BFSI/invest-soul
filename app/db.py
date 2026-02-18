import os, urllib.parse, json
from sqlalchemy import create_engine, String, Float, Boolean, Integer, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from datetime import datetime

AZURE_SQL_ODBC_CONNSTR = os.getenv("AZURE_SQL_ODBC_CONNSTR")
AZURE_SQL_SQLALCHEMY_URL = os.getenv("AZURE_SQL_SQLALCHEMY_URL")

def build_sqlalchemy_url_from_odbc(odbc: str) -> str:
    return f"mssql+pyodbc:///?odbc_connect={urllib.parse.quote_plus(odbc)}"

if AZURE_SQL_SQLALCHEMY_URL:
    SQLALCHEMY_URL = AZURE_SQL_SQLALCHEMY_URL
elif AZURE_SQL_ODBC_CONNSTR:
    SQLALCHEMY_URL = build_sqlalchemy_url_from_odbc(AZURE_SQL_ODBC_CONNSTR)
else:
    SQLALCHEMY_URL = None

engine = create_engine(SQLALCHEMY_URL, pool_pre_ping=True, pool_recycle=300) if SQLALCHEMY_URL else None
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False) if engine else None

class Base(DeclarativeBase): pass

class SessionState(Base):
    __tablename__ = "UserSessions"
    sessionId: Mapped[str] = mapped_column(String(64), primary_key=True)
    userName: Mapped[str | None] = mapped_column(String(100))
    userEmail: Mapped[str | None] = mapped_column(String(200))
    userCity: Mapped[str | None] = mapped_column(String(100))
    userCountry: Mapped[str | None] = mapped_column(String(100))
    currency: Mapped[str | None] = mapped_column(String(10))
    cashInflow: Mapped[float | None] = mapped_column(Float)
    cashOutflow: Mapped[float | None] = mapped_column(Float)
    liabilities: Mapped[float | None] = mapped_column(Float)
    riskAppetite: Mapped[str | None] = mapped_column(String(20))
    preferredSector: Mapped[str | None] = mapped_column(String(50))
    futureGoals: Mapped[str | None] = mapped_column(Text)
    investmentPeriod: Mapped[int | None] = mapped_column(Integer)
    netSurplus: Mapped[float | None] = mapped_column(Float)
    createdAt: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Portfolio(Base):
    __tablename__ = "Portfolios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sessionId: Mapped[str] = mapped_column(String(64), index=True)
    userName: Mapped[str] = mapped_column(String(100))
    userEmail: Mapped[str] = mapped_column(String(200))
    region: Mapped[str] = mapped_column(String(100))
    monthlyInflow: Mapped[float] = mapped_column(Float)
    monthlyOutflow: Mapped[float] = mapped_column(Float)
    totalDebt: Mapped[float] = mapped_column(Float)
    riskAppetite: Mapped[str] = mapped_column(String(20))
    preferredSector: Mapped[str] = mapped_column(String(50))
    investmentAmount: Mapped[float] = mapped_column(Float)
    investmentPeriod: Mapped[int] = mapped_column(Integer)
    futureGoals: Mapped[str] = mapped_column(Text)
    assetAllocation: Mapped[str] = mapped_column(String(200))
    equityRecommendation: Mapped[str] = mapped_column(String(200))
    alternateEquities: Mapped[str] = mapped_column(Text)
    debtRecommendation: Mapped[str] = mapped_column(String(200))
    portfolioSummary: Mapped[str] = mapped_column(Text)
    createdAt: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class MessageLog(Base):
    __tablename__ = "Messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sessionId: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    createdAt: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

def init_db():
    if engine:
        Base.metadata.create_all(engine)
