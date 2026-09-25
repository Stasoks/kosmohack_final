from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TraceQError(Exception):
    code: str
    message: str
    status_code: int = 400


class ForbiddenError(TraceQError):
    def __init__(self, message: str = "Insufficient permission") -> None:
        super().__init__("FORBIDDEN", message, 403)


class NotFoundError(TraceQError):
    def __init__(self, entity: str = "Resource") -> None:
        super().__init__("NOT_FOUND", f"{entity} not found", 404)
