"""
Managing an organization's tax setup: configuration entries, packs, its own registrations,
finance settings and customers' tax profiles. Every configuration change is checked (schema,
overlaps, references) and recorded as a new revision.
"""

from datetime import date, datetime, timezone
from typing import Iterable, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ClientNotFoundError
from finance import policies
from finance.errors import FinanceConflictError, FinanceNotFoundError, TaxConfigError
from finance.money import as_float, to_decimal
from finance.packs import get_pack, load_packs
from finance.packs.applier import EntryKey, apply_pack, plan_pack, summarize
from finance.tax.config_schema import validate_entry_data
from finance.tax.lint import lint_snapshot
from finance.tax.registrations import jurisdiction_from_registration, validate_registration_no
from finance.tax.snapshot import ConfigSnapshot
from finance.tax.store import (
    check_no_overlaps,
    ensure_tax_config,
    load_entries,
    load_snapshot,
    record_revision,
)
from models.client import Client
from models.client_tax_profile import ClientTaxProfile
from models.finance_settings import FinanceSettings
from models.tax_config import TaxConfigEntry, TaxConfigRevision, TaxPackApplication
from models.tax_registration import OrgTaxRegistration
from schemas.common import Money
from schemas.tax import (
    ClientTaxProfileResponse,
    ClientTaxProfileUpdate,
    FinanceSettingsResponse,
    FinanceSettingsUpdate,
    LineTax,
    TaxAmount,
    TaxCalculationLineResult,
    TaxCalculationRequest,
    TaxCalculationResponse,
    TaxConfigEntryCreate,
    TaxConfigEntryResponse,
    TaxConfigEntryUpdate,
    TaxConfigRevisionResponse,
    TaxPackApplicationCreate,
    TaxPackApplicationResponse,
    TaxPackChange,
    TaxPackDiff,
    TaxPackSummary,
    TaxRegistrationCreate,
    TaxRegistrationResponse,
    TaxRegistrationUpdate,
    WithholdingPreview,
)
from services.tax_service import DocumentLineSpec, calculate_document, customer_party, resolve_registration, supplier_party
from services.versioning import check_version

RawEntry = tuple[str, str, date, Optional[date], dict]


def _raw(row: TaxConfigEntry) -> RawEntry:
    return row.kind, row.code, row.effective_from, row.effective_to, row.data


def _lint_dates(*periods: tuple[date, Optional[date]], today: date) -> set[date]:
    days = {today}
    for starts, ends in periods:
        days.add(starts)
        if ends is not None:
            days.add(ends)
    return days


def _check_references(before: Iterable[RawEntry], after: Iterable[RawEntry], days: set[date]) -> None:
    """Refuse a change that breaks a reference the configuration did not already have broken."""
    before_rows, after_rows = list(before), list(after)
    introduced: set[str] = set()
    for day in days:
        introduced |= lint_snapshot(ConfigSnapshot.from_raw(day, 0, after_rows)) - lint_snapshot(
            ConfigSnapshot.from_raw(day, 0, before_rows)
        )
    if introduced:
        raise TaxConfigError(
            "TAX_CONFIG_BROKEN_REFERENCE",
            "This change would leave the tax configuration pointing at entries that are not in effect.",
            meta={"problems": sorted(introduced)},
        )


def _entry_response(row: TaxConfigEntry) -> TaxConfigEntryResponse:
    return TaxConfigEntryResponse.model_validate(row)


def _superseded_entry(existing: list[TaxConfigEntry], payload: TaxConfigEntryCreate) -> TaxConfigEntry:
    row = next((entry for entry in existing if entry.id == payload.supersedes_id), None)
    if row is None:
        raise FinanceNotFoundError("TAX_CONFIG_ENTRY_NOT_FOUND", f"Tax configuration entry '{payload.supersedes_id}' not found")
    if (row.kind, row.code) != (payload.kind, payload.code):
        raise TaxConfigError("TAX_CONFIG_SUPERSEDE_MISMATCH", "An entry can only supersede one of the same kind and code.")
    if payload.effective_from <= row.effective_from:
        raise TaxConfigError("TAX_CONFIG_INVALID_PERIOD", "The new entry must start after the one it supersedes.")
    if row.effective_to is not None and row.effective_to < payload.effective_from:
        raise TaxConfigError("TAX_CONFIG_INVALID_PERIOD", "The superseded entry already ends before the new one starts.")
    if payload.effective_from < date.today() and row.effective_from <= date.today():
        raise FinanceConflictError(
            "TAX_CONFIG_ENTRY_IN_EFFECT", "An entry in effect can be superseded from today onward, not in the past."
        )
    return row


