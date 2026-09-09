"""Handler routers, registered in the order they should match."""

from aiogram import Router

from guarantor.bot.handlers import admin, common, create, deals, join


def build_router() -> Router:
    """Assemble the application router.

    Order matters: admin commands are checked first so an operator command is
    never swallowed by the free-text steps of a deal-creation state.
    """
    router = Router(name="guarantor")
    router.include_router(admin.router)
    router.include_router(common.router)
    router.include_router(deals.router)
    router.include_router(join.router)
    router.include_router(create.router)
    return router


__all__ = ["build_router"]
