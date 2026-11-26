import socket

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from channels_cleaner.api import errors, models, utils
from channels_cleaner.api.dependencies import ComputerOnlyDep, ContextDep
from channels_cleaner.api.sse import sse_response
from channels_cleaner.services import COOKIE, COOKIE_MAX_AGE, NETWORK_TOPIC

# Managed on the computer only: a phone that could pair others or list them would be a way in for anyone it lets in
router = APIRouter(prefix="/network", tags=["network"], dependencies=[ComputerOnlyDep])
#: what a phone asks while pairing; the guard lets these through without a cookie
pairing_router = APIRouter(prefix="/pairing", tags=["network"])

COMPUTER = (errors.ComputerOnly,)
PAIRING = (*COMPUTER, errors.PairingNotFound)


def state(ctx: ContextDep) -> models.NetworkResponse:
    return models.NetworkResponse.model_validate(ctx.network.snapshot())


@router.get("", responses=errors.error_responses(*COMPUTER))
async def get_network(ctx: ContextDep) -> models.NetworkResponse:
    return state(ctx)


@router.get(
    "/events", response_class=StreamingResponse, responses={**errors.error_responses(*COMPUTER), **utils.EVENT_STREAM}
)
async def get_network_events(request: Request, ctx: ContextDep) -> StreamingResponse:
    return sse_response(request, ctx.bus, NETWORK_TOPIC, ctx.network.snapshot)


@router.put("", responses=errors.error_responses(*COMPUTER, errors.NetworkUnavailable))
async def put_network(body: models.NetworkRequest, ctx: ContextDep) -> models.NetworkResponse:
    """Starts or stops listening in the local network; turned off, every device is out until it is on again."""
    if body.enabled:
        await ctx.network.enable()

    else:
        await ctx.network.disable()

    return state(ctx)


@router.post("/pairing", responses=errors.error_responses(*COMPUTER, errors.NetworkAccessOff))
async def post_pairing(ctx: ContextDep) -> models.NetworkResponse:
    """A new QR link and code, valid for 2 minutes; the one before stops working."""
    ctx.network.start_pairing()
    return state(ctx)


@router.delete("/pairing", responses=errors.error_responses(*COMPUTER))
async def delete_pairing(ctx: ContextDep) -> models.NetworkResponse:
    ctx.network.cancel_pairing()
    return state(ctx)


@router.post("/pairing/approve", responses=errors.error_responses(*PAIRING))
async def post_approve_pairing(ctx: ContextDep) -> models.NetworkResponse:
    await ctx.network.approve()
    return state(ctx)


@router.post("/pairing/reject", responses=errors.error_responses(*PAIRING))
async def post_reject_pairing(ctx: ContextDep) -> models.NetworkResponse:
    ctx.network.reject()
    return state(ctx)


@router.patch("/devices/{device_id}", responses=errors.error_responses(*COMPUTER, errors.DeviceNotFound))
async def patch_device(device_id: int, body: models.DeviceRequest, ctx: ContextDep) -> models.NetworkResponse:
    await ctx.network.rename(device_id, body.name)
    return state(ctx)


@router.delete("/devices/{device_id}", responses=errors.error_responses(*COMPUTER, errors.DeviceNotFound))
async def delete_device(device_id: int, ctx: ContextDep) -> models.NetworkResponse:
    """Disconnects the device at once: its cookie stops working, its open streams close."""
    await ctx.network.forget(device_id)
    return state(ctx)


@pairing_router.post("/claim", responses=errors.error_responses(errors.PairingNotFound, errors.PairingTaken))
async def post_claim_pairing(
    body: models.PairingClaimRequest, request: Request, response: Response, ctx: ContextDep
) -> models.PairingResponse:
    """The phone opened the QR link: it gets its cookie, which works once the user approves it on the computer."""
    client = request.client
    token, code = ctx.network.claim(body.token, request.headers.get("user-agent", ""), client.host if client else None)
    # Plain http in the home network: no Secure flag. Strict: no other site gets the browser to send it
    response.set_cookie(COOKIE, token, max_age=COOKIE_MAX_AGE, httponly=True, samesite="strict")
    return models.PairingResponse(status="waiting", code=code, computer=socket.gethostname())


@pairing_router.get("", responses=errors.error_responses())
async def get_pairing(request: Request, ctx: ContextDep) -> models.PairingResponse:
    """What the phone's pairing screen polls: still waiting, or let in. Turned away: 401 device_not_paired."""
    token = request.cookies.get(COOKIE)

    if ctx.network.device(token) is not None:
        return models.PairingResponse(status="paired", code=None, computer=socket.gethostname())

    if pairing := ctx.network.waiting(token):
        return models.PairingResponse(status="waiting", code=pairing.code, computer=socket.gethostname())

    raise errors.DeviceNotPaired
