"""Authoritative canonical alias catalog.

This module is the **single source of truth** for all normalized alias →
canonical-field mappings.  It was produced by reconciling three pre-existing
sources:

* ``map.py`` (``DIRECT_ALIASES`` dict, ``STRUCTURAL_RULES`` list)
* ``backend/domain/utils/mapping.json``
* The Redis flat hash that ``backend/redis/__init__.py`` reads

Reconciliation notes
--------------------
The three sources were merged field-by-field.  Where two sources agreed on
the same (alias, target) pair the entry was kept as-is.  Where they
disagreed, the conflict is documented below and the semantically safer choice
was retained.

Conflicts documented
~~~~~~~~~~~~~~~~~~~~
``huyet_ap`` (mapping.json line 139)
    mapping.json maps the raw alias ``huyet_ap`` to the *intermediate* target
    ``"huyet_ap"`` which is **not** a canonical field in
    :class:`~backend.domain.ingestion.contracts.CanonicalRecord`.  The
    canonical fields are ``huyet_ap_tam_thu`` and ``huyet_ap_tam_truong``.
    A column header like "Huyết áp" that normalizes to ``huyet_ap`` belongs
    to a structural rule (COMPOSITE blood-pressure) rather than a direct
    alias.  **Resolution**: ``huyet_ap`` is therefore removed from
    :data:`DIRECT_ALIASES` and kept only in :data:`STRUCTURAL_RULES` under
    the ``COMPOSITE`` pattern list.

``blood_pressure`` / ``bp`` (mapping.json lines 187-188)
    Same issue as above – mapping.json points both to the pseudo-target
    ``"huyet_ap"``.  **Resolution**: moved to structural rule patterns only.

``chi_so_ha`` (mapping.json line 189)
    mapping.json has ``chi_so_ha`` mapped to a *list*
    ``["huyet_ap_tam_thu", "huyet_ap_tam_truong"]``, which cannot be
    expressed in a flat alias dict.  **Resolution**: moved to structural rule
    patterns only.

``ho`` (mapping.json line 34)
    mapping.json maps the single alias ``ho`` (surname) to ``ho_ten``
    (full name) with no confidence annotation.  ``map.py`` does not have
    this alias.  This is semantically ambiguous (surname ≠ full name) and
    may produce bad data if a file only contains a surname column.
    **Resolution**: retained in DIRECT_ALIASES at confidence 0.55 (below the
    HEURISTIC threshold) so the engine surfaces it as ambiguous rather than
    silently accepting it.

``ten`` (map.py line 22 / mapping.json line 44)
    Both sources map ``ten`` (given name) to ``ho_ten`` (full name).
    map.py assigns confidence 0.60 and notes the ambiguity.  Retained at
    confidence 0.60.

``don_thuoc`` (map.py line 185)
    map.py maps ``don_thuoc`` (prescription) to ``dieu_tri`` (treatment)
    at confidence 0.70 with an explicit ambiguity note.  mapping.json does
    not contain this alias.  Retained at 0.70 with the ambiguity flag.

``id`` (map.py line 41)
    map.py maps ``id`` (row ID / DB ID) to ``cccd`` at confidence 0.35.
    mapping.json does not have it.  This is kept at 0.35 because it is
    almost certainly not a citizen ID column in real data.

``tp`` (map.py line 110)
    map.py maps ``tp`` to ``tinh_thanh_pho`` at 0.50.  mapping.json does
    not have it.  Retained at 0.50.

``insurance_no`` / ``insurance_id`` / ``insurance_number``
    All three appear across the two sources and agree on target ``ma_bhyt``.
    Merged without conflict.

``ngay_sinh`` / ``dob`` / ``date_of_birth``
    mapping.json maps these to ``nam_sinh``.  map.py's STRUCTURAL_RULES uses
    the same normalized keys as DERIVED patterns.  Both sources agree on the
    target.  The aliases are retained in DIRECT_ALIASES at confidence 0.90;
    the structural rule is kept for the DERIVED extractor that extracts just
    the year component.

``nam`` / ``nu`` (indicator gender columns)
    These appear only in map.py STRUCTURAL_RULES as INDICATOR patterns.
    They do not appear in DIRECT_ALIASES in either source.  Kept in
    STRUCTURAL_RULES only.
"""

from __future__ import annotations

from typing import NamedTuple


class AliasEntry(NamedTuple):
    """(target_canonical_field, confidence)."""

    target: str
    confidence: float


