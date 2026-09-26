"""
Write-side actions for managing individual beds and patients:
admitting a patient to a free bed, discharging one, transferring one
between beds, and adding/removing/retiring beds themselves.

This is deliberately separate from services/ingestion.py: ingestion is
a *bulk replace* pipeline (a whole admissions sheet at once), while this
module makes one small, validated change at a time and is what the
"Manage Beds & Patients" panel in the UI calls directly. Both ultimately
write the same ORM models, so a resolved/live view built from
database.repository never has to know which path the data came from.

Every function here takes a live SQLAlchemy ``Session`` and either
returns the row it changed or raises :class:`BedManagementError` with a
message written for an end user (the UI shows it directly via
``st.error``, never a raw traceback).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from database.models import Admission, Bed, BedServiceStatus, Patient, Transfer
from database.repository import (
    bed_has_active_admission,
    bed_has_admission_history,
    get_active_admission_for_patient,
    get_bed_by_id,
    get_bed_by_ward_and_number,
    get_or_create_ward,
    get_patient_by_identifier,
)


class BedManagementError(ValueError):
    """Raised for any invalid bed/patient-management action.

    The message is always safe to show directly to an end user.
    """


# --------------------------------------------------------------------------
# Patient actions
# --------------------------------------------------------------------------

def admit_patient(
    session: Session,
    *,
    patient_identifier: str,
    ward_name: str,
    bed_number: str,
    admission_time: dt.datetime,
    planned_discharge_date: dt.date | None = None,
    allow_duplicate_active: bool = False,
) -> Admission:
    """Admit a patient into a specific, currently-free, in-service bed.

    Raises if the bed doesn't exist, is out of service, or is already
    occupied. If the patient already has an active admission elsewhere,
    this raises unless ``allow_duplicate_active=True`` is passed -- the
    UI uses that escape hatch deliberately, to let an administrator see
    (and the Data Quality panel flag) exactly the "duplicate active
    record" scenario this project is built around, rather than silently
    preventing it from ever happening.
    """
    patient_identifier = (patient_identifier or "").strip()
    if not patient_identifier:
        raise BedManagementError("Patient ID is required.")

    bed = get_bed_by_ward_and_number(session, ward_name, bed_number)
    if bed is None:
        raise BedManagementError(f"No such bed: {ward_name} / {bed_number}.")
    if bed.status != BedServiceStatus.IN_SERVICE.value:
        raise BedManagementError(f"Bed {ward_name}/{bed_number} is out of service.")
    if bed_has_active_admission(session, bed.id):
        raise BedManagementError(f"Bed {ward_name}/{bed_number} is already occupied.")

    patient = get_patient_by_identifier(session, patient_identifier)
    if patient is None:
        patient = Patient(patient_identifier=patient_identifier)
        session.add(patient)
        session.flush()
    else:
        existing_active = get_active_admission_for_patient(session, patient.id)
        if existing_active is not None and not allow_duplicate_active:
            raise BedManagementError(
                f"Patient {patient_identifier} already has an active admission "
                f"({existing_active.ward.name}/{existing_active.bed.bed_number}). "
                "Use Transfer instead, or confirm to admit anyway."
            )

    admission = Admission(
        patient_id=patient.id,
        ward_id=bed.ward_id,
        bed_id=bed.id,
        admission_time=admission_time,
        status="Occupied",
        planned_discharge_date=planned_discharge_date,
    )
    session.add(admission)
    session.flush()
    return admission


def discharge_patient(session: Session, admission_id: int, discharge_time: dt.datetime) -> Admission:
    """Close out an occupied admission."""
    admission = session.get(Admission, admission_id)
    if admission is None:
        raise BedManagementError("That admission record no longer exists.")
    if admission.status != "Occupied":
        raise BedManagementError("This admission is already discharged.")
    if discharge_time < admission.admission_time:
        raise BedManagementError("Discharge time cannot be before the admission time.")

    admission.status = "Discharged"
    admission.discharge_time = discharge_time
    session.flush()
    return admission


def transfer_patient(
    session: Session,
    admission_id: int,
    *,
    to_ward_name: str,
    to_bed_number: str,
    transfer_time: dt.datetime,
) -> Admission:
    """Move a patient from their current bed to a different, free, in-service bed.

    Unlike an unresolved duplicate-active record, this is a *clean*
    transfer: the old admission is properly closed (Discharged, with
    ``discharge_time = transfer_time``) and a new admission is opened in
    the destination bed, so the patient is never counted as occupying two
    beds at once. A :class:`Transfer` audit row is written directly
    (rather than reconstructed later from ambiguous data).
    """
    old_admission = session.get(Admission, admission_id)
    if old_admission is None:
        raise BedManagementError("That admission record no longer exists.")
    if old_admission.status != "Occupied":
        raise BedManagementError("This patient is not currently admitted.")
    if transfer_time < old_admission.admission_time:
        raise BedManagementError("Transfer time cannot be before the admission time.")

    dest_bed = get_bed_by_ward_and_number(session, to_ward_name, to_bed_number)
    if dest_bed is None:
        raise BedManagementError(f"No such bed: {to_ward_name} / {to_bed_number}.")
    if dest_bed.id == old_admission.bed_id:
        raise BedManagementError("Destination bed is the same as the current bed.")
    if dest_bed.status != BedServiceStatus.IN_SERVICE.value:
        raise BedManagementError(f"Bed {to_ward_name}/{to_bed_number} is out of service.")
    if bed_has_active_admission(session, dest_bed.id):
        raise BedManagementError(f"Bed {to_ward_name}/{to_bed_number} is already occupied.")

    from_ward_name = old_admission.ward.name
    from_bed_number = old_admission.bed.bed_number

    old_admission.status = "Discharged"
    old_admission.discharge_time = transfer_time

    new_admission = Admission(
        patient_id=old_admission.patient_id,
        ward_id=dest_bed.ward_id,
        bed_id=dest_bed.id,
        admission_time=transfer_time,
        status="Occupied",
        planned_discharge_date=old_admission.planned_discharge_date,
    )
    session.add(new_admission)

    session.add(
        Transfer(
            patient_id=old_admission.patient_id,
            from_ward=from_ward_name,
            from_bed=from_bed_number,
            to_ward=to_ward_name,
            to_bed=to_bed_number,
            transfer_time=transfer_time,
        )
    )
    session.flush()
    return new_admission


# --------------------------------------------------------------------------
# Bed roster actions
# --------------------------------------------------------------------------

def create_bed(session: Session, ward_name: str, bed_number: str) -> Bed:
    ward_name = (ward_name or "").strip()
    bed_number = (bed_number or "").strip()
    if not ward_name:
        raise BedManagementError("Ward name is required.")
    if not bed_number:
        raise BedManagementError("Bed number is required.")

    ward = get_or_create_ward(session, ward_name)
    if get_bed_by_ward_and_number(session, ward_name, bed_number) is not None:
        raise BedManagementError(f"Bed {ward_name}/{bed_number} already exists.")

    bed = Bed(ward_id=ward.id, bed_number=bed_number, status=BedServiceStatus.IN_SERVICE.value)
    session.add(bed)
    session.flush()
    return bed


def remove_bed(session: Session, bed_id: int) -> None:
    """Permanently remove a bed from the roster.

    Only allowed for a bed that has never had any admission recorded
    against it (i.e. it was created in error). A bed that has real
    history should be retired with :func:`set_bed_service_status` instead
    -- deleting it would either break the foreign-key link from its past
    admissions or silently erase that audit trail, neither of which this
    project does.
    """
    bed = get_bed_by_id(session, bed_id)
    if bed is None:
        raise BedManagementError("That bed no longer exists.")
    if bed_has_active_admission(session, bed_id):
        raise BedManagementError("This bed is currently occupied -- discharge or transfer the patient first.")
    if bed_has_admission_history(session, bed_id):
        raise BedManagementError(
            "This bed has admission history and cannot be deleted (it would break the audit "
            "trail). Mark it Out of Service instead."
        )

    session.delete(bed)
    session.flush()


def set_bed_service_status(
    session: Session,
    bed_id: int,
    new_status: str,
    *,
    reason: str | None = None,
    changed_at: dt.datetime | None = None,
) -> Bed:
    """Take a bed out of service, or bring it back into service."""
    if new_status not in {s.value for s in BedServiceStatus}:
        raise BedManagementError(f"Unknown bed status: {new_status!r}.")

    bed = get_bed_by_id(session, bed_id)
    if bed is None:
        raise BedManagementError("That bed no longer exists.")

    if new_status == BedServiceStatus.OUT_OF_SERVICE.value:
        if bed_has_active_admission(session, bed_id):
            raise BedManagementError("This bed is currently occupied -- discharge or transfer the patient first.")
        bed.status = BedServiceStatus.OUT_OF_SERVICE.value
        bed.out_of_service_reason = (reason or "").strip() or None
        bed.out_of_service_since = changed_at or dt.datetime.now()
    else:
        bed.status = BedServiceStatus.IN_SERVICE.value
        bed.out_of_service_reason = None
        bed.out_of_service_since = None

    session.flush()
    return bed
