from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime

from .domain import Consent, Customer, OnboardingChatSession, OtpChallenge
from .onboarding import OtpDeliveryProvider
from .repository import ConflictError, NotFoundError, Repository

TERMS_VERSION = "1.0"
PRIVACY_VERSION = "1.0"
BIOMETRICS_VERSION = "1.0"


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _affirmative(value: str) -> bool:
    return _fold(value) in {"sim", "s", "aceito", "concordo", "ok", "pode"}


def _negative(value: str) -> bool:
    return _fold(value) in {"nao", "n", "cancelar", "sair"}


def is_greeting(value: str) -> bool:
    return _fold(value) in {"oi", "ola", "bom dia", "boa tarde", "boa noite", "inicio"}


def _request_new_code(value: str) -> bool:
    return _fold(value) in {"reenviar", "reenviar codigo", "novo codigo", "nao recebi", "não recebi"}


def _optional_email(value: str) -> str | None | bool:
    folded = _fold(value)
    if folded in {"", "-", "nao tenho", "sem email", "pular", "prefiro nao informar"}:
        return None
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value.strip()):
        return False
    return value.strip().lower()


def _phone(value: str) -> str | None:
    raw = value.strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        candidate = f"+{digits}"
    elif len(digits) == 11:
        candidate = f"+55{digits}"
    else:
        return None
    return candidate if re.fullmatch(r"\+[1-9]\d{7,14}", candidate) else None


def _name(value: str) -> str:
    result = value.strip()
    result = re.sub(
        r"^(meu nome e|meu nome é|sou|aqui e|aqui é)\s+", "", result, flags=re.IGNORECASE
    )
    return result.strip(" .,!?")


def _mask_phone(phone: str) -> str:
    return f"{phone[:3]}*****{phone[-2:]}"


def _prompt(session: OnboardingChatSession) -> str:
    return {
        "NAME": "Para começar, qual é o seu nome?",
        "PHONE": "Qual é o seu celular com DDD? Pode enviar no formato (11) 99999-9999.",
        "EMAIL": "Qual é o seu e-mail? Se preferir não informar, responda 'pular'.",
        "OTP": "Digite o código de 6 números que enviamos para o seu celular.",
        "TERMS": "Você aceita os Termos de Uso? Responda 'sim' para continuar ou 'não' para cancelar.",
        "PRIVACY": "Você aceita o Aviso de Privacidade? Responda 'sim' para continuar ou 'não' para cancelar.",
        "BIOMETRICS": "Você autoriza o uso de biometria facial para liberar o acesso à loja? Responda 'sim' ou 'não'.",
        "BIOMETRIC_HANDOFF": "Sua autorização foi registrada. A próxima etapa é concluir a prova de vida facial em um ambiente seguro.",
        "CANCELLED": "Tudo bem. O cadastro não foi concluído. Quando quiser, envie uma nova mensagem para começar novamente.",
        "EXPIRED": "Esta sessão expirou. Inicie um novo cadastro para continuar.",
    }.get(session.step, "Vamos continuar seu cadastro.")


def _response(
    session: OnboardingChatSession,
    *messages: str,
    completed: bool = False,
    next_action: str | None = None,
    development_code: str | None = None,
) -> dict[str, object]:
    return {
        "session_id": session.session_id,
        "step": session.step,
        "customer_id": session.customer_id,
        "messages": list(messages),
        "completed": completed,
        "next_action": next_action,
        "expires_at": session.expires_at,
        "development_code": development_code,
    }


def _accept_consent(customer: Customer, kind: str, version: str) -> None:
    customer.consents = [item for item in customer.consents if item.kind != kind]
    customer.consents.append(Consent(kind=kind, version=version))
    customer.activate_if_ready()


