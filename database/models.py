"""
SQLAlchemy ORM models for the ICU Bed Occupancy Dashboard.

Schema overview
----------------
Ward        -- an ICU ward (e.g. "ICU-A").
Bed         -- a physical bed that belongs to exactly one ward.
Patient     -- a patient identified by an external ``patient_identifier``
               (e.g. "P001"), independent of any single admission.
Admission   -- one occupancy record: a patient assigned to a bed for a
               period of time. A patient can have several admissions over
               time (re-admissions, transfers). This is the source of
               truth for "who is where right now" -- see
               services/transfers.py for how the *current* admission is
               resolved when duplicate/active records exist.
Transfer    -- an append-only log entry describing a patient moving from
               one ward/bed to another. Written directly by
               services/bed_management.transfer_patient() for a
               deliberate, UI-driven transfer, and also reconstructed by
               the ingestion pipeline when it detects that an *uploaded*
               dataset already contains more than one currently-active
               admission for a patient (see services/transfers.py).
               Transfers are never read when computing live occupancy;
               they exist for audit and historical reporting.

Design notes
------------
* ``Bed.status`` is an *operational* field (In Service / Out of Service)
  -- see ``BedServiceStatus``. It is a separate axis from Occupied/Free:
  the dashboard never treats it as a substitute for live occupancy, which
  is always recomputed from ``Admission`` rows (see
  services/occupancy.py). This avoids the two ever silently drifting
  apart, which is the whole point of the "duplicate active record"
  bottleneck this project is built around; the service-status field only
  adds the third state (unavailable for use at all) that Admission rows
  cannot express on their own.
* There is deliberately no separate ``Discharge`` table. A discharge is
  simply an ``Admission`` whose ``discharge_time`` is set and whose
  ``status`` is ``Discharged``. Duplicating that into a second table
  would only invite the two to disagree. Discharge-oriented views are
  exposed through ``services`` functions instead.
* Using SQLAlchemy's engine-agnostic column types (String, DateTime,
  Date, Integer, Enum-like plain strings) keeps this schema portable to
  PostgreSQL later -- swapping ``DATABASE_URL`` is the only change
  required (see database/database.py).
"""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


class AdmissionStatus(str, enum.Enum):
    """Valid values for ``Admission.status``.

    Stored as plain strings (not a DB-level ENUM) so that SQLite and
    PostgreSQL behave identically and new statuses can be added without a
    migration.
    """

    OCCUPIED = "Occupied"
    DISCHARGED = "Discharged"


class Ward(Base):
    __tablename__ = "wards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    beds: Mapped[list["Bed"]] = relationship(back_populates="ward", cascade="all, delete-orphan")
    admissions: Mapped[list["Admission"]] = relationship(back_populates="ward")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Ward(id={self.id}, name={self.name!r})"


class BedServiceStatus(str, enum.Enum):
    """Valid values for ``Bed.status`` -- an *operational* property of the
    bed itself (is it available for use at all), independent of whether a
    patient currently occupies it.

    This is deliberately a separate axis from Occupied/Free: a bed can be
    In Service and Free, In Service and Occupied, or Out of Service (which
    implies Free, since a bed must be vacated before it can be taken out
    of service -- enforced in services/bed_management.py). Live
    occupancy/free counts are always recomputed from Admission rows (see
    services/occupancy.py); this column is never treated as a substitute
    for that -- it only adds the third, operational state that Admission
    rows cannot express.
    """

    IN_SERVICE = "In Service"
    OUT_OF_SERVICE = "Out of Service"


class Bed(Base):
    __tablename__ = "beds"
    __table_args__ = (UniqueConstraint("ward_id", "bed_number", name="uq_bed_ward_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ward_id: Mapped[int] = mapped_column(ForeignKey("wards.id"), nullable=False)
    bed_number: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=BedServiceStatus.IN_SERVICE.value)
    out_of_service_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    out_of_service_since: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    ward: Mapped["Ward"] = relationship(back_populates="beds")
    admissions: Mapped[list["Admission"]] = relationship(back_populates="bed")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Bed(id={self.id}, bed_number={self.bed_number!r}, ward_id={self.ward_id}, status={self.status!r})"


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_identifier: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    admissions: Mapped[list["Admission"]] = relationship(back_populates="patient")
    transfers: Mapped[list["Transfer"]] = relationship(back_populates="patient")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Patient(id={self.id}, patient_identifier={self.patient_identifier!r})"


class Admission(Base):
    """One occupancy record for a patient in a bed.

    NOTE: several ``Admission`` rows may exist for the same patient with
    ``status == Occupied`` at the same time -- this is exactly the
    "duplicate active record" data-quality problem the dashboard is
    designed to detect and resolve rather than assume away. See
    services/transfers.py.
    """

    __tablename__ = "admissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), nullable=False)
    ward_id: Mapped[int] = mapped_column(ForeignKey("wards.id"), nullable=False)
    bed_id: Mapped[int] = mapped_column(ForeignKey("beds.id"), nullable=False)

    admission_time: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    discharge_time: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=AdmissionStatus.OCCUPIED.value)
    planned_discharge_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="admissions")
    ward: Mapped["Ward"] = relationship(back_populates="admissions")
    bed: Mapped["Bed"] = relationship(back_populates="admissions")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"Admission(id={self.id}, patient_id={self.patient_id}, "
            f"bed_id={self.bed_id}, status={self.status!r})"
        )


class Transfer(Base):
    """Append-only, derived log of a patient moving ward/bed.

    Transfers are written by the ingestion pipeline (services/transfers.py)
    whenever it resolves a duplicate-active-record situation into a single
    current admission. They are historical/audit data only and are never
    read when computing live occupancy.
    """

    __tablename__ = "transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), nullable=False)
    from_ward: Mapped[str] = mapped_column(String(50), nullable=False)
    from_bed: Mapped[str] = mapped_column(String(20), nullable=False)
    to_ward: Mapped[str] = mapped_column(String(50), nullable=False)
    to_bed: Mapped[str] = mapped_column(String(20), nullable=False)
    transfer_time: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)

    patient: Mapped["Patient"] = relationship(back_populates="transfers")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"Transfer(patient_id={self.patient_id}, "
            f"{self.from_ward}/{self.from_bed} -> {self.to_ward}/{self.to_bed})"
        )
