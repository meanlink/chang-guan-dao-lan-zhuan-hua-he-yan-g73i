from sqlalchemy import String, JSON, Double, ForeignKey, Integer, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class RemoteSource(Base):
    __tablename__ = 'remote_sources'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    base_url: Mapped[str] = mapped_column(String(300))
    token: Mapped[str] = mapped_column(String(300), default='')
    page_size: Mapped[int] = mapped_column(Integer, default=100)
    current_dataset_id: Mapped[int | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
    created_at: Mapped[float] = mapped_column(Double)
class SourceVersion(Base):
    __tablename__ = 'source_versions'
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey('remote_sources.id'))
    version_no: Mapped[int] = mapped_column(Integer)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'), unique=True)
    snapshot: Mapped[str] = mapped_column(String(200))
    rows: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Double)
    __table_args__ = (Index('uq_source_version_no', 'source_id', 'version_no', unique=True),)
class SyncRun(Base):
    __tablename__ = 'sync_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey('remote_sources.id'))
    status: Mapped[str] = mapped_column(String(12), default='queued')  # queued/running/completed/failed
    snapshot: Mapped[str] = mapped_column(String(200), default='')
    cursor: Mapped[str] = mapped_column(String(500), default='')
    staged_records: Mapped[list] = mapped_column(JSON, default=list)
    fetched_pages: Mapped[int] = mapped_column(Integer, default=0)
    fetched_rows: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    restarts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(String(1000), default='')
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
    created_at: Mapped[float] = mapped_column(Double)
    updated_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    # 同一来源同一时间最多一个进行中的同步；并发登记与重试命中该约束后复用现有运行
    __table_args__ = (Index('uq_sync_run_active', 'source_id', unique=True,
                            sqlite_where=text("status IN ('queued','running')"),
                            postgresql_where=text("status IN ('queued','running')")),)
