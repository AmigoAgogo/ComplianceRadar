from __future__ import annotations

import json
import re
import requests

from app.models import utc_now_iso


class DemoAIService:
    BUSINESS_LENS = (
        "Interpret all regulatory signals from the perspective of Siemens Financial Leasing "
        "in mainland China. Prioritize implications for board, management, compliance, legal, "
        "and risk teams, and distinguish between macro regulatory trend, portfolio exposure, "
        "operational control gap, and immediate management action."
    )

    def normalize_openai_base(self, base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            normalized = normalized[: -len("/chat/completions")]
        if normalized.endswith("/responses"):
            normalized = normalized[: -len("/responses")]
        return normalized

    def build_console_context(self, dashboard: dict, prompt: str, context: str) -> dict:
        events = dashboard.get("events", [])
        summary = dashboard.get("summary", {})
        management_dashboard = dashboard.get("management_dashboard", {})
        agent_context = dashboard.get("agent_context", {})
        penalty_intelligence = management_dashboard.get("penalty_intelligence", [])
        early_warning = management_dashboard.get("early_warning", {})
        supporting_events = early_warning.get("supporting_events", [])[:3]
        if not supporting_events:
            supporting_events = [
                event
                for event in events
                if event.get("is_penalty_event") or event.get("severity") == "major"
            ][:3] or events[:3]
        briefs = agent_context.get("briefs", {})
        sections = agent_context.get("sections", {})
        top_reasons = management_dashboard.get("top_penalty_reasons", [])
        reason_lines = [
            f"{item.get('reason', 'Unknown')} ({item.get('count', 0)})"
            for item in top_reasons[:3]
            if item.get("reason")
        ]
        signal_thesis = (
            management_dashboard.get("headline")
            or early_warning.get("headline")
            or "No management judgment available yet."
        )
        context_lines = [
            f"Context mode: {context}",
            f"User ask: {prompt}",
            "Output rule: be concise, decision-ready, and split China management from Global compliance.",
            f"Organization lens: {self.BUSINESS_LENS}",
            f"China management brief: {briefs.get('china_management', '')}",
            f"Global compliance brief: {briefs.get('global_compliance', '')}",
            f"Output schema: {sections.get('output_schema', '')}",
            f"Style guide: {sections.get('style_and_length', '')}",
            f"Escalation triggers: {sections.get('escalation_triggers', '')}",
            f"Management judgment: {signal_thesis}",
            (
                "Radar snapshot: "
                f"{summary.get('total_events', 0)} events, "
                f"{summary.get('major_events', 0)} major events, "
                f"top category {summary.get('top_category', 'N/A')}."
            ),
            f"Primary penalty themes: {', '.join(reason_lines) or 'N/A'}",
            (
                "Management warning: "
                f"penalty intelligence {', '.join(item.get('value', '') if isinstance(item.get('value', ''), str) else str(item.get('value', '')) for item in penalty_intelligence[:3]) or 'N/A'}. "
                f"{early_warning.get('headline', 'No early warning headline available.')}"
            ),
            f"Early warning summary: {early_warning.get('summary', 'No early warning summary available.')}",
            f"Early warning detail: {early_warning.get('management_actions', [])[:3]}",
            "Priority events:",
        ]
        if agent_context.get("combined_text"):
            context_lines.extend(
                [
                    "Agent compliance guidance:",
                    agent_context["combined_text"],
                ]
            )
        for event in supporting_events:
            context_lines.append(
                "- "
                f"{event.get('published_at', '')[:10]} | {event.get('regulator', 'N/A')} | {event.get('title', 'Untitled signal')} | "
                f"{event.get('category', 'N/A')} | {event.get('analysis_summary') or event.get('risk_hint', '')}"
            )
        return {
            "business_lens": self.BUSINESS_LENS,
            "context_event_count": len(events),
            "context_digest": "\n".join(context_lines),
            "agent_file_count": agent_context.get("file_count", 0),
            "agent_folder": agent_context.get("folder", ""),
        }

    def fetch_model_catalog(self, provider: str, base_url: str, api_key: str) -> list[str]:
        if provider != "openai-compatible":
            return []
        catalog_url = self.normalize_openai_base(base_url) + "/models"
        response = requests.get(
            catalog_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return [item["id"] for item in payload.get("data", []) if item.get("id")]

    def test_connection(self, profile: dict) -> dict:
        if profile.get("provider") == "openai-compatible" and profile.get("api_key"):
            chat_url = self.normalize_openai_base(profile["base_url"]) + "/chat/completions"
            response = requests.post(
                chat_url,
                headers={
                    "Authorization": f"Bearer {profile['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": profile["model_id"],
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=profile.get("timeout", 30),
            )
            response.raise_for_status()
            return {"ok": True, "message": "connection ok"}
        return {"ok": True, "message": "demo profile does not require remote validation"}

    def enrich_event(self, event: dict, models: dict) -> dict:
        current_name = models["current_model"]
        profile = next(
            (item for item in models["profiles"] if item["name"] == current_name),
            None,
        )
        if not (
            profile
            and profile.get("provider") == "openai-compatible"
            and profile.get("api_key")
        ):
            return {
                "model": current_name,
                "used_llm": False,
                "event": event,
            }

        chat_url = self.normalize_openai_base(profile["base_url"]) + "/chat/completions"
        response = requests.post(
            chat_url,
            headers={
                "Authorization": f"Bearer {profile['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": profile["model_id"],
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a regulatory enforcement enrichment engine. "
                            "Return valid JSON only with keys summary, risk_hint, english_brief. "
                            "Keep institution names and regulator facts unchanged."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "title": event["title"],
                                "regulator": event["regulator"],
                                "region": event["region"],
                                "category": event["category"],
                                "institution_name": event.get("institution_name_original") or event.get("institution_name"),
                                "summary": event["summary"],
                                "risk_hint": event["risk_hint"],
                                "english_brief": event["english_brief"],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            },
            timeout=profile.get("timeout", 30),
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        enriched = self._parse_json_payload(content)
        updated = dict(event)
        updated["summary"] = enriched.get("summary", event["summary"])
        updated["risk_hint"] = enriched.get("risk_hint", event["risk_hint"])
        updated["english_brief"] = enriched.get("english_brief", event["english_brief"])
        updated["llm_enriched_by"] = current_name
        updated["llm_enriched_at"] = utc_now_iso()
        return {
            "model": current_name,
            "used_llm": True,
            "event": updated,
        }

    def _parse_json_payload(self, content: str) -> dict:
        cleaned = content.strip()
        cleaned = cleaned.replace("```json", "```")
        if "<think>" in cleaned and "</think>" in cleaned:
            cleaned = cleaned.split("</think>", 1)[1].strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = cleaned.strip("`").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = self._extract_json_object(cleaned)
            if match:
                return json.loads(match)
            raise

    def _extract_json_object(self, content: str) -> str | None:
        start = content.find("{")
        if start < 0:
            return None
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(content)):
            char = content[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return content[start : index + 1]
        return None

    def _normalize_answer(self, answer: str, dashboard: dict, console_context: dict) -> str:
        cleaned = self._strip_think_block(answer).strip()
        if not cleaned:
            return self._fallback_concise_answer(dashboard, console_context)
        summary = dashboard.get("summary", {})
        if int(summary.get("total_events", 0) or 0) == 0:
            return self._fallback_concise_answer(dashboard, console_context)
        if len(cleaned) <= 900 and "Executive Summary" in cleaned and "Recommended Actions" in cleaned:
            return cleaned
        sections = self._parse_answer_sections(cleaned)
        if not any(sections.values()):
            return self._fallback_concise_answer(dashboard, console_context)
        return self._render_compact_answer(sections, dashboard, console_context)

    def _strip_think_block(self, answer: str) -> str:
        cleaned = re.sub(r"<think>.*?</think>", "", answer, flags=re.S | re.I).strip()
        cleaned = re.sub(r"</?think>", "", cleaned, flags=re.I).strip()
        return cleaned

    def _parse_answer_sections(self, answer: str) -> dict[str, list[str]]:
        sections = {
            "summary": [],
            "china": [],
            "global": [],
            "signals": [],
            "risk": [],
            "actions": [],
            "evidence": [],
        }
        current = None
        for raw_line in answer.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            heading = line.lstrip("#").strip()
            lowered = heading.lower()
            if lowered.startswith("executive summary"):
                current = "summary"
                content = heading.split(":", 1)[1].strip() if ":" in heading else ""
                if content:
                    sections[current].append(content)
                continue
            if lowered.startswith("china management brief") or lowered == "china":
                current = "china"
                content = heading.split(":", 1)[1].strip() if ":" in heading else ""
                if content:
                    sections[current].append(content)
                continue
            if lowered.startswith("global compliance brief") or lowered == "global":
                current = "global"
                content = heading.split(":", 1)[1].strip() if ":" in heading else ""
                if content:
                    sections[current].append(content)
                continue
            if lowered.startswith("key signals"):
                current = "signals"
                content = heading.split(":", 1)[1].strip() if ":" in heading else ""
                if content:
                    sections[current].append(content)
                continue
            if lowered.startswith("risk to siemens financial leasing") or lowered.startswith("risk"):
                current = "risk"
                content = heading.split(":", 1)[1].strip() if ":" in heading else ""
                if content:
                    sections[current].append(content)
                continue
            if lowered.startswith("recommended actions") or lowered == "actions":
                current = "actions"
                content = heading.split(":", 1)[1].strip() if ":" in heading else ""
                if content:
                    sections[current].append(content)
                continue
            if lowered.startswith("evidence"):
                current = "evidence"
                content = heading.split(":", 1)[1].strip() if ":" in heading else ""
                if content:
                    sections[current].append(content)
                continue
            if current:
                sections[current].append(line.lstrip("-•*0123456789. ").strip())
        return sections

    def _first_sentence(self, text: str, limit: int = 160) -> str:
        compact = re.sub(r"[*_`]+", "", text)
        compact = re.sub(r"\s+", " ", compact).strip()
        if not compact:
            return ""
        match = re.search(r"^(.+?[。.!?])", compact)
        sentence = match.group(1) if match else compact
        if len(sentence) <= limit:
            return sentence.rstrip()
        cut = sentence[:limit]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        return cut.rstrip(" ,;:") + "..."

    def _collect_bullets(self, items: list[str], limit: int = 3, char_limit: int = 100) -> list[str]:
        bullets: list[str] = []
        heading_fragments = {
            "key signals",
            "global implications",
            "follow-up",
            "recommended actions",
            "关键信号",
            "建议行动",
            "管理动作",
        }
        for item in items:
            text = re.sub(r"[*_`]+", "", item)
            text = re.sub(r"\s+", " ", text).strip(" -•*")
            if not text:
                continue
            if text.rstrip(":：").strip().lower() in heading_fragments or text.endswith((":", "：")):
                continue
            text = re.split(r"[。.!?；;]", text, maxsplit=1)[0].strip()
            if len(text) > char_limit:
                cut = text[:char_limit]
                text = cut.rsplit(" ", 1)[0].rstrip(" ,;:") if " " in cut else cut.rstrip(" ,;:")
                text = re.sub(r"\b(and|or|of|to|for|with|in|on|at|the|a|an)$", "", text, flags=re.I).strip(" ,;:")
                text = text.rstrip(" ,;:") + "..."
            if len(text) < 6:
                continue
            bullets.append(text)
            if len(bullets) >= limit:
                break
        return bullets

    def _render_compact_answer(self, sections: dict[str, list[str]], dashboard: dict, console_context: dict) -> str:
        management_dashboard = dashboard.get("management_dashboard", {})
        early_warning = management_dashboard.get("early_warning", {})
        top_reasons = management_dashboard.get("top_penalty_reasons", [])
        summary_text = self._first_sentence(" ".join(sections["summary"]) or "Recent regulatory signals still point to leasing asset authenticity, disclosure discipline, and related-party oversight.", 220)
        china_items = self._collect_bullets(sections["china"], 2, 200)
        if not china_items:
            china_items = [
                "关注近期处罚是否反映资产真实性、信息披露或关联交易控制缺口。",
                "优先复核融资租赁与商业保理的同类控制点。",
            ]
        elif len(china_items) < 2:
            china_items.append("优先复核融资租赁与商业保理的同类控制点。")
        global_items = self._collect_bullets(sections["global"], 2, 200)
        if not global_items:
            global_items = [
                "This looks more like a recurring China control theme than a one-off case.",
                "Global alignment may be needed if the same weakness appears repeatedly.",
            ]
        elif len(global_items) < 2:
            global_items.append("Global alignment may be needed if the same weakness appears repeatedly.")
        signal_items = self._collect_bullets(sections["signals"], 3, 200)
        if not signal_items:
            reason_signals = [
                f"Primary control theme: {item.get('reason')}"
                for item in top_reasons[:2]
                if item.get("reason")
            ]
            signal_items = [
                *reason_signals,
                "Current window is rule-update heavy, so treat it as a pre-enforcement control signal.",
                f"{console_context.get('context_event_count', 0)} source-backed radar events support the current view.",
            ]
            signal_items = signal_items[:3]
        risk_text = self._first_sentence(
            " ".join(sections["risk"])
            or early_warning.get("summary", "")
            or "The key risk is whether the same control weakness could surface in onboarding, reporting, or affiliate oversight.",
            300,
        )
        action_items = self._collect_bullets(sections["actions"], 3, 240)
        if not action_items:
            action_items = (early_warning.get("management_actions") or [])[:3]
        if not action_items:
            action_items = [
                "Recheck the top control domain against current policies.",
                "Brief China management with one clear decision point.",
                "Tell Global whether the trend suggests broader control adjustment.",
            ]
        evidence_items = self._collect_bullets(sections["evidence"], 3, 320)
        if not evidence_items:
            evidence_items = [
                f"{event.get('published_at', '')[:10]} | {event.get('title', 'Source-backed event')}"
                for event in (early_warning.get("supporting_events") or [])[:3]
            ] or ["Use the latest source-backed events from Event Library."]
        lines = [
            f"Executive Summary: {summary_text}",
            "China Management Brief:",
            *[f"- {item}" for item in china_items],
            "Global Compliance Brief:",
            *[f"- {item}" for item in global_items],
            "Key Signals:",
            *[f"- {item}" for item in signal_items],
            f"Risk to Siemens Financial Leasing: {risk_text}",
            "Recommended Actions:",
            *[f"- {item}" for item in action_items],
            "Evidence:",
            *[f"- {item}" for item in evidence_items],
        ]
        return "\n".join(lines).strip()

    def _fallback_concise_answer(self, dashboard: dict, console_context: dict) -> str:
        primary_reason = "General Conduct and Control Weakness"
        top_reasons = dashboard.get("management_dashboard", {}).get("top_penalty_reasons", [])
        if top_reasons:
            primary_reason = top_reasons[0].get("reason", primary_reason)
        summary = dashboard.get("summary", {})
        return (
            "Executive Summary: Recent signals still point to asset authenticity, disclosure discipline, and related-party oversight.\n"
            "China Management Brief:\n"
            "- Focus on the latest high-signal penalties.\n"
            "- Check whether similar gaps exist in lease and factoring controls.\n"
            "- Escalate only if the issue is repeatable or material.\n"
            "Global Compliance Brief:\n"
            "- This looks like a recurring China control theme rather than an isolated incident.\n"
            "- Global policy or control expectations may need a China-specific refresh.\n"
            "Key Signals:\n"
            f"- {primary_reason}\n"
            f"- {summary.get('major_events', 0)} major events\n"
            f"- {console_context.get('context_event_count', 0)} source-backed radar events\n"
            "Risk to Siemens Financial Leasing: The main risk is whether the same control weakness could appear in onboarding, reporting, or affiliate oversight.\n"
            "Recommended Actions:\n"
            "- Recheck the top control domain against current policies.\n"
            "- Brief China management with one clear decision point.\n"
            "- Tell Global whether the trend suggests a broader control adjustment.\n"
            "Evidence:\n"
            "- Latest source-backed events from Event Library"
        )

    def chat(self, prompt: str, context: str, models: dict, dashboard: dict) -> dict:
        current_name = models["current_model"]
        profile = next(
            (item for item in models["profiles"] if item["name"] == current_name),
            None,
        )
        console_context = self.build_console_context(dashboard, prompt, context)

        output_contract = (
            "Return a concise management-ready answer with exactly these sections: "
            "Executive Summary, China Management Brief, Global Compliance Brief, Key Signals, "
            "Risk to Siemens Financial Leasing, Recommended Actions, Evidence. "
            "Keep China Management Brief in Chinese. Keep Global Compliance Brief in English. "
            "Limit Key Signals to 3 bullets, Recommended Actions to 3 bullets, Evidence to 3 items. "
            "Lead with a judgment, not a digest. Do not restate the full event chronology or source metadata. "
            "Use the strongest control theme, the likely business impact, and the next management decision."
        )

        if (
            profile
            and profile.get("provider") == "openai-compatible"
            and profile.get("api_key")
        ):
            chat_url = self.normalize_openai_base(profile["base_url"]) + "/chat/completions"
            response = requests.post(
                chat_url,
                headers={
                    "Authorization": f"Bearer {profile['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": profile["model_id"],
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are the compliance analysis engine.\n"
                                f"{console_context['business_lens']}\n"
                                f"{output_contract}\n"
                                "Use the supplied regulatory radar context to explain what it means "
                                "for Siemens Financial Leasing. Be concrete, structured, and management-ready."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"{console_context['context_digest']}\n\n"
                                "Emphasize what changed, why it matters, and what should happen next.\n\n"
                                f"Question: {prompt}"
                            ),
                        },
                    ],
                },
                timeout=profile.get("timeout", 30),
            )
            response.raise_for_status()
            payload = response.json()
            raw_answer = payload["choices"][0]["message"]["content"]
            answer = self._normalize_answer(raw_answer, dashboard, console_context)
            return {
                "model": current_name,
                "answer": answer,
                "raw_answer": raw_answer,
                "generated_at": utc_now_iso(),
                "business_lens": console_context["business_lens"],
                "context_event_count": console_context["context_event_count"],
                "context_digest": console_context["context_digest"],
                "agent_file_count": console_context["agent_file_count"],
                "agent_folder": console_context["agent_folder"],
            }

        return {
            "model": current_name,
            "answer": (
                f"[{current_name}] Executive Summary: China enforcement continues to emphasize asset authenticity, disclosure discipline, and related-party oversight.\n"
                "China Management Brief: 1) Focus on the latest high-signal penalties. 2) Check whether similar gaps exist in lease and factoring controls. 3) Escalate only if the issue is repeatable or material.\n"
                "Global Compliance Brief: The pattern looks like a recurring China control theme rather than an isolated incident. Consider whether global policy or control expectations need a China-specific refresh.\n"
                "Key Signals: "
                f"{dashboard['management_dashboard']['top_penalty_reasons'][0]['reason'] if dashboard['management_dashboard']['top_penalty_reasons'] else 'General Conduct and Control Weakness'}; "
                f"{dashboard['summary']['major_events']} major events; "
                f"{console_context['context_event_count']} source-backed radar events.\n"
                "Risk to Siemens Financial Leasing: The main risk is not the headline penalty itself, but whether the same control weakness could appear in onboarding, reporting, or affiliate oversight.\n"
                "Recommended Actions: 1) Recheck the top control domain against current policies. 2) Brief China management with one clear decision point. 3) Tell Global whether the trend suggests a broader control adjustment."
            ),
            "generated_at": utc_now_iso(),
            "business_lens": console_context["business_lens"],
            "context_event_count": console_context["context_event_count"],
            "context_digest": console_context["context_digest"],
            "agent_file_count": console_context["agent_file_count"],
            "agent_folder": console_context["agent_folder"],
        }