def advance_onboarding_chat(
    repo: Repository,
    session: OnboardingChatSession,
    message: str,
    *,
    otp_provider: OtpDeliveryProvider,
    otp_ttl_minutes: int = 5,
    check_otp_rate_limit: Callable[[str], None] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    now = now or datetime.now(UTC)
    if session.expires_at <= now:
        session.step = "EXPIRED"
        session.touch()
        repo.save_chat_session(session)
        return _response(session, _prompt(session), next_action="RESTART")

    value = message.strip()
    if session.step == "NAME":
        name = _name(value)
        if len(name) < 2:
            return _response(session, "Não consegui identificar seu nome. Pode me dizer como você se chama?")
        session.name = name[:160]
        session.step = "PHONE"
        session.touch()
        repo.save_chat_session(session)
        return _response(session, f"Prazer, {session.name}! {_prompt(session)}")

    if session.step == "PHONE":
        phone = _phone(value)
        if not phone:
            return _response(
                session,
                "Esse telefone parece inválido. Envie o número com DDD, por exemplo: (11) 99999-9999.",
            )
        session.phone = phone
        session.step = "EMAIL"
        session.touch()
        repo.save_chat_session(session)
        return _response(session, _prompt(session))

    if session.step == "EMAIL":
        email = _optional_email(value)
        if email is False:
            return _response(session, "Esse e-mail parece inválido. Tente novamente ou responda 'pular'.")
        if not session.name or not session.phone:
            session.step = "NAME"
            session.touch()
            repo.save_chat_session(session)
            return _response(session, "Vamos reiniciar seu cadastro. Qual é o seu nome?")
        customer = Customer(name=session.name, phone=session.phone, email=email)
        try:
            repo.add_customer(customer)
        except ConflictError:
            session.step = "CANCELLED"
            session.touch()
            repo.save_chat_session(session)
            return _response(
                session,
                "Esse celular já possui um cadastro. Procure o atendimento da loja para recuperar o acesso.",
                next_action="SUPPORT",
            )
        if check_otp_rate_limit:
            check_otp_rate_limit(customer.customer_id)
        challenge, code = OtpChallenge.issue(customer.customer_id, otp_ttl_minutes)
        repo.add_otp(challenge)
        delivery = otp_provider.send(customer, code)
        repo.audit("CustomerRegistered", customer.customer_id, customer.customer_id, channel="ONBOARDING_CHAT")
        repo.audit(
            "OtpRequested",
            customer.customer_id,
            challenge.challenge_id,
            delivery_reference=delivery.provider_reference,
        )
        session.customer_id = customer.customer_id
        session.challenge_id = challenge.challenge_id
        session.name = session.phone = session.email = None
        session.step = "OTP"
        session.touch()
        repo.save_chat_session(session)
        return _response(
            session,
            f"Cadastro iniciado. Enviamos um código de verificação para {_mask_phone(customer.phone)}.",
            _prompt(session),
            development_code=delivery.development_code,
        )

    if session.step == "OTP":
        if _request_new_code(value):
            if not session.customer_id:
                return _response(session, _prompt(session))
            if check_otp_rate_limit:
                check_otp_rate_limit(session.customer_id)
            customer = repo.get_customer(session.customer_id)
            challenge, code = OtpChallenge.issue(session.customer_id, otp_ttl_minutes)
            repo.add_otp(challenge)
            delivery = otp_provider.send(customer, code)
            session.challenge_id = challenge.challenge_id
            session.touch()
            repo.save_chat_session(session)
            repo.audit(
                "OtpRequested",
                customer.customer_id,
                challenge.challenge_id,
                delivery_reference=delivery.provider_reference,
                resend=True,
            )
            return _response(
                session,
                "Enviamos um novo código de verificação.",
                _prompt(session),
                development_code=delivery.development_code,
            )
        if not session.customer_id or not session.challenge_id or not re.fullmatch(r"\d{6}", value):
            return _response(session, "Digite o código de 6 números enviado para o seu celular.")
        try:
            challenge = repo.get_otp(session.challenge_id)
        except NotFoundError:
            return _response(
                session,
                "Esse código não está mais disponível. Solicite um novo código para continuar.",
                next_action="REQUEST_NEW_OTP",
            )
        if not challenge.verify(value):
            repo.save_otp(challenge)
            return _response(
                session,
                "Código inválido ou expirado. Confira os números e tente novamente.",
                next_action="REQUEST_NEW_OTP" if challenge.attempts >= 5 else None,
            )
        repo.save_otp(challenge)
        customer = repo.get_customer(session.customer_id)
        customer.phone_verified = True
        customer.activate_if_ready()
        repo.save_customer(customer)
        repo.audit("PhoneVerified", customer.customer_id, challenge.challenge_id, channel="ONBOARDING_CHAT")
        session.step = "TERMS"
        session.touch()
        repo.save_chat_session(session)
        return _response(session, "Celular verificado com sucesso!", _prompt(session))

    if session.step in {"TERMS", "PRIVACY", "BIOMETRICS"}:
        if _negative(value):
            session.step = "CANCELLED"
            session.touch()
            repo.save_chat_session(session)
            return _response(
                session,
                "Tudo bem. Sem esse consentimento não é possível concluir o cadastro.",
                next_action="SUPPORT",
            )
        if not _affirmative(value):
            return _response(session, _prompt(session))
        if not session.customer_id:
            session.step = "EXPIRED"
            session.touch()
            repo.save_chat_session(session)
            return _response(session, "Não encontrei o cliente desta conversa. Inicie um novo cadastro.", next_action="RESTART")
        customer = repo.get_customer(session.customer_id)
        accepted_step = session.step
        if accepted_step == "TERMS":
            _accept_consent(customer, "TERMS", TERMS_VERSION)
            session.step = "PRIVACY"
        elif accepted_step == "PRIVACY":
            _accept_consent(customer, "PRIVACY", PRIVACY_VERSION)
            session.step = "BIOMETRICS"
        else:
            _accept_consent(customer, "BIOMETRICS", BIOMETRICS_VERSION)
            session.step = "BIOMETRIC_HANDOFF"
        repo.save_customer(customer)
        repo.audit("ConsentAccepted", customer.customer_id, customer.customer_id, kind=accepted_step)
        session.touch()
        repo.save_chat_session(session)
        return _response(
            session,
            "Consentimento registrado.",
            _prompt(session),
            next_action="BIOMETRIC_ENROLLMENT" if session.step == "BIOMETRIC_HANDOFF" else None,
        )

    return _response(
        session,
        _prompt(session),
        next_action="RESTART" if session.step in {"EXPIRED", "CANCELLED"} else None,
    )
