"""Project-side interpretation of official documentation evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


CleanClaim = Callable[[str | None], str | None]
KindedCleanClaim = Callable[[str | None, str], str | None]
TextPredicate = Callable[[str], bool]
TextListNormalizer = Callable[[list[str]], list[str]]


@dataclass
class DocsEvidenceBundle:
    target_name: str
    ticker: str | None
    official_urls: dict[str, list[str]] = field(default_factory=dict)
    docs_urls_read: list[str] = field(default_factory=list)
    read_stats: dict[str, Any] = field(default_factory=dict)
    evidence_by_topic: dict[str, list[str]] = field(default_factory=dict)
    raw_snippets: list[dict[str, str]] = field(default_factory=list)
    source_presence_flags: dict[str, bool] = field(default_factory=dict)
    compatibility_hints: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_profile(cls, profile) -> "DocsEvidenceBundle":
        official_urls = {
            str(key): [str(url) for url in (value or []) if str(url).strip()]
            for key, value in ((getattr(profile, "official_urls", {}) or {}).items())
        }
        evidence_by_topic = {
            "overview": _string_list([getattr(profile, "what_the_project_does", None)]),
            "product_entities": _string_list(getattr(profile, "key_product_entities", []) or []),
            "token_utility": _string_list(getattr(profile, "token_utility_points", []) or []),
            "value_capture": _string_list(getattr(profile, "value_capture_points", []) or []),
            "tokenomics": _string_list(getattr(profile, "tokenomics_points", []) or []),
            "token_distribution": _string_list(getattr(profile, "token_distribution_points", []) or []),
            "revenue_model": _string_list(getattr(profile, "revenue_model_points", []) or []),
            "governance": _string_list(getattr(profile, "governance_points", []) or []),
            "treasury": _string_list(getattr(profile, "treasury_points", []) or []),
            "vesting": _string_list(getattr(profile, "vesting_points", []) or []),
            "treasury_control": _string_list(getattr(profile, "treasury_control_points", []) or []),
            "fee_recipients": _string_list(getattr(profile, "fee_recipient_points", []) or []),
            "product_token_link": _string_list(getattr(profile, "product_token_link_points", []) or []),
            "team": _string_list(getattr(profile, "team_points", []) or []),
            "investors_partners": _string_list(getattr(profile, "investor_partner_points", []) or []),
            "roadmap": _string_list(getattr(profile, "roadmap_points", []) or []),
            "risks": _string_list(getattr(profile, "risk_factors", []) or []),
            "audit_highlights": _string_list(getattr(profile, "audit_highlights", []) or []),
            "security_highlights": _string_list(getattr(profile, "security_highlights", []) or []),
        }
        source_presence_flags = {
            "has_security_page": bool(official_urls.get("security")),
            "has_audits_page": bool(official_urls.get("audits")),
            "has_tokenomics_page": bool(official_urls.get("tokenomics")),
            "has_governance_page": bool(official_urls.get("governance")),
            "has_treasury_page": bool(official_urls.get("treasury")),
        }
        compatibility_hints = {
            "project_type": getattr(profile, "project_type", None),
            "project_subtype": getattr(profile, "project_subtype", None),
            "product_lines": getattr(profile, "product_lines", []) or [],
            "confidence": getattr(profile, "confidence", None),
            "business_model": getattr(profile, "business_model", None),
            "revenue_model": getattr(profile, "revenue_model", None),
            "token_role": getattr(profile, "token_role", None),
            "token_exists": getattr(profile, "token_exists", None),
            "governance_present": getattr(profile, "governance_present", None),
            "tokenomics_present": getattr(profile, "tokenomics_present", None),
            "security_section_present": getattr(profile, "security_section_present", None),
            "audits_present": getattr(profile, "audits_present", None),
            "audit_providers": getattr(profile, "audit_providers", []) or [],
            "supported_chains": getattr(profile, "supported_chains", []) or [],
        }
        return cls(
            target_name=str(getattr(profile, "project_name", "") or ""),
            ticker=None,
            official_urls=official_urls,
            docs_urls_read=_string_list(getattr(profile, "docs_urls_read", []) or []),
            read_stats=dict(getattr(profile, "read_stats", {}) or {}),
            evidence_by_topic=evidence_by_topic,
            raw_snippets=list(getattr(profile, "evidence_snippets", []) or []),
            source_presence_flags=source_presence_flags,
            compatibility_hints=compatibility_hints,
        )


@dataclass
class DocumentationInterpretation:
    evidence: DocsEvidenceBundle
    overview: str | None = None
    business_model: str | None = None
    revenue_model: str | None = None
    token_role: str | None = None
    token_utility_claims: list[str] = field(default_factory=list)
    value_capture_claims: list[str] = field(default_factory=list)
    tokenomics_claims: list[str] = field(default_factory=list)
    revenue_model_claims: list[str] = field(default_factory=list)
    fee_recipient_claims: list[str] = field(default_factory=list)
    product_token_link_claims: list[str] = field(default_factory=list)
    governance_claims: list[str] = field(default_factory=list)
    treasury_claims: list[str] = field(default_factory=list)
    treasury_control_claims: list[str] = field(default_factory=list)
    governance_section_claims: list[str] = field(default_factory=list)
    treasury_section_claims: list[str] = field(default_factory=list)
    project_overview_section_claims: list[str] = field(default_factory=list)
    token_utility_section_claims: list[str] = field(default_factory=list)
    value_capture_section_claims: list[str] = field(default_factory=list)
    tokenomics_section_claims: list[str] = field(default_factory=list)
    revenue_model_section_claims: list[str] = field(default_factory=list)
    demand_driver_section_claims: list[str] = field(default_factory=list)
    team_claims: list[str] = field(default_factory=list)
    investors_partners_claims: list[str] = field(default_factory=list)
    roadmap_claims: list[str] = field(default_factory=list)
    fee_flow_detail_present: bool = False
    treasury_control_detail_present: bool = False
    token_needed: bool = False
    documentation_strengths: list[str] = field(default_factory=list)
    documentation_weaknesses: list[str] = field(default_factory=list)
    critical_gaps: list[str] = field(default_factory=list)
    project_type: str | None = None
    project_subtype: str | None = None
    product_lines: list[dict[str, Any]] = field(default_factory=list)


class DocumentationInterpreter:
    """Interprets collector evidence into research-spec concepts."""

    def __init__(
        self,
        *,
        clean_doc_claim: KindedCleanClaim,
        trim_token_utility_noise: CleanClaim,
        looks_like_docs_shell: TextPredicate,
        dedupe_text_items: TextListNormalizer,
    ) -> None:
        self.clean_doc_claim = clean_doc_claim
        self.trim_token_utility_noise = trim_token_utility_noise
        self.looks_like_docs_shell = looks_like_docs_shell
        self.dedupe_text_items = dedupe_text_items

    def interpret(self, profile) -> DocumentationInterpretation:
        evidence = DocsEvidenceBundle.from_profile(profile)
        return DocumentationInterpretation(
            evidence=evidence,
            overview=self._overview(evidence),
            business_model=self._business_model(evidence),
            revenue_model=self._revenue_model(evidence),
            token_role=self._token_role(evidence),
            token_utility_claims=self._token_utility_claims(evidence),
            value_capture_claims=self._value_capture_claims(evidence),
            tokenomics_claims=self._tokenomics_claims(evidence),
            revenue_model_claims=self._revenue_model_claims(evidence),
            fee_recipient_claims=self._fee_recipient_claims(evidence),
            product_token_link_claims=self._product_token_link_claims(evidence),
            governance_claims=self._governance_claims(evidence),
            treasury_claims=self._treasury_claims(evidence),
            treasury_control_claims=self._treasury_control_claims(evidence),
            governance_section_claims=self._governance_section_claims(evidence),
            treasury_section_claims=self._treasury_section_claims(evidence),
            project_overview_section_claims=self._project_overview_section_claims(evidence),
            token_utility_section_claims=self._token_utility_section_claims(evidence),
            value_capture_section_claims=self._value_capture_section_claims(evidence),
            tokenomics_section_claims=self._tokenomics_section_claims(evidence),
            revenue_model_section_claims=self._revenue_model_section_claims(evidence),
            demand_driver_section_claims=self._demand_driver_section_claims(evidence),
            team_claims=self._team_claims(evidence),
            investors_partners_claims=self._investors_partners_claims(evidence),
            roadmap_claims=self._roadmap_claims(evidence),
            fee_flow_detail_present=self._fee_flow_detail_present(evidence),
            treasury_control_detail_present=self._treasury_control_detail_present(evidence),
            token_needed=self._token_needed(evidence),
            documentation_strengths=self._documentation_strengths(evidence),
            documentation_weaknesses=self._documentation_weaknesses(evidence),
            critical_gaps=self._critical_gaps(evidence),
            project_type=str(evidence.compatibility_hints.get("project_type") or ""),
            project_subtype=str(evidence.compatibility_hints.get("project_subtype") or "") or None,
            product_lines=list(evidence.compatibility_hints.get("product_lines") or []),
        )

    def _clean(self, value: str | None, *, kind: str) -> str | None:
        return self.clean_doc_claim(value, kind)

    def _overview(self, evidence: DocsEvidenceBundle) -> str | None:
        for raw in evidence.evidence_by_topic.get("overview", []):
            cleaned = self._clean(raw, kind="overview")
            if cleaned:
                return cleaned
        return None

    def _business_model(self, evidence: DocsEvidenceBundle) -> str | None:
        project_type = str(evidence.compatibility_hints.get("project_type") or "").strip()
        subtype = str(evidence.compatibility_hints.get("project_subtype") or "").strip() or None
        mapped = business_model_from_project_type(project_type, subtype)
        if mapped:
            return mapped
        inferred = _business_model_from_evidence(evidence)
        if inferred:
            return inferred
        raw = evidence.compatibility_hints.get("business_model")
        cleaned = self._clean(str(raw), kind="business_model") if raw else None
        if cleaned:
            return cleaned
        return None

    def _revenue_model(self, evidence: DocsEvidenceBundle) -> str | None:
        direct_raw = evidence.compatibility_hints.get("revenue_model")
        direct = self._clean(str(direct_raw), kind="revenue_model") if direct_raw else None
        for raw in evidence.evidence_by_topic.get("revenue_model", []):
            cleaned = self._clean(raw, kind="revenue_model")
            if cleaned:
                if direct and _is_weak_revenue_claim(cleaned):
                    return direct
                return cleaned
        for raw in evidence.evidence_by_topic.get("fee_recipients", []):
            cleaned = self._clean(raw, kind="fact")
            if cleaned and _looks_like_fee_flow_claim(cleaned):
                return cleaned
        if direct:
            return direct
        return None

    def _token_role(self, evidence: DocsEvidenceBundle) -> str | None:
        raw = evidence.compatibility_hints.get("token_role")
        return self._clean(str(raw), kind="token_role") if raw else None

    def _token_utility_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        items = [
            self._clean(raw, kind="token_role")
            for raw in evidence.evidence_by_topic.get("token_utility", [])
        ]
        return self.dedupe_text_items(
            [
                trimmed
                for item in items
                if item and not self.looks_like_docs_shell(item)
                for trimmed in [self.trim_token_utility_noise(item)]
                if trimmed
            ]
        )[:4]

    def _value_capture_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims = [
            self._clean(raw, kind="token_role")
            for raw in evidence.evidence_by_topic.get("value_capture", [])
        ]
        return self.dedupe_text_items([claim for claim in claims if claim and not self.looks_like_docs_shell(claim)])[:4]

    def _tokenomics_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims = [
            self._clean(raw, kind="token_role")
            for raw in evidence.evidence_by_topic.get("tokenomics", [])
        ]
        return self.dedupe_text_items([claim for claim in claims if claim and not self.looks_like_docs_shell(claim)])[:4]

    def _revenue_model_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims = [
            self._clean(raw, kind="revenue_model")
            for raw in evidence.evidence_by_topic.get("revenue_model", [])
        ]
        return self.dedupe_text_items([claim for claim in claims if claim and not _is_weak_revenue_claim(claim)])[:4]

    def _fee_recipient_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims = [
            self._clean(raw, kind="fact")
            for raw in evidence.evidence_by_topic.get("fee_recipients", [])
        ]
        return self.dedupe_text_items([claim for claim in claims if claim and _looks_like_fee_flow_claim(claim)])[:4]

    def _product_token_link_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims = [
            self._clean(raw, kind="fact")
            for raw in evidence.evidence_by_topic.get("product_token_link", [])
        ]
        return self.dedupe_text_items([claim for claim in claims if claim])[:4]

    def _governance_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims = [
            self._clean(raw, kind="token_role")
            for raw in evidence.evidence_by_topic.get("governance", [])
        ]
        return self.dedupe_text_items([claim for claim in claims if claim])[:4]

    def _treasury_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims = [
            self._clean(raw, kind="token_role")
            for raw in evidence.evidence_by_topic.get("treasury", [])
        ]
        return self.dedupe_text_items([claim for claim in claims if claim])[:4]

    def _treasury_control_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims = [
            self._clean(raw, kind="fact")
            for raw in evidence.evidence_by_topic.get("treasury_control", [])
        ]
        return self.dedupe_text_items([claim for claim in claims if claim])[:4]

    def _team_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims = [
            self._clean(raw, kind="fact")
            for raw in evidence.evidence_by_topic.get("team", [])
        ]
        return self.dedupe_text_items([claim for claim in claims if claim])[:4]

    def _investors_partners_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims = [
            self._clean(raw, kind="fact")
            for raw in evidence.evidence_by_topic.get("investors_partners", [])
        ]
        return self.dedupe_text_items([claim for claim in claims if claim])[:6]

    def _roadmap_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims = [
            self._clean(raw, kind="fact")
            for raw in evidence.evidence_by_topic.get("roadmap", [])
        ]
        return self.dedupe_text_items([claim for claim in claims if claim])[:5]

    def _governance_section_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims: list[str] = []
        if evidence.compatibility_hints.get("governance_present"):
            claims.append("Governance в документации присутствует как отдельная часть протокольной логики.")
        token_role = self._token_role(evidence)
        if token_role and "governance" in token_role.lower():
            claims.append(token_role)
        claims.extend(self._governance_claims(evidence))
        return self.dedupe_text_items(claims)[:5]

    def _treasury_section_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims: list[str] = []
        claims.extend(self._treasury_claims(evidence))
        claims.extend(self._treasury_control_claims(evidence))
        claims.extend(
            claim
            for claim in self._fee_recipient_claims(evidence)
            if _looks_like_treasury_or_holder_fee_flow(claim)
        )
        return self.dedupe_text_items(claims)[:4]

    def _project_overview_section_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims: list[str] = []
        overview = self._overview(evidence)
        if overview:
            claims.append(overview)
        classification = _project_classification_claim(evidence)
        if classification:
            claims.append(classification)
        product_lines = _product_lines_claim(evidence)
        if product_lines:
            claims.append(product_lines)
        business_model = self._business_model(evidence)
        if business_model:
            claims.append(f"Как сам проект монетизирует или позиционирует себя: {business_model}")
        return self.dedupe_text_items(claims)[:4]

    def _token_utility_section_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims: list[str] = []
        token_exists = evidence.compatibility_hints.get("token_exists")
        if token_exists is True:
            claims.append("В документации явно присутствует нативный токен проекта.")
        elif token_exists is False:
            claims.append("В изученной документации не видно явного нативного токена проекта.")
        token_role = self._token_role(evidence)
        if token_role:
            claims.append(f"Роль токена: {token_role}")
        claims.extend(self._token_utility_claims(evidence))
        if evidence.compatibility_hints.get("governance_present"):
            claims.append("Governance-механика в документации раскрыта явно.")
        return self.dedupe_text_items(claims)[:6]

    def _value_capture_section_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims: list[str] = []
        token_role = self._token_role(evidence)
        if token_role and any(token in token_role.lower() for token in ("комисс", "fees", "fee", "revenue", "protocol fees", "gauge", "vecrv")):
            claims.append(token_role)
        claims.extend(self._value_capture_claims(evidence))
        claims.extend(self._fee_recipient_claims(evidence))
        claims.extend(self._product_token_link_claims(evidence))
        revenue_model = self._revenue_model(evidence)
        if revenue_model:
            claims.append(f"Модель выручки: {revenue_model}")
        return self.dedupe_text_items(claims)[:5]

    def _tokenomics_section_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims: list[str] = []
        if evidence.compatibility_hints.get("tokenomics_present"):
            claims.append("В документации есть отдельные tokenomics-разделы или упоминания токеномики.")
        token_role = self._token_role(evidence)
        if token_role:
            claims.append(f"Tokenomics-механика токена: {token_role}")
        claims.extend(f"Tokenomics-механика токена: {claim}" for claim in self._token_utility_claims(evidence))
        claims.extend(self._tokenomics_claims(evidence))
        claims.extend(f"Экономическая механика токена: {claim}" for claim in self._value_capture_claims(evidence))
        claims.extend(f"Связь продукта и токена: {claim}" for claim in self._product_token_link_claims(evidence))
        claims.extend(
            claim
            for claim in (
                self._clean(raw, kind="fact")
                for raw in evidence.evidence_by_topic.get("vesting", [])
            )
            if claim
        )
        return self.dedupe_text_items(claims)[:6]

    def _revenue_model_section_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims: list[str] = []
        revenue_model = self._revenue_model(evidence)
        if revenue_model:
            claims.append(revenue_model)
        claims.extend(self._revenue_model_claims(evidence))
        claims.extend(self._fee_recipient_claims(evidence))
        return self.dedupe_text_items(claims)[:5]

    def _demand_driver_section_claims(self, evidence: DocsEvidenceBundle) -> list[str]:
        claims: list[str] = []
        overview = self._overview(evidence)
        if overview:
            claims.append(f"Спрос на продукт должен идти из описанного use case: {overview}")
        business_model = self._business_model(evidence)
        if business_model:
            claims.append(f"Спрос на продукт и сеть логически связан с этой моделью: {business_model}")
        claims.extend(
            f"Спрос на токен по docs связан со следующим механизмом: {claim}"
            for claim in self._token_utility_claims(evidence)
            if any(term in claim.lower() for term in ("governance", "staking", "fee", "emission", "buyback", "security"))
        )
        return self.dedupe_text_items(claims)[:5]

    def _fee_flow_detail_present(self, evidence: DocsEvidenceBundle) -> bool:
        if self._revenue_model(evidence):
            return True
        if evidence.evidence_by_topic.get("fee_recipients"):
            return True
        token_role = self._token_role(evidence)
        if token_role and _looks_like_fee_flow_claim(token_role):
            return True
        return any(
            _looks_like_fee_flow_claim(claim)
            for claim in self._value_capture_claims(evidence)
        )

    def _treasury_control_detail_present(self, evidence: DocsEvidenceBundle) -> bool:
        if self._treasury_control_claims(evidence):
            return True
        return any(
            _looks_like_treasury_control_claim(claim)
            for claim in self._treasury_section_claims(evidence)
        )

    def _token_needed(self, evidence: DocsEvidenceBundle) -> bool:
        claims = list(self._token_utility_claims(evidence))
        claims.extend(self._product_token_link_claims(evidence))
        if evidence.compatibility_hints.get("token_exists") and evidence.compatibility_hints.get("governance_present"):
            return True
        if not claims:
            return False
        joined = " ".join(claims).lower()
        return any(term in joined for term in ("governance", "staking", "комис", "fees", "security", "эмис", "vote"))

    def _documentation_strengths(self, evidence: DocsEvidenceBundle) -> list[str]:
        strengths: list[str] = []
        if self._overview(evidence) or self._business_model(evidence) or _project_classification_claim(evidence):
            strengths.append("понятное позиционирование продукта")
        if self._token_utility_claims(evidence):
            strengths.append("есть конкретика по utility токена")
        if evidence.compatibility_hints.get("audits_present") or evidence.compatibility_hints.get("security_section_present"):
            strengths.append("есть хотя бы базовое security-раскрытие")
        if evidence.compatibility_hints.get("governance_present"):
            strengths.append("governance-механика описана")
        if evidence.compatibility_hints.get("supported_chains"):
            strengths.append("понятен сетевой охват продукта")
        return strengths or ["минимальная базовая документация присутствует"]

    def _documentation_weaknesses(self, evidence: DocsEvidenceBundle) -> list[str]:
        weaknesses: list[str] = []
        business_model = self._business_model(evidence)
        revenue_model = self._revenue_model(evidence)
        if not business_model and not revenue_model:
            weaknesses.append("неясна бизнес-модель и модель выручки")
        elif business_model and not revenue_model:
            weaknesses.append("не хватает конкретики по модели выручки")
        if not evidence.evidence_by_topic.get("risks"):
            weaknesses.append("слабое раскрытие рисков")
        if not evidence.compatibility_hints.get("audit_providers") and not evidence.compatibility_hints.get("audits_present"):
            weaknesses.append("мало конкретики по security и audits")
        if not evidence.compatibility_hints.get("tokenomics_present"):
            weaknesses.append("нет явной tokenomics-структуры")
        if not self._token_utility_claims(evidence) and evidence.compatibility_hints.get("token_exists"):
            weaknesses.append("utility токена раскрыта слабо")
        return weaknesses or ["крупных слабых мест по docs автоматически не выделено"]

    def _critical_gaps(self, evidence: DocsEvidenceBundle) -> list[str]:
        gaps: list[str] = []
        if not evidence.compatibility_hints.get("tokenomics_present"):
            gaps.append("детальной tokenomics")
        if not evidence.evidence_by_topic.get("vesting"):
            gaps.append("vesting / unlock schedule")
        if not self._revenue_model(evidence):
            gaps.append("понятной модели выручки")
        if not self._fee_flow_detail_present(evidence):
            gaps.append("кто получает fees / revenue")
        if not self._treasury_control_detail_present(evidence):
            gaps.append("кто управляет treasury")
        if not evidence.evidence_by_topic.get("risks"):
            gaps.append("явного risk disclosure")
        if not evidence.compatibility_hints.get("audit_providers") and not evidence.compatibility_hints.get("audits_present"):
            gaps.append("конкретики по audits / bug bounty")
        return gaps


def _string_list(values) -> list[str]:
    items: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text:
            items.append(text)
    return items


def _project_classification_claim(evidence: DocsEvidenceBundle) -> str | None:
    project_type = str(evidence.compatibility_hints.get("project_type") or "").strip()
    subtype = str(evidence.compatibility_hints.get("project_subtype") or "").strip()
    if not project_type or project_type in {"unknown_other", "unknownother"}:
        return None
    project_type_label = _translate_project_type(project_type)
    subtype_label = _translate_project_subtype(subtype) if subtype else ""
    if subtype:
        return f"Документация относит проект к типу {project_type_label}, подтип: {subtype_label or subtype}."
    return f"Документация относит проект к типу {project_type_label}."


def _product_lines_claim(evidence: DocsEvidenceBundle) -> str | None:
    lines = list(evidence.compatibility_hints.get("product_lines") or [])
    labels: list[str] = []
    for item in lines:
        if str(item.get("role") or "").strip() != "secondary":
            continue
        line_type = str(item.get("type") or "").strip()
        if not line_type:
            continue
        subtype = str(item.get("subtype") or "").strip()
        label = _translate_project_type(line_type)
        if subtype:
            label = f"{label} ({_translate_project_subtype(subtype) or subtype})"
        if label not in labels:
            labels.append(label)
    if not labels:
        return None
    return f"Дополнительные продуктовые направления по документации: {', '.join(labels[:4])}."


def business_model_from_project_type(project_type: str, subtype: str | None) -> str | None:
    del subtype
    mapping = {
        "lending": "Протокол связывает заёмщиков и поставщиков ликвидности на ончейн-кредитных рынках.",
        "dex_spot": "Проект обеспечивает ликвидность и маршрутизацию для спотовой торговли токенами.",
        "dex_aggregator": "Проект агрегирует ликвидность и маршруты обменов между DEX/liquidity sources для лучшего исполнения swaps.",
        "perp_dex": "Проект обеспечивает работу рынков перпетуальной торговли и монетизирует торговую активность.",
        "synthetic_dollar": "Проект выпускает крипто-нативный синтетический доллар, обеспеченный залогом, кастоди и инфраструктурой хеджирования.",
        "bridge": "Проект предоставляет cross-chain messaging и interoperability-инфраструктуру для приложений между сетями.",
        "oracle": "Проект предоставляет oracle-инфраструктуру и data feed services для приложений и протоколов.",
        "agent_platform": "Проект предоставляет платформу для токенизации, запуска и ончейн-коммерции AI-агентов.",
        "depin_wireless": "Проект предоставляет децентрализованную wireless-инфраструктуру, где hotspots обеспечивают IoT или mobile coverage, а пользователи платят за использование сети.",
        "liquid_staking": "Проект токенизирует staked/restaked assets, позволяя сохранять ликвидность и получать staking/restaking yield.",
        "asset_management": "Проект предоставляет ончейн asset-management продукты: managed vaults, portfolios, indexes или автоматизированные стратегии.",
        "nft_marketplace": "Проект предоставляет marketplace-инфраструктуру для NFT minting, listings, bids и secondary trading.",
        "gaming": "Проект строит Web3 gaming-экономику вокруг ончейн-активов, rewards или marketplace-флоу.",
        "social": "Проект предоставляет SocialFi или creator-network инфраструктуру вокруг profiles, communities, creators или social graph.",
        "prediction_market": "Проект предоставляет prediction/outcome markets, где пользователи торгуют вероятностями событий и результатами market resolution.",
        "meme": "Проект выглядит как community/meme token; продуктовая utility и бизнес-модель должны подтверждаться отдельно в документации.",
        "ai_network": "Проект предоставляет AI-инфраструктуру: inference, compute, model, agent или subnet marketplaces.",
        "data_infra": "Проект предоставляет инфраструктурные сервисы для других приложений и протоколов.",
        "vault_yield": "Проект автоматизирует распределение капитала по vault-стратегиям для получения доходности.",
        "yield_trading": "Проект позволяет токенизировать, торговать и хеджировать будущую доходность DeFi-активов.",
    }
    return mapping.get((project_type or "").strip())


def _translate_project_type(text: str) -> str:
    mapping = {
        "lending": "лендинг",
        "dex_spot": "спотовый DEX",
        "dex_aggregator": "DEX aggregator",
        "perp_dex": "перпетуальный DEX",
        "synthetic_dollar": "протокол синтетического доллара",
        "bridge": "interoperability / cross-chain messaging",
        "oracle": "оракул",
        "agent_platform": "AI-agent tokenization / commerce platform",
        "depin_wireless": "DePIN / decentralized wireless network",
        "liquid_staking": "liquid staking / restaking",
        "asset_management": "asset management / vault strategies",
        "nft_marketplace": "NFT marketplace",
        "gaming": "gaming / GameFi",
        "social": "SocialFi / creator network",
        "prediction_market": "prediction market",
        "meme": "meme / community token",
        "ai_network": "AI infrastructure / AI network",
        "blockchain": "блокчейн",
        "data_infra": "инфраструктура данных",
        "vault_yield": "yield-хранилища",
        "yield_trading": "yield / interest-rate trading",
    }
    return mapping.get((text or "").strip(), (text or "").strip())


def _translate_project_subtype(text: str) -> str:
    mapping = {
        "cdp_lending": "cdp-lending",
        "amm_spot_dex": "AMM-спотовый DEX",
        "orderbook_spot_dex": "orderbook-спотовый DEX",
        "orderbook_perp_dex": "orderbook-perp DEX",
        "amm_perp_dex": "AMM-perp DEX",
        "payments_tokenization_l1": "payment / asset-tokenization L1",
    }
    return mapping.get((text or "").strip(), (text or "").strip())


def _business_model_from_evidence(evidence: DocsEvidenceBundle) -> str | None:
    haystack = " ".join(
        item
        for topic in ("overview", "revenue_model")
        for item in evidence.evidence_by_topic.get(topic, [])
    ).lower()
    if any(term in haystack for term in ("borrow", "borrower", "suppliers", "supply assets", "collateral", "lending")):
        return "Протокол связывает заёмщиков и поставщиков ликвидности на ончейн-кредитных рынках."
    if any(term in haystack for term in ("dex aggregator", "swap aggregator", "smart order routing", "liquidity sources", "best execution")):
        return "Проект агрегирует ликвидность и маршруты обменов между DEX/liquidity sources для лучшего исполнения swaps."
    if any(term in haystack for term in ("interoperability", "cross-chain messaging", "cross chain messaging", "omnichain", "layerzero", "oapp")):
        return "Проект предоставляет cross-chain messaging и interoperability-инфраструктуру для приложений между сетями."
    if any(term in haystack for term in ("agent tokenization", "ai agent", "ai agents", "agent commerce protocol", "agent tokens", "agent launch")):
        return "Проект предоставляет платформу для токенизации, запуска и ончейн-коммерции AI-агентов."
    if any(term in haystack for term in ("wireless network", "hotspot", "hotspots", "data credits", "proof of coverage", "iot network", "mobile network")):
        return "Проект предоставляет децентрализованную wireless-инфраструктуру, где hotspots обеспечивают IoT или mobile coverage, а пользователи платят за использование сети."
    if any(term in haystack for term in ("liquid staking", "liquid restaking", "staked eth", "staking rewards", "lst", "lrt")):
        return "Проект токенизирует staked/restaked assets, позволяя сохранять ликвидность и получать staking/restaking yield."
    if any(term in haystack for term in ("asset management", "managed vault", "portfolio", "structured product", "strategy vault", "rebalancing")):
        return "Проект предоставляет ончейн asset-management продукты: managed vaults, portfolios, indexes или автоматизированные стратегии."
    if any(term in haystack for term in ("nft marketplace", "nft trading", "creator royalties", "secondary sales", "listings")):
        return "Проект предоставляет marketplace-инфраструктуру для NFT minting, listings, bids и secondary trading."
    if any(term in haystack for term in ("prediction market", "outcome market", "forecast market", "market resolution", "odds")):
        return "Проект предоставляет prediction/outcome markets, где пользователи торгуют вероятностями событий и результатами market resolution."
    if any(term in haystack for term in ("ai network", "inference", "compute marketplace", "gpu compute", "ai models", "subnets")):
        return "Проект предоставляет AI-инфраструктуру: inference, compute, model, agent или subnet marketplaces."
    if any(term in haystack for term in ("trade and hedge yield", "trade yield", "hedge yield", "yield tokenization", "principal token", "yield token", "fixed yield")):
        return "Проект позволяет токенизировать, торговать и хеджировать будущую доходность DeFi-активов."
    if any(term in haystack for term in ("stablecoin", "synthetic dollar", "usds", "stability fee", "surplus buffer")):
        return "Проект выпускает крипто-нативный синтетический доллар, обеспеченный залогом, кастоди и инфраструктурой хеджирования."
    if any(term in haystack for term in ("swap fees", "trading fees", "liquidity pools", "token swaps", "spot exchange")):
        return "Проект обеспечивает ликвидность и маршрутизацию для спотовой торговли токенами."
    if any(term in haystack for term in ("perpetual", "funding", "open interest", "liquidation")):
        return "Проект обеспечивает работу рынков перпетуальной торговли и монетизирует торговую активность."
    return None


def _looks_like_fee_flow_claim(text: str) -> bool:
    lowered = (text or "").lower()
    return any(token in lowered for token in ("fees", "fee", "revenue", "комис", "treasury", "holders", "stakers", "surplus"))


def _looks_like_treasury_or_holder_fee_flow(text: str) -> bool:
    lowered = (text or "").lower()
    return any(token in lowered for token in ("treasury", "dao", "governance", "holders", "stakers", "fees", "fee", "revenue", "комис"))


def _looks_like_treasury_control_claim(text: str) -> bool:
    lowered = (text or "").lower()
    return any(token in lowered for token in ("governance", "dao", "vote", "treasury", "allocat", "direct", "управ", "контрол"))


def _is_weak_revenue_claim(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        term in lowered
        for term in (
            "монетизация завязана на использовании сетевой",
            "primary revenue likely comes",
            "основная выручка протокола, вероятно",
        )
    ) and not any(term in lowered for term in ("reserve factor", "borrower interest", "stability fee", "surplus buffer", "swap fees", "routing fees"))