class TaxConfigService:
    # ------------------------------------------------------------ entries

    @staticmethod
    async def list_entries(
        session: AsyncSession, org_id: uuid.UUID, kind: Optional[str], code: Optional[str], as_of: Optional[date]
    ) -> list[TaxConfigEntryResponse]:
        await ensure_tax_config(session, org_id)
        rows = await load_entries(session, org_id, kind)
        if code is not None:
            rows = [row for row in rows if row.code == code]
        if as_of is not None:
            rows = [row for row in rows if row.effective_from <= as_of and (row.effective_to is None or as_of < row.effective_to)]
        return [_entry_response(row) for row in rows]

    @staticmethod
    async def get_entry(session: AsyncSession, org_id: uuid.UUID, entry_id: uuid.UUID) -> TaxConfigEntry:
        row = await session.get(TaxConfigEntry, entry_id)
        if row is None or row.organization_id != org_id:
            raise FinanceNotFoundError("TAX_CONFIG_ENTRY_NOT_FOUND", f"Tax configuration entry '{entry_id}' not found")
        return row

    @staticmethod
    async def create_entry(
        session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, payload: TaxConfigEntryCreate
    ) -> TaxConfigEntryResponse:
        await ensure_tax_config(session, org_id, user_id)
        data = validate_entry_data(payload.kind, payload.data).model_dump(mode="json")
        if payload.effective_to is not None and payload.effective_to <= payload.effective_from:
            raise TaxConfigError("TAX_CONFIG_INVALID_PERIOD", "effective_to must be after effective_from")
        existing = await load_entries(session, org_id)
        if any((row.kind, row.code, row.effective_from) == (payload.kind, payload.code, payload.effective_from) for row in existing):
            raise FinanceConflictError(
                "TAX_CONFIG_ENTRY_EXISTS", f"A {payload.kind} '{payload.code}' starting {payload.effective_from} already exists."
            )
        superseded = _superseded_entry(existing, payload) if payload.supersedes_id else None
        new_raw: RawEntry = (payload.kind, payload.code, payload.effective_from, payload.effective_to, data)
        before = [_raw(row) for row in existing]
        after = [_raw(row) for row in existing if row is not superseded]
        if superseded is not None:
            after.append((superseded.kind, superseded.code, superseded.effective_from, payload.effective_from, superseded.data))
        after.append(new_raw)
        _check_references(before, after, _lint_dates((payload.effective_from, payload.effective_to), today=date.today()))

        if superseded is not None:
            superseded.effective_to = payload.effective_from
            superseded.locally_modified = superseded.origin != "manual"
            superseded.version += 1

        row = TaxConfigEntry(
            organization_id=org_id, kind=payload.kind, code=payload.code, effective_from=payload.effective_from,
            effective_to=payload.effective_to, data=data, origin="manual", created_by=user_id,
        )
        session.add(row)
        await session.flush()
        check_no_overlaps(await load_entries(session, org_id))
        action = "Superseded" if superseded is not None else "Added"
        await record_revision(session, org_id, user_id, "manual", f"{action} {payload.kind} {payload.code} from {payload.effective_from}")
        return _entry_response(row)

    @staticmethod
    async def update_entry(
        session: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        entry_id: uuid.UUID,
        payload: TaxConfigEntryUpdate,
        if_match: Optional[str],
    ) -> TaxConfigEntryResponse:
        row = await TaxConfigService.get_entry(session, org_id, entry_id)
        check_version(if_match, row.version)
        today = date.today()
        in_effect = row.effective_from <= today

        new_data = row.data
        if payload.data is not None:
            if in_effect:
                raise FinanceConflictError(
                    "TAX_CONFIG_ENTRY_IN_EFFECT",
                    "This entry is already in effect, so documents may rely on it. Close it with effective_to and add a new entry.",
                )
            new_data = validate_entry_data(row.kind, payload.data).model_dump(mode="json")

        new_end = None if payload.clear_effective_to else (payload.effective_to or row.effective_to)
        if new_end is not None and new_end <= row.effective_from:
            raise TaxConfigError("TAX_CONFIG_INVALID_PERIOD", "effective_to must be after effective_from")
        if in_effect and new_end != row.effective_to and new_end is not None and new_end < today:
            raise FinanceConflictError(
                "TAX_CONFIG_ENTRY_IN_EFFECT", "An entry in effect can be closed from today onward, not in the past."
            )

        existing = await load_entries(session, org_id)
        before = [_raw(other) for other in existing]
        after = [_raw(other) for other in existing if other.id != row.id]
        after.append((row.kind, row.code, row.effective_from, new_end, new_data))
        _check_references(before, after, _lint_dates((row.effective_from, row.effective_to), (row.effective_from, new_end), today=today))

        row.data, row.effective_to = new_data, new_end
        row.locally_modified = row.origin != "manual"
        row.version += 1
        await session.flush()
        check_no_overlaps(await load_entries(session, org_id))
        await record_revision(session, org_id, user_id, "manual", f"Changed {row.kind} {row.code} from {row.effective_from}")
        return _entry_response(row)

    @staticmethod
    async def delete_entry(
        session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, entry_id: uuid.UUID, if_match: Optional[str]
    ) -> None:
        row = await TaxConfigService.get_entry(session, org_id, entry_id)
        check_version(if_match, row.version)
        if row.effective_from <= date.today():
            raise FinanceConflictError(
                "TAX_CONFIG_ENTRY_IN_EFFECT", "Only entries that have not started yet can be deleted. Close this one instead."
            )
        existing = await load_entries(session, org_id)
        before = [_raw(other) for other in existing]
        after = [_raw(other) for other in existing if other.id != row.id]
        _check_references(before, after, _lint_dates((row.effective_from, row.effective_to), today=date.today()))
        await session.delete(row)
        await session.flush()
        await record_revision(session, org_id, user_id, "manual", f"Deleted {row.kind} {row.code} from {row.effective_from}")

    @staticmethod
    async def list_revisions(session: AsyncSession, org_id: uuid.UUID) -> list[TaxConfigRevisionResponse]:
        rows = await session.execute(
            select(TaxConfigRevision)
            .where(TaxConfigRevision.organization_id == org_id)
            .order_by(TaxConfigRevision.revision.desc())
        )
        return [TaxConfigRevisionResponse.model_validate(row) for row in rows.scalars().all()]

    # ------------------------------------------------------------ packs

    @staticmethod
    async def _applied_versions(session: AsyncSession, org_id: uuid.UUID) -> dict[str, int]:
        rows = await session.execute(
            select(TaxPackApplication.pack_code, TaxPackApplication.pack_version).where(
                TaxPackApplication.organization_id == org_id
            )
        )
        applied: dict[str, int] = {}
        for pack_code, version in rows.all():
            applied[pack_code] = max(version, applied.get(pack_code, 0))
        return applied

    @staticmethod
    async def list_packs(session: AsyncSession, org_id: uuid.UUID) -> list[TaxPackSummary]:
        await ensure_tax_config(session, org_id)
        applied = await TaxConfigService._applied_versions(session, org_id)
        summaries = []
        for code, versions in sorted(load_packs().items()):
            latest = versions[max(versions)]
            summaries.append(TaxPackSummary(
                code=code, title=latest.title, description=latest.description,
                latest_version=latest.version, applied_version=applied.get(code),
            ))
        return summaries

    @staticmethod
    async def diff_pack(session: AsyncSession, org_id: uuid.UUID, code: str, version: int) -> TaxPackDiff:
        await ensure_tax_config(session, org_id)
        pack = get_pack(code, version)
        changes = plan_pack(pack, await load_entries(session, org_id), date.today())
        return TaxPackDiff(
            code=pack.code, version=pack.version, summary=summarize(changes),
            changes=[TaxPackChange(**change.as_dict()) for change in changes if change.action != "unchanged"],
        )

    @staticmethod
    async def apply_pack(
        session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, payload: TaxPackApplicationCreate
    ) -> TaxPackApplicationResponse:
        await ensure_tax_config(session, org_id, user_id)
        pack = get_pack(payload.pack, payload.version)
        overwrite: frozenset[EntryKey] = frozenset((ref.kind, ref.code, ref.effective_from) for ref in payload.overwrite)
        application = await apply_pack(session, org_id, pack, user_id=user_id, today=date.today(), overwrite=overwrite)
        return TaxPackApplicationResponse.model_validate(application)

    @staticmethod
    async def list_pack_applications(session: AsyncSession, org_id: uuid.UUID) -> list[TaxPackApplicationResponse]:
        rows = await session.execute(
            select(TaxPackApplication)
            .where(TaxPackApplication.organization_id == org_id)
            .order_by(TaxPackApplication.applied_at.desc())
        )
        return [TaxPackApplicationResponse.model_validate(row) for row in rows.scalars().all()]

    # ------------------------------------------------------------ registrations

    @staticmethod
    async def list_registrations(session: AsyncSession, org_id: uuid.UUID) -> list[TaxRegistrationResponse]:
        rows = await session.execute(
            select(OrgTaxRegistration)
            .where(OrgTaxRegistration.organization_id == org_id)
            .order_by(OrgTaxRegistration.registration_no)
        )
        return [TaxRegistrationResponse.model_validate(row) for row in rows.scalars().all()]

    @staticmethod
    async def get_registration(session: AsyncSession, org_id: uuid.UUID, registration_id: uuid.UUID) -> OrgTaxRegistration:
        row = await session.get(OrgTaxRegistration, registration_id)
        if row is None or row.organization_id != org_id:
            raise FinanceNotFoundError("TAX_REGISTRATION_NOT_FOUND", f"Tax registration '{registration_id}' not found")
        return row

    @staticmethod
    async def _clear_other_defaults(session: AsyncSession, org_id: uuid.UUID, keep: uuid.UUID) -> None:
        rows = await session.execute(
            select(OrgTaxRegistration).where(
                OrgTaxRegistration.organization_id == org_id, OrgTaxRegistration.is_default.is_(True)
            )
        )
        for other in rows.scalars().all():
            if other.id != keep:
                other.is_default = False
                other.version += 1

    @staticmethod
    async def create_registration(
        session: AsyncSession, org_id: uuid.UUID, payload: TaxRegistrationCreate
    ) -> TaxRegistrationResponse:
        snapshot = await load_snapshot(session, org_id, date.today())
        regime = snapshot.regime(payload.regime_code)
        if regime.kind != "indirect":
            raise TaxConfigError("TAX_REGIME_NOT_INDIRECT", f"{payload.regime_code} is a withholding regime; registrations are made under an indirect tax regime.")
        number = validate_registration_no(payload.regime_code, regime, payload.registration_no)
        derived = jurisdiction_from_registration(regime, number)
        jurisdiction = payload.jurisdiction_code or derived
        if payload.jurisdiction_code and derived and payload.jurisdiction_code != derived:
            raise TaxConfigError(
                "REGISTRATION_JURISDICTION_MISMATCH",
                f"Registration {number} belongs to jurisdiction {derived}, not {payload.jurisdiction_code}.",
            )
        if jurisdiction and snapshot.jurisdiction(payload.regime_code, jurisdiction) is None:
            raise TaxConfigError("JURISDICTION_UNKNOWN", f"'{jurisdiction}' is not a jurisdiction of {regime.name}.")
        duplicate = await session.execute(
            select(OrgTaxRegistration.id).where(
                OrgTaxRegistration.organization_id == org_id,
                OrgTaxRegistration.regime_code == payload.regime_code,
                OrgTaxRegistration.registration_no == number,
            )
        )
        if duplicate.first() is not None:
            raise FinanceConflictError("TAX_REGISTRATION_EXISTS", f"Registration {number} is already set up.")

        row = OrgTaxRegistration(
            organization_id=org_id, regime_code=payload.regime_code, registration_no=number,
            legal_name=payload.legal_name, trade_name=payload.trade_name, jurisdiction_code=jurisdiction,
            registration_type=payload.registration_type, address=payload.address, lut_number=payload.lut_number,
            lut_valid_from=payload.lut_valid_from, lut_valid_to=payload.lut_valid_to, is_default=payload.is_default,
            valid_from=payload.valid_from, valid_to=payload.valid_to,
        )
        session.add(row)
        await session.flush()
        if row.is_default:
            await TaxConfigService._clear_other_defaults(session, org_id, row.id)
        await session.flush()
        return TaxRegistrationResponse.model_validate(row)

    @staticmethod
    async def update_registration(
        session: AsyncSession,
        org_id: uuid.UUID,
        registration_id: uuid.UUID,
        payload: TaxRegistrationUpdate,
        if_match: Optional[str],
    ) -> TaxRegistrationResponse:
        row = await TaxConfigService.get_registration(session, org_id, registration_id)
        check_version(if_match, row.version)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(row, field, value)
        row.version += 1
        if row.is_default:
            await TaxConfigService._clear_other_defaults(session, org_id, row.id)
        await session.flush()
        return TaxRegistrationResponse.model_validate(row)

    # ------------------------------------------------------------ finance settings

    @staticmethod
    async def get_settings(session: AsyncSession, org_id: uuid.UUID) -> FinanceSettingsResponse:
        settings = await policies.load_settings(session, org_id)
        response = FinanceSettingsResponse.model_validate(settings)
        # A never-saved row reports version 0, so the first PATCH sends If-Match "0".
        if await session.get(FinanceSettings, org_id) is None:
            response.version = 0
        return response

    @staticmethod
    async def update_settings(
        session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, payload: FinanceSettingsUpdate, if_match: Optional[str]
    ) -> FinanceSettingsResponse:
        saved = await session.get(FinanceSettings, org_id)
        check_version(if_match, saved.version if saved else 0)
        changes = payload.model_dump(exclude_unset=True)
        if changes.get("default_tax_category") or changes.get("deductee_type"):
            snapshot = await load_snapshot(session, org_id, date.today())
            if changes.get("default_tax_category"):
                snapshot.category(changes["default_tax_category"])
            deductee_types = {kind for entry in snapshot.entries("regime") for kind in entry.data.deductee_types}  # type: ignore[attr-defined]
            if changes.get("deductee_type") and changes["deductee_type"] not in deductee_types:
                raise TaxConfigError(
                    "DEDUCTEE_TYPE_UNKNOWN", f"'{changes['deductee_type']}' is not a deductee type.",
                    meta={"allowed": sorted(deductee_types)},
                )
        if saved is None:
            saved = policies.defaults(org_id)
            saved.version = 0
            session.add(saved)
        for field, value in changes.items():
            setattr(saved, field, value)
        saved.version += 1
        saved.updated_by = user_id
        saved.updated_at = datetime.now(timezone.utc)
        await session.flush()
        return FinanceSettingsResponse.model_validate(saved)

    # ------------------------------------------------------------ customer tax profiles

    @staticmethod
    async def _client(session: AsyncSession, org_id: uuid.UUID, client_id: uuid.UUID) -> Client:
        client = await session.get(Client, client_id)
        if client is None or client.organization_id != org_id:
            raise ClientNotFoundError(str(client_id))
        return client

    @staticmethod
    async def _profile_response(
        session: AsyncSession, org_id: uuid.UUID, client: Client, profile: Optional[ClientTaxProfile]
    ) -> ClientTaxProfileResponse:
        effective: dict = {}
        today = date.today()
        try:
            registration = await resolve_registration(session, org_id, None, today)
        except TaxConfigError:
            registration = None
        if registration is not None:
            snapshot = await load_snapshot(session, org_id, today)
            regime = snapshot.regime(registration.regime_code)
            settings = await policies.load_settings(session, org_id)
            party = customer_party(client, profile, regime, supplier_party(registration, regime, today), settings.deductee_type)
            effective = {
                "registration_type": party.registration_type,
                "registration_no": party.registration_no,
                "place_of_supply": party.place_of_supply,
                "country": party.country,
                "tds_section_code": party.withholding.section_code if party.withholding else None,
            }
        if profile is None:
            return ClientTaxProfileResponse(client_id=client.id, effective=effective)
        return ClientTaxProfileResponse(
            client_id=client.id, registration_type=profile.registration_type, registration_no=profile.registration_no,
            place_of_supply=profile.place_of_supply, country=profile.country, tds_section_code=profile.tds_section_code,
            lower_deduction_certificates=profile.lower_deduction_certificates or [],
            effective=effective, version=profile.version,
        )

    @staticmethod
    async def get_client_profile(session: AsyncSession, org_id: uuid.UUID, client_id: uuid.UUID) -> ClientTaxProfileResponse:
        client = await TaxConfigService._client(session, org_id, client_id)
        return await TaxConfigService._profile_response(session, org_id, client, await session.get(ClientTaxProfile, client.id))

    @staticmethod
    async def put_client_profile(
        session: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        client_id: uuid.UUID,
        payload: ClientTaxProfileUpdate,
        if_match: Optional[str],
    ) -> ClientTaxProfileResponse:
        client = await TaxConfigService._client(session, org_id, client_id)
        profile = await session.get(ClientTaxProfile, client.id)
        check_version(if_match, profile.version if profile else 0)
        await TaxConfigService._check_profile_against_config(session, org_id, payload)

        if profile is None:
            profile = ClientTaxProfile(client_id=client.id, organization_id=org_id, version=0)
            session.add(profile)
        profile.registration_type = payload.registration_type
        profile.registration_no = payload.registration_no
        profile.place_of_supply = payload.place_of_supply
        profile.country = payload.country.upper() if payload.country else None
        profile.tds_section_code = payload.tds_section_code
        profile.lower_deduction_certificates = [item.model_dump(mode="json") for item in payload.lower_deduction_certificates]
        profile.version += 1
        profile.updated_by = user_id
        profile.updated_at = datetime.now(timezone.utc)
        await session.flush()
        return await TaxConfigService._profile_response(session, org_id, client, profile)

    @staticmethod
    async def _check_profile_against_config(session: AsyncSession, org_id: uuid.UUID, payload: ClientTaxProfileUpdate) -> None:
        snapshot = await load_snapshot(session, org_id, date.today())
        known_types = {kind for entry in snapshot.entries("regime") for kind in entry.data.party_registration_types}  # type: ignore[attr-defined]
        if payload.registration_type and known_types and payload.registration_type not in known_types:
            raise TaxConfigError(
                "REGISTRATION_TYPE_UNKNOWN",
                f"'{payload.registration_type}' is not a customer registration type of any regime in use.",
                meta={"allowed": sorted(known_types)},
            )
        if payload.tds_section_code and snapshot.withholding_section(payload.tds_section_code) is None:
            raise TaxConfigError(
                "WITHHOLDING_SECTION_NOT_EFFECTIVE", f"No withholding section '{payload.tds_section_code}' is in effect today."
            )

    # ------------------------------------------------------------ preview

    @staticmethod
    async def calculate(session: AsyncSession, org_id: uuid.UUID, payload: TaxCalculationRequest) -> TaxCalculationResponse:
        client = await TaxConfigService._client(session, org_id, payload.client_id)
        tax_point = payload.tax_point_date or date.today()
        lines = [
            DocumentLineSpec(
                line_no=position,
                quantity=to_decimal(line.quantity),
                unit_price=to_decimal(line.unit_price.amount),
                discount_amount=to_decimal(line.discount.amount) if line.discount else to_decimal(0),
                discount_percent=to_decimal(line.discount_pct),
                category_code=line.tax_category_code,
                classification_code=line.sac_code,
                price_includes_tax=line.price_includes_tax,
            )
            for position, line in enumerate(payload.lines, start=1)
        ]
        calculation = await calculate_document(
            session, org_id, client, lines, tax_point, payload.document_type, payload.currency,
            payload.tax_registration_id, payload.place_of_supply,
        )
        result, currency = calculation.result, payload.currency

        def money(amount) -> Money:
            return Money(amount=as_float(amount), currency=currency)

        return TaxCalculationResponse(
            regime_code=result.regime_code,
            config_revision=result.config_revision,
            tax_point_date=tax_point,
            supply_type=result.supply_type,
            place_of_supply=result.place_of_supply,
            reverse_charge=result.reverse_charge,
            lines=[
                TaxCalculationLineResult(
                    line_no=line.line_no, tax_category_code=line.category_code,
                    classification_code=line.classification_code, taxable_value=money(line.taxable_value),
                    taxes=[
                        LineTax(component_code=tax.component_code, label=tax.label, behaviour=tax.behaviour,
                                rate=as_float(tax.percent), amount=money(tax.amount), base=money(tax.base), rule_code=tax.rule_code)
                        for tax in line.taxes
                    ],
                    line_total=money(line.line_total),
                )
                for line in result.lines
            ],
            subtotal=money(result.subtotal),
            discount_total=money(result.discount_total),
            taxable_total=money(result.taxable_total),
            taxes=[
                TaxAmount(component_code=tax.component_code, label=tax.label, behaviour=tax.behaviour,
                          rate=as_float(tax.percent), amount=money(tax.amount))
                for tax in result.taxes
            ],
            tax_total=money(result.tax_total),
            round_off=money(result.round_off),
            grand_total=money(result.grand_total),
            withholding=[
                WithholdingPreview(section_code=item.section_code, statute_ref=item.statute_ref, payment_code=item.payment_code,
                                   rate=as_float(item.percent), base=money(item.base), amount=money(item.amount),
                                   certificate_no=item.certificate_no)
                for item in result.withholding
            ],
            net_receivable=money(result.net_receivable),
            notes=list(result.notes),
        )
