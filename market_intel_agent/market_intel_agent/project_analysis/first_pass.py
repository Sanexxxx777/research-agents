"""First-pass execution using DefiLlama skills with bridge fallback."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from market_intel_agent.project_analysis.models import ResolvedEntity, SectorType
from market_intel_agent.project_analysis.normalization import normalize_first_pass_output
from market_intel_agent.project_analysis.registry import (
    canonical_first_pass_skill,
    metrics_covered_by_first_pass,
    metrics_for_first_pass_skill,
)
from market_intel_agent.project_analysis.sources import ProjectAnalysisSources

_DEFAULT_SKILLS = ["protocol-deep-dive", "market-analysis", "risk-assessment"]


class FirstPassRunner:
    def __init__(self, *, config: dict[str, Any], sources: ProjectAnalysisSources):
        self.config = config
        self.sources = sources

        pa_cfg = config.get("project_analysis", {})
        skills_cfg = pa_cfg.get("skills", {}) if isinstance(pa_cfg, dict) else {}

        configured = skills_cfg.get("enabled") if isinstance(skills_cfg, dict) else None
        if isinstance(configured, list) and configured:
            requested = [str(item).strip() for item in configured if str(item).strip()]
        else:
            requested = list(_DEFAULT_SKILLS)

        self.skill_bindings: list[tuple[str, str]] = []
        seen_canonical: set[str] = set()
        for requested_skill in requested:
            canonical = canonical_first_pass_skill(requested_skill)
            if not canonical or canonical in seen_canonical:
                continue
            seen_canonical.add(canonical)
            self.skill_bindings.append((requested_skill, canonical))
        self.skills = [canonical for _, canonical in self.skill_bindings]

        self.command_template = str(skills_cfg.get("command_template") or "").strip()

    async def run(self, *, asset_input: str, entity: ResolvedEntity, sector: SectorType) -> dict[str, Any]:
        raw_outputs: dict[str, Any] = {}
        normalized: dict[str, Any] = {}
        covered_metrics = metrics_covered_by_first_pass(self.skills)
        command_audit: list[dict[str, Any]] = []

        if self.command_template:
            for requested_skill, canonical_skill in self.skill_bindings:
                payload = await self._run_skill_command(
                    skill=requested_skill,
                    canonical_skill=canonical_skill,
                    asset_input=asset_input,
                    entity=entity,
                    sector=sector,
                )
                if isinstance(payload, dict) and isinstance(payload.get("_audit"), list):
                    for item in payload.get("_audit") or []:
                        if not isinstance(item, dict):
                            continue
                        entry = dict(item)
                        entry.setdefault("skill", requested_skill)
                        entry.setdefault("canonical_skill", canonical_skill)
                        command_audit.append(entry)
                raw_outputs[canonical_skill] = payload
                normalized.update(normalize_first_pass_output(payload))
            mode = "skills_command"
        else:
            bridge_payload = await self.sources.fetch_defillama_metrics(
                asset_input=asset_input,
                sector=sector,
                candidate_slug=entity.defillama_slug,
                coingecko_id=entity.coingecko_id,
                token_symbol=entity.token_symbol,
                required_metrics=covered_metrics,
            )
            bridge_audit = []
            if isinstance(bridge_payload, dict) and isinstance(bridge_payload.get("_audit"), list):
                bridge_audit = [item for item in bridge_payload.get("_audit") or [] if isinstance(item, dict)]
                bridge_payload = {k: v for k, v in bridge_payload.items() if k != "_audit"}
            for _, canonical_skill in self.skill_bindings:
                skill_metrics = metrics_for_first_pass_skill(canonical_skill)
                skill_payload = {
                    metric: bridge_payload.get(metric)
                    for metric in skill_metrics
                    if bridge_payload.get(metric) is not None
                }
                raw_outputs[canonical_skill] = {"mode": "bridge_skill_profile", "metrics": skill_payload}
                normalized.update(normalize_first_pass_output(skill_payload))
            mode = "bridge_skill_profiles"

        unavailable_known = {
            str(item.get("metric") or "")
            for item in command_audit
            if isinstance(item, dict) and str(item.get("event") or "") == "metric_unavailable"
        }
        for metric in covered_metrics:
            if normalized.get(metric) is not None or metric in unavailable_known:
                continue
            command_audit.append(
                {
                    "event": "metric_unavailable",
                    "metric": metric,
                    "owner": "defillama",
                    "reason": "first_pass_skills output missing metric",
                }
            )

        return {
            "skills": list(self.skills),
            "covered_metrics": covered_metrics,
            "mode": mode,
            "raw_outputs": raw_outputs,
            "normalized": normalized,
            "source_audit": bridge_audit if not self.command_template else command_audit,
            "skill_aliases": {
                canonical: requested
                for requested, canonical in self.skill_bindings
                if requested != canonical
            },
        }

    async def _run_skill_command(
        self,
        *,
        skill: str,
        canonical_skill: str,
        asset_input: str,
        entity: ResolvedEntity,
        sector: SectorType,
    ) -> Any:
        command = self.command_template.format(
            skill=skill,
            canonical_skill=canonical_skill,
            asset_input=asset_input,
            name=entity.name,
            symbol=entity.token_symbol or "",
            sector=sector,
            coingecko_id=entity.coingecko_id or "",
            defillama_slug=entity.defillama_slug or "",
        )
        if not command:
            return {}

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await proc.communicate()
            stdout = (stdout_b or b"").decode("utf-8", errors="ignore").strip()
            stderr = (stderr_b or b"").decode("utf-8", errors="ignore").strip()
            if proc.returncode != 0:
                logger.warning(f"project_analysis first-pass skill command failed ({skill}): {stderr}")
                return {"error": stderr or f"exit_code={proc.returncode}"}
            if not stdout:
                return {}
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                return stdout
        except Exception as exc:
            logger.warning(f"project_analysis first-pass command exception ({skill}): {exc}")
            return {"error": str(exc)}
