"""Unit tests for services/bed_management.py."""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Admission, Base, Bed, Patient, Transfer, Ward
from database.repository import ensure_wards_and_beds
from services.bed_management import (
    BedManagementError,
    admit_patient,
    create_bed,
    discharge_patient,
    remove_bed,
    set_bed_service_status,
    transfer_patient,
)

NOW = dt.datetime(2026, 1, 10, 9, 0)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    s = SessionLocal()
    ensure_wards_and_beds(s, {"ICU-A": ["A01", "A02"], "ICU-B": ["B01"]})
    yield s
    s.close()


def _admit(session, patient="P001", ward="ICU-A", bed="A01", **kwargs):
    return admit_patient(
        session,
        patient_identifier=patient,
        ward_name=ward,
        bed_number=bed,
        admission_time=kwargs.pop("admission_time", NOW),
        **kwargs,
    )


# --------------------------------------------------------------------------
# admit_patient
# --------------------------------------------------------------------------

def test_admit_into_free_bed_succeeds(session):
    admission = _admit(session)
    assert admission.status == "Occupied"
    assert session.query(Patient).filter_by(patient_identifier="P001").count() == 1


def test_admit_into_occupied_bed_is_rejected(session):
    _admit(session)
    with pytest.raises(BedManagementError, match="already occupied"):
        _admit(session, patient="P002")  # same ward/bed


def test_admit_into_unknown_bed_is_rejected(session):
    with pytest.raises(BedManagementError, match="No such bed"):
        _admit(session, bed="Z99")


def test_admit_blank_patient_id_is_rejected(session):
    with pytest.raises(BedManagementError, match="Patient ID is required"):
        _admit(session, patient="   ")


def test_admit_into_out_of_service_bed_is_rejected(session):
    bed = session.query(Bed).filter_by(bed_number="A01").one()
    set_bed_service_status(session, bed.id, "Out of Service", reason="Cleaning")
    with pytest.raises(BedManagementError, match="out of service"):
        _admit(session)


def test_admit_second_active_record_for_same_patient_requires_confirmation(session):
    _admit(session, patient="P001", bed="A01")
    with pytest.raises(BedManagementError, match="already has an active admission"):
        _admit(session, patient="P001", bed="A02")

    # Explicit override is allowed -- this is exactly the duplicate-active
    # scenario the Data Quality panel is built to detect, not something
    # the system silently prevents from ever happening.
    admission = _admit(session, patient="P001", bed="A02", allow_duplicate_active=True)
    assert admission.status == "Occupied"
    active_count = (
        session.query(Admission)
        .join(Patient)
        .filter(Patient.patient_identifier == "P001", Admission.status == "Occupied")
        .count()
    )
    assert active_count == 2


# --------------------------------------------------------------------------
# discharge_patient
# --------------------------------------------------------------------------

def test_discharge_closes_the_admission(session):
    admission = _admit(session)
    discharge_time = NOW + dt.timedelta(days=1)
    updated = discharge_patient(session, admission.id, discharge_time)
    assert updated.status == "Discharged"
    assert updated.discharge_time == discharge_time


def test_discharge_already_discharged_admission_is_rejected(session):
    admission = _admit(session)
    discharge_patient(session, admission.id, NOW + dt.timedelta(hours=2))
    with pytest.raises(BedManagementError, match="already discharged"):
        discharge_patient(session, admission.id, NOW + dt.timedelta(hours=3))


def test_discharge_before_admission_time_is_rejected(session):
    admission = _admit(session)
    with pytest.raises(BedManagementError, match="cannot be before"):
        discharge_patient(session, admission.id, NOW - dt.timedelta(hours=1))


# --------------------------------------------------------------------------
# transfer_patient
# --------------------------------------------------------------------------

