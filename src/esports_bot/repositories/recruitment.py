"""Recruitment repository (find-a-team posts + recruit requests)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import RecruitmentPostStatus
from ..models import RecruitmentPost, RecruitmentRequest


class RecruitmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    def add_post(self, post: RecruitmentPost) -> None:
        self._s.add(post)

    async def get_post(self, post_id: int) -> RecruitmentPost | None:
        return await self._s.get(RecruitmentPost, post_id)

    async def open_post_for_user(
        self, event_id: int, user_id: int
    ) -> RecruitmentPost | None:
        res = await self._s.execute(
            select(RecruitmentPost).where(
                RecruitmentPost.event_id == event_id,
                RecruitmentPost.user_id == user_id,
                RecruitmentPost.status == RecruitmentPostStatus.OPEN,
            )
        )
        return res.scalar_one_or_none()

    async def get_request(self, request_id: int) -> RecruitmentRequest | None:
        return await self._s.get(RecruitmentRequest, request_id)

    def add_request(self, request: RecruitmentRequest) -> None:
        self._s.add(request)
