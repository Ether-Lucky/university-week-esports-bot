"""Recruitment repository (find-a-team posts + recruit requests)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RecruitmentPost, RecruitmentRequest


class RecruitmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    def add_post(self, post: RecruitmentPost) -> None:
        self._s.add(post)

    async def get_request(self, request_id: int) -> RecruitmentRequest | None:
        return await self._s.get(RecruitmentRequest, request_id)

    def add_request(self, request: RecruitmentRequest) -> None:
        self._s.add(request)
