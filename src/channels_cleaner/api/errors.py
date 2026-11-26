"""The API's errors: a class per HTTP status, under it one dataclass per error; its fields go into the body."""

from collections import defaultdict
from dataclasses import asdict, dataclass, fields, is_dataclass
from functools import cache, reduce
from typing import Any, ClassVar, Literal

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, create_model
from starlette.exceptions import HTTPException

from channels_cleaner.telegram import FloodWaitError, GatewayError, NotAuthorizedError


class BaseError(Exception):
    # Upper case: a class attribute named type would shadow the builtin inside the class body
    CODE: ClassVar[int]
    TYPE: ClassVar[str]
    MESSAGE: ClassVar[str]

    def body(self) -> dict[str, Any]:
        values = asdict(self) if is_dataclass(self) else {}
        return {"ok": False, "type": self.TYPE, "message": self.MESSAGE, **jsonable_encoder(values)}

    def response(self) -> JSONResponse:
        return JSONResponse(self.body(), self.CODE)


class ErrorDetail(BaseModel):
    loc: list[str | int]
    msg: str


class BadRequest(BaseError):
    CODE = 400


class Unauthorized(BaseError):
    CODE = 401


class Forbidden(BaseError):
    CODE = 403


class NotFound(BaseError):
    CODE = 404


class Conflict(BaseError):
    CODE = 409


class UnprocessableEntity(BaseError):
    CODE = 422


class TooManyRequests(BaseError):
    CODE = 429


class BadGateway(BaseError):
    CODE = 502


@dataclass
class InvalidRequest(UnprocessableEntity):
    TYPE = "invalid_request"
    MESSAGE = "The request doesn't fit the API"
    details: list[ErrorDetail]


@dataclass
class RouteNotFound(NotFound):
    TYPE = "not_found"
    MESSAGE = "Unknown endpoint"


@dataclass
class MethodNotAllowed(BaseError):
    CODE = 405
    TYPE = "method_not_allowed"
    MESSAGE = "This endpoint doesn't take that method"


@dataclass
class HttpInternalError(BaseError):
    CODE = 500
    TYPE = "internal_error"
    # Nothing about the cause leaves the app: the traceback is in its log
    MESSAGE = "Something went wrong in the app; its log has the details"


@dataclass
class HostNotAllowed(Forbidden):
    TYPE = "host_not_allowed"
    MESSAGE = "Open the app at http://localhost"


@dataclass
class CrossOriginRefused(Forbidden):
    TYPE = "cross_origin_refused"
    MESSAGE = "Requests from other sites are refused"


@dataclass
class NotAuthorized(Unauthorized):
    TYPE = "not_authorized"
    MESSAGE = "Log in to Telegram first"


@dataclass
class InvalidPhone(BadRequest):
    TYPE = "invalid_phone"
    MESSAGE = "That phone number is not valid"
    reason: str


@dataclass
class InvalidCode(BadRequest):
    TYPE = "invalid_code"
    MESSAGE = "That code is not valid"
    reason: str


@dataclass
class InvalidPassword(BadRequest):
    TYPE = "invalid_password"
    MESSAGE = "Wrong password"
    reason: str


@dataclass
class LoginStepUnexpected(Conflict):
    TYPE = "login_step_unexpected"
    MESSAGE = "The login is not at that step"
    reason: str


@dataclass
class ChannelNotFound(NotFound):
    TYPE = "channel_not_found"
    MESSAGE = "Unknown chat"
    channel_id: int


@dataclass
class AccountNotFound(NotFound):
    TYPE = "account_not_found"
    MESSAGE = "No such account to switch to"
    account_id: int


@dataclass
class AvatarNotFound(NotFound):
    TYPE = "avatar_not_found"
    MESSAGE = "The account has no profile photo"
    account_id: int


@dataclass
class PictureNotFound(NotFound):
    TYPE = "picture_not_found"
    MESSAGE = "The chat has no such picture"
    channel_id: int


@dataclass
class ApplyJobRunning(Conflict):
    TYPE = "apply_job_running"
    MESSAGE = "Wait for the running apply job to finish"


@dataclass
class NotChatOwner(Conflict):
    TYPE = "not_chat_owner"
    MESSAGE = "Only the chat's owner can do that"
    channel_id: int


@dataclass
class SuccessorNotAdmin(Conflict):
    TYPE = "successor_not_admin"
    MESSAGE = "The chat can go only to one of its admins"
    channel_id: int
    user_id: int


@dataclass
class ChatTooLargeToDelete(Conflict):
    TYPE = "chat_too_large_to_delete"
    MESSAGE = "Telegram deletes only chats up to 1000 members; leave or hand it over instead"
    channel_id: int
    members_count: int


@dataclass
class NoPublicLink(Conflict):
    TYPE = "no_public_link"
    MESSAGE = "The chat has no public link to free"
    channel_id: int


@dataclass
class FloodWait(TooManyRequests):
    TYPE = "flood_wait"
    MESSAGE = "Telegram asks to wait before the next request"
    retry_after: int


@dataclass
class TelegramError(BadGateway):
    TYPE = "telegram_error"
    MESSAGE = "Telegram refused the request"
    reason: str


COMMON_ERRORS: tuple[type[BaseError], ...] = (HostNotAllowed, CrossOriginRefused, InvalidRequest, HttpInternalError)


@cache
def error_model(error: type[BaseError]) -> type[BaseModel]:
    field_defs: dict[str, Any] = {
        "ok": (Literal[False], False),
        "type": (Literal[error.TYPE], error.TYPE),
        "message": (str, error.MESSAGE),
    }

    # Field types are real types here: this module must not use `from __future__ import annotations`
    if is_dataclass(error):
        for field in fields(error):
            field_defs[field.name] = (field.type, ...)

    name = error.__name__ if error.__name__.endswith("Error") else f"{error.__name__}Error"
    return create_model(name, **field_defs)


def error_responses(*errors: type[BaseError]) -> dict[int | str, dict[str, Any]]:
    grouped: dict[int, list[Any]] = defaultdict(list)

    for error in (*COMMON_ERRORS, *errors):
        grouped[error.CODE].append(error_model(error))

    return {code: {"model": reduce(lambda a, b: a | b, models)} for code, models in grouped.items()}


def translate(exc: Exception) -> BaseError:  # noqa: PLR0911 - one answer per kind of error
    match exc:
        case BaseError():
            return exc
        # FloodWaitError and NotAuthorizedError are GatewayErrors too: the narrower ones first
        case FloodWaitError():
            return FloodWait(retry_after=exc.seconds)
        case NotAuthorizedError():
            return NotAuthorized()
        case GatewayError():
            return TelegramError(reason=str(exc) or type(exc).__name__)
        case RequestValidationError():
            return InvalidRequest(details=[ErrorDetail(loc=list(e["loc"]), msg=e["msg"]) for e in exc.errors()])
        case HTTPException(status_code=405):
            return MethodNotAllowed()
        case HTTPException(status_code=404):
            return RouteNotFound()
        case _:
            # Starlette logs the traceback itself once this answer is out
            return HttpInternalError()


async def handle(_: Request, exc: Exception) -> JSONResponse:
    return translate(exc).response()


def install(app: FastAPI) -> None:
    for error in (BaseError, GatewayError, RequestValidationError, HTTPException, Exception):
        app.add_exception_handler(error, handle)