# ---------------------------------------------------------------------------
# DIRECT_ALIASES
# ---------------------------------------------------------------------------
# Keys are *normalized* alias strings (output of ``normalize()``).
# Values are :class:`AliasEntry` (target_canonical_field, confidence).
#
# Confidence semantics (deterministic, not statistically calibrated):
#   1.00 – canonical name or unambiguous well-known alias
#   0.95 – near-canonical alias, extremely unlikely to mean anything else
#   0.90 – strong alias, context makes meaning almost certain
#   0.85 – good alias with minor ambiguity risk
#   0.80 – reasonable alias, edge-case ambiguity possible
#   0.75 – plausible alias, some ambiguity possible
#   0.70 – weak alias or documented semantic ambiguity
#   0.60 – low confidence, known ambiguity (e.g. given name vs full name)
#   0.55 – very low confidence, likely ambiguous
#   ≤0.50 – use with caution; the engine will flag as ambiguous
#
DIRECT_ALIASES: dict[str, AliasEntry] = {
    # -----------------------------------------------------------------------
    # ho_ten (patient full name)
    # -----------------------------------------------------------------------
    "ho_ten": AliasEntry("ho_ten", 1.00),
    "ho_va_ten": AliasEntry("ho_ten", 1.00),
    "ho_ten_bn": AliasEntry("ho_ten", 1.00),
    "ho_va_ten_bn": AliasEntry("ho_ten", 1.00),
    "ho_ten_benh_nhan": AliasEntry("ho_ten", 1.00),
    "ho_va_ten_benh_nhan": AliasEntry("ho_ten", 1.00),
    "ho_ten_nguoi_benh": AliasEntry("ho_ten", 1.00),
    "patient_name": AliasEntry("ho_ten", 1.00),
    "patient_full_name": AliasEntry("ho_ten", 1.00),
    "full_name": AliasEntry("ho_ten", 0.95),
    "fullname": AliasEntry("ho_ten", 0.95),
    "name_of_patient": AliasEntry("ho_ten", 0.95),
    "ten_benh_nhan": AliasEntry("ho_ten", 0.95),
    "ten_bn": AliasEntry("ho_ten", 0.95),
    "ten_nguoi_benh": AliasEntry("ho_ten", 0.95),
    "ho_ten_nguoi_kham": AliasEntry("ho_ten", 0.90),
    "ho_ten_khach_hang": AliasEntry("ho_ten", 0.85),
    "hoten": AliasEntry("ho_ten", 1.00),
    "ht": AliasEntry("ho_ten", 0.80),
    "name": AliasEntry("ho_ten", 0.75),
    # Ambiguous: given name only, not full name (see reconciliation note)
    "ten": AliasEntry("ho_ten", 0.60),
    # Ambiguous: surname only (see reconciliation note)
    "ho": AliasEntry("ho_ten", 0.55),
    # -----------------------------------------------------------------------
    # cccd (citizen identity card number, includes old CMND)
    # -----------------------------------------------------------------------
    "cccd": AliasEntry("cccd", 1.00),
    "so_cccd": AliasEntry("cccd", 1.00),
    "ma_cccd": AliasEntry("cccd", 1.00),
    "can_cuoc_cong_dan": AliasEntry("cccd", 1.00),
    "so_can_cuoc_cong_dan": AliasEntry("cccd", 1.00),
    "can_cuoc": AliasEntry("cccd", 0.95),
    "so_can_cuoc": AliasEntry("cccd", 0.95),
    "cmnd": AliasEntry("cccd", 0.95),
    "so_cmnd": AliasEntry("cccd", 0.95),
    "chung_minh_nhan_dan": AliasEntry("cccd", 0.95),
    "cmnd_cccd": AliasEntry("cccd", 1.00),
    "cccd_cmnd": AliasEntry("cccd", 1.00),
    "cmt": AliasEntry("cccd", 0.90),
    "so_cmt": AliasEntry("cccd", 0.90),
    "citizen_id": AliasEntry("cccd", 1.00),
    "national_id": AliasEntry("cccd", 1.00),
    "national_id_number": AliasEntry("cccd", 1.00),
    "id_number": AliasEntry("cccd", 0.95),
    "identity_number": AliasEntry("cccd", 0.95),
    "so_dinh_danh": AliasEntry("cccd", 0.90),
    "ma_dinh_danh": AliasEntry("cccd", 0.90),
    "dinh_danh_ca_nhan": AliasEntry("cccd", 0.90),
    # Very low confidence – almost certainly not a citizen ID (see notes)
    "id": AliasEntry("cccd", 0.35),
    # -----------------------------------------------------------------------
    # ma_bhyt (health insurance card number)
    # -----------------------------------------------------------------------
    "ma_bhyt": AliasEntry("ma_bhyt", 1.00),
    "so_bhyt": AliasEntry("ma_bhyt", 1.00),
    "so_the_bhyt": AliasEntry("ma_bhyt", 1.00),
    "ma_the_bhyt": AliasEntry("ma_bhyt", 1.00),
    "so_the_bao_hiem_y_te": AliasEntry("ma_bhyt", 1.00),
    "bhyt_no": AliasEntry("ma_bhyt", 1.00),
    "bhyt_id": AliasEntry("ma_bhyt", 1.00),
    "health_insurance_id": AliasEntry("ma_bhyt", 1.00),
    "health_insurance_number": AliasEntry("ma_bhyt", 1.00),
    "ma_so_bhyt": AliasEntry("ma_bhyt", 1.00),
    "ma_bao_hiem_y_te": AliasEntry("ma_bhyt", 1.00),
    "bhyt": AliasEntry("ma_bhyt", 0.95),
    "the_bhyt": AliasEntry("ma_bhyt", 0.95),
    "bao_hiem_y_te": AliasEntry("ma_bhyt", 0.90),
    "bao_hiem": AliasEntry("ma_bhyt", 0.85),
    "insurance_no": AliasEntry("ma_bhyt", 0.70),
    "insurance_id": AliasEntry("ma_bhyt", 0.85),
    "insurance_number": AliasEntry("ma_bhyt", 0.85),
    # -----------------------------------------------------------------------
    # gioi_tinh (gender)
    # -----------------------------------------------------------------------
    "gioi_tinh": AliasEntry("gioi_tinh", 1.00),
    "gioi_tinh_bn": AliasEntry("gioi_tinh", 1.00),
    "gioi_tinh_benh_nhan": AliasEntry("gioi_tinh", 1.00),
    "patient_gender": AliasEntry("gioi_tinh", 1.00),
    "patient_sex": AliasEntry("gioi_tinh", 1.00),
    "gender": AliasEntry("gioi_tinh", 1.00),
    "sex": AliasEntry("gioi_tinh", 1.00),
    "gioi": AliasEntry("gioi_tinh", 0.90),
    "gt": AliasEntry("gioi_tinh", 0.85),
    # -----------------------------------------------------------------------
    # nam_sinh (year of birth; date-of-birth aliases included here because
    # the structural DERIVED rule extracts the year component)
    # -----------------------------------------------------------------------
    "nam_sinh": AliasEntry("nam_sinh", 1.00),
    "nam_sinh_bn": AliasEntry("nam_sinh", 1.00),
    "nam_sinh_benh_nhan": AliasEntry("nam_sinh", 1.00),
    "birth_year": AliasEntry("nam_sinh", 1.00),
    "year_of_birth": AliasEntry("nam_sinh", 1.00),
    "yob": AliasEntry("nam_sinh", 0.95),
    "namsinh": AliasEntry("nam_sinh", 1.00),
    # DOB aliases – high confidence that the target is birth year
    "ngay_sinh": AliasEntry("nam_sinh", 0.90),
    "dob": AliasEntry("nam_sinh", 0.90),
    "date_of_birth": AliasEntry("nam_sinh", 0.90),
    "birth_date": AliasEntry("nam_sinh", 0.90),
    "birthday": AliasEntry("nam_sinh", 0.90),
    "ns": AliasEntry("nam_sinh", 0.75),
    # -----------------------------------------------------------------------
    # sdt (phone number)
    # -----------------------------------------------------------------------
    "sdt": AliasEntry("sdt", 1.00),
    "so_dien_thoai": AliasEntry("sdt", 1.00),
    "so_dt": AliasEntry("sdt", 0.95),
    "dien_thoai": AliasEntry("sdt", 0.95),
    "dien_thoai_di_dong": AliasEntry("sdt", 0.95),
    "so_dien_thoai_di_dong": AliasEntry("sdt", 1.00),
    "phone": AliasEntry("sdt", 1.00),
    "phone_number": AliasEntry("sdt", 1.00),
    "mobile": AliasEntry("sdt", 0.95),
    "mobile_number": AliasEntry("sdt", 0.95),
    "telephone": AliasEntry("sdt", 0.95),
    "contact_number": AliasEntry("sdt", 0.90),
    "dt": AliasEntry("sdt", 0.70),
    # -----------------------------------------------------------------------
    # dia_chi (address – full composite)
    # -----------------------------------------------------------------------
    "dia_chi": AliasEntry("dia_chi", 1.00),
    "dia_chi_nha": AliasEntry("dia_chi", 1.00),
    "dia_chi_bn": AliasEntry("dia_chi", 1.00),
    "dia_chi_benh_nhan": AliasEntry("dia_chi", 1.00),
    "dia_chi_hien_tai": AliasEntry("dia_chi", 0.95),
    "dia_chi_thuong_tru": AliasEntry("dia_chi", 0.95),
    "residential_address": AliasEntry("dia_chi", 1.00),
    "home_address": AliasEntry("dia_chi", 1.00),
    "patient_address": AliasEntry("dia_chi", 1.00),
    "address": AliasEntry("dia_chi", 1.00),
    "full_address": AliasEntry("dia_chi", 1.00),
    "noi_o": AliasEntry("dia_chi", 0.90),
    # -----------------------------------------------------------------------
    # phuong_xa (ward / commune)
    # -----------------------------------------------------------------------
    "phuong_xa": AliasEntry("phuong_xa", 1.00),
    "phuong_xa_thi_tran": AliasEntry("phuong_xa", 1.00),
    "don_vi_hanh_chinh_cap_xa": AliasEntry("phuong_xa", 1.00),
    "ward": AliasEntry("phuong_xa", 1.00),
    "commune": AliasEntry("phuong_xa", 1.00),
    "ward_commune": AliasEntry("phuong_xa", 1.00),
    "phuong": AliasEntry("phuong_xa", 0.90),
    "xa": AliasEntry("phuong_xa", 0.90),
    "thi_tran": AliasEntry("phuong_xa", 0.90),
    "px": AliasEntry("phuong_xa", 0.85),
    # -----------------------------------------------------------------------
    # quan_huyen (district)
    # -----------------------------------------------------------------------
    "quan_huyen": AliasEntry("quan_huyen", 1.00),
    "don_vi_hanh_chinh_cap_huyen": AliasEntry("quan_huyen", 1.00),
    "district": AliasEntry("quan_huyen", 1.00),
    "district_name": AliasEntry("quan_huyen", 1.00),
    "quan": AliasEntry("quan_huyen", 0.90),
    "huyen": AliasEntry("quan_huyen", 0.90),
    "thi_xa": AliasEntry("quan_huyen", 0.90),
    "thanh_pho_thuoc_tinh": AliasEntry("quan_huyen", 0.90),
    "qh": AliasEntry("quan_huyen", 0.80),
    # -----------------------------------------------------------------------
    # tinh_thanh_pho (province / city)
    # -----------------------------------------------------------------------
    "tinh_thanh_pho": AliasEntry("tinh_thanh_pho", 1.00),
    "tinh_tp": AliasEntry("tinh_thanh_pho", 1.00),
    "tinh_thanh": AliasEntry("tinh_thanh_pho", 1.00),
    "tinh_thanh_pho_truc_thuoc_trung_uong": AliasEntry("tinh_thanh_pho", 1.00),
    "don_vi_hanh_chinh_cap_tinh": AliasEntry("tinh_thanh_pho", 1.00),
    "province": AliasEntry("tinh_thanh_pho", 1.00),
    "province_name": AliasEntry("tinh_thanh_pho", 1.00),
    "tinh": AliasEntry("tinh_thanh_pho", 0.90),
    "thanh_pho": AliasEntry("tinh_thanh_pho", 0.85),
    "city": AliasEntry("tinh_thanh_pho", 0.85),
    "city_name": AliasEntry("tinh_thanh_pho", 0.85),
    # Ambiguous: thành phố or medical shorthand (see reconciliation note)
    "tp": AliasEntry("tinh_thanh_pho", 0.50),
    # -----------------------------------------------------------------------
    # ngay_kham (visit / examination date)
    # -----------------------------------------------------------------------
    "ngay_kham": AliasEntry("ngay_kham", 1.00),
    "ngay_kham_benh": AliasEntry("ngay_kham", 1.00),
    "ngay_kcb": AliasEntry("ngay_kham", 1.00),
    "ngay_kham_bn": AliasEntry("ngay_kham", 1.00),
    "ngay_kham_benh_nhan": AliasEntry("ngay_kham", 1.00),
    "ngay_kham_tai_co_so": AliasEntry("ngay_kham", 1.00),
    "ngay_kham_chua_benh": AliasEntry("ngay_kham", 1.00),
    "ngay_kham_suc_khoe": AliasEntry("ngay_kham", 0.95),
    "ngay_gio_kham": AliasEntry("ngay_kham", 0.95),
    "ngay_vao_kham": AliasEntry("ngay_kham", 0.95),
    "ngay_dieu_tri": AliasEntry("ngay_kham", 0.90),
    "visit_date": AliasEntry("ngay_kham", 1.00),
    "exam_date": AliasEntry("ngay_kham", 1.00),
    "examination_date": AliasEntry("ngay_kham", 1.00),
    "date_of_visit": AliasEntry("ngay_kham", 1.00),
    "checkup_date": AliasEntry("ngay_kham", 1.00),
    "date": AliasEntry("ngay_kham", 0.70),
    # -----------------------------------------------------------------------
    # icd_tha (ICD code for hypertension / tăng huyết áp)
    # -----------------------------------------------------------------------
    "icd_tha": AliasEntry("icd_tha", 1.00),
    "ma_icd_tha": AliasEntry("icd_tha", 1.00),
    "icd10_tha": AliasEntry("icd_tha", 1.00),
    "icd_tang_huyet_ap": AliasEntry("icd_tha", 1.00),
    "icd_tang_huyet_ap_tha": AliasEntry("icd_tha", 1.00),
    "ma_icd_tang_huyet_ap": AliasEntry("icd_tha", 1.00),
    "ma_benh_tang_huyet_ap": AliasEntry("icd_tha", 1.00),
    "ma_benh_tha": AliasEntry("icd_tha", 0.95),
    "icd_htn": AliasEntry("icd_tha", 1.00),
    "htn_icd": AliasEntry("icd_tha", 1.00),
    "icd_hypertension": AliasEntry("icd_tha", 1.00),
    "hypertension_icd": AliasEntry("icd_tha", 1.00),
    "hypertension_code": AliasEntry("icd_tha", 1.00),
    "tang_huyet_ap": AliasEntry("icd_tha", 0.90),
    "ma_tha": AliasEntry("icd_tha", 0.90),
    # -----------------------------------------------------------------------
    # icd_dtd (ICD code for diabetes / đái tháo đường)
    # -----------------------------------------------------------------------
    "icd_dtd": AliasEntry("icd_dtd", 1.00),
    "ma_icd_dtd": AliasEntry("icd_dtd", 1.00),
    "icd10_dtd": AliasEntry("icd_dtd", 1.00),
    "icd_dai_thao_duong": AliasEntry("icd_dtd", 1.00),
    "icd_tieu_duong": AliasEntry("icd_dtd", 1.00),
    "ma_icd_dai_thao_duong": AliasEntry("icd_dtd", 1.00),
    "ma_benh_dai_thao_duong": AliasEntry("icd_dtd", 1.00),
    "ma_benh_dtd": AliasEntry("icd_dtd", 0.95),
    "icd_dm": AliasEntry("icd_dtd", 1.00),
    "dm_icd": AliasEntry("icd_dtd", 1.00),
    "icd_diabetes": AliasEntry("icd_dtd", 1.00),
    "diabetes_icd": AliasEntry("icd_dtd", 1.00),
    "diabetes_code": AliasEntry("icd_dtd", 1.00),
    "dai_thao_duong": AliasEntry("icd_dtd", 0.90),
    "tieu_duong": AliasEntry("icd_dtd", 0.90),
    "ma_dtd": AliasEntry("icd_dtd", 0.90),
    # -----------------------------------------------------------------------
    # chan_doan_di_kem (secondary / accompanying diagnosis)
    # -----------------------------------------------------------------------
    "chan_doan_di_kem": AliasEntry("chan_doan_di_kem", 1.00),
    "chan_doan_kem": AliasEntry("chan_doan_di_kem", 1.00),
    "chan_doan_kem_theo": AliasEntry("chan_doan_di_kem", 1.00),
    "chan_doan_kem_theo_icd": AliasEntry("chan_doan_di_kem", 1.00),
    "accompanying_diagnosis": AliasEntry("chan_doan_di_kem", 1.00),
    "secondary_diagnosis": AliasEntry("chan_doan_di_kem", 1.00),
    "chan_doan_phu": AliasEntry("chan_doan_di_kem", 0.95),
    "benh_kem_theo": AliasEntry("chan_doan_di_kem", 0.95),
    "benh_mac_kem": AliasEntry("chan_doan_di_kem", 0.95),
    "comorbidities": AliasEntry("chan_doan_di_kem", 1.00),
    "comorbidity": AliasEntry("chan_doan_di_kem", 1.00),
    # -----------------------------------------------------------------------
    # huyet_ap_tam_thu (systolic blood pressure – direct single-column)
    # -----------------------------------------------------------------------
    "huyet_ap_tam_thu": AliasEntry("huyet_ap_tam_thu", 1.00),
    "tam_thu": AliasEntry("huyet_ap_tam_thu", 1.00),
    "ha_tam_thu": AliasEntry("huyet_ap_tam_thu", 1.00),
    "huyet_ap_tam_thu_mmhg": AliasEntry("huyet_ap_tam_thu", 1.00),
    "huyet_ap_thu": AliasEntry("huyet_ap_tam_thu", 0.95),
    "systolic": AliasEntry("huyet_ap_tam_thu", 1.00),
    "sbp": AliasEntry("huyet_ap_tam_thu", 1.00),
    "systolic_bp": AliasEntry("huyet_ap_tam_thu", 1.00),
    "systolic_blood_pressure": AliasEntry("huyet_ap_tam_thu", 1.00),
    "ap_luc_tam_thu": AliasEntry("huyet_ap_tam_thu", 1.00),
    "hatt": AliasEntry("huyet_ap_tam_thu", 0.95),
    # -----------------------------------------------------------------------
    # huyet_ap_tam_truong (diastolic blood pressure – direct single-column)
    # -----------------------------------------------------------------------
    "huyet_ap_tam_truong": AliasEntry("huyet_ap_tam_truong", 1.00),
    "tam_truong": AliasEntry("huyet_ap_tam_truong", 1.00),
    "ha_tam_truong": AliasEntry("huyet_ap_tam_truong", 1.00),
    "huyet_ap_tam_truong_mmhg": AliasEntry("huyet_ap_tam_truong", 1.00),
    "huyet_ap_ttruong": AliasEntry("huyet_ap_tam_truong", 0.95),
    "huyet_ap_truong": AliasEntry("huyet_ap_tam_truong", 0.95),
    "diastolic": AliasEntry("huyet_ap_tam_truong", 1.00),
    "dbp": AliasEntry("huyet_ap_tam_truong", 1.00),
    "diastolic_bp": AliasEntry("huyet_ap_tam_truong", 1.00),
    "diastolic_blood_pressure": AliasEntry("huyet_ap_tam_truong", 1.00),
    "ap_luc_tam_truong": AliasEntry("huyet_ap_tam_truong", 1.00),
    "hattr": AliasEntry("huyet_ap_tam_truong", 0.95),
    # -----------------------------------------------------------------------
    # chi_so_duong_huyet (blood glucose level)
    # -----------------------------------------------------------------------
    "chi_so_duong_huyet": AliasEntry("chi_so_duong_huyet", 1.00),
    "duong_huyet": AliasEntry("chi_so_duong_huyet", 1.00),
    "duong_mau": AliasEntry("chi_so_duong_huyet", 1.00),
    "glucose_mau": AliasEntry("chi_so_duong_huyet", 1.00),
    "blood_glucose": AliasEntry("chi_so_duong_huyet", 1.00),
    "blood_glucose_level": AliasEntry("chi_so_duong_huyet", 1.00),
    "blood_sugar": AliasEntry("chi_so_duong_huyet", 1.00),
    "duong_huyet_mau": AliasEntry("chi_so_duong_huyet", 1.00),
    "duong_huyet_mai": AliasEntry("chi_so_duong_huyet", 0.95),
    "duong_huyet_luc_doi": AliasEntry("chi_so_duong_huyet", 0.95),
    "duong_huyet_doi": AliasEntry("chi_so_duong_huyet", 0.95),
    "duong_glucose": AliasEntry("chi_so_duong_huyet", 0.95),
    "chi_so_duong": AliasEntry("chi_so_duong_huyet", 0.90),
    "chi_so_dh": AliasEntry("chi_so_duong_huyet", 0.90),
    "fasting_glucose": AliasEntry("chi_so_duong_huyet", 0.95),
    "glucose_level": AliasEntry("chi_so_duong_huyet", 0.95),
    "glucose_value": AliasEntry("chi_so_duong_huyet", 0.95),
    "glucose": AliasEntry("chi_so_duong_huyet", 0.95),
    "glu": AliasEntry("chi_so_duong_huyet", 0.90),
    # -----------------------------------------------------------------------
    # chi_so_hba1c (HbA1c level)
    # -----------------------------------------------------------------------
    "chi_so_hba1c": AliasEntry("chi_so_hba1c", 1.00),
    "hba1c": AliasEntry("chi_so_hba1c", 1.00),
    "hba1c_level": AliasEntry("chi_so_hba1c", 1.00),
    "hba1c_value": AliasEntry("chi_so_hba1c", 1.00),
    "xet_nghiem_hba1c": AliasEntry("chi_so_hba1c", 1.00),
    "glycated_hemoglobin": AliasEntry("chi_so_hba1c", 1.00),
    "glycosylated_hemoglobin": AliasEntry("chi_so_hba1c", 1.00),
    "hemoglobin_a1c": AliasEntry("chi_so_hba1c", 1.00),
    "hb_a1c": AliasEntry("chi_so_hba1c", 1.00),
    "chi_so_a1c": AliasEntry("chi_so_hba1c", 1.00),
    "a1c_level": AliasEntry("chi_so_hba1c", 0.95),
    "a1c": AliasEntry("chi_so_hba1c", 0.95),
    "ha1c": AliasEntry("chi_so_hba1c", 0.90),
    # -----------------------------------------------------------------------
    # ghi_chu (notes / remarks)
    # -----------------------------------------------------------------------
    "ghi_chu": AliasEntry("ghi_chu", 1.00),
    "ghi_chu_bn": AliasEntry("ghi_chu", 1.00),
    "ghi_chu_benh_nhan": AliasEntry("ghi_chu", 1.00),
    "ghi_chu_khac": AliasEntry("ghi_chu", 0.95),
    "luu_y": AliasEntry("ghi_chu", 0.90),
    "note": AliasEntry("ghi_chu", 1.00),
    "notes": AliasEntry("ghi_chu", 1.00),
    "remark": AliasEntry("ghi_chu", 1.00),
    "remarks": AliasEntry("ghi_chu", 1.00),
    "comment": AliasEntry("ghi_chu", 0.90),
    "comments": AliasEntry("ghi_chu", 0.90),
    "description": AliasEntry("ghi_chu", 0.85),
    # -----------------------------------------------------------------------
    # dieu_tri (treatment)
    # -----------------------------------------------------------------------
    "dieu_tri": AliasEntry("dieu_tri", 1.00),
    "phuong_phap_dieu_tri": AliasEntry("dieu_tri", 1.00),
    "phac_do_dieu_tri": AliasEntry("dieu_tri", 0.95),
    "dieu_tri_benh": AliasEntry("dieu_tri", 1.00),
    "dieu_tri_dtd": AliasEntry("dieu_tri", 1.00),
    "dieu_tri_tha": AliasEntry("dieu_tri", 1.00),
    "tinh_trang_dieu_tri": AliasEntry("dieu_tri", 0.95),
    "huong_dieu_tri": AliasEntry("dieu_tri", 0.95),
    "dieu_tri_thuoc_huong_dan_cham_soc": AliasEntry("dieu_tri", 0.90),
    "thuoc_dieu_tri": AliasEntry("dieu_tri", 0.85),
    "thuoc_dang_dieu_tri": AliasEntry("dieu_tri", 0.85),
    "treatment": AliasEntry("dieu_tri", 1.00),
    "treatment_plan": AliasEntry("dieu_tri", 1.00),
    "treatment_method": AliasEntry("dieu_tri", 1.00),
    "treatment_regimen": AliasEntry("dieu_tri", 1.00),
    "therapy": AliasEntry("dieu_tri", 0.90),
    "medication": AliasEntry("dieu_tri", 0.85),
    "medications": AliasEntry("dieu_tri", 0.85),
    # Ambiguous: prescription ≠ treatment regimen (see reconciliation note)
    "don_thuoc": AliasEntry("dieu_tri", 0.70),
}


