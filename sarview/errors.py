"""Errors surfaced to the local UI."""

from __future__ import annotations


class SarviewError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
