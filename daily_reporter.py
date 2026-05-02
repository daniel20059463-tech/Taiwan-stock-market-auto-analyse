from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from notifier import MAX_TELEGRAM_MESSAGE_LENGTH


@dataclass(slots=True)
class DailyReportDelivery:
    text: str
    used_fallback: bool
    highlight_count: int


class NoopDailyReportLLM:
    """Fallback client that forces template mode when no real LLM is configured."""

    def summarize_trade(self, payload: dict[str, Any]) -> str:
        raise RuntimeError("llm_not_configured")

    def summarize_day(self, payload: dict[str, Any]) -> str:
        raise RuntimeError("llm_not_configured")


class OpenAIDailyReportLLM:
    """Minimal OpenAI Responses API client for end-of-day trade reports."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(5.0, float(timeout_seconds))

    def summarize_trade(self, payload: dict[str, Any]) -> str:
        prompt = (
            "請用 1 到 2 句中文說明這筆交易。重點放在進出場理由、"
            "正反觀點哪一邊最後被市場證明較合理，以及這筆交易最值得記住的教訓。"
            "內容會直接發到 Telegram，請保持精簡。\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )
        return self._responses_text(prompt)

    def summarize_day(self, payload: dict[str, Any]) -> str:
        prompt = (
            "請把以下資料整理成一則中文 Telegram 盤後日報。"
            "內容要包含今日總結、損益、勝率、風控狀態，以及 2 到 3 筆重點交易觀察。"
            "語氣務實、簡潔、可直接閱讀，不要寫成長篇報告。\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )
        return self._responses_text(prompt)

    def _responses_text(self, prompt: str) -> str:
        request_body = {
            "model": self.model,
            "input": prompt,
        }
        request = urllib.request.Request(
            url=f"{self.base_url}/responses",
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(request_body).encode("utf-8"),
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"openai_http_error:{exc.code}:{body}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover
            raise RuntimeError(f"openai_network_error:{exc.reason}") from exc

        text = payload.get("output_text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        output = payload.get("output") or []
        for item in output:
            for content in item.get("content") or []:
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        raise RuntimeError("openai_empty_output")


class DailyReporter:
    def __init__(
        self,
        *,
        chat_id: int,
        telegram_sender: Callable[..., Any],
        llm_client: Any,
        max_length: int = MAX_TELEGRAM_MESSAGE_LENGTH,
        highlight_count: int = 3,
    ) -> None:
        self.chat_id = int(chat_id)
        self.telegram_sender = telegram_sender
        self.llm_client = llm_client
        self.max_length = max_length
        self.highlight_count = highlight_count

    def build_and_send(self, *, day_payload: dict[str, Any]) -> DailyReportDelivery:
        if str(day_payload.get("source", "")).strip() != "runtime_eod":
            raise RuntimeError("daily_report_invalid_source")
        highlights = self.select_highlight_trades(day_payload.get("trades", []))
        highlight_summaries: list[str] = []
        used_fallback = False

        try:
            for trade in highlights:
                highlight_summaries.append(
                    self.llm_client.summarize_trade(self.build_trade_prompt_payload(trade)).strip()
                )
            report_text = self.llm_client.summarize_day(
                self.build_day_prompt_payload(day_payload, highlight_summaries)
            ).strip()
        except Exception:
            used_fallback = True
            report_text = self.build_fallback_report(day_payload, highlights)

        report_text = self._merge_with_highlights(report_text, highlight_summaries, day_payload)
        report_text = self.clamp_telegram_text(report_text)
        self.telegram_sender(chat_id=self.chat_id, text=report_text, parse_mode="")
        return DailyReportDelivery(
            text=report_text,
            used_fallback=used_fallback,
            highlight_count=len(highlights),
        )

    def select_highlight_trades(self, trades: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked = sorted(
            list(trades),
            key=lambda trade: (
                abs(float(trade.get("netPnl", trade.get("pnl", 0.0)) or 0.0)),
                float((trade.get("decisionReport") or {}).get("confidence", 0) or 0),
            ),
            reverse=True,
        )
        return ranked[: self.highlight_count]

    def build_trade_prompt_payload(self, trade: dict[str, Any]) -> dict[str, Any]:
        decision_report = dict(trade.get("decisionReport") or {})
        return {
            "symbol": trade.get("symbol", "--"),
            "action": trade.get("action", "--"),
            "price": float(trade.get("price", 0.0) or 0.0),
            "net_pnl": float(trade.get("netPnl", trade.get("pnl", 0.0)) or 0.0),
            "reason": trade.get("reason", "--"),
            "decision_report": {
                "summary": decision_report.get("summary", ""),
                "finalReason": decision_report.get("finalReason", ""),
                "confidence": decision_report.get("confidence", 0),
                "bullCase": decision_report.get("bullCase", ""),
                "bearCase": decision_report.get("bearCase", ""),
                "riskCase": decision_report.get("riskCase", ""),
                "bullArgument": decision_report.get("bullArgument", ""),
                "bearArgument": decision_report.get("bearArgument", ""),
                "refereeVerdict": decision_report.get("refereeVerdict", ""),
                "debateWinner": decision_report.get("debateWinner", ""),
            },
        }

    def build_day_prompt_payload(
        self,
        day_payload: dict[str, Any],
        highlights: list[str],
    ) -> dict[str, Any]:
        return {
            "date": day_payload.get("date", ""),
            "tradeCount": int(day_payload.get("tradeCount", 0) or 0),
            "winRate": float(day_payload.get("winRate", 0.0) or 0.0),
            "realizedPnl": float(day_payload.get("realizedPnl", 0.0) or 0.0),
            "unrealizedPnl": float(day_payload.get("unrealizedPnl", 0.0) or 0.0),
            "totalPnl": float(day_payload.get("totalPnl", 0.0) or 0.0),
            "riskStatus": dict(day_payload.get("riskStatus") or {}),
            "highlights": list(highlights),
            "newPositions": list(day_payload.get("newPositions") or []),
        }

    def build_fallback_report(
        self,
        day_payload: dict[str, Any],
        highlights: list[dict[str, Any]],
    ) -> str:
        date = day_payload.get("date", "--")
        trade_count = int(day_payload.get("tradeCount", 0) or 0)
        win_rate = float(day_payload.get("winRate", 0.0) or 0.0)
        total_pnl = float(day_payload.get("totalPnl", 0.0) or 0.0)
        risk = dict(day_payload.get("riskStatus") or {})
        risk_label = "正常" if not risk.get("isHalted") and not risk.get("isWeeklyHalted") else "已停用"
        lines = [
            f"**盤後日報｜{date}**",
            "模板摘要",
            "今日總結",
            f"今日總交易數：{trade_count}",
            f"勝率：{win_rate:.1f}%",
            f"總損益：{total_pnl:+,.0f}",
            f"風控狀態：{risk_label}",
        ]
        new_positions = day_payload.get("newPositions") or []
        if new_positions:
            lines.append("今日新倉")
            for pos in new_positions:
                symbol = pos.get("symbol", "--")
                price = float(pos.get("price", 0.0) or 0.0)
                shares = int(pos.get("shares", 0) or 0)
                lots = shares // 1000
                stop = pos.get("stopPrice")
                stop_str = f"，停損 {stop:,.2f}" if stop else ""
                lines.append(f"- {symbol} 買入 {price:,.2f} 元 {lots} 張{stop_str}")
        if highlights:
            lines.append("重點交易")
            for trade in highlights:
                symbol = trade.get("symbol", "--")
                reason = trade.get("reason", "--")
                pnl = float(trade.get("netPnl", trade.get("pnl", 0.0)) or 0.0)
                lines.append(f"- {symbol} {reason}，損益 {pnl:+,.0f}")
        return "\n".join(lines)

    def clamp_telegram_text(self, text: str) -> str:
        if len(text) <= self.max_length:
            return text
        suffix = "\n內容已截斷。"
        room = max(0, self.max_length - len(suffix))
        return text[:room] + suffix

    def _merge_with_highlights(
        self,
        report_text: str,
        highlight_summaries: list[str],
        day_payload: dict[str, Any],
    ) -> str:
        report_text = report_text.strip()
        if not report_text:
            report_text = self.build_fallback_report(day_payload, [])

        lines = [report_text]
        if highlight_summaries:
            lines.extend(["", "重點短評", *[f"- {summary}" for summary in highlight_summaries]])
        merged = "\n".join(lines)
        if "盤後日報" not in merged:
            merged = f"**盤後日報｜{day_payload.get('date', '--')}**\n{merged}"
        return merged


def telegram_sender_from_env(*, bot_token: str, timeout_seconds: float = 10.0) -> Callable[..., None]:
    def _send(*, chat_id: int, text: str, parse_mode: str) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        import time

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                request = urllib.request.Request(
                    url=f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(payload).encode("utf-8"),
                )
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                if not body.get("ok"):
                    raise RuntimeError(f"telegram_api_error:{body.get('description', 'unknown_error')}")
                return
            except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise RuntimeError(f"telegram_send_failed:{exc}") from exc
        if last_error is not None:
            raise RuntimeError(f"telegram_send_failed:{last_error}") from last_error

    return _send


def llm_client_from_env() -> Any:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return NoopDailyReportLLM()
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip() or "https://api.openai.com/v1"
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30") or "30")
    return OpenAIDailyReportLLM(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )


def daily_reporter_from_env() -> DailyReporter | None:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        return None
    return DailyReporter(
        chat_id=int(chat_id),
        telegram_sender=telegram_sender_from_env(bot_token=bot_token),
        llm_client=llm_client_from_env(),
    )
