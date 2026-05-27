from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from project_knowledge_agent.config import Settings
from project_knowledge_agent.docs_stage import OfficialDocsStage
from project_knowledge_agent.documentation_prompt import DOCUMENTATION_ANALYSIS_PROMPT_VERSION
from project_knowledge_agent.official_blog_stage import OfficialBlogPost, OfficialBlogStage
from project_knowledge_agent.documentation_interpreter import business_model_from_project_type
from project_knowledge_agent.service import DocsEvidenceBundle, ProjectKnowledgeAgent, Target, _new_documentation_interpreter, _render_official_blog_claim


class _StubDocsProfile:
    def __init__(self) -> None:
        self.project_name = "Ripple"
        self.official_urls = {
            "website": ["https://ripple.com/"],
            "docs": ["https://docs.ripple.com/overview"],
            "tokenomics": ["https://docs.ripple.com/tokenomics"],
            "security": ["https://docs.ripple.com/security"],
            "audits": ["https://ripple.com/audits"],
        }
        self.docs_urls_read = [
            "https://docs.ripple.com/overview",
            "https://docs.ripple.com/security",
        ]
        self.project_type = "blockchain"
        self.project_subtype = "payments"
        self.product_lines = [
            {
                "type": "blockchain",
                "subtype": "payments",
                "role": "primary",
                "confidence": 0.91,
                "evidence_urls": ["https://docs.ripple.com/overview"],
            }
        ]
        self.confidence = 0.91
        self.what_the_project_does = "Ripple provides cross-border payments infrastructure."
        self.business_model = "The network monetizes payment and settlement infrastructure usage."
        self.revenue_model = "Revenue is tied to infrastructure and enterprise network adoption."
        self.token_role = "XRP is used for settlement and network liquidity."
        self.token_utility_points = [
            "XRP is used for settlement and network liquidity.",
        ]
        self.value_capture_points = [
            "XRP supports network liquidity and settlement demand across payment corridors.",
        ]
        self.tokenomics_points = [
            "Tokenomics documentation describes supply and network-level token mechanics.",
        ]
        self.token_distribution_points = [
            "Treasury and ecosystem allocations are referenced in official materials.",
        ]
        self.revenue_model_points = [
            "Монетизация завязана на использовании сетевой и расчётной инфраструктуры проекта.",
        ]
        self.governance_points = [
            "Token holders can participate in governance decisions affecting network operations.",
        ]
        self.treasury_points = [
            "Treasury resources are managed through governance-linked decision processes.",
        ]
        self.team_points = [
            "Ripple leadership includes operators focused on enterprise payments and settlement infrastructure.",
        ]
        self.investor_partner_points = [
            "Ripple documentation highlights enterprise liquidity partnerships and ecosystem integrations.",
        ]
        self.roadmap_points = [
            "The roadmap prioritizes expansion of payment corridors and settlement capabilities.",
        ]
        self.vesting_points = [
            "Unlock schedule and vesting terms are described in official token documentation.",
        ]
        self.treasury_control_points = [
            "Governance can direct treasury resources toward ecosystem priorities.",
        ]
        self.fee_recipient_points = [
            "A documented share of protocol value is routed to treasury-aligned stakeholders.",
        ]
        self.product_token_link_points = [
            "Token mechanics are tied to network usage, liquidity, and governance participation.",
        ]
        self.supported_chains = ["XRP Ledger"]
        self.audits_present = True
        self.governance_present = True
        self.tokenomics_present = True
        self.security_section_present = True
        self.token_exists = True
        self.risk_factors = ["Operational and regulatory risks are documented in security materials."]
        self.key_product_entities = ["Liquidity Hub", "Cross-border settlement"]
        self.evidence_snippets = [
            {
                "text": "Ripple supports enterprise payment corridors and cross-border settlement flows.",
                "url": "https://docs.ripple.com/overview",
            }
        ]

    def model_dump(self, mode: str = "python") -> dict:
        del mode
        return {
            "project_name": self.project_name,
            "official_urls": self.official_urls,
            "docs_urls_read": self.docs_urls_read,
            "project_type": self.project_type,
            "project_subtype": self.project_subtype,
            "product_lines": self.product_lines,
            "confidence": self.confidence,
            "what_the_project_does": self.what_the_project_does,
            "business_model": self.business_model,
            "revenue_model": self.revenue_model,
            "token_role": self.token_role,
            "token_utility_points": self.token_utility_points,
            "value_capture_points": self.value_capture_points,
            "tokenomics_points": self.tokenomics_points,
            "token_distribution_points": self.token_distribution_points,
            "revenue_model_points": self.revenue_model_points,
            "governance_points": self.governance_points,
            "treasury_points": self.treasury_points,
            "team_points": self.team_points,
            "investor_partner_points": self.investor_partner_points,
            "roadmap_points": self.roadmap_points,
            "vesting_points": self.vesting_points,
            "treasury_control_points": self.treasury_control_points,
            "fee_recipient_points": self.fee_recipient_points,
            "product_token_link_points": self.product_token_link_points,
            "supported_chains": self.supported_chains,
            "audits_present": self.audits_present,
            "governance_present": self.governance_present,
            "tokenomics_present": self.tokenomics_present,
            "security_section_present": self.security_section_present,
            "token_exists": self.token_exists,
            "risk_factors": self.risk_factors,
            "key_product_entities": self.key_product_entities,
            "evidence_snippets": self.evidence_snippets,
        }


class _StubDocsStage:
    async def collect(self, target, *, client, period_days: int = 365):
        del target, client, period_days
        profile = _StubDocsProfile()
        return type(
            "DocsResult",
            (),
            {
                "profile": profile,
                "status": "ok",
                "summary": profile.what_the_project_does,
                "citations": ["https://docs.ripple.com/overview"],
                "coverage": {"available": True, "pages_read": 2},
            },
        )()


class _StubBlogStage:
    async def collect(self, target, *, client, docs_result, period_days: int = 365):
        del target, client, docs_result
        post = type(
            "OfficialBlogPost",
            (),
            {
                "url": "https://ripple.com/blog/enterprise-expansion",
                "title": "Ripple enterprise expansion",
                "published_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
                "summary": "Ripple announced new enterprise payment corridors and liquidity partnerships.",
                "key_points": [
                    "Ripple expanded payment corridors across new enterprise markets.",
                    "The company highlighted new liquidity partnerships for settlement flows.",
                ],
                "categories": ["partnership", "official_update"],
                "source_name": "official_blog",
                "source_type": "official_blog",
            },
        )()
        return type(
            "OfficialBlogResult",
            (),
            {
                "posts": [post],
                "citations": [post.url],
                "status": "ok",
                "coverage": {"available": True, "period_days": period_days, "posts_kept": 1},
            },
        )()


def _settings() -> Settings:
    return Settings(
        http_timeout_seconds=5,
        docs_stage_cap_seconds=5,
        docs_cache_dir="/tmp/project-knowledge-test-cache",
        docs_cache_ttl_seconds=3600,
        docs_max_pages=10,
        docs_max_seed_pages=5,
        official_blog_max_posts=8,
        official_blog_max_seed_pages=6,
    )


class _RecordingDocsBuilder:
    def __init__(self) -> None:
        self.manual_docs_urls: list[str] | None = None

    async def build(
        self,
        request,
        *,
        client,
        deadline_at: float,
        refresh: bool = False,
        manual_docs_urls: list[str] | None = None,
    ):
        del request, client, deadline_at, refresh
        self.manual_docs_urls = manual_docs_urls
        return type(
            "Profile",
            (),
            {
                "official_urls": {"docs": manual_docs_urls or [], "website": ["https://uniswap.org/"]},
                "docs_urls_read": manual_docs_urls or [],
                "what_the_project_does": "Uniswap provides decentralized trading infrastructure.",
                "read_stats": {"pages_read": len(manual_docs_urls or [])},
                "project_type": "dex_spot",
                "project_subtype": "amm_spot_dex",
            },
        )()


def test_project_knowledge_agent_builds_section_from_docs_and_official_blog():
    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_StubDocsStage(),
        blog_stage=_StubBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Ripple", ticker="XRP"), []))

    assert section.section_id == "project_knowledge"
    assert section.status == "ok"
    assert "### 1. Metadata" in section.markdown
    assert "### 2. Project Overview" in section.markdown
    assert "### 18. Final Documentation Verdict" in section.markdown
    assert "Official Blogs and Announcements" not in section.markdown
    assert "Treasury-ресурсы управляются через процессы принятия решений, связанные с governance." in section.markdown
    assert "Монетизация завязана на использовании сетевой и расчётной инфраструктуры проекта." in section.markdown
    assert "Руководство Ripple включает специалистов, сфокусированных на корпоративных платежах и расчётной инфраструктуре." in section.markdown
    assert "Roadmap делает акцент на расширении платёжных коридоров и расчётных возможностей." in section.markdown
    assert "В официальных token-документации описаны график unlock и условия vesting." not in section.markdown
    assert "В официальной token-документации описаны график unlock и условия vesting." in section.markdown
    assert "Governance может направлять treasury-ресурсы на приоритеты экосистемы." in section.markdown
    assert "https://docs.ripple.com/overview" in section.citations
    assert "](" not in section.markdown
    assert any(item.category == "project_overview" for item in section.findings)
    assert not any(item.source_type == "official_blog" for item in section.findings)
    assert section.metadata["documentation_analysis_prompt_version"] == DOCUMENTATION_ANALYSIS_PROMPT_VERSION


def test_docs_evidence_bundle_keeps_collector_output_as_evidence_and_compatibility_hints():
    profile = _StubDocsProfile()
    profile.revenue_model_points = ["Protocol revenue comes from swap fees and routing fees."]
    profile.token_utility_points = ["XRP holders can vote on governance proposals."]

    bundle = DocsEvidenceBundle.from_profile(profile)

    assert bundle.evidence_by_topic["revenue_model"] == ["Protocol revenue comes from swap fees and routing fees."]
    assert bundle.evidence_by_topic["token_utility"] == ["XRP holders can vote on governance proposals."]
    assert bundle.compatibility_hints["business_model"] == "The network monetizes payment and settlement infrastructure usage."
    assert bundle.source_presence_flags["has_tokenomics_page"] is True


def test_documentation_interpreter_prefers_evidence_and_treats_collector_fields_as_hints():
    profile = _StubDocsProfile()
    profile.what_the_project_does = None
    profile.business_model = None
    profile.revenue_model = "Primary revenue likely comes from gas or network fees."
    profile.revenue_model_points = ["Protocol revenue comes from service fees."]
    profile.value_capture_points = ["Токен связан с использованием сети, ликвидностью и governance participation."]
    profile.tokenomics_points = ["Документация описывает supply и сетевую механику токена."]
    profile.fee_recipient_points = ["Доля protocol fees направляется в treasury протокола."]
    profile.product_token_link_points = []
    profile.token_utility_points = ["XRP holders can vote on governance proposals."]
    profile.governance_points = ["Token holders can participate in governance decisions affecting network operations."]
    profile.treasury_points = ["Treasury resources are managed through governance-linked decision processes."]
    profile.treasury_control_points = ["Governance can direct treasury resources toward ecosystem priorities."]
    profile.team_points = ["Ripple leadership includes operators focused on enterprise payments and settlement infrastructure."]
    profile.investor_partner_points = ["Ripple documentation highlights enterprise liquidity partnerships and ecosystem integrations."]
    profile.roadmap_points = ["The roadmap prioritizes expansion of payment corridors and settlement capabilities."]

    interpretation = _new_documentation_interpreter().interpret(profile)

    assert interpretation.business_model is None
    assert interpretation.revenue_model == "Выручка протокола формируется за счёт service fees."
    assert interpretation.revenue_model_claims == ["Выручка протокола формируется за счёт service fees."]
    assert interpretation.token_utility_claims == ["Держатели XRP могут голосовать по governance proposals."]
    assert interpretation.value_capture_claims == ["Токен связан с использованием сети, ликвидностью и governance participation."]
    assert interpretation.tokenomics_claims == ["Документация описывает supply и сетевую механику токена."]
    assert interpretation.fee_recipient_claims == ["Доля protocol fees направляется в treasury протокола."]
    assert interpretation.governance_claims == ["Держатели токена могут участвовать в governance-решениях, влияющих на работу сети."]
    assert interpretation.treasury_claims == ["Treasury-ресурсы управляются через процессы принятия решений, связанные с governance."]
    assert interpretation.treasury_control_claims == ["Governance может направлять treasury-ресурсы на приоритеты экосистемы."]
    assert interpretation.team_claims == ["Руководство Ripple включает специалистов, сфокусированных на корпоративных платежах и расчётной инфраструктуре."]
    assert interpretation.investors_partners_claims == ["Документация Ripple выделяет корпоративные liquidity-партнёрства и ecosystem-интеграции."]
    assert interpretation.roadmap_claims == ["Roadmap делает акцент на расширении платёжных коридоров и расчётных возможностей."]


def test_official_docs_stage_uses_manual_docs_url_override_from_target_metadata():
    builder = _RecordingDocsBuilder()
    stage = OfficialDocsStage(settings=_settings(), builder=builder)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
            return await stage.collect(
                Target(
                    name="Uni",
                    ticker="UNI",
                    metadata={"docs_url": "https://developers.uniswap.org/docs/"},
                ),
                client=client,
            )

    result = asyncio.run(run())

    assert builder.manual_docs_urls == ["https://developers.uniswap.org/docs/"]
    assert "https://developers.uniswap.org/docs/" in result.citations
    assert result.status == "ok"


def test_project_knowledge_agent_keeps_business_and_revenue_fallbacks_and_drops_jsx_noise():
    class _AaveLikeProfile(_StubDocsProfile):
        def __init__(self) -> None:
            super().__init__()
            self.project_name = "Aave"
            self.official_urls = {
                "website": ["https://aave.com/"],
                "docs": ["https://aave.com/help"],
            }
            self.docs_urls_read = ["https://aave.com/help"]
            self.project_type = "lending"
            self.project_subtype = "cdp_lending"
            self.what_the_project_does = "Aave is an open source liquidity protocol where users supply assets to earn yield and borrow against collateral."
            self.business_model = "Connects suppliers and borrowers in onchain credit markets."
            self.revenue_model = "Primary revenue likely comes from borrow demand, reserve spreads, and protocol fees."
            self.token_utility_points = [
                'Teams operating in Web3 are increasingly expected to demonstrate mature internal controls." }), "\\n", jsx(components.p, { children: "Noise',
                "AAVE is used as the centre of gravity of Aave protocol governance.",
                "AAVE can be staked within the protocol Safety Module to earn incentives.",
                "Governance The Aave Governance forum.",
            ]
            self.token_role = "AAVE is used as the centre of gravity of Aave protocol governance."

    class _AaveDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _AaveLikeProfile()
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://aave.com/help"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_AaveDocsStage(),
        blog_stage=_StubBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Aave", ticker="AAVE"), []))

    assert "Протокол связывает заёмщиков и поставщиков ликвидности на ончейн-кредитных рынках." in section.markdown
    assert "Основная выручка протокола, вероятно, формируется за счёт спроса на займы, процентных спредов резервов и протокольных комиссий." in section.markdown
    assert "Выглядит ли бизнес-модель понятной: да." in section.markdown
    assert "jsx(components.p" not in section.markdown
    assert "Governance The Aave Governance forum." not in section.markdown


def test_project_knowledge_agent_distinguishes_clear_business_model_from_missing_revenue_specifics():
    class _DexLikeProfile(_StubDocsProfile):
        def __init__(self) -> None:
            super().__init__()
            self.project_name = "Aerodrome"
            self.official_urls = {
                "website": ["https://aerodrome.finance/"],
                "docs": ["https://aerodrome.finance/docs"],
            }
            self.docs_urls_read = ["https://aerodrome.finance/docs"]
            self.project_type = "dex_spot"
            self.project_subtype = "amm_spot_dex"
            self.business_model = "Provides spot exchange liquidity and routing for token trading."
            self.revenue_model = None
            self.revenue_model_points = []
            self.fee_recipient_points = []
            self.token_utility_points = [
                "AERO can be locked for governance and emissions voting.",
            ]
            self.token_role = "AERO can be locked for governance and emissions voting."

    class _DexDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _DexLikeProfile()
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://aerodrome.finance/docs"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DexDocsStage(),
        blog_stage=_StubBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Aerodrome", ticker="AERO"), []))

    assert "Выглядит ли бизнес-модель понятной: да." in section.markdown
    assert "не хватает конкретики по модели выручки" in section.markdown
    assert "неясна бизнес-модель и модель выручки" not in section.markdown
    assert "Бизнес-модель и модель выручки проекта по изученной документации остаются неясными." not in section.markdown


