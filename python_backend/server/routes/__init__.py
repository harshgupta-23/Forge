"""
Routes package.
"""
from server.routes.ws import ws_router
from server.routes.rest import rest_router

__all__ = ["ws_router", "rest_router"]

