"""App-facing API schemas for the real web frontend."""

from __future__ import annotations

from math import ceil
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator


class AppErrorBody(BaseModel):
    code: StrictStr
    message: StrictStr
    details: dict[str, Any] | None = None


class WorkspaceGrantResponse(BaseModel):
    tenantId: StrictStr
    workspaceId: StrictStr
    label: StrictStr


class AppSessionResponse(BaseModel):
    authenticated: bool
    subject: StrictStr | None = None
    role: StrictStr | None = None
    grants: list[WorkspaceGrantResponse] = Field(default_factory=list)
    currentWorkspaceId: StrictStr | None = None
    currentTenantId: StrictStr | None = None
    uiCapabilities: dict[str, bool] = Field(default_factory=dict)


class PaginationMeta(BaseModel):
    page: int = 1
    pageSize: int = 20
    totalItems: int = 0
    totalPages: int = 0

    @classmethod
    def build(cls, *, page: int, page_size: int, total_items: int) -> PaginationMeta:
        total_pages = ceil(total_items / page_size) if page_size else 0
        return cls(page=page, pageSize=page_size, totalItems=total_items, totalPages=total_pages)


class AnalysisListItem(BaseModel):
    analysisId: StrictStr
    title: StrictStr
    question: StrictStr
    status: StrictStr
    statusLabel: StrictStr
    createdAt: StrictStr
    updatedAt: StrictStr
    summary: StrictStr = ""
    hasOutputs: bool = False
    hasWarnings: bool = False


class AnalysisListResponse(BaseModel):
    items: list[AnalysisListItem] = Field(default_factory=list)
    pagination: PaginationMeta
    currentWorkspaceId: StrictStr


class CreateAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: StrictStr
    assetIds: list[StrictStr] = Field(default_factory=list)
    analysisModePreset: StrictStr | None = None
    workspaceId: StrictStr | None = None

    @model_validator(mode="after")
    def _normalize(self) -> CreateAnalysisRequest:
        self.question = self.question.strip()
        if not self.question:
            raise ValueError("question must not be empty")
        normalized_ids: list[str] = []
        for asset_id in self.assetIds:
            stripped = asset_id.strip()
            if not stripped:
                raise ValueError("assetIds must not contain empty values")
            normalized_ids.append(stripped)
        self.assetIds = normalized_ids
        if self.analysisModePreset is not None:
            self.analysisModePreset = self.analysisModePreset.strip() or None
        if self.workspaceId is not None:
            self.workspaceId = self.workspaceId.strip() or None
        return self


class CreateAnalysisResponse(BaseModel):
    analysisId: StrictStr
    status: StrictStr
    statusLabel: StrictStr


class AnalysisEvidenceItem(BaseModel):
    id: StrictStr
    label: StrictStr


class AnalysisOutputItem(BaseModel):
    id: StrictStr
    title: StrictStr
    type: StrictStr
    summary: StrictStr = ""
    downloadUrl: StrictStr | None = None
    previewKind: StrictStr = "none"


class AnalysisProgressSummary(BaseModel):
    currentStatus: StrictStr
    statusLabel: StrictStr
    currentStep: StrictStr
    activitySummary: StrictStr
    executionCount: int = 0
    updatedAt: StrictStr


class AnalysisDetailResponse(BaseModel):
    analysisId: StrictStr
    title: StrictStr
    question: StrictStr
    status: StrictStr
    statusLabel: StrictStr
    createdAt: StrictStr
    updatedAt: StrictStr
    summary: StrictStr
    keyFindings: list[StrictStr] = Field(default_factory=list)
    evidence: list[AnalysisEvidenceItem] = Field(default_factory=list)
    outputs: list[AnalysisOutputItem] = Field(default_factory=list)
    warnings: list[StrictStr] = Field(default_factory=list)
    nextAction: StrictStr = ""
    progress: AnalysisProgressSummary
    isDebugAvailable: bool = False


class AnalysisEventItem(BaseModel):
    eventId: StrictStr
    kind: StrictStr
    timestamp: StrictStr
    title: StrictStr
    message: StrictStr = ""
    status: StrictStr | None = None


class AnalysisEventsResponse(BaseModel):
    analysisId: StrictStr
    lastEventId: StrictStr | None = None
    events: list[AnalysisEventItem] = Field(default_factory=list)


class AssetListItem(BaseModel):
    assetId: StrictStr
    name: StrictStr
    kind: StrictStr
    status: StrictStr
    readinessLabel: StrictStr
    filePath: StrictStr | None = None
    schemaReady: bool = False


class AssetListResponse(BaseModel):
    items: list[AssetListItem] = Field(default_factory=list)
    pagination: PaginationMeta
    currentWorkspaceId: StrictStr


class AssetUploadItem(BaseModel):
    assetId: StrictStr
    name: StrictStr
    kind: StrictStr
    status: StrictStr


class AssetUploadResponse(BaseModel):
    uploaded: list[AssetUploadItem] = Field(default_factory=list)


class MethodCard(BaseModel):
    methodId: StrictStr
    name: StrictStr
    description: StrictStr
    requiredCapabilities: list[StrictStr] = Field(default_factory=list)
    usageCount: int = 0
    promotionStatus: StrictStr = "available"


class MethodListResponse(BaseModel):
    items: list[MethodCard] = Field(default_factory=list)
    currentWorkspaceId: StrictStr


class AuditListItem(BaseModel):
    auditId: StrictStr
    action: StrictStr
    outcome: StrictStr
    subject: StrictStr
    role: StrictStr
    resourceType: StrictStr
    recordedAt: StrictStr
    taskId: StrictStr | None = None
    executionId: StrictStr | None = None


class AuditListResponse(BaseModel):
    items: list[AuditListItem] = Field(default_factory=list)
    pagination: PaginationMeta
    currentWorkspaceId: StrictStr


class AppAuditQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: StrictInt = 1
    pageSize: StrictInt = 20
    subject: StrictStr | None = None
    role: StrictStr | None = None
    action: StrictStr | None = None
    outcome: StrictStr | None = None
    taskId: StrictStr | None = None
    executionId: StrictStr | None = None

    @model_validator(mode="after")
    def _normalize(self) -> AppAuditQuery:
        self.page = max(1, int(self.page))
        self.pageSize = max(1, min(100, int(self.pageSize)))
        for field_name in ("subject", "role", "action", "outcome", "taskId", "executionId"):
            value = getattr(self, field_name)
            if value is not None:
                setattr(self, field_name, value.strip() or None)
        return self
