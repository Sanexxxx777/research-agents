"""External master research agent for deterministic scoring and dossier assembly."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from core.models import EvidenceBundle, EvidenceFact, ProjectDossier, ScoreDimension, SectionDocument, Target
from core.report import build_report

WEIGHTS: dict[str, dict[str, float]] = {
    "defi_lending": {
        "fundamentals_usage": 0.28,
        "unit_economics": 0.20,
        "tokenomics": 0.14,
        "market_liquidity": 0.13,
        "social": 0.10,
        "smart_money": 0.05,
        "risk": 0.10,
    },
    "dex_spot": {
        "fundamentals_usage": 0.24,
        "unit_economics": 0.18,
        "tokenomics": 0.14,
        "market_liquidity": 0.18,
        "social": 0.11,
        "smart_money": 0.05,
        "risk": 0.10,
    },
    "perp_dex": {
        "fundamentals_usage": 0.24,
        "unit_economics": 0.20,
        "tokenomics": 0.10,
        "market_liquidity": 0.18,
        "social": 0.08,
        "smart_money": 0.10,
        "risk": 0.10,
    },
    "l1_l2": {
        "fundamentals_usage": 0.30,
        "unit_economics": 0.12,
        "tokenomics": 0.10,
        "market_liquidity": 0.12,
        "social": 0.10,
        "smart_money": 0.08,
        "risk": 0.18,
    },
    "generic_token": {
        "fundamentals_usage": 0.20,
        "unit_economics": 0.12,
        "tokenomics": 0.18,
        "market_liquidity": 0.20,
        "social": 0.15,
        "smart_money": 0.05,
        "risk": 0.10,
    },
}


class MasterResearchAgent:
    def availability(self) -> tuple[bool, str]:
        return True, "ok"

    async def build_project_dossier(
        self,
        target: Target,
        baseline_results: list,
        market_intel: EvidenceBundle | None,
        analysis: dict | None = None,
        sections: list[SectionDocument] | None = None,
        auxiliary_sources: dict | None = None,
    ) -> ProjectDossier:
        analysis = analysis or {}
        sections = sections or []
        auxiliary_sources = auxiliary_sources or {}
        bundle = market_intel or EvidenceBundle(agent="market_intel_agent")
        profile = bundle.profile or "generic_token"
        facts_by_key = self._facts_by_key(bundle.facts)
        conflicts = self._detect_conflicts(bundle.facts)
        dimension_scores = self._compute_dimensions(
            profile=profile,
            facts_by_key=facts_by_key,
            baseline_results=baseline_results,
            auxiliary_sources=auxiliary_sources,
        )
        final_score = self._final_score(profile, dimension_scores)
        citations = self._citations(bundle.facts, sections=sections)
        summary = analysis.get("take") or analysis.get("analysis") or ""
        markdown = self._build_markdown(
            target=target,
            baseline_results=baseline_results,
            analysis=analysis,
            profile=profile,
            final_score=final_score,
            dimension_scores=dimension_scores,
            coverage=bundle.coverage,
            missing_metrics=bundle.missing_metrics,
            conflicts=conflicts,
            facts=bundle.facts,
            sections=sections,
        )
        return ProjectDossier(
            target_name=target.name,
            profile=profile,
            final_score=final_score,
            summary=summary,
            markdown=markdown,
            analysis=analysis,
            evidence=bundle,
            dimension_scores=dimension_scores,
            coverage={
                **(bundle.coverage or {}),
                "facts_count": len(bundle.facts),
                "missing_metrics": bundle.missing_metrics,
                "sections": {section.section_id: section.status for section in sections},
            },
            conflicts=conflicts,
            citations=citations,
            sections=sections,
            metadata={"agent": "master_research_agent"},
        )

    def _build_markdown(
        self,
        target: Target,
        baseline_results: list,
        analysis: dict,
        profile: str,
        final_score: float,
        dimension_scores: list[ScoreDimension],
        coverage: dict,
        missing_metrics: list[str],
        conflicts: list[dict[str, Any]],
        facts: list[EvidenceFact],
        sections: list[SectionDocument],
    ) -> str:
        base_md = build_report(
            target,
            baseline_results,
            analysis=analysis or None,
        )
        lines = [base_md.rstrip(), "", "🧭 *Dossier Layer*"]
        lines.append(f"Профиль: `{profile}`")
        lines.append(f"Итоговый score: `{final_score:.0f}/100`")
        lines.append("")
        lines.append("*Scorecard*")
        for score in dimension_scores:
            lines.append(
                f"• `{score.score:.0f}/100` {score.key} "
                f"(вес {int(score.weight * 100)}%)"
            )
        if coverage:
            lines.append("")
            lines.append("*Coverage*")
            facts_count = coverage.get("facts_count")
            if facts_count is not None:
                lines.append(f"• facts: {facts_count}")
            plan = coverage.get("sources", {})
            if plan:
                lines.append(f"• sources: {', '.join(sorted(plan.keys())[:10])}")
        if missing_metrics:
            lines.append("")
            lines.append("*Missing Metrics*")
            for metric in missing_metrics[:10]:
                lines.append(f"• {metric}")
        if conflicts:
            lines.append("")
            lines.append("*Conflicts*")
            for conflict in conflicts[:5]:
                values = ", ".join(
                    f"{item['source']}={item['value']}" for item in conflict.get("values", [])[:4]
                )
                lines.append(f"• {conflict['key']}: {values}")
        highlights = sorted(
            facts,
            key=lambda fact: (fact.confidence, fact.key),
            reverse=True,
        )[:8]
        if highlights:
            lines.append("")
            lines.append("*Market Intel Highlights*")
            for fact in highlights:
                line = f"• {fact.key}: {fact.value}"
                if fact.unit:
                    line += f" {fact.unit}"
                line += f" [{fact.source}]"
                lines.append(line)
        for section in sections:
            if not section.markdown:
                continue
            lines.append("")
            lines.append(section.markdown.strip())
        return "\n".join(lines).strip()

    def _compute_dimensions(
        self,
        profile: str,
        facts_by_key: dict[str, list[EvidenceFact]],
        baseline_results: list,
        auxiliary_sources: dict[str, Any],
    ) -> list[ScoreDimension]:
        weights = WEIGHTS.get(profile, WEIGHTS["generic_token"])
        scores = {
            "fundamentals_usage": self._fundamentals_usage(profile, facts_by_key),
            "unit_economics": self._unit_economics(facts_by_key),
            "tokenomics": self._tokenomics(facts_by_key),
            "market_liquidity": self._market_liquidity(facts_by_key),
            "social": self._social_score(facts_by_key, baseline_results, auxiliary_sources),
            "smart_money": self._smart_money_score(facts_by_key, auxiliary_sources),
            "risk": self._risk_score(profile, facts_by_key),
        }
        return [
            ScoreDimension(
                key=key,
                score=value,
                weight=weights.get(key, 0),
            )
            for key, value in scores.items()
        ]

    def _facts_by_key(self, facts: list[EvidenceFact]) -> dict[str, list[EvidenceFact]]:
        grouped: dict[str, list[EvidenceFact]] = defaultdict(list)
        for fact in facts:
            grouped[fact.key].append(fact)
        return grouped

    def _detect_conflicts(self, facts: list[EvidenceFact]) -> list[dict[str, Any]]:
        grouped = self._facts_by_key(facts)
        conflicts: list[dict[str, Any]] = []
        for key, candidates in grouped.items():
            values = []
            for fact in candidates:
                if isinstance(fact.value, (int, float)):
                    values.append({"source": fact.source, "value": round(float(fact.value), 4)})
            distinct = {item["value"] for item in values}
            if len(distinct) >= 2:
                low = min(distinct)
                high = max(distinct)
                if low == 0 or (high / low) >= 1.15:
                    conflicts.append({"key": key, "values": values[:5]})
        return conflicts

    def _final_score(self, profile: str, dimension_scores: list[ScoreDimension]) -> float:
        weights = WEIGHTS.get(profile, WEIGHTS["generic_token"])
        score = 0.0
        for dimension in dimension_scores:
            score += dimension.score * weights.get(dimension.key, dimension.weight)
        return round(max(0.0, min(100.0, score)), 1)

    def _fundamentals_usage(self, profile: str, facts_by_key: dict[str, list[EvidenceFact]]) -> float:
        if profile == "defi_lending":
            return self._average(
                self._log_score(self._numeric_value(facts_by_key, "tvl"), 1e7, 1e10),
                self._log_score(self._numeric_value(facts_by_key, "supplied_usd"), 5e6, 1e10),
                self._log_score(self._numeric_value(facts_by_key, "borrows_usd"), 1e6, 5e9),
            )
        if profile == "dex_spot":
            return self._average(
                self._log_score(self._numeric_value(facts_by_key, "volume_24h"), 1e6, 5e9),
                self._log_score(self._numeric_value(facts_by_key, "liquidity_usd"), 5e5, 1e9),
                self._log_score(self._numeric_value(facts_by_key, "tvl"), 1e7, 1e10),
            )
        if profile == "perp_dex":
            return self._average(
                self._log_score(self._numeric_value(facts_by_key, "volume_24h"), 5e6, 5e9),
                self._log_score(self._numeric_value(facts_by_key, "open_interest"), 1e6, 5e9),
                self._log_score(self._numeric_value(facts_by_key, "fees_24h"), 1e4, 2e7),
            )
        if profile == "l1_l2":
            return self._average(
                self._log_score(self._numeric_value(facts_by_key, "transactions_24h"), 5e4, 5e6),
                self._log_score(self._numeric_value(facts_by_key, "active_addresses"), 1e4, 1e6),
                self._log_score(self._numeric_value(facts_by_key, "tvl"), 1e7, 1e10),
            )
        return self._average(
            self._log_score(self._numeric_value(facts_by_key, "market_cap"), 1e7, 2e10),
            self._log_score(self._numeric_value(facts_by_key, "volume_24h"), 1e5, 1e9),
            self._log_score(self._numeric_value(facts_by_key, "liquidity_usd"), 1e5, 1e8),
        )

    def _unit_economics(self, facts_by_key: dict[str, list[EvidenceFact]]) -> float:
        return self._average(
            self._log_score(self._numeric_value(facts_by_key, "fees_24h"), 1e4, 2e7),
            self._log_score(self._numeric_value(facts_by_key, "revenue_24h"), 1e3, 5e6),
            self._log_score(self._numeric_value(facts_by_key, "buybacks"), 1e3, 1e6),
            neutral=50.0,
        )

    def _tokenomics(self, facts_by_key: dict[str, list[EvidenceFact]]) -> float:
        score = 55.0
        unlocked_pct = self._numeric_value(facts_by_key, "unlocked_pct")
        if unlocked_pct is not None:
            score += 15 if unlocked_pct >= 70 else 5 if unlocked_pct >= 40 else -10
        unlock_value = self._numeric_value(facts_by_key, "unlock_value_usd")
        if unlock_value is not None:
            score -= self._log_score(unlock_value, 1e6, 5e8) * 0.25
        circulating = self._numeric_value(facts_by_key, "circulating_supply")
        total = self._numeric_value(facts_by_key, "total_supply")
        if circulating and total and total > 0:
            ratio = circulating / total
            score += 10 if ratio >= 0.6 else 3 if ratio >= 0.3 else -8
        return self._clamp(score)

    def _market_liquidity(self, facts_by_key: dict[str, list[EvidenceFact]]) -> float:
        momentum = 50.0
        change_7d = self._numeric_value(facts_by_key, "price_change_7d")
        if change_7d is not None:
            momentum = self._clamp(50 + max(-25, min(25, change_7d)))
        return self._average(
            self._log_score(self._numeric_value(facts_by_key, "market_cap"), 1e7, 2e10),
            self._log_score(self._numeric_value(facts_by_key, "volume_24h"), 1e5, 1e9),
            self._log_score(self._numeric_value(facts_by_key, "liquidity_usd"), 1e5, 1e8),
            momentum,
        )

    def _social_score(
        self,
        facts_by_key: dict[str, list[EvidenceFact]],
        baseline_results: list,
        auxiliary_sources: dict[str, Any],
    ) -> float:
        tweets = auxiliary_sources.get("tweets") or []
        tweet_score = self._clamp(45 + min(30, len(tweets) * 2))
        youtube_count = 0
        for result in baseline_results:
            if result.source.value == "youtube":
                youtube_count += len(result.items)
        youtube_score = self._clamp(40 + min(25, youtube_count * 3))
        yaps_score = self._log_score(self._numeric_value(facts_by_key, "yaps_score"), 100, 10000)
        return self._average(tweet_score, youtube_score, yaps_score, neutral=50.0)

    def _smart_money_score(self, facts_by_key: dict[str, list[EvidenceFact]], auxiliary_sources: dict[str, Any]) -> float:
        smart_money = auxiliary_sources.get("smart_money") or {}
        if isinstance(smart_money, dict):
            if smart_money.get("score") is not None:
                return self._clamp(float(smart_money["score"]))
        return self._average(
            self._log_score(self._numeric_value(facts_by_key, "open_interest"), 1e6, 5e9),
            self._log_score(self._numeric_value(facts_by_key, "volume_24h"), 1e6, 5e9),
            neutral=50.0,
        )

    def _risk_score(self, profile: str, facts_by_key: dict[str, list[EvidenceFact]]) -> float:
        score = 55.0
        stage = self._string_value(facts_by_key, "stage")
        if stage:
            stage_lower = stage.lower()
            if "stage 2" in stage_lower:
                score += 25
            elif "stage 1" in stage_lower:
                score += 10
            else:
                score -= 5
        bad_debt = self._numeric_value(facts_by_key, "bad_debt_usd")
        if bad_debt is not None and bad_debt > 0:
            score -= self._log_score(bad_debt, 1e5, 1e9) * 0.4
        funding = self._numeric_value(facts_by_key, "funding_rate")
        if profile == "perp_dex" and funding is not None:
            score += 5 if abs(funding) < 0.05 else -5
        return self._clamp(score)

    def _numeric_value(self, facts_by_key: dict[str, list[EvidenceFact]], key: str) -> float | None:
        facts = facts_by_key.get(key) or []
        if not facts:
            return None
        sorted_facts = sorted(
            facts,
            key=lambda fact: (fact.confidence, fact.as_of.timestamp() if fact.as_of else 0),
            reverse=True,
        )
        for fact in sorted_facts:
            if isinstance(fact.value, (int, float)):
                return float(fact.value)
        return None

    def _string_value(self, facts_by_key: dict[str, list[EvidenceFact]], key: str) -> str | None:
        facts = facts_by_key.get(key) or []
        if not facts:
            return None
        best = sorted(
            facts,
            key=lambda fact: (fact.confidence, fact.as_of.timestamp() if fact.as_of else 0),
            reverse=True,
        )[0]
        return str(best.value) if best.value is not None else None

    def _average(self, *values: float | None, neutral: float | None = None) -> float:
        clean = [value for value in values if value is not None]
        if not clean:
            return neutral if neutral is not None else 50.0
        return round(sum(clean) / len(clean), 1)

    def _log_score(self, value: float | None, low: float, high: float) -> float | None:
        if value is None or value <= 0 or low <= 0 or high <= 0:
            return None
        import math

        low_log = math.log10(low)
        high_log = math.log10(high)
        value_log = math.log10(max(value, low))
        if high_log == low_log:
            return 50.0
        return self._clamp((value_log - low_log) / (high_log - low_log) * 100)

    def _clamp(self, value: float) -> float:
        return round(max(0.0, min(100.0, value)), 1)

    def _citations(self, facts: list[EvidenceFact], *, sections: list[SectionDocument] | None = None) -> list[str]:
        seen: set[str] = set()
        citations: list[str] = []
        for fact in facts:
            if fact.citation_url and fact.citation_url not in seen:
                seen.add(fact.citation_url)
                citations.append(fact.citation_url)
        for section in sections or []:
            for url in section.citations:
                if url and url not in seen:
                    seen.add(url)
                    citations.append(url)
        return citations