def test_project_knowledge_agent_uses_business_model_when_overview_missing_in_final_verdict():
    class _SkyLikeProfile(_StubDocsProfile):
        def __init__(self) -> None:
            super().__init__()
            self.project_name = "Sky"
            self.official_urls = {
                "website": ["https://sky.money/"],
                "docs": ["https://developers.skyeco.com/"],
            }
            self.docs_urls_read = ["https://sky.money/", "https://developers.skyeco.com/"]
            self.project_type = "synthetic_dollar"
            self.project_subtype = None
            self.what_the_project_does = None
            self.business_model = "Issues a crypto-native synthetic dollar backed by collateral, custody, and hedging infrastructure."
            self.revenue_model = None
            self.token_utility_points = ["SKY используется для управления протоколом через governance."]
            self.token_role = "SKY используется для управления протоколом через governance."

    class _SkyDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _SkyLikeProfile()
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": None,
                    "citations": ["https://sky.money/"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_SkyDocsStage(),
        blog_stage=_StubBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Sky", ticker="SKY"), []))

    assert "Что это за проект: Sky: Проект выпускает крипто-нативный синтетический доллар, обеспеченный залогом, кастоди и инфраструктурой хеджирования." in section.markdown
    assert "без достаточно чёткого высокоуровневого описания" not in section.markdown


def test_project_knowledge_agent_uses_classification_summary_when_overview_and_business_model_missing():
    class _UniLikeProfile(_StubDocsProfile):
        def __init__(self) -> None:
            super().__init__()
            self.project_name = "Uni"
            self.official_urls = {
                "website": ["https://uniswap.org/"],
                "docs": ["https://developers.uniswap.org/docs"],
            }
            self.docs_urls_read = ["https://developers.uniswap.org/docs"]
            self.project_type = "dex_spot"
            self.project_subtype = "amm_spot_dex"
            self.what_the_project_does = None
            self.business_model = None
            self.revenue_model = None
            self.token_exists = True
            self.token_utility_points = []
            self.token_role = None
            self.governance_present = False
            self.tokenomics_present = False
            self.security_section_present = False
            self.audits_present = False
            self.risk_factors = []

    class _UniDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _UniLikeProfile()
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": None,
                    "citations": ["https://developers.uniswap.org/docs"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_UniDocsStage(),
        blog_stage=_StubBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Uni", ticker="UNI"), []))

    assert (
        "Что это за проект: Uni: спотовый DEX, подтип: AMM-спотовый DEX." in section.markdown
        or "Что это за проект: Uni: Проект обеспечивает ликвидность и маршрутизацию для спотовой торговли токенами." in section.markdown
    )
    assert "без достаточно чёткого высокоуровневого описания" not in section.markdown


def test_project_knowledge_agent_uses_revenue_fee_and_treasury_points_to_avoid_false_gaps():
    class _LinkProtoProfile(_StubDocsProfile):
        def __init__(self) -> None:
            super().__init__()
            self.project_name = "LinkProto"
            self.official_urls = {
                "website": ["https://linkproto.org/"],
                "docs": ["https://linkproto.org/tokenomics"],
                "tokenomics": ["https://linkproto.org/tokenomics"],
                "governance": ["https://linkproto.org/governance"],
                "treasury": ["https://linkproto.org/treasury"],
            }
            self.docs_urls_read = [
                "https://linkproto.org/tokenomics",
                "https://linkproto.org/governance",
                "https://linkproto.org/treasury",
                "https://linkproto.org/fees",
            ]
            self.what_the_project_does = "LinkProto provides decentralized trading infrastructure."
            self.business_model = "Provides spot exchange liquidity and routing for token trading."
            self.revenue_model = None
            self.revenue_model_points = ["Protocol revenue comes from swap fees and routing fees."]
            self.value_capture_points = ["LINKP can be locked to direct emissions toward liquidity pools that route the most trading activity."]
            self.fee_recipient_points = ["Thirty percent of fees accrues to the treasury while the remainder is distributed to locked LINKP holders."]
            self.treasury_control_points = ["The DAO can direct treasury reserves toward ecosystem grants and liquidity support programs."]
            self.treasury_points = ["The protocol treasury receives a share of fees and governance can direct treasury reserves to ecosystem grants."]
            self.product_token_link_points = ["LINKP can be locked to direct emissions toward liquidity pools that route the most trading activity."]

    class _LinkProtoDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _LinkProtoProfile()
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://linkproto.org/tokenomics"],
                    "coverage": {"available": True, "pages_read": 4},
                },
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_LinkProtoDocsStage(),
        blog_stage=_StubBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="LinkProto", ticker="LINKP"), []))

    assert "locked LINKP holders" in section.markdown
    assert "30% комиссий начисляется в treasury" in section.markdown
    assert "DAO может направлять treasury reserves" in section.markdown
    assert "нет явного описания модели выручки" not in section.markdown
    assert "понятной модели выручки" not in section.markdown
    assert "кто получает fees / revenue" not in section.markdown
    assert "кто управляет treasury" not in section.markdown


def test_project_knowledge_agent_filters_non_official_noise_from_main_sources_reviewed():
    class _UniLikeProfile(_StubDocsProfile):
        def __init__(self) -> None:
            super().__init__()
            self.project_name = "Uni"
            self.official_urls = {
                "website": ["https://uniswap.org/"],
                "docs": ["https://developers.uniswap.org/docs"],
            }
            self.docs_urls_read = [
                "https://developers.uniswap.org/docs",
                "https://developers.uniswap.org/dashboard/welcome",
                "https://docs.cantina.xyz/about-cantina/platform-overview",
                "https://docs.curve.finance/llms.txt",
            ]
            self.what_the_project_does = "Uniswap provides decentralized trading infrastructure."
            self.business_model = "Provides spot exchange liquidity and routing for token trading."

    class _UniDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _UniLikeProfile()
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": profile.docs_urls_read,
                    "coverage": {"available": True, "pages_read": 4},
                },
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_UniDocsStage(),
        blog_stage=_StubBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Uni", ticker="UNI"), []))

    assert "Main official sources reviewed: https://uniswap.org/, https://developers.uniswap.org/docs." in section.markdown
    assert "dashboard/welcome" not in section.markdown
    assert "cantina.xyz" not in section.markdown
    assert "llms.txt" not in section.markdown


def test_official_blog_stage_discovers_posts_from_official_sources_only():
    stage = OfficialBlogStage(_settings())
    docs_result = type(
        "DocsResult",
        (),
        {
            "profile": _StubDocsProfile(),
            "status": "ok",
            "summary": "",
            "citations": [],
            "coverage": {"available": True},
        },
    )()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://ripple.com/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://ripple.com/blog">Blog</a>
                  <a href="https://external.example/ripple-update">External</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.ripple.com/overview":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://ripple.com/news/ripple-liquidity-hub-update">Liquidity hub update</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.ripple.com/security":
            return httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
        if url == "https://ripple.com/blog":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://ripple.com/blog/ripple-expands-payments">Ripple expands payments</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://ripple.com/news/ripple-liquidity-hub-update":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <title>Ripple liquidity hub update</title>
                    <meta property="article:published_time" content="2026-03-10T12:00:00Z" />
                  </head>
                  <body>
                    Ripple announced a Liquidity Hub update for enterprise payment flows and XRP settlement.
                  </body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://ripple.com/blog/ripple-expands-payments":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <title>Ripple expands payments</title>
                    <meta property="article:published_time" content="2026-03-12T12:00:00Z" />
                  </head>
                  <body>
                    Ripple expanded enterprise payment corridors and XRP liquidity coverage across new regions.
                  </body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await stage.collect(
                Target(name="Ripple", ticker="XRP"),
                client=client,
                docs_result=docs_result,
                period_days=365,
            )

    result = asyncio.run(run())

    assert result.status == "ok"
    assert len(result.posts) == 2
    assert all(url.startswith("https://ripple.com/") for url in result.citations)
    assert result.posts[0].url == "https://ripple.com/blog/ripple-expands-payments"