# ---------------------------------------------------------------------------
# STRUCTURAL_RULES
# ---------------------------------------------------------------------------
# Each rule describes a relationship between *source column patterns* and
# *target canonical fields* that cannot be expressed as a 1-to-1 alias.
#
# Rule types
# ~~~~~~~~~~
# COMPOSITE  – one source column contains multiple target values concatenated
#              (e.g. "120/80" encodes systolic and diastolic).
# INDICATOR  – two or more boolean/indicator source columns together encode a
#              single target field (e.g. separate Nam / Nữ columns encode
#              gender).
# SPLIT      – two or more source columns must be concatenated to form a
#              single target value (e.g. Họ + Tên → Họ và tên).
# DERIVED    – one source column contains a richer value from which a
#              specific sub-value is derived (e.g. DOB → birth year).
#
# ``patterns`` are *normalized* strings (output of ``normalize()``).
# ``extractor`` names a value-extraction function defined in the extraction
# layer (outside this mapping module).  The mapping layer does NOT call
# extractors – it records which extractor should be invoked.
#
STRUCTURAL_RULES: list[dict] = [
    {
        "rule_type": "COMPOSITE",
        "patterns": [
            "huyet_ap",
            "ha",
            "blood_pressure",
            "bp",
            "chi_so_ha",
            "chiso_ha",
            "chiso_huyet_ap",
            "chi_so_huyet_ap",
            "cs_huyetap",
            "csha",
        ],
        "targets": ["huyet_ap_tam_thu", "huyet_ap_tam_truong"],
        "extractor": "extract_blood_pressure",
        "description": (
            "A single source column containing 'systolic/diastolic' notation "
            "(e.g. '120/80') maps to both huyet_ap_tam_thu and huyet_ap_tam_truong."
        ),
    },
    # A single source column that stores both the hypertension ICD code and the
    # diabetes ICD code together (e.g. "ICD THA/ĐTĐ", "Mã bệnh THA - ĐTĐ",
    # "icd_tha_dtd").  The extractor layer is responsible for splitting the cell
    # value into the two separate codes; the mapping layer only declares the
    # relationship.
    {
        "rule_type": "COMPOSITE",
        "patterns": [
            # Explicit combined headers (Vietnamese)
            "icd_tha_dtd",
            "icd_dtd_tha",
            "ma_benh_tha_dtd",
            "ma_benh_dtd_tha",
            "ma_icd_tha_dtd",
            "ma_icd_dtd_tha",
            "icd_tha_va_dtd",
            "icd_dtd_va_tha",
            "icd_htn_dm",
            "icd_dm_htn",
            "icd_hypertension_diabetes",
            "icd_diabetes_hypertension",
            "diagnosis_code",  # generic combined-diagnosis column label
            "ma_benh",  # generic disease-code label (ambiguous but common)
            "ma_chan_doan",  # generic diagnostic-code label
        ],
        "targets": ["icd_tha", "icd_dtd"],
        "extractor": "extract_combined_icd",
        "description": (
            "A single source column that encodes both the hypertension ICD code "
            "(icd_tha) and the diabetes ICD code (icd_dtd), typically separated "
            "by '/', '-', or whitespace (e.g. 'I10/E11.9'). The extractor splits "
            "the cell value into the two separate canonical fields."
        ),
    },
    {
        "rule_type": "INDICATOR",
        "patterns": ["nam", "nu", "male", "female", "gioi_tinh_nam", "gioi_tinh_nu"],
        "target": "gioi_tinh",
        "extractor": "extract_indicator_gender",
        "description": (
            "Separate boolean indicator columns for male (Nam) and female (Nữ) "
            "together encode a single gender field."
        ),
    },
    {
        "rule_type": "SPLIT",
        "patterns": ["ho", "ten"],
        "target": "ho_ten",
        "extractor": "extract_split_name",
        "description": (
            "Separate surname (Họ) and given-name (Tên) columns are concatenated "
            "to produce a full name."
        ),
    },
    {
        "rule_type": "DERIVED",
        "patterns": ["ngay_sinh", "ngay_thang_nam_sinh", "dob", "date_of_birth"],
        "target": "nam_sinh",
        "extractor": "extract_year_from_date",
        "description": (
            "A full date-of-birth column; the birth year is extracted as nam_sinh."
        ),
    },
]

# Expose canonical field names for use by consumers that need to enumerate
# all known targets without importing contracts.
CANONICAL_FIELDS: frozenset[str] = frozenset(
    {entry.target for entry in DIRECT_ALIASES.values()}
    | {
        t
        for rule in STRUCTURAL_RULES
        for t in rule.get("targets", [rule.get("target", "")])
    }
)
