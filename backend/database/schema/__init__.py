from sqlalchemy import Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from enum import Enum


class Base(DeclarativeBase):
    pass


class Report(Base):
    __tablename__ = "report"
    __table_args__ = {"schema": "Diabetes"}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    ma_bhyt: Mapped[str] = mapped_column(Text, nullable=False)
    cccd: Mapped[str] = mapped_column(Text, nullable=False)

    ho_ten: Mapped[str | None] = mapped_column(Text, nullable=True)
    gioi_tinh: Mapped[str | None] = mapped_column(Text, nullable=True)
    nam_sinh: Mapped[str | None] = mapped_column(Text, nullable=True)
    sdt: Mapped[str | None] = mapped_column(Text, nullable=True)

    dia_chi: Mapped[str | None] = mapped_column(Text, nullable=True)
    phuong_xa: Mapped[str | None] = mapped_column(Text, nullable=True)
    quan_huyen: Mapped[str | None] = mapped_column(Text, nullable=True)
    tinh_thanh_pho: Mapped[str | None] = mapped_column(Text, nullable=True)

    ngay_kham: Mapped[str | None] = mapped_column(Text, nullable=True)

    icd_tha: Mapped[str | None] = mapped_column(Text, nullable=True)
    icd_dtd: Mapped[str | None] = mapped_column(Text, nullable=True)

    huyet_ap_tam_truong: Mapped[str | None] = mapped_column(Text, nullable=True)
    huyet_ap_tam_thu: Mapped[str | None] = mapped_column(Text, nullable=True)

    chi_so_duong_huyet: Mapped[str | None] = mapped_column(Text, nullable=True)
    chi_so_hba1c: Mapped[str | None] = mapped_column(Text, nullable=True)

    ghi_chu: Mapped[str | None] = mapped_column(Text, nullable=True)
    dieu_tri: Mapped[str | None] = mapped_column(Text, nullable=True)


class FileStatus(str, Enum):
    PENDING: str = "PENDING"
    PROCESSED: str = "PROCESSED"
    ERROR: str = "ERROR"


class FileInfo(Base):
    __tablename__ = "status"
    __table_args__ = {"schema": "Files"}

    file_hashed: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)

    uploaded_date: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(default=FileStatus.PENDING)


__all__ = ["Report", "FileInfo", "Report", "Base"]
