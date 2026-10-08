"""Bounded stage → assistant → tools → assistant cycle inspired by SalesGPT and LangGraph."""

from datetime_utils import utc_now
import json
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from pydantic import ValidationError

from ..schemas import AIChatOut
from .stages import analyze_stage, system_prompt
from .state import public_pending, trim_history
from .tools import ARG_MODELS, TOOL_SCHEMAS
from .policy import policy_for

MAX_TOOL_ROUNDS = 6


def response(conversation, reply: str, **kwargs):
    return AIChatOut(reply=reply, conversation_id=conversation.id, stage=conversation.stage,
                     mode=conversation.mode, pending_action=public_pending(conversation), **kwargs)


def handoff(conversation, reason: str):
    conversation.mode = "human"
    conversation.stage = "handoff"
    conversation.handoff_reason = reason
    conversation.action = None
    conversation.action_id = None


async def chat(provider, tools, conversation, message: str):
    history = trim_history([*conversation.messages, {"role": "user", "content": message}])
    if conversation.mode == "human":
        reply = "Диалог передан оператору. Ваше сообщение сохранено для него."
        history.append({"role": "assistant", "content": reply})
        conversation.messages = history
        return response(conversation, reply)
    policy = policy_for(tools.business)
    if not policy.allows("create_booking") and (conversation.action or {}).get("status") == "pending":
        conversation.action, conversation.action_id = None, None
    if not policy.enabled:
        handoff(conversation, "ИИ отключён настройками компании")
        reply = "ИИ-консультант отключён. Передал сообщение оператору."
        conversation.messages = [*history, {"role": "assistant", "content": reply}]
        return response(conversation, reply)
    conversation.stage, conversation.facts = await analyze_stage(provider, conversation, history)
    prepared = None
    for _ in range(MAX_TOOL_ROUNDS):
        result = await provider.complete([
            {"role": "system", "content": system_prompt(tools.business, conversation)}, *history],
            [schema for schema in TOOL_SCHEMAS if policy.allows(schema["function"]["name"])])
        history.append(result)
        calls = result.get("tool_calls") or []
        if not calls:
            reply = result["content"] or "Уточните, пожалуйста, какую услугу вы ищете."
            history[-1]["content"] = reply
            conversation.messages = history
            return response(conversation, reply)
        for call in calls:
            name = call["function"]["name"]
            try:
                if name not in ARG_MODELS:
                    raise ValueError("Unknown tool")
                args = ARG_MODELS[name].model_validate_json(call["function"]["arguments"])
                await tools.require_tool(name)
                if conversation.mode == "human":
                    output = {"error": "Диалог уже передан оператору; инструменты ИИ остановлены"}
                elif name == "create_booking":
                    if prepared is not None:
                        output = {"error": "Подтверждается только одна запись за сообщение"}
                    else:
                        prepared = await tools.prepare_booking(args)
                        conversation.action_id = str(uuid.uuid4())
                        conversation.action = {**prepared, "status": "pending",
                            "expires_at": (utc_now() + timedelta(minutes=20)).isoformat()}
                        conversation.stage = "closing"
                        output = {"status": "awaiting_confirmation", "description": prepared["description"],
                                  "instruction": "Запись ещё не создана. Клиент должен нажать кнопку подтверждения."}
                elif name == "handoff_to_human":
                    handoff(conversation, args.reason)
                    output = {"status": "queued_for_human", "phone": tools.business.phone,
                              "instruction": "Диалог сохранён в очереди оператора. Не обещай время ответа."}
                else:
                    output = await tools.execute_read(name, args)
            except ValidationError:
                # Do not echo invalid arguments (may contain contact details or injection text).
                output = {"error": "Неверные параметры инструмента. Используй объявленную схему."}
            except HTTPException as exc:
                output = {"error": str(exc.detail)}
            except (ValueError, TypeError, KeyError):
                output = {"error": "Неизвестный инструмент или неверные параметры"}
            history.append({"role": "tool", "tool_call_id": call["id"],
                            "content": json.dumps(output, ensure_ascii=False)})
        if conversation.mode == "human":
            reply = "Передал диалог оператору."
            if tools.business.phone:
                reply += f" Можно также связаться с компанией: {tools.business.phone}."
            history.append({"role": "assistant", "content": reply})
            conversation.messages = history
            return response(conversation, reply)
        if prepared is not None:
            # The confirmation copy comes from the DB, not another model call that
            # could claim a successful booking or alter the price in its wording.
            reply = "Проверьте детали и подтвердите запись в карточке ниже."
            history.append({"role": "assistant", "content": reply})
            conversation.messages = history
            return response(conversation, reply)
    reply = "Не удалось завершить подбор. Уточните услугу или обратитесь к оператору."
    history.append({"role": "assistant", "content": reply})
    conversation.messages = history
    return response(conversation, reply)