def test_official_blog_stage_ignores_css_and_keeps_article_text():
    stage = OfficialBlogStage(_settings())
    docs_result = type(
        "DocsResult",
        (),
        {
            "profile": _StubDocsProfile(),
            "status": "ok",
            "summary": "",
            "citations": [],
            "coverage": {"available": True},
        },
    )()
    docs_result.profile.project_name = "Aave"
    docs_result.profile.official_urls = {
        "website": ["https://aave.com/"],
        "docs": ["https://aave.com/docs"],
    }
    docs_result.profile.docs_urls_read = ["https://aave.com/docs"]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://aave.com/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://aave.com/blog">Blog</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://aave.com/docs":
            return httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
        if url == "https://aave.com/blog":
            return httpx.Response(
                200,
                text='<html><body><a href="https://aave.com/blog/aave-v3-update">Aave V3 update</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://aave.com/blog/aave-v3-update":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <title>Aave V3 update</title>
                    <meta property="article:published_time" content="2026-03-12T12:00:00Z" />
                    <style>
                      @font-face { font-family: "Aave Repro"; src: url("/fonts/AaveReproVariable.woff2") format("woff2"); }
                      :root { --font-sans: "Aave Repro", sans-serif; }
                    </style>
                  </head>
                  <body>
                    <article>Aave announced a V3 update with governance improvements and expanded market support.</article>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await stage.collect(
                Target(name="Aave", ticker="AAVE"),
                client=client,
                docs_result=docs_result,
                period_days=365,
            )

    result = asyncio.run(run())

    assert result.posts
    assert "@font-face" not in result.posts[0].summary
    assert "Aave announced a V3 update" in result.posts[0].summary
    assert all("Products Resources Developers About Aave" not in post.summary for post in result.posts)


def test_official_blog_stage_drops_product_and_case_study_pages_for_aave():
    stage = OfficialBlogStage(_settings())
    docs_result = type(
        "DocsResult",
        (),
        {
            "profile": _StubDocsProfile(),
            "status": "ok",
            "summary": "",
            "citations": [],
            "coverage": {"available": True},
        },
    )()
    docs_result.profile.project_name = "Aave"
    docs_result.profile.official_urls = {
        "website": ["https://aave.com/"],
        "docs": ["https://aave.com/docs"],
    }
    docs_result.profile.docs_urls_read = ["https://aave.com/docs", "https://aave.com/build"]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://aave.com/":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://aave.com/blog">Blog</a>
                  <a href="https://aave.com/build/aave-pro-v4">Aave Pro V4</a>
                  <a href="https://aave.com/case-studies/best-build">Case Studies</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://aave.com/docs":
            return httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
        if url == "https://aave.com/build":
            return httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
        if url == "https://aave.com/blog":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://aave.com/build/aave-pro-v4">Aave Pro V4</a>
                  <a href="https://aave.com/case-studies/best-build">Case Studies</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await stage.collect(
                Target(name="Aave", ticker="AAVE"),
                client=client,
                docs_result=docs_result,
                period_days=90,
            )

    result = asyncio.run(run())

    assert result.posts == []


def test_official_blog_stage_drops_generic_site_shell_pages():
    stage = OfficialBlogStage(_settings())
    docs_result = type(
        "DocsResult",
        (),
        {
            "profile": _StubDocsProfile(),
            "status": "ok",
            "summary": "",
            "citations": [],
            "coverage": {"available": True},
        },
    )()
    docs_result.profile.project_name = "Aave"
    docs_result.profile.official_urls = {
        "website": ["https://aave.com/"],
        "docs": ["https://aave.com/docs"],
    }
    docs_result.profile.docs_urls_read = ["https://aave.com/docs"]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://aave.com/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://aave.com/blog">Blog</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://aave.com/docs":
            return httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
        if url == "https://aave.com/blog":
            return httpx.Response(
                200,
                text='<html><body><a href="https://aave.com/blog/fake-shell">Fake shell</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://aave.com/blog/fake-shell":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head><title>Blog | Aave</title></head>
                  <body>
                    Blog The latest news and updates.
                    Aave Labs Learn about Aave Labs.
                    Products Resources Developers About Aave App Savings for everyone.
                  </body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await stage.collect(
                Target(name="Aave", ticker="AAVE"),
                client=client,
                docs_result=docs_result,
                period_days=90,
            )

    result = asyncio.run(run())

    assert result.posts == []


def test_official_blog_stage_uses_rich_blog_listing_preview_when_article_page_is_shell():
    stage = OfficialBlogStage(_settings())
    docs_result = type(
        "DocsResult",
        (),
        {
            "profile": _StubDocsProfile(),
            "status": "ok",
            "summary": "",
            "citations": [],
            "coverage": {"available": True},
        },
    )()
    docs_result.profile.project_name = "Aave"
    docs_result.profile.official_urls = {
        "website": ["https://aave.com/"],
        "docs": ["https://aave.com/docs"],
    }
    docs_result.profile.docs_urls_read = ["https://aave.com/docs"]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://aave.com/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://aave.com/blog">Blog</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://aave.com/docs":
            return httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
        if url == "https://aave.com/blog":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a href="https://aave.com/blog/aave-v4-live">Aave V4 is Live on Ethereum. Aave V4 launches on Ethereum mainnet with its Hub and Spoke architecture and unified liquidity. News</a>
                </body></html>
                """,
                headers={"content-type": "text/html"},
            )
        if url == "https://aave.com/blog/aave-v4-live":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <title>Blog | Aave</title>
                    <meta property="article:published_time" content="2026-03-12T12:00:00Z" />
                  </head>
                  <body>
                    Blog The latest news and updates.
                    Aave Labs Learn about Aave Labs.
                    Products Resources Developers About Aave App Savings for everyone.
                  </body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await stage.collect(
                Target(name="Aave", ticker="AAVE"),
                client=client,
                docs_result=docs_result,
                period_days=90,
            )

    result = asyncio.run(run())

    assert len(result.posts) == 1
    assert "Aave V4 launches on Ethereum mainnet" in result.posts[0].summary
    assert result.posts[0].key_points == []


def test_official_blog_stage_prefers_article_body_over_landing_navigation_shell():
    stage = OfficialBlogStage(_settings())
    docs_result = type(
        "DocsResult",
        (),
        {
            "profile": _StubDocsProfile(),
            "status": "ok",
            "summary": "",
            "citations": [],
            "coverage": {"available": True},
        },
    )()
    docs_result.profile.project_name = "Morpho"
    docs_result.profile.official_urls = {
        "website": ["https://morpho.org/"],
        "docs": ["https://docs.morpho.org/"],
    }
    docs_result.profile.docs_urls_read = ["https://docs.morpho.org/"]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://morpho.org/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://morpho.org/blog">Blog</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.morpho.org/":
            return httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
        if url == "https://morpho.org/blog":
            return httpx.Response(
                200,
                text='<html><body><a href="https://morpho.org/blog/morpho-fixed-rate-lending">Morpho TBA brings fixed-rate lending onchain</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://morpho.org/blog/morpho-fixed-rate-lending":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <title>Morpho TBA brings fixed-rate lending onchain</title>
                    <meta property="article:published_time" content="2026-03-25T12:00:00Z" />
                  </head>
                  <body>
                    <nav>Company Jobs Blog Support Brand Copy as png Copy as svg Products Consumer Vaults Markets Prime Curate Rewards Infra API SDK Launch App Launch App</nav>
                    <article>
                      Morpho TBA brings fixed-rate lending onchain.
                      Morpho TBA takes onchain lending beyond crypto markets.
                    </article>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await stage.collect(
                Target(name="Morpho", ticker="MORPHO"),
                client=client,
                docs_result=docs_result,
                period_days=90,
            )

    result = asyncio.run(run())

    assert result.posts
    assert "Company Jobs Blog Support Brand" not in result.posts[0].summary
    assert result.posts[0].summary == "Morpho TBA brings fixed-rate lending onchain."


def test_official_blog_stage_filters_posts_outside_period_and_undated_posts():
    stage = OfficialBlogStage(_settings())
    now = datetime.now(timezone.utc)
    old_post = OfficialBlogPost(
        url="https://example.com/old",
        title="Old",
        published_at=datetime(2025, 10, 10, tzinfo=timezone.utc),
        summary="Old summary",
    )
    fresh_post = OfficialBlogPost(
        url="https://example.com/fresh",
        title="Fresh",
        published_at=now,
        summary="Fresh summary",
    )
    undated_post = OfficialBlogPost(
        url="https://example.com/undated",
        title="Undated",
        published_at=None,
        summary="Undated summary",
    )

    filtered = stage  # silence unused constructor intent
    del filtered
    from project_knowledge_agent.official_blog_stage import _filter_posts_by_period

    result = _filter_posts_by_period([old_post, fresh_post, undated_post], period_days=90)

    assert [post.url for post in result] == ["https://example.com/fresh"]


def test_project_knowledge_agent_drops_legal_docs_noise_and_keeps_blog_urls():
    class _NoisyDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.what_the_project_does = (
                "Sky Ecosystem | Sky Protocol Docs Skip to content Search Ctrl K Powered by GitBook"
            )
            profile.revenue_model = (
                "You, and not Skybase International will be responsible for any and all fees and charges "
                "associated with your use of any third-party services."
            )
            profile.risk_factors = [
                "Terms of Use | Sky Legal Documents binding agreement and third-party services."
            ]
            profile.official_urls["website"] = ["https://sky.money/", "https://sky.money/brand"]
            profile.docs_urls_read = ["https://sky.money/docs", "https://sky.money/security", "https://sky.money/brand"]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://sky.money/docs", "https://sky.money/brand"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    class _BlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            post = type(
                "OfficialBlogPost",
                (),
                {
                    "url": "https://sky.money/blog/sky-launch-update",
                    "title": "Sky launch update",
                    "published_at": datetime(2026, 1, 15, tzinfo=timezone.utc),
                    "summary": "Sky Protocol launched a governance and stablecoin update for the protocol.",
                    "key_points": ["Sky Protocol launched a governance and stablecoin update for the protocol."],
                    "categories": ["launch"],
                    "source_name": "official_blog",
                    "source_type": "official_blog",
                },
            )()
            return type(
                "OfficialBlogResult",
                (),
                {
                    "posts": [post],
                    "citations": [post.url],
                    "status": "ok",
                    "coverage": {"available": True, "period_days": 365, "posts_kept": 1},
                },
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_NoisyDocsStage(),
        blog_stage=_BlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Sky", ticker="SKY"), []))

    assert "Terms of Use" not in section.markdown
    assert "third-party services" not in section.markdown
    assert "Powered by GitBook" not in section.markdown
    assert "https://sky.money/brand" not in section.citations
    assert "https://sky.money/blog/sky-launch-update" not in section.citations


def test_project_knowledge_agent_filters_malformed_sky_source_urls():
    class _SkyDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Sky"
            profile.official_urls = {
                "website": ["https://sky.money/", "https://skyeco.com/- https://www.skyeco.com/"],
                "docs": ["https://developers.skyeco.com/"],
            }
            profile.docs_urls_read = [
                "https://developers.skyeco.com/",
                "https://skyeco.com/- https://www.skyeco.com/",
            ]
            profile.project_type = "synthetic_dollar"
            profile.business_model = "Issues a crypto-native synthetic dollar backed by collateral, custody, and hedging infrastructure."
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": [
                        "https://developers.skyeco.com/",
                        "https://skyeco.com/- https://www.skyeco.com/",
                    ],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_SkyDocsStage(),
        blog_stage=_StubBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Sky", ticker="SKY"), []))

    assert "https://developers.skyeco.com/" in section.citations
    assert "https://skyeco.com/- https://www.skyeco.com/" not in section.citations
    assert "https://skyeco.com/- https://www.skyeco.com/" not in section.markdown


def test_project_knowledge_agent_filters_brand_and_marketing_noise_for_aave_like_docs():
    class _AaveDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.official_urls = {
                "docs": ["https://aave.com/docs"],
                "security": ["https://aave.com/security"],
                "website": ["https://aave.com/", "https://aave.com/brand", "https://aave.com/app"],
            }
            profile.docs_urls_read = [
                "https://aave.com/brand",
                "https://aave.com/docs",
                "https://aave.com/security",
            ]
            profile.what_the_project_does = "Wordmark The Ghost Logomark is supported and extended by the Aave wordmark."
            profile.business_model = "The protocol connects borrowers and suppliers in onchain credit markets."
            profile.revenue_model = "Drive new revenue, boost user retention, and cut costs."
            profile.token_role = "What is the Aave token?"
            profile.risk_factors = ["Does Aave have risks?"]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://aave.com/brand", "https://aave.com/docs", "https://aave.com/security"],
                    "coverage": {"available": True, "pages_read": 3},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {
                    "posts": [],
                    "citations": [],
                    "status": "partial",
                    "coverage": {"available": True, "period_days": 90, "posts_kept": 0},
                },
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_AaveDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Aave", ticker="AAVE"), []))

    assert "Wordmark" not in section.markdown
    assert "Drive new revenue" not in section.markdown
    assert "What is the Aave token?" not in section.markdown
    assert "https://aave.com/brand" not in section.citations
    assert "https://aave.com/app" not in section.citations
    assert "https://aave.com/docs" in section.citations


def test_project_knowledge_agent_preserves_meaningful_aave_overview_details_in_russian():
    class _AaveDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Aave"
            profile.official_urls = {
                "docs": ["https://docs.aave.com/"],
                "website": ["https://aave.com/"],
            }
            profile.docs_urls_read = ["https://aave.com/", "https://docs.aave.com/"]
            profile.what_the_project_does = (
                "Aave is an open source liquidity protocol where users supply assets to earn yield and borrow against collateral."
            )
            profile.business_model = None
            profile.revenue_model = None
            profile.token_role = None
            profile.risk_factors = []
            profile.key_product_entities = []
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.aave.com/"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_AaveDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Aave", ticker="AAVE"), []))

    assert "открытый протокол ликвидности" in section.markdown
    assert "предоставлять активы" in section.markdown
    assert "брать займы под залог" in section.markdown


def test_project_knowledge_agent_translates_aave_governance_token_role():
    class _AaveDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Aave"
            profile.official_urls = {
                "docs": ["https://aave.com/docs"],
                "tokenomics": ["https://aave.com/governance"],
            }
            profile.docs_urls_read = ["https://aave.com/docs", "https://aave.com/governance"]
            profile.token_role = (
                "Decentralised Governance Decentralised Governance The protocol is governed by AAVE token holders through a decentralised governance framework."
            )
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://aave.com/docs"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_AaveDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Aave", ticker="AAVE"), []))

    assert "Токен AAVE используется для управления протоколом" in section.markdown
    assert "Decentralised Governance Decentralised Governance" not in section.markdown


def test_project_knowledge_agent_adds_concrete_audit_and_token_utility_details():
    class _AaveDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Aave"
            profile.official_urls = {
                "docs": ["https://aave.com/docs"],
                "tokenomics": ["https://aave.com/help/governance"],
                "security": ["https://aave.com/security"],
                "audits": ["https://audits.sherlock.xyz/bug-bounties/300"],
            }
            profile.audit_providers = ["Sherlock"]
            profile.audit_highlights = ["A bug bounty program is live through Sherlock for the protocol."]
            profile.security_highlights = ["Security procedures and bug bounty coverage are documented for the protocol."]
            profile.token_utility_points = [
                "AAVE can be staked in the Safety Module.",
                "AAVE token holders participate in governance voting.",
            ]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://aave.com/docs"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_AaveDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Aave", ticker="AAVE"), []))

    assert "### 4. Token Utility" in section.markdown
    assert "Sherlock" in section.markdown
    assert "Safety Module" in section.markdown
    tokenomics_slice = section.markdown.split("### 6. Tokenomics")[1].split("### 7. Token Distribution")[0]
    assert "Tokenomics-механика токена" in tokenomics_slice
    assert "Safety Module" in tokenomics_slice


def test_project_knowledge_agent_renders_multiple_token_utility_points_separately_for_aerodrome_like_docs():
    class _AerodromeDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Aerodrome"
            profile.official_urls = {
                "docs": ["https://aerodrome.finance/docs"],
                "tokenomics": ["https://aerodrome.finance/docs/tokenomics"],
            }
            profile.docs_urls_read = ["https://aerodrome.finance/docs"]
            profile.what_the_project_does = "Aerodrome is a central liquidity hub on Base."
            profile.token_utility_points = [
                "AERO can be locked for governance and emissions voting.",
                "veAERO holders vote on emissions and receive incentives and fees generated by the protocol.",
                "Foundation uses its share of protocol revenue for buybacks and ecosystem growth.",
                "Epochs determine how emissions and voting outcomes are distributed across gauges.",
            ]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://aerodrome.finance/docs"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_AerodromeDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Aerodrome", ticker="AERO"), []))

    assert "AERO можно блокировать для governance и голосования по распределению эмиссии." in section.markdown
    assert "veAERO отражает vote-escrow механику протокола" in section.markdown
    assert "Foundation использует свою долю доходов" in section.markdown
    assert "В протоколе используются эпохи" in section.markdown
    assert "### 4. Token Utility" in section.markdown


def test_project_knowledge_agent_translates_aave_token_utility_to_russian():
    class _AaveDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Aave"
            profile.official_urls = {
                "docs": ["https://aave.com/docs"],
                "tokenomics": ["https://aave.com/help/governance"],
            }
            profile.token_utility_points = [
                "AAVE is used as the centre of gravity of Aave Protocol governance.",
                "Apart from this, AAVE can be staked within the protocol Safety Module to provide a backstop in the case of a shortfall event, and earn incentives for doing so.",
            ]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://aave.com/docs"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_AaveDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Aave", ticker="AAVE"), []))

    assert "основной токен governance протокола" in section.markdown
    assert "можно стейкать в Safety Module" in section.markdown


def test_project_knowledge_agent_keeps_docs_section_non_empty_for_aerodrome_like_case():
    class _AerodromeDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Aerodrome"
            profile.official_urls = {"website": ["https://aerodrome.finance/"]}
            profile.docs_urls_read = ["https://aerodrome.finance/"]
            profile.project_type = "unknown_other"
            profile.project_subtype = None
            profile.what_the_project_does = None
            profile.business_model = None
            profile.revenue_model = None
            profile.token_role = None
            profile.supported_chains = []
            profile.audits_present = False
            profile.governance_present = None
            profile.tokenomics_present = False
            profile.security_section_present = False
            profile.token_exists = None
            profile.risk_factors = []
            profile.key_product_entities = []
            profile.evidence_snippets = []
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "partial",
                    "summary": "Aerodrome is a central liquidity hub on Base.",
                    "citations": ["https://aerodrome.finance/"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_AerodromeDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Aerodrome", ticker="AERO"), []))

    assert "### 2. Project Overview" in section.markdown
    assert "Aerodrome выступает центральным хабом ликвидности в экосистеме Base." in section.markdown


def test_project_knowledge_agent_translates_ethena_token_role_and_entities_to_russian():
    class _EthenaDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Ethena"
            profile.official_urls = {
                "docs": ["https://docs.ethena.fi/how-usde-works"],
                "tokenomics": ["https://docs.ethena.fi/ena"],
            }
            profile.project_type = "unknown_other"
            profile.project_subtype = None
            profile.what_the_project_does = (
                "A crypto-native synthetic dollar utilizing spot assets as backing, onchain custody, and centralized liquidity venues."
            )
            profile.business_model = None
            profile.token_role = (
                "In this framework, $ENA governance tokenholders are able to delegate everyday decision-making "
                "with respect to key aspects of the ecosystem to sophisticated, expert-level stakeholders while "
                "retaining transparency during the process."
            )
            profile.key_product_entities = ["markets", "positions", "collateral", "vault"]
            profile.token_utility_points = ["Staked ENA can be obtained by staking ENA."]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.ethena.fi/how-usde-works"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 180}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_EthenaDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Ethena", ticker="ENA"), []))

    assert "Токен ENA используется для governance" in section.markdown
    assert "держатели могут делегировать часть повседневных решений" in section.markdown
    assert "рынки, позиции, залог, хранилище" in section.markdown
    assert "Пользователи могут застейкать ENA и получить sENA" in section.markdown
    assert "Документация относит проект к типу" not in section.markdown


def test_project_knowledge_agent_renders_virtuals_from_whitepaper_meaningfully():
    class _VirtualDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Virtual"
            profile.official_urls = {
                "docs": ["https://whitepaper.virtuals.io/about-virtuals"],
                "tokenomics": ["https://whitepaper.virtuals.io/info-hub/usdvirtual"],
            }
            profile.what_the_project_does = (
                "Virtuals Protocol is a society of AI agents: a coordinated, onchain ecosystem where autonomous agents generate services or products and engage in commerce with humans and other agents."
            )
            profile.business_model = None
            profile.token_role = (
                "The $VIRTUAL token functions as the base liquidity pair and transactional currency across agent interactions, forming the monetary backbone of the ecosystem."
            )
            profile.key_product_entities = ["pools", "pairs", "liquidity"]
            profile.token_utility_points = [
                "Allocate up to 5% of supply to veVIRTUAL stakers.",
                "2% to $VIRTUAL stakers and 3% to active ecosystem participants (Based on ACP Score).",
            ]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://whitepaper.virtuals.io/about-virtuals"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_VirtualDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Virtual", ticker="VIRTUAL"), []))

    assert "ончейн-экосистема AI-агентов" in section.markdown
    assert "$VIRTUAL выступает базовой валютной парой" in section.markdown
    assert "пулы, пары, ликвидность" in section.markdown
    assert "veVIRTUAL-стейкеры могут получать распределения токенов" in section.markdown
    assert "Проект обеспечивает ликвидность и маршрутизацию для спотовой торговли токенами." not in section.markdown


def test_project_knowledge_agent_filters_curve_hub_noise_and_normalizes_crv_role():
    class _CurveDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Curve"
            profile.official_urls = {
                "docs": ["https://docs.curve.finance/user/introduction"],
                "tokenomics": ["https://docs.curve.finance/user/curve-tokens/crv"],
            }
            profile.what_the_project_does = "Curve is a decentralized exchange."
            profile.business_model = None
            profile.token_role = "## C CRV - The governance token of Curve Finance, used for voting and earning protocol fees."
            profile.key_product_entities = ["pools", "pairs", "liquidity", "traders", "routes"]
            profile.token_utility_points = [
                "Curve Knowledge Hub Users Developers Build on Curve Your gateway to understanding and building with Curve - Documentation, metrics, and latest updates.",
            ]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.curve.finance/user/introduction"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_CurveDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Curve", ticker="CRV"), []))

    assert "CRV — governance-токен Curve Finance" in section.markdown
    assert "пулы, пары, ликвидность, трейдеры, маршруты" in section.markdown
    assert "Knowledge Hub" not in section.markdown
    assert "Gauges & Emissions" not in section.markdown
    assert "Явная схема value capture для токена" not in section.markdown
    assert "кто получает fees / revenue" not in section.markdown


def test_project_knowledge_agent_uses_curve_fee_architecture_points_as_revenue_evidence():
    class _CurveDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Curve"
            profile.official_urls = {
                "docs": ["https://docs.curve.finance/fee-architecture"],
                "tokenomics": ["https://docs.curve.finance/user/curve-tokens/crv"],
            }
            profile.docs_urls_read = [
                "https://docs.curve.finance/fee-architecture",
                "https://docs.curve.finance/user/curve-tokens/crv",
            ]
            profile.project_type = "dex_spot"
            profile.project_subtype = "amm_spot_dex"
            profile.what_the_project_does = "Curve is an automated market maker designed for efficient stable asset trading with liquidity pools."
            profile.business_model = None
            profile.revenue_model = None
            profile.token_role = "CRV is the governance token of Curve Finance, used for voting and earning protocol fees through veCRV."
            profile.value_capture_points = [
                "A share of admin fees accrues to veCRV holders while protocol fees are retained by the DAO.",
            ]
            profile.revenue_model_points = [
                "Curve fee architecture routes swap fees through pool fee parameters and admin fees.",
            ]
            profile.fee_recipient_points = [
                "A share of admin fees accrues to veCRV holders while protocol fees are retained by the DAO.",
            ]
            profile.product_token_link_points = [
                "CRV is used for voting and earning protocol fees through veCRV.",
            ]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.curve.finance/fee-architecture"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_CurveDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Curve", ticker="CRV"), []))

    assert "Модель выручки Curve завязана на архитектуре комиссий: swap fees проходят через параметры pool fee и admin fees." in section.markdown
    assert "Выглядит ли бизнес-модель понятной: да." in section.markdown
    assert "понятной модели выручки" not in section.markdown
    assert "кто получает fees / revenue" not in section.markdown
    assert "неясна бизнес-модель и модель выручки" not in section.markdown


def test_project_knowledge_agent_uses_aave_reserve_factor_points_as_revenue_evidence():
    class _AaveDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Aave"
            profile.official_urls = {
                "docs": ["https://aave.com/help/borrowing"],
            }
            profile.docs_urls_read = ["https://aave.com/help", "https://aave.com/help/borrowing"]
            profile.project_type = "lending"
            profile.project_subtype = "cdp_lending"
            profile.what_the_project_does = "Aave is an open source liquidity protocol where users supply assets to earn yield and borrow against collateral."
            profile.business_model = "Connects suppliers and borrowers in onchain credit markets."
            profile.revenue_model = None
            profile.revenue_model_points = [
                "Borrowers pay interest and a reserve factor directs a share of protocol fees to the protocol treasury.",
                "The protocol captures revenue from reserve spreads and protocol fees across lending markets.",
            ]
            profile.fee_recipient_points = [
                "A reserve factor directs a share of protocol fees to the protocol treasury.",
            ]
            profile.treasury_points = [
                "A reserve factor directs a share of protocol fees to the protocol treasury.",
            ]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://aave.com/help/borrowing"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_AaveDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Aave", ticker="AAVE"), []))

    assert "Заёмщики Aave платят проценты, а reserve factor направляет долю protocol fees в treasury протокола." in section.markdown
    assert "Выглядит ли бизнес-модель понятной: да." in section.markdown
    assert "понятной модели выручки" not in section.markdown
    assert "кто получает fees / revenue" not in section.markdown
    assert "кто управляет treasury" not in section.markdown
    assert "не хватает конкретики по модели выручки" not in section.markdown


def test_project_knowledge_agent_uses_lending_borrower_interest_after_protocol_fees_as_revenue():
    class _LendingDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "LendProto"
            profile.official_urls = {
                "docs": ["https://docs.lendproto.example/borrowing"],
            }
            profile.docs_urls_read = ["https://docs.lendproto.example/borrowing"]
            profile.project_type = "lending"
            profile.project_subtype = "cdp_lending"
            profile.what_the_project_does = "LendProto is an open source liquidity protocol where users supply assets and borrow against collateral."
            profile.business_model = "Connects suppliers and borrowers in onchain credit markets."
            profile.revenue_model = "The supply rate is derived from borrower interest after protocol fees and reflects supply and demand for that asset."
            profile.revenue_model_points = []
            profile.fee_recipient_points = []
            profile.treasury_points = []
            profile.treasury_control_points = []
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.lendproto.example/borrowing"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_LendingDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="LendProto", ticker="LEND"), []))

    assert "borrower interest после protocol fees" in section.markdown
    assert "The supply rate is derived from borrower interest" not in section.markdown
    assert "нет явного описания модели выручки" not in section.markdown
    assert "понятной модели выручки" not in section.markdown
    assert "не хватает конкретики по модели выручки" not in section.markdown


def test_project_knowledge_agent_uses_sky_stability_fee_points_as_revenue_evidence():
    class _SkyDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Sky"
            profile.official_urls = {
                "docs": ["https://developers.skyeco.com/"],
                "treasury": ["https://developers.skyeco.com/modules/surplus-buffer"],
            }
            profile.docs_urls_read = [
                "https://developers.skyeco.com/",
                "https://developers.skyeco.com/rates/stability-fees",
                "https://developers.skyeco.com/modules/surplus-buffer",
                "https://developers.skyeco.com/guides/psm/litepsm",
            ]
            profile.project_type = "synthetic_dollar"
            profile.what_the_project_does = "Sky Protocol includes USDS, the decentralized stablecoin upgraded from Dai, and the SKY governance token."
            profile.business_model = "Issues a crypto-native synthetic dollar backed by collateral, custody, and hedging infrastructure."
            profile.revenue_model = None
            profile.revenue_model_points = [
                "Vault owners pay a stability fee on generated USDS debt, and those fees accrue to the protocol surplus buffer.",
                "Protocol surplus collects stability fees, liquidation penalties, and PSM fees before governance allocates surplus through protocol mechanisms.",
                "LitePSM charges fees on swaps between USDS and supported stablecoins, creating spread income for the protocol.",
            ]
            profile.fee_recipient_points = [
                "Fees accrue to the protocol surplus buffer.",
            ]
            profile.treasury_points = [
                "Protocol surplus collects stability fees, liquidation penalties, and PSM fees before governance allocates surplus through protocol mechanisms.",
            ]
            profile.treasury_control_points = [
                "Governance allocates surplus through protocol mechanisms.",
            ]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://developers.skyeco.com/"],
                    "coverage": {"available": True, "pages_read": 4},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_SkyDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Sky", ticker="SKY"), []))

    assert "stability fee" in section.markdown
    assert "surplus buffer" in section.markdown
    assert "Выглядит ли бизнес-модель понятной: да." in section.markdown
    assert "понятной модели выручки" not in section.markdown
    assert "кто получает fees / revenue" not in section.markdown
    assert "кто управляет treasury" not in section.markdown
    assert "не хватает конкретики по модели выручки" not in section.markdown


def test_project_knowledge_agent_renders_sky_docs_claims_in_russian_and_drops_noise():
    class _SkyDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Sky"
            profile.official_urls = {
                "website": ["https://sky.money/"],
                "docs": ["https://developers.skyeco.com/"],
                "governance": ["https://vote.sky.money/"],
                "treasury": ["https://developers.skyeco.com/protocol/core/vow"],
            }
            profile.docs_urls_read = [
                "https://sky.money/",
                "https://developers.skyeco.com/",
                "https://developers.skyeco.com/protocol/core/vow",
                "https://vote.sky.money/",
            ]
            profile.project_type = "synthetic_dollar"
            profile.project_subtype = ""
            profile.what_the_project_does = "Sky Protocol includes USDS, the decentralized stablecoin upgraded from Dai, and the SKY governance token."
            profile.business_model = "Issues a crypto-native synthetic dollar backed by collateral, custody, and hedging infrastructure."
            profile.revenue_model = None
            profile.token_role = ""
            profile.token_utility_points = [
                "All parameters are governance-set and smart-contract-executed by the respective Sky Agent or ecosystem partner.",
                "You earn Sky Agent governance tokens from ecosystem projects like Spark.",
                "All Sky Agent tokens carry governance utility beyond their market price, letting you participate in the governance of the protocols generating Sky Protocol's revenue.",
                "By supplying USDS into the Ecosystem Rewards module in the Sky.money platform, you earn points or governance tokens from independent capital allocators part of the Sky Agent Network.",
            ]
            profile.value_capture_points = [
                "stUSDS funds and supports liquidity for SKY stakers, encouraging more participation in SKY governance, leading to a more secure ecosystem.",
                "Previous SKY Next Staking Rewards Released into the public domain (CC0 1.0 Universal) – trademarks remain with their owners; no warranty.",
            ]
            profile.tokenomics_points = [
                "Every 3 months after, the penalty will increase by an additional 1%.",
                "Collect Your Position Data” Check the following before starting the migration: What to Check Why It Matters During Shutdown USDS debt (drawn balance) Must be zero before you can unlock collateral in V1.",
                "Unlock collateral: Call free(uint wad) to release MKR to your wallet.",
            ]
            profile.token_distribution_points = [
                "Phase 4 — Communications Done 2025-05-13 A community-wide marketing campaign for the Sky Ecosystem will be launched.",
            ]
            profile.revenue_model_points = [
                "In particular, the Vow acts as the recipient of both the system surplus and system debt.",
            ]
            profile.fee_recipient_points = [
                "In particular, the Vow acts as the recipient of both the system surplus and system debt.",
                "Governance can extract these accumulated fees by executing the collect(to) function at its discretion.",
            ]
            profile.treasury_points = [
                "In particular, the Vow acts as the recipient of both the system surplus and system debt.",
            ]
            profile.treasury_control_points = [
                "Now, governance can update the fee parameter, which determines the fee charged during MKR-to-SKY conversions.",
            ]
            profile.investor_partner_points = [
                "All parameters are governance-set and smart-contract-executed by the respective Sky Agent or ecosystem partner.",
                "stUSDS — Risk Capital High-performance risk capital token earning premium yield by funding SKY-backed borrowing.",
            ]
            profile.governance_points = [
                "The Sky Governance Portal allows for anyone to view governance proposals, and also allows for SKY holders to vote.",
            ]
            profile.roadmap_points = [
                "This upgrade marks a key milestone in Sky’s evolution from its MakerDAO roots and empowers SKY holders with full protocol control.",
            ]
            profile.team_points = []
            profile.product_token_link_points = []
            profile.vesting_points = []
            profile.supported_chains = ["Ethereum", "Base", "Solana"]
            profile.token_exists = True
            profile.governance_present = True
            profile.tokenomics_present = True
            profile.security_section_present = False
            profile.audits_present = False
            profile.risk_factors = []
            profile.key_product_entities = ["minting", "custody"]
            profile.evidence_snippets = []
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://developers.skyeco.com/"],
                    "coverage": {"available": True, "pages_read": 4},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_SkyDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Sky", ticker="SKY"), []))

    assert "Пользователь может получать governance-токены Sky Agents" in section.markdown
    assert "Модуль Vow выступает получателем системного surplus" in section.markdown
    assert "Выглядит ли бизнес-модель понятной: да." in section.markdown
    assert "понятной модели выручки" not in section.markdown
    assert "All parameters are governance-set" not in section.markdown
    assert "You earn Sky Agent governance tokens" not in section.markdown
    assert "All Sky Agent tokens carry governance utility" not in section.markdown
    assert "By supplying USDS into the Ecosystem Rewards module" not in section.markdown
    assert "Previous SKY Next Staking Rewards" not in section.markdown
    assert "Every 3 months after" not in section.markdown
    assert "Collect Your Position Data" not in section.markdown
    assert "Phase 4" not in section.markdown
    assert "The Sky Governance Portal allows" not in section.markdown
    assert "This upgrade marks a key milestone" not in section.markdown


def test_project_knowledge_agent_normalizes_generic_docs_claims_without_project_specific_rules():
    class _GenericDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "GenericDex"
            profile.official_urls = {
                "website": ["https://genericdex.example/"],
                "docs": ["https://docs.genericdex.example/"],
                "tokenomics": ["https://docs.genericdex.example/token"],
                "treasury": ["https://docs.genericdex.example/treasury"],
                "governance": ["https://docs.genericdex.example/governance"],
            }
            profile.docs_urls_read = [
                "https://docs.genericdex.example/",
                "https://docs.genericdex.example/token",
                "https://docs.genericdex.example/treasury",
                "https://docs.genericdex.example/governance",
            ]
            profile.project_type = "dex_spot"
            profile.project_subtype = "amm_spot_dex"
            profile.what_the_project_does = "GenericDex provides spot exchange liquidity and routing for token trading."
            profile.business_model = "Provides spot exchange liquidity and routing for token trading."
            profile.revenue_model = None
            profile.revenue_model_points = [
                "Protocol revenue comes from swap fees and routing fees.",
            ]
            profile.token_role = ""
            profile.token_utility_points = [
                "GDX can be staked to earn rewards and participate in governance.",
                "GDX holders can vote on governance proposals.",
            ]
            profile.value_capture_points = [
                "GDX can be locked to direct emissions toward liquidity pools that route the most trading activity.",
                "Stakers receive a share of protocol fees.",
            ]
            profile.product_token_link_points = [
                "GDX can be locked to direct emissions toward liquidity pools that route the most trading activity.",
            ]
            profile.fee_recipient_points = [
                "Fees accrue to the protocol treasury.",
                "A share of fees is distributed to stakers.",
            ]
            profile.treasury_points = [
                "The protocol treasury receives a share of fees.",
            ]
            profile.treasury_control_points = [
                "Treasury is controlled by governance.",
            ]
            profile.governance_points = [
                "Token holders can vote on governance proposals.",
            ]
            profile.team_points = []
            profile.investor_partner_points = []
            profile.roadmap_points = []
            profile.tokenomics_points = []
            profile.token_distribution_points = []
            profile.vesting_points = []
            profile.supported_chains = ["Ethereum"]
            profile.token_exists = True
            profile.governance_present = True
            profile.tokenomics_present = True
            profile.security_section_present = False
            profile.audits_present = False
            profile.risk_factors = []
            profile.key_product_entities = ["pools", "liquidity", "routes"]
            profile.evidence_snippets = []
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.genericdex.example/"],
                    "coverage": {"available": True, "pages_read": 4},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_GenericDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="GenericDex", ticker="GDX"), []))

    assert "Выручка протокола формируется за счёт swap fees и routing fees." in section.markdown
    assert "GDX можно стейкать для получения rewards и участия в governance." in section.markdown
    assert "Держатели GDX могут голосовать по governance proposals." in section.markdown
    assert "GDX можно блокировать, чтобы направлять emissions в liquidity pools." in section.markdown
    assert "Комиссии начисляются в protocol treasury." in section.markdown
    assert "Treasury контролируется governance/DAO." in section.markdown
    assert "Выглядит ли бизнес-модель понятной: да." in section.markdown
    assert "понятной модели выручки" not in section.markdown
    assert "кто получает fees / revenue" not in section.markdown
    assert "кто управляет treasury" not in section.markdown
    assert "Protocol revenue comes from swap fees" not in section.markdown
    assert "can be staked to earn rewards" not in section.markdown
    assert "holders can vote on governance proposals" not in section.markdown
    assert "Fees accrue to the protocol treasury" not in section.markdown
    assert "Treasury is controlled by governance" not in section.markdown


def test_project_knowledge_agent_uses_dex_buyback_and_burn_as_value_capture_evidence():
    class _PancakeLikeDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Cake"
            profile.official_urls = {
                "website": ["https://pancakeswap.finance/"],
                "docs": ["https://docs.pancakeswap.finance/"],
                "tokenomics": ["https://docs.pancakeswap.finance/earn/pancakeswap-pools"],
            }
            profile.docs_urls_read = [
                "https://docs.pancakeswap.finance/trade/pancakeswap-exchange/trade",
                "https://docs.pancakeswap.finance/earn/pancakeswap-pools",
            ]
            profile.project_type = "dex_spot"
            profile.project_subtype = "amm_spot_dex"
            profile.what_the_project_does = "PancakeSwap is a decentralized exchange."
            profile.business_model = "Provides spot exchange liquidity and routing for token trading."
            profile.revenue_model = None
            profile.revenue_model_points = [
                "For Exchange V2 liquidity pools, a fixed 0.25% trading fee is applied: 0.17% is returned to Liquidity Pools, 0.0225% is sent to the PancakeSwap Treasury, and 0.0575% is sent towards CAKE buyback and burn.",
            ]
            profile.value_capture_points = [
                "Trading fees for Exchange V3 are distributed to Liquidity Providers, CAKE Burn, and Treasury according to each fee tier.",
                "CAKE Burn receives a share of total swap fees, permanently removing CAKE to reduce supply.",
            ]
            profile.fee_recipient_points = [
                "For Exchange V2 liquidity pools, a fixed 0.25% trading fee is applied: 0.17% is returned to Liquidity Pools, 0.0225% is sent to the PancakeSwap Treasury, and 0.0575% is sent towards CAKE buyback and burn.",
            ]
            profile.token_role = ""
            profile.token_utility_points = []
            profile.product_token_link_points = []
            profile.treasury_points = []
            profile.treasury_control_points = []
            profile.governance_points = []
            profile.team_points = []
            profile.investor_partner_points = []
            profile.roadmap_points = []
            profile.tokenomics_points = []
            profile.token_distribution_points = []
            profile.vesting_points = []
            profile.supported_chains = []
            profile.token_exists = True
            profile.governance_present = False
            profile.tokenomics_present = True
            profile.security_section_present = False
            profile.audits_present = False
            profile.risk_factors = []
            profile.key_product_entities = ["pools", "liquidity", "routes"]
            profile.evidence_snippets = []
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.pancakeswap.finance/"],
                    "coverage": {"available": True, "pages_read": 3},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_PancakeLikeDocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Cake", ticker="CAKE"), []))

    assert "trading fee 0.25%" in section.markdown
    assert "CAKE buyback and burn" in section.markdown
    assert "CAKE Burn получает долю total swap fees" in section.markdown
    assert "Явная схема value capture" not in section.markdown
    assert "понятной модели выручки" not in section.markdown
    assert "fixed 0.25% trading fee is applied" not in section.markdown


def test_project_knowledge_agent_does_not_project_blog_claims_into_link_partners_or_roadmap():
    class _LinkDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Link"
            profile.official_urls = {
                "website": ["https://chain.link/"],
                "docs": ["https://docs.chain.link/docs"],
            }
            profile.docs_urls_read = ["https://docs.chain.link/docs"]
            profile.project_type = "oracle"
            profile.project_subtype = None
            profile.what_the_project_does = "Chainlink connects blockchains to real-world data, other blockchains, and enterprise systems."
            profile.business_model = "Supplies external data and pricing infrastructure to onchain applications."
            profile.investor_partner_points = []
            profile.roadmap_points = []
            profile.token_role = "LINK используется для оплаты oracle-услуг, payment abstraction, механизмов сетевой безопасности и reward-механик."
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.chain.link/docs"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    class _LinkBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            posts = [
                type(
                    "Post",
                    (),
                    {
                        "url": "https://chain.link/blog/unichain-scale",
                        "title": "Unichain joins Chainlink Scale",
                        "published_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
                        "summary": "Unichain joined Chainlink Scale.",
                        "key_points": [
                            "Unichain adopted the Chainlink data standard.",
                            "Data Feeds and SVR are now live on mainnet for Unichain builders.",
                        ],
                        "categories": ["official_update"],
                        "source_name": "official_blog",
                        "source_type": "official_blog",
                    },
                )()
            ]
            return type(
                "OfficialBlogResult",
                (),
                {
                    "posts": posts,
                    "citations": [posts[0].url],
                    "status": "ok",
                    "coverage": {"available": True, "period_days": 90, "posts_kept": 1},
                },
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_LinkDocsStage(),
        blog_stage=_LinkBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Link", ticker="LINK"), []))
    roadmap_slice = section.markdown.split("### 15. Roadmap")[1].split("### 16. Risks Mentioned by Project")[0]

    assert "### 11. Investors and Partners" in section.markdown
    assert "подтверждённый список инвесторов и содержательных партнёрств" in section.markdown
    assert "Unichain joined Chainlink Scale." not in section.markdown.split("### 12. Security")[0]
    assert "### 15. Roadmap" in section.markdown
    assert "Data Feeds and SVR are now live on mainnet for Unichain builders." not in roadmap_slice


def test_project_knowledge_agent_hides_generic_fallback_business_model_from_output():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Generic"
            profile.official_urls = {"docs": ["https://docs.example.com/overview"]}
            profile.what_the_project_does = "Generic Protocol connects blockchains to real-world data, other blockchains, and enterprise systems."
            profile.business_model = "Supplies external data and pricing infrastructure to onchain applications."
            profile.token_role = None
            profile.key_product_entities = ["feeds", "oracles", "consumers"]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.example.com/overview"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Generic", ticker="GEN"), []))

    assert "Бизнес-модель:" not in section.markdown


def test_project_knowledge_agent_hides_generic_fallback_business_model_with_subtype_suffix():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Subtype Generic"
            profile.official_urls = {"docs": ["https://docs.example.com/overview"]}
            profile.what_the_project_does = "Subtype Generic lets users trade yield and manage positions."
            profile.business_model = "Facilitates perpetual trading markets and monetizes trading activity. Subtype: orderbook_perp_dex."
            profile.token_role = None
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.example.com/overview"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Subtype Generic", ticker="SG"), []))

    assert "Бизнес-модель:" not in section.markdown


def test_project_knowledge_agent_filters_generic_docs_shell_from_token_utility():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Shell"
            profile.official_urls = {"docs": ["https://docs.example.com/overview"], "tokenomics": ["https://docs.example.com/token"]}
            profile.what_the_project_does = "Shell Protocol is a decentralized protocol."
            profile.token_utility_points = [
                "Developers Get Started Docs DevHub Faucets Bootcamps Tutorials Get Involved Popular Developer resources.",
                "Resources Investor Relations Journalists Agencies Client Login Send a Release.",
            ]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.example.com/overview"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Shell", ticker="SHL"), []))

    assert "Утилити токена по документации" not in section.markdown


def test_official_blog_stage_filters_press_release_shell_noise():
    stage = OfficialBlogStage(_settings())
    docs_result = type(
        "DocsResult",
        (),
        {
            "profile": _StubDocsProfile(),
            "status": "ok",
            "summary": "",
            "citations": [],
            "coverage": {"available": True},
        },
    )()
    docs_result.profile.project_name = "Chainlink"
    docs_result.profile.official_urls = {"website": ["https://chain.link/"], "docs": ["https://docs.chain.link/docs"]}
    docs_result.profile.docs_urls_read = ["https://docs.chain.link/docs"]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://chain.link/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://chain.link/news/unichain-scale">News</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.chain.link/docs":
            return httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
        if url == "https://chain.link/news/unichain-scale":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <title>Chainlink news</title>
                    <meta property="article:published_time" content="2026-03-18T12:00:00Z" />
                  </head>
                  <body>
                    Accessibility Statement Skip Navigation Resources Investor Relations Journalists Agencies Client Login Send a Release.
                    SAN FRANCISCO, March 18, 2026 -- Unichain has adopted the Chainlink data standard and joined the Chainlink Scale program.
                    By adopting the Chainlink data standard, Unichain enables builders to create secure applications with Data Feeds live on mainnet.
                  </body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await stage.collect(
                Target(name="Link", ticker="LINK"),
                client=client,
                docs_result=docs_result,
                period_days=90,
            )

    result = asyncio.run(run())

    assert result.posts
    assert "Accessibility Statement" not in result.posts[0].summary
    assert "PRNewswire" not in result.posts[0].summary
    assert "News in Focus" not in result.posts[0].summary
    assert "Unichain has adopted the Chainlink data standard" in result.posts[0].summary


def test_official_blog_stage_ignores_third_party_hosts_even_if_profile_urls_are_polluted():
    stage = OfficialBlogStage(_settings())
    docs_result = type(
        "DocsResult",
        (),
        {
            "profile": _StubDocsProfile(),
            "status": "ok",
            "summary": "",
            "citations": [],
            "coverage": {"available": True},
        },
    )()
    docs_result.profile.project_name = "Chainlink"
    docs_result.profile.official_urls = {
        "website": ["https://chain.link/"],
        "docs": ["https://docs.chain.link/docs"],
        "tokenomics": [
            "https://www.prnewswire.com/news-releases/example.html",
            "https://www.coindesk.com/web3/2025/12/04/example",
        ],
    }
    docs_result.profile.docs_urls_read = [
        "https://docs.chain.link/docs",
        "https://cointelegraph.com/news/example",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://chain.link/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://chain.link/news/ccip-update">News</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.chain.link/docs":
            return httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
        if url == "https://chain.link/news/ccip-update":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <title>Chainlink CCIP update</title>
                    <meta property="article:published_time" content="2026-03-18T12:00:00Z" />
                  </head>
                  <body>
                    Chainlink announced a CCIP update for cross-chain messaging and token transfers.
                  </body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await stage.collect(
                Target(name="Link", ticker="LINK"),
                client=client,
                docs_result=docs_result,
                period_days=365,
            )

    result = asyncio.run(run())

    assert len(result.posts) == 1
    assert result.posts[0].url == "https://chain.link/news/ccip-update"


def test_project_knowledge_agent_translates_chainlink_token_utility_from_docs_toc():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Link"
            profile.official_urls = {"docs": ["https://docs.chain.link/resources/link-token-contracts"]}
            profile.what_the_project_does = "Chainlink connects blockchains to external data and systems."
            profile.token_role = None
            profile.token_utility_points = [
                "LINK Token Contracts | Chainlink Documentation LINK Token Contracts Payment for oracle services Payment Abstraction Chainlink Reserve Network security and rewards Token standard and cross-chain transfers",
            ]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.chain.link/resources/link-token-contracts"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Link", ticker="LINK"), []))

    assert "oracle-услуг" in section.markdown
    assert "LINK Token Contracts | Chainlink Documentation" not in section.markdown


def test_project_knowledge_agent_filters_third_party_link_sources_from_citations():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Link"
            profile.official_urls = {
                "website": ["https://chain.link/"],
                "docs": ["https://docs.chain.link/docs"],
                "tokenomics": [
                    "https://chain.link/economics",
                    "https://www.prnewswire.com/news-releases/example.html",
                    "https://cointelegraph.com/news/example",
                    "https://youtu.be/SCvREV39GEE",
                    "https://int.media.amundi.com/article/example",
                ],
            }
            profile.docs_urls_read = [
                "https://docs.chain.link/docs",
                "https://docs.chain.link/resources/link-token-contracts",
                "https://www.prnewswire.com/news-releases/example.html",
            ]
            profile.what_the_project_does = "Chainlink connects blockchains to external data and systems."
            profile.token_role = "The program enables Chainlink Build projects to make their native tokens claimable by Chainlink ecosystem participants, including eligible LINK Stakers."
            profile.token_utility_points = [
                "LINK Token Contracts | Chainlink Documentation LINK Token Contracts Payment for oracle services Payment Abstraction Chainlink Reserve Network security and rewards Token standard and cross-chain transfers",
            ]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": [
                        "https://chain.link/",
                        "https://docs.chain.link/docs",
                        "https://www.prnewswire.com/news-releases/example.html",
                        "https://cointelegraph.com/news/example",
                        "https://youtu.be/SCvREV39GEE",
                    ],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    class _BlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            post = OfficialBlogPost(
                url="https://chain.link/news/ccip-update",
                title="Chainlink CCIP update",
                published_at=datetime(2026, 3, 18, tzinfo=timezone.utc),
                summary="Chainlink announced a CCIP update for cross-chain messaging and token transfers.",
                key_points=[],
                categories=["official_update"],
            )
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [post], "citations": [post.url], "status": "ok", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_BlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Link", ticker="LINK"), []))

    joined = "\n".join(section.citations) + "\n" + section.markdown
    assert "https://chain.link/" in joined
    assert "https://docs.chain.link/docs" in joined
    assert "https://chain.link/news/ccip-update" not in joined
    assert "prnewswire.com" not in joined
    assert "cointelegraph.com" not in joined
    assert "youtu.be/" not in joined
    assert "amundi.com" not in joined


def test_official_blog_stage_skips_chainlink_changelog_shell_sentences():
    stage = OfficialBlogStage(_settings())
    docs_result = type(
        "DocsResult",
        (),
        {
            "profile": _StubDocsProfile(),
            "status": "ok",
            "summary": "",
            "citations": [],
            "coverage": {"available": True},
        },
    )()
    docs_result.profile.project_name = "Chainlink"
    docs_result.profile.official_urls = {"website": ["https://chain.link/"], "docs": ["https://docs.chain.link/docs"]}
    docs_result.profile.docs_urls_read = ["https://docs.chain.link/docs"]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://chain.link/":
            return httpx.Response(
                200,
                text='<html><body><a href="https://chain.link/changelog/cre-cli-v1-11-0">Changelog</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.chain.link/docs":
            return httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
        if url == "https://chain.link/changelog/cre-cli-v1-11-0":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <title>CRE CLI v1.11.0</title>
                    <meta property="article:published_time" content="2026-04-16T12:00:00Z" />
                  </head>
                  <body>
                    Resources ORCHESTRATION CRE All-in-one orchestration layer for your institutional-grade smart contracts.
                    Docs Learn View all resources Learn about Chainlink Data.
                    Back to Changelog Release Release April 16, 2026.
                    CRE CLI version 1.11.0 adds registry list support, paused workflow warnings, and simulator fixes.
                  </body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await stage.collect(
                Target(name="Link", ticker="LINK"),
                client=client,
                docs_result=docs_result,
                period_days=365,
            )

    result = asyncio.run(run())

    assert result.posts
    assert "registry list support" in result.posts[0].summary
    assert "Resources ORCHESTRATION" not in result.posts[0].summary


def test_official_blog_stage_accepts_explicit_official_medium_publication():
    stage = OfficialBlogStage(_settings())
    docs_result = type(
        "DocsResult",
        (),
        {
            "profile": _StubDocsProfile(),
            "status": "ok",
            "summary": "",
            "citations": [],
            "coverage": {"available": True},
        },
    )()
    docs_result.profile.project_name = "Link"
    docs_result.profile.official_urls = {
        "website": ["https://chain.link/"],
        "docs": ["https://docs.chain.link/docs"],
        "blog": ["https://medium.com/chainlink"],
    }
    docs_result.profile.docs_urls_read = ["https://docs.chain.link/docs"]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://chain.link/":
            return httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
        if url == "https://docs.chain.link/docs":
            return httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
        if url == "https://medium.com/chainlink":
            return httpx.Response(
                200,
                text='<html><body><a href="https://medium.com/chainlink/ccip-update-123">Chainlink CCIP update Chainlink announced a CCIP update for cross-chain messaging and token transfers.</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://medium.com/chainlink/ccip-update-123":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <title>Chainlink CCIP update</title>
                    <meta property="article:published_time" content="2026-03-18T12:00:00Z" />
                  </head>
                  <body>
                    Chainlink announced a CCIP update for cross-chain messaging and token transfers.
                  </body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await stage.collect(
                Target(name="Link", ticker="LINK"),
                client=client,
                docs_result=docs_result,
                period_days=365,
            )

    result = asyncio.run(run())

    assert result.posts
    assert result.posts[0].url == "https://medium.com/chainlink/ccip-update-123"


def test_project_knowledge_agent_translates_official_blog_claims_to_russian():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Link"
            profile.official_urls = {
                "website": ["https://chain.link/"],
                "docs": ["https://docs.chain.link/docs"],
            }
            profile.docs_urls_read = ["https://docs.chain.link/docs"]
            profile.what_the_project_does = "Chainlink connects blockchains to external data and systems."
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.chain.link/docs"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    class _BlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            post = OfficialBlogPost(
                url="https://chain.link/news/ccip-update",
                title="Chainlink CCIP update",
                published_at=datetime(2026, 3, 18, tzinfo=timezone.utc),
                summary="Chainlink announced a CCIP update for cross-chain messaging and token transfers.",
                key_points=[
                    "The partnership integrates Chainlink as an infrastructure provider for blockchain services across ADI Chain's ecosystem, including oracle services for stablecoins and tokenized assets.",
                ],
                categories=["official_update"],
            )
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [post], "citations": [post.url], "status": "ok", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_BlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Link", ticker="LINK"), []))

    assert "Chainlink объявил об обновлении CCIP для кроссчейн-сообщений и переводов токенов." not in section.markdown
    assert "Партнёрство интегрирует Chainlink как инфраструктурного провайдера блокчейн-сервисов" not in section.markdown
    assert "Chainlink announced a CCIP update for cross-chain messaging and token transfers." not in section.markdown


def test_project_knowledge_agent_translates_morpho_official_blog_claims_to_russian():
    assert (
        _render_official_blog_claim("Morpho TBA brings fixed-rate lending onchain.")
        == "Morpho TBA переносит fixed-rate lending в ончейн-формат."
    )
    assert _render_official_blog_claim(
        "Apollo and Morpho will be working together to support onchain lending markets on Morpho’s protocol."
    ) == "Apollo и Morpho будут совместно поддерживать ончейн-рынки кредитования на протоколе Morpho."
    assert _render_official_blog_claim(
        "Company Jobs Blog Support Brand Copy as png Copy as svg Products Consumer Vaults Markets Prime Curate Rewards Infra API SDK"
    ) is None


def test_project_knowledge_agent_translates_media_style_blog_claims_from_official_site_output():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Link"
            profile.official_urls = {
                "website": ["https://chain.link/"],
                "docs": ["https://docs.chain.link/docs"],
            }
            profile.docs_urls_read = ["https://docs.chain.link/docs"]
            profile.what_the_project_does = "Chainlink connects blockchains to external data and systems."
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.chain.link/docs"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    class _BlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            post = OfficialBlogPost(
                url="https://chain.link/news/example",
                title="Chainlink mention roundup",
                published_at=datetime(2026, 3, 18, tzinfo=timezone.utc),
                summary="News in Focus Browse News Releases All News Releases All Public Company English-only News Releases Overview Multimedia Gallery.",
                key_points=[
                    "According to a post from Ondo on Wednesday, the feeds are now being used on Euler.",
                    "Cointelegraph reached out to Chainlink for comment and had not received a response by publication.",
                    "Chainlink announced a CCIP update for cross-chain messaging and token transfers.",
                ],
                categories=["official_update"],
            )
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [post], "citations": [post.url], "status": "ok", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_BlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Link", ticker="LINK"), []))

    assert "News in Focus" not in section.markdown
    assert "Согласно посту Ondo" not in section.markdown
    assert "Cointelegraph запросил у Chainlink комментарий" not in section.markdown


def test_project_knowledge_agent_translates_prnewswire_style_chainlink_blog_claims_more_cleanly():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Link"
            profile.official_urls = {
                "website": ["https://chain.link/"],
                "docs": ["https://docs.chain.link/docs"],
            }
            profile.docs_urls_read = ["https://docs.chain.link/docs"]
            profile.what_the_project_does = "Chainlink connects blockchains to external data and systems."
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.chain.link/docs"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    class _BlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            post = OfficialBlogPost(
                url="https://chain.link/news/example-2",
                title="Chainlink press style roundup",
                published_at=datetime(2026, 3, 18, tzinfo=timezone.utc),
                summary="SAN FRANCISCO , March 18, 2026 /PRNewswire/ -- Unichain , the DeFi chain powered by Uniswap, has adopted the Chainlink data standard and joined the Chainlink Scale program to accelerate the growth of the Unichain ecosystem.",
                key_points=[
                    "ABU DHABI, UAE , March 3, 2026 /PRNewswire/ -- ADI Foundation , the Abu Dhabi-based institutional blockchain platform founded by Sirius International Holding – the digital arm of IHC , one of the largest investment companies in the world – and Chainlink , the industry-standard or",
                    "The partnership integrates Chainlink as an infrastructure provider for blockchain services across ADI Chain's ecosystem, including oracle services for stablecoins and tokenized assets.",
                ],
                categories=["official_update"],
            )
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [post], "citations": [post.url], "status": "ok", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_BlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Link", ticker="LINK"), []))

    assert "PRNewswire" not in section.markdown
    assert "SAN FRANCISCO" not in section.markdown
    assert "ABU DHABI" not in section.markdown
    assert "рост экосистемы Unichain" not in section.markdown
    assert "в экосистеме ADI Chain" not in section.markdown


def test_project_knowledge_agent_filters_binary_pdf_security_garbage_and_normalizes_omnichain_docs_claims():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Zro"
            profile.official_urls = {
                "website": ["https://layerzero.network/"],
                "docs": ["https://docs.layerzero.network/"],
                "security": ["https://docs.layerzero.network/community/bug-bounty-support"],
            }
            profile.docs_urls_read = ["https://docs.layerzero.network/", "https://docs.layerzero.network/community/bug-bounty-support"]
            profile.what_the_project_does = "LayerZero provides interoperability infrastructure across blockchains."
            profile.business_model = None
            profile.revenue_model = None
            profile.token_role = "This enables LayerZero to support chains where the native token has no economic value."
            profile.token_utility_points = [
                "Core Benefits : Unified Supply : One token, many chains, consistent total supply across all deployments No Wrapped Tokens : Native representation on each chain without bridging artifacts Direct Transfer Model : Direct chain-to-chain token transfers without intermediaries ; Characteristics : Contract Structure : Single contract per chain containing both token and bridge logic",
            ]
            profile.security_highlights = [
                "n3���)��!5�o�J�  �W ЫN�0������Ne�onz���uOz?� b�9�r  &�� Ro77ո��@�w�� � e}� endstream endobj 1 0 obj << /Annots [ 1320 0 R ] /MediaBox  0 0 612 792 /Resources 1328 0 R /Type /Page >> endobj",
            ]
            profile.audit_providers = ["OpenZeppelin", "Immunefi"]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.layerzero.network/"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Zro", ticker="ZRO"), []))

    assert "endstream endobj" not in section.markdown
    assert "Это позволяет LayerZero поддерживать сети, где нативный токен не имеет собственной экономической ценности." in section.markdown
    assert "омничейн-модель с единым предложением между сетями" in section.markdown
    assert "Contract Structure" not in section.markdown


def test_official_blog_stage_filters_zero_table_of_contents_shell_noise():
    stage = OfficialBlogStage(_settings())
    docs_result = type(
        "DocsResult",
        (),
        {
            "profile": _StubDocsProfile(),
            "status": "ok",
            "summary": "",
            "citations": [],
            "coverage": {"available": True},
        },
    )()
    docs_result.profile.project_name = "Zro"
    docs_result.profile.official_urls = {"website": ["https://layerzero.network/zero"], "docs": ["https://docs.layerzero.network/"]}
    docs_result.profile.docs_urls_read = ["https://docs.layerzero.network/"]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://layerzero.network/zero":
            return httpx.Response(
                200,
                text='<html><body><a href="https://layerzero.network/blog/zero-thesis">Research Zero</a></body></html>',
                headers={"content-type": "text/html"},
            )
        if url == "https://docs.layerzero.network/":
            return httpx.Response(200, text="<html><body></body></html>", headers={"content-type": "text/html"})
        if url == "https://layerzero.network/blog/zero-thesis":
            return httpx.Response(
                200,
                text="""
                <html>
                  <head>
                    <title>Research Zero: Technical Positioning Paper</title>
                    <meta property="article:published_time" content="2026-02-10T12:00:00Z" />
                  </head>
                  <body>
                    Products About Blog Zero Developers About Blog Developers /// PRODUCTS Interoperability Stargate Zero Table of Contents 01 What is a Blockchain?
                    Products About Blog Zero Developers About Blog Developers /// PRODUCTS Interoperability Stargate Zero Table of Contents 01 The technology underlying the Zero blockchain 02 Decentralization-first: The ethos of blockchain.
                    Zero introduces a designated Atomicity Zone, called the System Zone, which handles core functions often placed in the settlement layer on other blockchains: Native coin (ZRO) circulation.
                    The System Zone maintains ZRO balances and processes ZRO transfers.
                  </body>
                </html>
                """,
                headers={"content-type": "text/html"},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await stage.collect(
                Target(name="Zro", ticker="ZRO"),
                client=client,
                docs_result=docs_result,
                period_days=365,
            )

    result = asyncio.run(run())

    assert result.posts == []


def test_project_knowledge_agent_hides_key_findings_section_from_markdown():
    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_StubDocsStage(),
        blog_stage=_StubBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Ripple", ticker="XRP"), []))

    assert "### Ключевые выводы" not in section.markdown


def test_project_knowledge_agent_filters_uniswap_docs_shell_from_token_utility():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Uni"
            profile.official_urls = {
                "website": ["https://uniswap.org/"],
                "docs": ["https://developers.uniswap.org/docs"],
                "tokenomics": ["https://developers.uniswap.org/docs"],
            }
            profile.docs_urls_read = ["https://developers.uniswap.org/docs"]
            profile.what_the_project_does = "Uniswap provides decentralized trading infrastructure."
            profile.business_model = None
            profile.revenue_model = None
            profile.token_role = None
            profile.token_utility_points = [
                "Uniswap Developers Docs | Uniswap Developers Developers Docs API Reference Resources API keys API keys Search / Get Started Quick Start Concepts Trade Trading Overview Swapping Custom Linking Liquidity Liquidity Overview Liquidity Provisioning Liquidity Launch",
                "All reward decisions, including eligibility for and amounts of the rewards and the manner in which such rewards will be paid, are made at Uniswap Labs' sole discretion.",
            ]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://developers.uniswap.org/docs"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Uni", ticker="UNI"), []))

    assert "Утилити токена по документации" not in section.markdown
    assert "API keys" not in section.markdown
    assert "sole discretion" not in section.markdown


def test_project_knowledge_agent_keeps_uniswap_overview_when_utility_is_filtered():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Uni"
            profile.official_urls = {
                "website": ["https://uniswap.org/"],
                "docs": ["https://developers.uniswap.org/docs"],
            }
            profile.docs_urls_read = ["https://developers.uniswap.org/docs"]
            profile.what_the_project_does = "Uniswap provides decentralized trading infrastructure."
            profile.business_model = None
            profile.revenue_model = None
            profile.token_role = None
            profile.key_product_entities = []
            profile.supported_chains = []
            profile.token_utility_points = [
                "Uniswap Developers Docs | Uniswap Developers Developers Docs API Reference Resources API keys API keys Search / Get Started Quick Start Concepts Trade Trading Overview Swapping Custom Linking Liquidity Liquidity Overview Liquidity Provisioning Liquidity Launch",
            ]
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://developers.uniswap.org/docs"],
                    "coverage": {"available": True, "pages_read": 1},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Uni", ticker="UNI"), []))

    assert "Uniswap предоставляет децентрализованную торговую инфраструктуру." in section.markdown
    assert "Из официальной документации не удалось извлечь достаточно содержательных тезисов" not in section.markdown


def test_project_knowledge_agent_renders_zero_blog_without_table_of_contents_shell():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Zro"
            profile.official_urls = {
                "website": ["https://layerzero.network/zero"],
                "docs": ["https://docs.layerzero.network/"],
            }
            profile.docs_urls_read = ["https://docs.layerzero.network/"]
            profile.what_the_project_does = "LayerZero provides interoperability infrastructure across blockchains."
            return type(
                "DocsResult",
                (),
                {"profile": profile, "status": "ok", "summary": profile.what_the_project_does, "citations": ["https://docs.layerzero.network/"], "coverage": {"available": True}},
            )()

    class _BlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            post = OfficialBlogPost(
                url="https://layerzero.network/blog/zero-thesis",
                title="Research Zero",
                published_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
                summary="Products About Blog Zero Developers About Blog Developers /// PRODUCTS Interoperability Stargate Zero Table of Contents 01 What is a Blockchain?",
                key_points=[
                    "ZRO stakers delegate their tokens to validators who run the network.",
                    "Zero introduces a designated Atomicity Zone, called the System Zone, which handles core functions often placed in the settlement layer on other blockchains: Native coin (ZRO) circulation.",
                    "The System Zone maintains ZRO balances and processes ZRO transfers.",
                ],
                categories=["official_update"],
            )
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [post], "citations": [post.url], "status": "ok", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_BlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Zro", ticker="ZRO"), []))

    assert "Products About Blog Zero Developers" not in section.markdown
    assert "Table of Contents" not in section.markdown
    assert "Стейкеры ZRO делегируют свои токены валидаторам" not in section.markdown
    assert "System Zone ведёт балансы ZRO" not in section.markdown


def test_project_knowledge_agent_renders_layerzero_as_interoperability_not_blockchain_or_dex():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Zro"
            profile.official_urls = {
                "website": ["https://layerzero.network/"],
                "docs": ["https://docs.layerzero.network/"],
            }
            profile.docs_urls_read = ["https://docs.layerzero.network/"]
            profile.project_type = "bridge"
            profile.project_subtype = None
            profile.what_the_project_does = "LayerZero is an interoperability protocol that enables applications to send messages across chains."
            profile.business_model = "Provides cross-chain messaging and interoperability infrastructure for applications across chains."
            profile.revenue_model = None
            profile.token_role = ""
            profile.token_utility_points = []
            profile.value_capture_points = []
            profile.tokenomics_points = []
            profile.product_token_link_points = []
            profile.fee_recipient_points = []
            profile.revenue_model_points = []
            profile.supported_chains = []
            profile.key_product_entities = ["messages", "endpoints", "oapps", "workers", "chains"]
            return type(
                "DocsResult",
                (),
                {"profile": profile, "status": "ok", "summary": profile.what_the_project_does, "citations": ["https://docs.layerzero.network/"], "coverage": {"available": True}},
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Zro", ticker="ZRO"), []))

    assert "interoperability / cross-chain messaging" in section.markdown
    assert "cross-chain messaging и interoperability-инфраструктуру" in section.markdown
    assert "спотовой торговли токенами" not in section.markdown
    assert "типу блокчейн" not in section.markdown


def test_project_knowledge_agent_renders_stellar_like_network_as_blockchain_not_bridge():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Xlm"
            profile.official_urls = {
                "website": ["https://www.stellar.org/"],
                "docs": ["https://developers.stellar.org/docs"],
            }
            profile.docs_urls_read = ["https://developers.stellar.org/docs"]
            profile.project_type = "blockchain"
            profile.project_subtype = "payments_tokenization_l1"
            profile.what_the_project_does = "Stellar is an open source decentralized network for payments and asset tokenization."
            profile.business_model = "Provides a public blockchain network for payments, asset issuance, tokenization, and smart-contract transactions."
            profile.revenue_model = "Primary revenue likely comes from gas or network fees."
            profile.token_role = "Lumens (XLM) are the native currency of the Stellar network and are used to pay transaction fees and cover minimum balances."
            profile.token_utility_points = ["XLM is used to pay transaction fees and cover minimum balance requirements."]
            profile.value_capture_points = ["Transaction fees are paid in lumens on the Stellar network."]
            profile.tokenomics_points = []
            profile.product_token_link_points = ["All transaction fees are paid using the native Stellar token, XLM."]
            profile.fee_recipient_points = ["All fees are paid using the native Stellar token, the lumen or XLM."]
            profile.revenue_model_points = ["Stellar requires a fee for all transactions to make it to the ledger, and all fees are paid using XLM."]
            profile.supported_chains = []
            profile.key_product_entities = ["accounts", "transactions", "ledger", "validators", "assets", "payments"]
            return type(
                "DocsResult",
                (),
                {"profile": profile, "status": "ok", "summary": profile.what_the_project_does, "citations": ["https://developers.stellar.org/docs"], "coverage": {"available": True}},
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Xlm", ticker="XLM"), []))

    assert "типу блокчейн, подтип: payment / asset-tokenization L1" in section.markdown
    assert "публичную блокчейн-сеть для платежей" in section.markdown
    assert "сетевых комиссий" in section.markdown
    assert "XLM используется для оплаты transaction fees" in section.markdown
    assert "interoperability / cross-chain messaging" not in section.markdown
    assert "cross-chain messaging и interoperability-инфраструктуру" not in section.markdown


def test_project_knowledge_agent_renders_helium_like_depin_wireless_with_data_credit_model():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Helium"
            profile.official_urls = {
                "website": ["https://www.helium.com/"],
                "docs": ["https://docs.helium.com/tokens/hnt-token", "https://docs.helium.com/tokens/data-credit"],
            }
            profile.docs_urls_read = ["https://docs.helium.com/tokens/hnt-token", "https://docs.helium.com/tokens/data-credit"]
            profile.project_type = "depin_wireless"
            profile.project_subtype = None
            profile.what_the_project_does = "Helium is a decentralized wireless network where Hotspots provide IoT and Mobile coverage."
            profile.business_model = "Provides decentralized wireless network infrastructure where hotspots supply IoT or mobile coverage and users pay for network usage."
            profile.revenue_model = "Primary revenue likely comes from network usage paid with data credits, hotspot onboarding fees, and token burn-and-mint mechanics."
            profile.token_role = "Data Credits, which are a USD-pegged utility token derived from HNT, are used to pay transaction fees for wireless data transmissions on the Network."
            profile.token_utility_points = [
                "HNT serves the needs of Hotspot Hosts and Operators while enterprises use Data Credits derived from HNT.",
                "Data Credits, which are a USD-pegged utility token derived from HNT, are used to pay transaction fees for wireless data transmissions on the Network.",
            ]
            profile.value_capture_points = ["Data Credits are only produced by burning HNT. This relationship is called burn and mint economics."]
            profile.tokenomics_points = ["The Network uses burn and mint economics and net emissions."]
            profile.product_token_link_points = ["Data Credits are only produced by burning HNT."]
            profile.fee_recipient_points = ["Data Credits are the mechanism by which all Helium network usage is paid for."]
            profile.revenue_model_points = [
                "Data Credits are the mechanism by which all Helium network usage is paid for.",
                "Data Credits are only produced by burning HNT.",
            ]
            profile.supported_chains = []
            profile.key_product_entities = ["hotspots", "coverage", "data credits", "iot network", "mobile network", "operators"]
            return type(
                "DocsResult",
                (),
                {"profile": profile, "status": "ok", "summary": profile.what_the_project_does, "citations": ["https://docs.helium.com/tokens/hnt-token"], "coverage": {"available": True}},
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Helium", ticker="HNT"), []))

    assert "DePIN / decentralized wireless network" in section.markdown
    assert "wireless-инфраструктуру" in section.markdown
    assert "Data Credits" in section.markdown
    assert "burn-and-mint" in section.markdown
    assert "payment / asset-tokenization L1" not in section.markdown
    assert "публичную блокчейн-сеть для платежей" not in section.markdown


def test_project_knowledge_agent_renders_agent_platform_without_spot_dex_language():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Virtual"
            profile.official_urls = {
                "website": ["https://www.virtuals.io/"],
                "docs": ["https://whitepaper.virtuals.io/"],
            }
            profile.docs_urls_read = ["https://whitepaper.virtuals.io/"]
            profile.project_type = "agent_platform"
            profile.project_subtype = None
            profile.what_the_project_does = "Virtuals is an agent tokenization platform for launching AI agents and agent tokens."
            profile.business_model = "Provides an AI-agent tokenization and commerce platform where autonomous agents can be launched, owned, and transact onchain."
            profile.revenue_model = "Primary revenue likely comes from agent launch or creation fees, trading taxes, and agent commerce transaction fees."
            profile.token_role = "$VIRTUAL is the base asset and routing currency for agent tokens."
            profile.token_utility_points = ["$VIRTUAL is the base asset and routing currency for agent tokens."]
            profile.value_capture_points = ["Creating a new agent requires $VIRTUAL liquidity pairing and can create demand for $VIRTUAL."]
            profile.tokenomics_points = []
            profile.product_token_link_points = ["$VIRTUAL is the base asset and routing currency for agent tokens."]
            profile.fee_recipient_points = ["A 1% trading tax applies to agent-token activity and fees are allocated to the protocol treasury, creators, and ACP incentives."]
            profile.revenue_model_points = [
                "Each launch has a one-time creation fee of 1,000 $VIRTUAL.",
                "A 1% trading tax applies to agent-token activity; fees are allocated to the protocol treasury, agent creators, and ACP incentives.",
            ]
            profile.supported_chains = []
            profile.key_product_entities = ["agents", "agent tokens", "launches", "commerce protocol", "services"]
            return type(
                "DocsResult",
                (),
                {"profile": profile, "status": "ok", "summary": profile.what_the_project_does, "citations": ["https://whitepaper.virtuals.io/"], "coverage": {"available": True}},
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Virtual", ticker="VIRTUAL"), []))

    assert "AI-agent tokenization / commerce platform" in section.markdown
    assert "токенизации, запуска и ончейн-коммерции AI-агентов" in section.markdown
    assert "trading tax" in section.markdown
    assert "Поддерживаемые сети" not in section.markdown
    assert "спотовой торговли токенами" not in section.markdown


def test_project_knowledge_agent_renders_shared_sector_taxonomy_without_dex_fallbacks():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del client, period_days
            profile = _StubDocsProfile()
            profile.project_name = target.name
            profile.official_urls = {"website": ["https://example.test/"], "docs": ["https://example.test/docs"]}
            profile.docs_urls_read = ["https://example.test/docs"]
            profile.project_subtype = None
            profile.supported_chains = []
            profile.token_role = None
            profile.token_utility_points = []
            profile.value_capture_points = []
            profile.tokenomics_points = []
            profile.product_token_link_points = []
            profile.fee_recipient_points = []

            if target.ticker == "PSP":
                profile.project_type = "dex_aggregator"
                profile.what_the_project_does = "ParaSwap is a DEX aggregator and swap aggregator."
                profile.business_model = "Aggregates swap liquidity and routes orders across DEXs or liquidity sources for better execution."
                profile.revenue_model = "Primary revenue likely comes from routing, aggregation, partner, or execution-related fees."
                profile.revenue_model_points = ["Protocol revenue comes from routing fees, aggregation fees, and partner fees on executed swaps."]
                profile.key_product_entities = ["routes", "quotes", "liquidity sources", "solvers"]
            elif target.ticker == "LDO":
                profile.project_type = "liquid_staking"
                profile.what_the_project_does = "Lido is a liquid staking protocol."
                profile.business_model = "Tokenizes staked or restaked assets so users can keep liquidity while earning staking or restaking rewards."
                profile.revenue_model = "Primary revenue likely comes from staking or restaking fees, validator commissions, and protocol fee shares on rewards."
                profile.revenue_model_points = ["The protocol distributes staking rewards while charging staking fees and validator commissions."]
                profile.key_product_entities = ["validators", "staking rewards", "staked tokens"]
            else:
                profile.project_type = "nft_marketplace"
                profile.what_the_project_does = "Blur is an NFT marketplace."
                profile.business_model = "Provides marketplace infrastructure for NFT minting, listings, bids, and secondary trading."
                profile.revenue_model = "Primary revenue likely comes from marketplace trading fees, mint fees, and creator-royalty or platform fee flows."
                profile.revenue_model_points = ["Marketplace fees and creator royalties can apply to NFT trades."]
                profile.key_product_entities = ["listings", "bids", "collections", "royalties"]

            return type(
                "DocsResult",
                (),
                {"profile": profile, "status": "ok", "summary": profile.what_the_project_does, "citations": ["https://example.test/docs"], "coverage": {"available": True}},
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_EmptyBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    paraswap = asyncio.run(agent.collect_project_knowledge(Target(name="ParaSwap", ticker="PSP"), []))
    lido = asyncio.run(agent.collect_project_knowledge(Target(name="Lido", ticker="LDO"), []))
    blur = asyncio.run(agent.collect_project_knowledge(Target(name="Blur", ticker="BLUR"), []))

    assert "DEX aggregator" in paraswap.markdown
    assert "агрегирует ликвидность" in paraswap.markdown
    assert "routing/aggregation fees" in paraswap.markdown

    assert "liquid staking / restaking" in lido.markdown
    assert "staked/restaked assets" in lido.markdown
    assert "staking/restaking fees" in lido.markdown

    assert "NFT marketplace" in blur.markdown


def test_project_knowledge_agent_renders_secondary_product_lines_for_multi_surface_platform():
    class _JupLikeProfile(_StubDocsProfile):
        def __init__(self) -> None:
            super().__init__()
            self.project_name = "Jup"
            self.project_type = "dex_aggregator"
            self.project_subtype = None
            self.product_lines = [
                {"type": "dex_aggregator", "subtype": None, "role": "primary", "confidence": 0.95, "evidence_urls": ["https://docs.jup.ag/user-docs/trade/swap"]},
                {"type": "perp_dex", "subtype": None, "role": "secondary", "confidence": 0.58, "evidence_urls": ["https://docs.jup.ag/user-docs/trade/perps-and-jlp"]},
                {"type": "prediction_market", "subtype": None, "role": "secondary", "confidence": 0.51, "evidence_urls": ["https://docs.jup.ag/user-docs/trade/predict"]},
            ]
            self.what_the_project_does = "Jupiter is a DEX aggregator and swap aggregator."
            self.business_model = None
            self.supported_chains = ["Solana"]

    class _JupDocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _JupLikeProfile()
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://docs.jup.ag/user-docs/trade/swap"],
                    "coverage": {"available": True, "pages_read": 2},
                },
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_JupDocsStage(),
        blog_stage=_StubBlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Jup", ticker="JUP"), []))

    assert "Документация относит проект к типу DEX aggregator." in section.markdown
    assert "Дополнительные продуктовые направления по документации: перпетуальный DEX, prediction market." in section.markdown


def test_project_knowledge_agent_translates_generic_giza_blog_claims_to_russian():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Giza"
            profile.official_urls = {
                "website": ["https://www.gizatech.xyz/"],
                "docs": ["https://docs.gizaprotocol.ai/"],
            }
            profile.docs_urls_read = ["https://docs.gizaprotocol.ai/"]
            profile.what_the_project_does = "Giza builds autonomous agents for DeFi."
            return type(
                "DocsResult",
                (),
                {"profile": profile, "status": "ok", "summary": profile.what_the_project_does, "citations": ["https://docs.gizaprotocol.ai/"], "coverage": {"available": True}},
            )()

    class _BlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            posts = [
                OfficialBlogPost(
                    url="https://www.gizatech.xyz/blog/economics",
                    title="Giza Economics",
                    published_at=datetime(2026, 3, 31, tzinfo=timezone.utc),
                    summary="Back to Blog Giza Economics Giza Economics Feb 26, 2026 Executive Summary Giza builds autonomous agents that manage DeFi positions on behalf of users.",
                    key_points=[
                        "This document explains how Giza creates value, captures revenue, and distributes that value to token holders.",
                    ],
                    categories=["official_update"],
                ),
                OfficialBlogPost(
                    url="https://www.gizatech.xyz/blog/optimizer",
                    title="The Giza Optimizer",
                    published_at=datetime(2026, 3, 31, tzinfo=timezone.utc),
                    summary="Back to Blog The Giza Optimizer The Giza Optimizer Feb 26, 2026 Earlier this week, we launched the new Giza Agent.",
                    key_points=[
                        "The brain inside is called the Giza Optimizer.",
                        "The Giza Optimizer asks a different question entirely: how should your capital be distributed across lending markets to maximize yield given your specific risk preferences?",
                    ],
                    categories=["official_update"],
                ),
            ]
            return type(
                "OfficialBlogResult",
                (),
                {"posts": posts, "citations": [p.url for p in posts], "status": "ok", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_BlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Giza", ticker="GIZA"), []))

    assert "Back to Blog" not in section.markdown
    assert "Этот документ объясняет, как Giza создаёт ценность" not in section.markdown
    assert "Ранее на этой неделе мы запустили новый Giza Agent." not in section.markdown
    assert "Внутренний модуль называется the Giza Optimizer." not in section.markdown
    assert "Внутренний модуль называется The Giza Optimizer." not in section.markdown


def test_project_knowledge_agent_normalizes_giza_like_mojibake_before_blog_translation():
    class _DocsStage:
        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = "Giza"
            profile.official_urls = {
                "website": ["https://www.gizatech.xyz/"],
                "docs": ["https://docs.gizaprotocol.ai/"],
            }
            profile.docs_urls_read = ["https://docs.gizaprotocol.ai/"]
            profile.what_the_project_does = "Giza builds autonomous agents for DeFi."
            return type(
                "DocsResult",
                (),
                {"profile": profile, "status": "ok", "summary": profile.what_the_project_does, "citations": ["https://docs.gizaprotocol.ai/"], "coverage": {"available": True}},
            )()

    class _BlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            post = OfficialBlogPost(
                url="https://www.gizatech.xyz/blog/mojibake",
                title="Giza Mojibake",
                published_at=datetime(2026, 3, 31, tzinfo=timezone.utc),
                summary="Giza builds autonomous agents thВ manage DeFi positions on behalf of users.",
                key_points=[
                    "The Value Giza CreВes The Cognitive Labor Problem The fundamental limiting resource in finance is cognition itself.",
                    "WhВ's happening?",
                    "Today, we are happy to announce thВ Giza Agents, which are moving more than $40m of volume to dВe, are going institutional.",
                ],
                categories=["official_update"],
            )
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [post], "citations": [post.url], "status": "ok", "coverage": {"available": True, "period_days": 90}},
            )()

    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=_DocsStage(),
        blog_stage=_BlogStage(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    section = asyncio.run(agent.collect_project_knowledge(Target(name="Giza", ticker="GIZA"), []))

    assert "thВ" not in section.markdown
    assert "CreВes" not in section.markdown
    assert "dВe" not in section.markdown
    assert "Giza создаёт автономных агентов" not in section.markdown
    assert "создаёт автономных агентов, которые управляют DeFi-позициями" not in section.markdown
    assert "Сегодня мы рады объявить, что Giza Agents" not in section.markdown


def test_project_knowledge_agent_sector_smoke_matrix_keeps_classification_and_business_fields_stable():
    interpreter = _new_documentation_interpreter()
    scenarios = [
        {
            "ticker": "AAVE",
            "project_type": "lending",
            "project_subtype": "cdp_lending",
            "supported_chains": ["Ethereum", "Base", "Arbitrum"],
            "what_the_project_does": "Aave is a decentralized non-custodial liquidity protocol where users can supply, borrow, or use assets as collateral.",
            "business_model": None,
            "revenue_model": None,
            "revenue_model_points": ["Borrowers pay interest and a reserve factor directs a share of protocol fees to the protocol treasury."],
            "value_capture_points": ["Reserve factor directs a share of protocol fees to the protocol treasury."],
            "expected_business": "заёмщиков и поставщиков ликвидности",
            "expected_revenue": "reserve factor",
        },
        {
            "ticker": "PSP",
            "project_type": "dex_aggregator",
            "project_subtype": None,
            "supported_chains": ["Ethereum", "Arbitrum", "Polygon"],
            "what_the_project_does": "ParaSwap is a DEX aggregator and swap aggregator focused on best execution across liquidity sources.",
            "business_model": None,
            "revenue_model": "Primary revenue likely comes from routing, aggregation, partner, or execution-related fees.",
            "revenue_model_points": ["Protocol revenue comes from routing fees, aggregation fees, and partner fees on executed swaps."],
            "value_capture_points": ["Protocol revenue comes from routing fees and aggregation fees on executed swaps."],
            "expected_business": "агрегирует ликвидность",
            "expected_revenue": "aggregation fees",
        },
        {
            "ticker": "LDO",
            "project_type": "liquid_staking",
            "project_subtype": None,
            "supported_chains": ["Ethereum", "Solana"],
            "what_the_project_does": "Lido is a liquid staking protocol for staked ETH and other proof-of-stake assets.",
            "business_model": None,
            "revenue_model": "Primary revenue likely comes from staking or restaking fees, validator commissions, and protocol fee shares on rewards.",
            "revenue_model_points": ["The protocol distributes staking rewards while charging staking fees and validator commissions."],
            "value_capture_points": ["The protocol keeps a fee share on staking rewards generated by staked assets."],
            "expected_business": "staked/restaked assets",
            "expected_revenue": "staking/restaking fees",
        },
        {
            "ticker": "MLN",
            "project_type": "asset_management",
            "project_subtype": None,
            "supported_chains": ["Ethereum", "Polygon"],
            "what_the_project_does": "Enzyme provides managed vaults, portfolios, and strategy tooling for onchain asset management.",
            "business_model": None,
            "revenue_model": "Primary revenue likely comes from management fees, performance fees, strategy fees or product spreads.",
            "revenue_model_points": ["Protocol revenue comes from management fees and performance fees on managed vault products."],
            "value_capture_points": ["Managed vaults can accrue management and performance fees to protocol-aligned participants."],
            "expected_business": "asset-management",
            "expected_revenue": "management fees",
        },
        {
            "ticker": "BLUR",
            "project_type": "nft_marketplace",
            "project_subtype": None,
            "supported_chains": ["Ethereum", "Blast"],
            "what_the_project_does": "Blur is an NFT marketplace for listings, bids, and secondary trading.",
            "business_model": None,
            "revenue_model": "Primary revenue likely comes from marketplace trading fees, mint fees, and creator-royalty or platform fee flows.",
            "revenue_model_points": ["Marketplace fees and creator royalties can apply to NFT trades."],
            "value_capture_points": ["Marketplace trading fees and creator royalties can flow through NFT transactions."],
            "expected_business": "NFT minting",
            "expected_revenue": "marketplace trading fees",
        },
        {
            "ticker": "AXS",
            "project_type": "gaming",
            "project_subtype": None,
            "supported_chains": ["Ronin", "Ethereum"],
            "what_the_project_does": "Axie Infinity provides a web3 gaming economy with game assets, rewards, and marketplace flows.",
            "business_model": None,
            "revenue_model": "Primary revenue likely comes from marketplace fees, game-asset sales, platform fees and transaction fees.",
            "revenue_model_points": ["Protocol revenue comes from marketplace fees and game-asset sales across the gaming economy."],
            "value_capture_points": ["Marketplace fees and in-game asset sales create protocol-level value capture."],
            "expected_business": "gaming-экономику",
            "expected_revenue": "marketplace fees",
        },
        {
            "ticker": "LENS",
            "project_type": "social",
            "project_subtype": None,
            "supported_chains": ["Polygon"],
            "what_the_project_does": "Lens provides SocialFi and creator-network infrastructure around profiles, communities, and social graph interactions.",
            "business_model": None,
            "revenue_model": "Primary revenue likely comes from creator fees, platform fees, subscriptions, social transactions or marketplace fees.",
            "revenue_model_points": ["Protocol revenue comes from creator fees, platform fees, and social transactions."],
            "value_capture_points": ["Creator fees and social transactions can accrue to protocol participants."],
            "expected_business": "SocialFi",
            "expected_revenue": "creator fees",
        },
        {
            "ticker": "POLY",
            "project_type": "prediction_market",
            "project_subtype": None,
            "supported_chains": ["Polygon"],
            "what_the_project_does": "Polymarket provides prediction markets and outcome markets for event probabilities and market resolution.",
            "business_model": None,
            "revenue_model": "Primary revenue likely comes from trading fees, market fees, settlement fees or spread capture.",
            "revenue_model_points": ["Protocol revenue comes from trading fees, market fees, and settlement fees."],
            "value_capture_points": ["Trading fees and settlement fees create protocol-level value capture around market resolution."],
            "expected_business": "prediction/outcome markets",
            "expected_revenue": "trading fees",
        },
        {
            "ticker": "MEME",
            "project_type": "meme",
            "project_subtype": None,
            "supported_chains": ["Ethereum"],
            "what_the_project_does": "Meme is a community token with ecosystem participation mechanics.",
            "business_model": None,
            "revenue_model": None,
            "revenue_model_points": [],
            "value_capture_points": ["Token utility and business-model evidence remain limited in official docs."],
            "expected_business": "community/meme token",
            "expected_revenue": None,
        },
        {
            "ticker": "GIZA",
            "project_type": "ai_network",
            "project_subtype": None,
            "supported_chains": ["Ethereum", "Base"],
            "what_the_project_does": "Giza provides AI network infrastructure for inference, agent execution, and model marketplaces.",
            "business_model": None,
            "revenue_model": "Primary revenue likely comes from compute, inference, model, API or marketplace usage fees.",
            "revenue_model_points": ["Protocol revenue comes from compute, inference, and API usage fees."],
            "value_capture_points": ["Inference and compute usage can create value capture around agent and model demand."],
            "expected_business": "AI-инфраструктуру",
            "expected_revenue": "compute",
        },
        {
            "ticker": "ZRO",
            "project_type": "bridge",
            "project_subtype": None,
            "supported_chains": ["Ethereum", "Arbitrum", "Base"],
            "what_the_project_does": "LayerZero provides cross-chain messaging and interoperability infrastructure for omnichain applications.",
            "business_model": None,
            "revenue_model": "Primary revenue likely comes from cross-chain messaging, verification, executor, or bridge fees.",
            "revenue_model_points": ["Protocol revenue comes from cross-chain messaging, verification, and executor fees."],
            "value_capture_points": ["Cross-chain messaging and executor fees create value capture around omnichain application usage."],
            "expected_business": "cross-chain messaging",
            "expected_revenue": "cross-chain messaging",
        },
        {
            "ticker": "HNT",
            "project_type": "depin_wireless",
            "project_subtype": None,
            "supported_chains": ["Solana"],
            "what_the_project_does": "Helium provides decentralized wireless network infrastructure where hotspots supply IoT or mobile coverage.",
            "business_model": None,
            "revenue_model": "Primary revenue likely comes from network usage paid with data credits, hotspot onboarding fees, and token burn-and-mint mechanics.",
            "revenue_model_points": ["The mechanism by which all Helium Network usage is paid is Data Credits."],
            "value_capture_points": ["Data Credits are only produced by burning HNT."],
            "expected_business": "wireless-инфраструктуру",
            "expected_revenue": "Data Credits",
        },
        {
            "ticker": "VIRTUAL",
            "project_type": "agent_platform",
            "project_subtype": None,
            "supported_chains": ["Base"],
            "what_the_project_does": "Virtual provides an AI-agent tokenization and commerce platform where autonomous agents can be launched and transact onchain.",
            "business_model": None,
            "revenue_model": "Primary revenue likely comes from agent launch or creation fees, trading taxes, and agent commerce transaction fees.",
            "revenue_model_points": ["A 1% trading tax applies to agent-token activity; fees are allocated to the protocol treasury, agent creators, and ACP incentives."],
            "value_capture_points": ["Creating a new agent requires VIRTUAL liquidity pairing and can create demand for VIRTUAL."],
            "expected_business": "AI-агентов",
            "expected_revenue": "trading tax",
        },
        {
            "ticker": "SKY",
            "project_type": "synthetic_dollar",
            "project_subtype": None,
            "supported_chains": ["Ethereum"],
            "what_the_project_does": "Sky Protocol includes USDS, the decentralized stablecoin upgraded from Dai, and the SKY governance token.",
            "business_model": None,
            "revenue_model": None,
            "revenue_model_points": ["Protocol surplus collects stability fees, liquidation penalties, and PSM fees before governance allocates surplus through protocol mechanisms."],
            "value_capture_points": ["stUSDS funds and supports liquidity for SKY stakers, encouraging more participation in SKY governance."],
            "expected_business": "синтетический доллар",
            "expected_revenue": "stability fees",
        },
        {
            "ticker": "LINK",
            "project_type": "oracle",
            "project_subtype": None,
            "supported_chains": ["Ethereum", "Arbitrum", "Base"],
            "what_the_project_does": "Chainlink supplies external data and pricing infrastructure to onchain applications.",
            "business_model": "Supplies external data and pricing infrastructure to onchain applications.",
            "revenue_model": "Primary revenue likely comes from data feed usage and service fees.",
            "revenue_model_points": ["Protocol revenue comes from service fees."],
            "value_capture_points": ["Payment for oracle services and network security can support token demand."],
            "expected_business": "oracle-инфраструктуру",
            "expected_revenue": "service fees",
        },
    ]

    for scenario in scenarios:
        profile = _StubDocsProfile()
        profile.project_name = scenario["ticker"]
        profile.project_type = scenario["project_type"]
        profile.project_subtype = scenario["project_subtype"]
        profile.supported_chains = scenario["supported_chains"]
        profile.what_the_project_does = scenario["what_the_project_does"]
        profile.business_model = scenario["business_model"]
        profile.revenue_model = scenario["revenue_model"]
        profile.revenue_model_points = scenario["revenue_model_points"]
        profile.value_capture_points = scenario["value_capture_points"]
        profile.tokenomics_points = []
        profile.token_utility_points = []
        profile.product_token_link_points = []
        profile.fee_recipient_points = []
        profile.governance_points = []
        profile.treasury_points = []
        profile.treasury_control_points = []
        profile.team_points = []
        profile.investor_partner_points = []
        profile.roadmap_points = []

        interpretation = interpreter.interpret(profile)

        assert interpretation.project_type == scenario["project_type"], scenario["ticker"]
        assert interpretation.project_subtype == scenario["project_subtype"], scenario["ticker"]
        assert interpretation.evidence.compatibility_hints["supported_chains"] == scenario["supported_chains"], scenario["ticker"]
        business_model = interpretation.business_model or business_model_from_project_type(
            scenario["project_type"],
            scenario["project_subtype"],
        )
        assert scenario["expected_business"] in (business_model or ""), scenario["ticker"]
        if scenario["expected_revenue"] is None:
            assert interpretation.revenue_model is None, scenario["ticker"]
        else:
            assert scenario["expected_revenue"].lower() in (interpretation.revenue_model or "").lower(), scenario["ticker"]
        assert isinstance(interpretation.value_capture_claims, list), scenario["ticker"]


def test_project_knowledge_agent_markdown_regression_smoke_keeps_core_sections_stable():
    scenarios = [
        {
            "target": Target(name="Aave", ticker="AAVE"),
            "project_type": "lending",
            "project_subtype": "cdp_lending",
            "what_the_project_does": "Aave is a decentralized non-custodial liquidity protocol where users can supply, borrow, or use assets as collateral.",
            "business_model": None,
            "revenue_model": None,
            "revenue_model_points": ["Borrowers pay interest and a reserve factor directs a share of protocol fees to the protocol treasury."],
            "value_capture_points": ["Reserve factor directs a share of protocol fees to the protocol treasury."],
            "token_exists": True,
            "token_role": "AAVE token holders participate in governance voting.",
            "token_utility_points": ["AAVE can be staked in the Safety Module."],
            "tokenomics_present": True,
            "governance_present": True,
            "treasury_points": ["Reserve factor directs a share of protocol fees to the protocol treasury."],
            "treasury_control_points": ["Governance can direct treasury resources toward ecosystem priorities."],
            "risk_factors": ["Smart contract and liquidation risks are documented in security materials."],
            "audit_providers": ["Certora"],
            "expected": [
                "Документация относит проект к типу лендинг, подтип: cdp-lending.",
                "reserve factor",
            ],
        },
        {
            "target": Target(name="Virtual", ticker="VIRTUAL"),
            "project_type": "agent_platform",
            "project_subtype": None,
            "what_the_project_does": "Virtuals is an agent tokenization platform for launching AI agents and agent tokens.",
            "business_model": "Provides an AI-agent tokenization and commerce platform where autonomous agents can be launched, owned, and transact onchain.",
            "revenue_model": "Primary revenue likely comes from agent launch or creation fees, trading taxes, and agent commerce transaction fees.",
            "revenue_model_points": [
                "Each launch has a one-time creation fee of 1,000 $VIRTUAL.",
                "A 1% trading tax applies to agent-token activity; fees are allocated to the protocol treasury, agent creators, and ACP incentives.",
            ],
            "value_capture_points": ["Creating a new agent requires $VIRTUAL liquidity pairing and can create demand for $VIRTUAL."],
            "token_exists": True,
            "token_role": "$VIRTUAL is the base asset and routing currency for agent tokens.",
            "token_utility_points": ["$VIRTUAL is the base asset and routing currency for agent tokens."],
            "tokenomics_present": True,
            "governance_present": False,
            "treasury_points": ["Fees are allocated to the protocol treasury, creators, and ACP incentives."],
            "treasury_control_points": [],
            "risk_factors": ["Execution and adoption risks are documented."],
            "audit_providers": [],
            "expected": [
                "Документация относит проект к типу AI-agent tokenization / commerce platform.",
                "AI-agent tokenization / commerce platform",
                "trading tax",
            ],
        },
        {
            "target": Target(name="Helium", ticker="HNT"),
            "project_type": "depin_wireless",
            "project_subtype": None,
            "what_the_project_does": "Helium is a decentralized wireless network where Hotspots provide IoT and Mobile coverage.",
            "business_model": "Provides decentralized wireless network infrastructure where hotspots supply IoT or mobile coverage and users pay for network usage.",
            "revenue_model": "Primary revenue likely comes from network usage paid with data credits, hotspot onboarding fees, and token burn-and-mint mechanics.",
            "revenue_model_points": ["Data Credits are the mechanism by which all Helium network usage is paid for."],
            "value_capture_points": ["Data Credits are only produced by burning HNT. This relationship is called burn and mint economics."],
            "token_exists": True,
            "token_role": "Data Credits, which are a USD-pegged utility token derived from HNT, are used to pay transaction fees for wireless data transmissions on the Network.",
            "token_utility_points": ["HNT serves the needs of Hotspot Hosts and Operators while enterprises use Data Credits derived from HNT."],
            "tokenomics_present": True,
            "governance_present": False,
            "treasury_points": [],
            "treasury_control_points": [],
            "risk_factors": ["Network rollout and usage risks are documented."],
            "audit_providers": [],
            "expected": [
                "Документация относит проект к типу DePIN / decentralized wireless network.",
                "Data Credits",
                "burning HNT",
            ],
        },
        {
            "target": Target(name="Sky", ticker="SKY"),
            "project_type": "synthetic_dollar",
            "project_subtype": None,
            "what_the_project_does": "Sky Protocol includes USDS, the decentralized stablecoin upgraded from Dai, and the SKY governance token.",
            "business_model": None,
            "revenue_model": None,
            "revenue_model_points": ["Protocol surplus collects stability fees, liquidation penalties, and PSM fees before governance allocates surplus through protocol mechanisms."],
            "value_capture_points": ["stUSDS funds and supports liquidity for SKY stakers, encouraging more participation in SKY governance."],
            "token_exists": True,
            "token_role": "Sky Governance Portal allows SKY holders to vote.",
            "token_utility_points": ["Sky Governance Portal allows for anyone to view governance proposals, and also allows for SKY holders to vote."],
            "tokenomics_present": True,
            "governance_present": True,
            "treasury_points": ["Protocol surplus collects stability fees, liquidation penalties, and PSM fees."],
            "treasury_control_points": ["Governance allocates surplus through protocol mechanisms."],
            "risk_factors": ["Collateral and parameter risks are documented."],
            "audit_providers": ["Cantina"],
            "expected": [
                "Документация относит проект к типу протокол синтетического доллара.",
                "stability fees",
                "кто управляет treasury",
            ],
            "expected_absent": ["перпетуальный DEX"],
        },
    ]

    class _DocsStage:
        def __init__(self, scenario):
            self.scenario = scenario

        async def collect(self, target, *, client, period_days: int = 365):
            del target, client, period_days
            profile = _StubDocsProfile()
            profile.project_name = self.scenario["target"].name
            profile.official_urls = {
                "website": ["https://example.test/"],
                "docs": ["https://example.test/docs"],
                "tokenomics": ["https://example.test/tokenomics"],
                "governance": ["https://example.test/governance"],
                "treasury": ["https://example.test/treasury"],
            }
            profile.docs_urls_read = ["https://example.test/docs"]
            for field in (
                "project_type",
                "project_subtype",
                "what_the_project_does",
                "business_model",
                "revenue_model",
                "revenue_model_points",
                "value_capture_points",
                "token_exists",
                "token_role",
                "token_utility_points",
                "tokenomics_present",
                "governance_present",
                "treasury_points",
                "treasury_control_points",
                "risk_factors",
                "audit_providers",
            ):
                setattr(profile, field, self.scenario[field])
            profile.fee_recipient_points = []
            profile.product_token_link_points = []
            profile.tokenomics_points = []
            profile.team_points = []
            profile.investor_partner_points = []
            profile.roadmap_points = []
            profile.supported_chains = []
            profile.audits_present = bool(profile.audit_providers)
            profile.security_section_present = bool(profile.risk_factors)
            profile.key_product_entities = []
            profile.evidence_snippets = []
            return type(
                "DocsResult",
                (),
                {
                    "profile": profile,
                    "status": "ok",
                    "summary": profile.what_the_project_does,
                    "citations": ["https://example.test/docs"],
                    "coverage": {"available": True},
                },
            )()

    class _EmptyBlogStage:
        async def collect(self, target, *, client, docs_result, period_days: int = 365):
            del target, client, docs_result, period_days
            return type(
                "OfficialBlogResult",
                (),
                {"posts": [], "citations": [], "status": "partial", "coverage": {"available": True, "period_days": 90}},
            )()

    for scenario in scenarios:
        agent = ProjectKnowledgeAgent(
            settings=_settings(),
            docs_stage=_DocsStage(scenario),
            blog_stage=_EmptyBlogStage(),
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
        )
        section = asyncio.run(agent.collect_project_knowledge(scenario["target"], []))

        assert "### 18. Final Documentation Verdict" in section.markdown, scenario["target"].ticker
        for expected in scenario["expected"]:
            if expected == "кто управляет treasury":
                assert expected not in section.markdown, scenario["target"].ticker
            else:
                assert expected in section.markdown, scenario["target"].ticker
        for expected_absent in scenario.get("expected_absent", []):
            assert expected_absent not in section.markdown, scenario["target"].ticker


def test_project_knowledge_agent_splits_malformed_combined_source_urls():
    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=OfficialDocsStage(_settings()),
        blog_stage=OfficialBlogStage(_settings()),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    citations = agent._collect_citations(
        ["https://lido.fi/how-lido-works- https://docs.lido.fi/deployed-contracts"],
        findings=[],
    )

    assert "https://lido.fi/how-lido-works" in citations
    assert "https://docs.lido.fi/deployed-contracts" in citations
    assert all(" https://" not in item for item in citations)


def test_project_knowledge_agent_splits_hyphen_joined_source_urls_from_sources_block():
    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=OfficialDocsStage(_settings()),
        blog_stage=OfficialBlogStage(_settings()),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    citations = agent._collect_citations(
        ["https://docs.lido.fi/deployed-contracts- https://docs.lido.fi/guides/lido-tokens-integration-guide"],
        findings=[],
    )

    assert "https://docs.lido.fi/deployed-contracts" in citations
    assert "https://docs.lido.fi/guides/lido-tokens-integration-guide" in citations
    assert all(" https://" not in item for item in citations)


def test_project_knowledge_agent_splits_multiple_join_styles_in_source_urls():
    agent = ProjectKnowledgeAgent(
        settings=_settings(),
        docs_stage=OfficialDocsStage(_settings()),
        blog_stage=OfficialBlogStage(_settings()),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    citations = agent._collect_citations(
        ["https://docs.lido.fi/guides/lido-tokens-integration-guide- https://lido.fi/stvaults"],
        findings=[],
    )

    assert "https://docs.lido.fi/guides/lido-tokens-integration-guide" in citations
    assert "https://lido.fi/stvaults" in citations
    assert all(" https://" not in item for item in citations)