def test_transfer_closes_old_and_opens_new_without_duplicate(session):
    old = _admit(session, ward="ICU-A", bed="A01")
    transfer_time = NOW + dt.timedelta(hours=4)

    new = transfer_patient(session, old.id, to_ward_name="ICU-B", to_bed_number="B01", transfer_time=transfer_time)

    session.refresh(old)
    assert old.status == "Discharged"
    assert old.discharge_time == transfer_time
    assert new.status == "Occupied"
    assert new.ward.name == "ICU-B" and new.bed.bed_number == "B01"

    # Exactly one active admission remains for this patient -- a clean
    # transfer must never look like a duplicate-active record.
    active_count = session.query(Admission).filter_by(patient_id=old.patient_id, status="Occupied").count()
    assert active_count == 1

    transfer_log = session.query(Transfer).filter_by(patient_id=old.patient_id).all()
    assert len(transfer_log) == 1
    assert transfer_log[0].from_ward == "ICU-A" and transfer_log[0].from_bed == "A01"
    assert transfer_log[0].to_ward == "ICU-B" and transfer_log[0].to_bed == "B01"


def test_transfer_into_occupied_bed_is_rejected(session):
    old = _admit(session, patient="P001", ward="ICU-A", bed="A01")
    _admit(session, patient="P002", ward="ICU-A", bed="A02")
    with pytest.raises(BedManagementError, match="already occupied"):
        transfer_patient(session, old.id, to_ward_name="ICU-A", to_bed_number="A02", transfer_time=NOW)


def test_transfer_into_same_bed_is_rejected(session):
    old = _admit(session, ward="ICU-A", bed="A01")
    with pytest.raises(BedManagementError, match="same as the current bed"):
        transfer_patient(session, old.id, to_ward_name="ICU-A", to_bed_number="A01", transfer_time=NOW)


# --------------------------------------------------------------------------
# Bed roster: create / remove
# --------------------------------------------------------------------------

def test_create_bed_succeeds_and_rejects_duplicate(session):
    bed = create_bed(session, "ICU-A", "A03")
    assert bed.bed_number == "A03"
    with pytest.raises(BedManagementError, match="already exists"):
        create_bed(session, "ICU-A", "A03")


def test_create_bed_in_new_ward_creates_the_ward(session):
    bed = create_bed(session, "ICU-D", "D01")
    assert bed.ward.name == "ICU-D"
    assert session.query(Ward).filter_by(name="ICU-D").count() == 1


def test_remove_never_used_bed_succeeds(session):
    bed = create_bed(session, "ICU-A", "A03")
    bed_id = bed.id
    remove_bed(session, bed_id)
    assert session.get(Bed, bed_id) is None


def test_remove_occupied_bed_is_rejected(session):
    admission = _admit(session, ward="ICU-A", bed="A01")
    with pytest.raises(BedManagementError, match="currently occupied"):
        remove_bed(session, admission.bed_id)


def test_remove_bed_with_history_is_rejected(session):
    admission = _admit(session, ward="ICU-A", bed="A01")
    discharge_patient(session, admission.id, NOW + dt.timedelta(hours=1))
    with pytest.raises(BedManagementError, match="admission history"):
        remove_bed(session, admission.bed_id)


# --------------------------------------------------------------------------
# Bed roster: out-of-service toggle
# --------------------------------------------------------------------------

def test_mark_free_bed_out_of_service_and_back(session):
    bed = session.query(Bed).filter_by(bed_number="A01").one()
    set_bed_service_status(session, bed.id, "Out of Service", reason="Cleaning")
    session.refresh(bed)
    assert bed.status == "Out of Service"
    assert bed.out_of_service_reason == "Cleaning"
    assert bed.out_of_service_since is not None

    set_bed_service_status(session, bed.id, "In Service")
    session.refresh(bed)
    assert bed.status == "In Service"
    assert bed.out_of_service_reason is None
    assert bed.out_of_service_since is None


def test_mark_occupied_bed_out_of_service_is_rejected(session):
    admission = _admit(session, ward="ICU-A", bed="A01")
    with pytest.raises(BedManagementError, match="currently occupied"):
        set_bed_service_status(session, admission.bed_id, "Out of Service")
