import { QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'

import { AppShell } from '@/app/AppShell'
import { SessionGate } from '@/app/SessionGate'
import { api } from '@/lib/api'
import { queryClient } from '@/lib/query-client'
import type { ApiClientConfig } from '@/lib/api'
import type { AnalysisEvent, AppSession, CreateAnalysisRequest } from '@/lib/types'
import { AnalysesPage } from '@/pages/AnalysesPage'
import { AnalysisDetailPage } from '@/pages/AnalysisDetailPage'
import { AssetsPage } from '@/pages/AssetsPage'
import { AuditPage } from '@/pages/AuditPage'
import { MethodsPage } from '@/pages/MethodsPage'
import { NewAnalysisPage } from '@/pages/NewAnalysisPage'
import { SessionSettingsPage } from '@/pages/SessionSettingsPage'

const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000'
const ANALYSIS_REFRESH_INTERVAL_MS = 4000
const ANALYSIS_LIST_REFRESH_INTERVAL_MS = 10000
const TERMINAL_ANALYSIS_STATUSES = new Set(['success', 'failed', 'waiting_for_human'])

type ViewMode = 'business' | 'runtime'

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : '请求失败，请稍后重试。'
}

function sessionGateErrorMessage(session: AppSession | undefined, sessionError: unknown, accessToken: string) {
  if (!accessToken) {
    return null
  }
  if (sessionError) {
    return errorMessage(sessionError)
  }
  if (session?.authenticated === false) {
    if (session.grants.length) {
      return 'API 已返回工作区，但会话仍被标记为未连接。请重启后端，并确认它已加载最新的本地会话修复。'
    }
    return 'API 已响应，但没有建立可用会话。若你在本地联调，请检查 API_AUTH_REQUIRED、API_AUTH_TOKENS_JSON，或重启后端让本地默认 scope 生效。'
  }
  return null
}

function loadStoredValue(key: string, fallback: string) {
  return window.localStorage.getItem(key) ?? fallback
}

function loadStoredViewMode(): ViewMode {
  return window.localStorage.getItem('lite-interpreter:viewMode') === 'runtime' ? 'runtime' : 'business'
}

function routeViewMode(pathname: string, fallback: ViewMode): ViewMode {
  if (pathname.startsWith('/runtime')) {
    return 'runtime'
  }
  if (pathname.startsWith('/analyses')) {
    return 'business'
  }
  return fallback
}

function resolveWorkbenchPath(targetViewMode: ViewMode, pathname: string): string {
  const runtimeDetailPrefix = '/runtime/analyses/'
  const businessDetailPrefix = '/analyses/'

  if (targetViewMode === 'runtime') {
    if (pathname.startsWith(runtimeDetailPrefix) || pathname === '/runtime') {
      return pathname
    }
    if (pathname.startsWith(businessDetailPrefix) && pathname !== '/analyses/new') {
      return `/runtime/analyses/${pathname.slice(businessDetailPrefix.length)}`
    }
    return '/runtime'
  }

  if (pathname.startsWith(businessDetailPrefix) || pathname === '/analyses') {
    return pathname
  }
  if (pathname.startsWith(runtimeDetailPrefix)) {
    return `/analyses/${pathname.slice(runtimeDetailPrefix.length)}`
  }
  return '/analyses'
}

function isTerminalAnalysisStatus(status: string | null | undefined) {
  return TERMINAL_ANALYSIS_STATUSES.has(String(status || '').trim())
}

function resolveWorkspaceId(session: AppSession | undefined, storedWorkspaceId: string) {
  if (!session) {
    return storedWorkspaceId
  }
  const normalizedStoredWorkspaceId = storedWorkspaceId.trim()
  if (normalizedStoredWorkspaceId && session.grants.some((grant) => grant.workspaceId === normalizedStoredWorkspaceId)) {
    return normalizedStoredWorkspaceId
  }
  return session.currentWorkspaceId ?? session.grants[0]?.workspaceId ?? ''
}

function AppInner() {
  const location = useLocation()
  const navigate = useNavigate()
  const [apiBaseUrl, setApiBaseUrl] = useState(() => loadStoredValue('lite-interpreter:apiBaseUrl', DEFAULT_API_BASE_URL))
  const [accessToken, setAccessToken] = useState(() => loadStoredValue('lite-interpreter:accessToken', ''))
  const [workspaceId, setWorkspaceId] = useState(() => window.localStorage.getItem('lite-interpreter:workspaceId') ?? '')
  const [preferredViewMode, setPreferredViewMode] = useState<ViewMode>(() => loadStoredViewMode())
  const [auditPage, setAuditPage] = useState(1)

  const config = useMemo<ApiClientConfig>(
    () => ({ apiBaseUrl, accessToken, workspaceId: workspaceId || undefined }),
    [apiBaseUrl, accessToken, workspaceId],
  )
  const client = useQueryClient()

  const sessionQuery = useQuery({
    queryKey: ['app-session', config],
    queryFn: () => api.getSession(config),
    retry: false,
    enabled: Boolean(apiBaseUrl && accessToken),
  })

  const session = sessionQuery.data as AppSession | undefined
  const sessionGateMessage = sessionGateErrorMessage(session, sessionQuery.error, accessToken)
  const effectiveWorkspaceId = useMemo(() => resolveWorkspaceId(session, workspaceId), [session, workspaceId])
  const effectiveConfig = useMemo<ApiClientConfig>(
    () => ({ ...config, workspaceId: effectiveWorkspaceId || undefined }),
    [config, effectiveWorkspaceId],
  )
  const shellViewMode = routeViewMode(location.pathname, preferredViewMode)

  useEffect(() => {
    if (effectiveWorkspaceId && effectiveWorkspaceId !== workspaceId) {
      window.localStorage.setItem('lite-interpreter:workspaceId', effectiveWorkspaceId)
      setWorkspaceId(effectiveWorkspaceId)
    }
  }, [effectiveWorkspaceId, workspaceId])

  useEffect(() => {
    setAuditPage(1)
  }, [effectiveWorkspaceId])

  const analysesQuery = useQuery({
    queryKey: ['analyses', effectiveConfig],
    queryFn: () => api.listAnalyses(effectiveConfig),
    enabled: Boolean(session?.authenticated && effectiveWorkspaceId),
    refetchInterval: (query) => {
      const data = query.state.data as { items?: Array<{ status?: string | null }> } | undefined
      const hasActiveItems = (data?.items ?? []).some((item) => !isTerminalAnalysisStatus(item.status))
      return hasActiveItems ? ANALYSIS_LIST_REFRESH_INTERVAL_MS : false
    },
  })

  const assetsQuery = useQuery({
    queryKey: ['assets', effectiveConfig],
    queryFn: () => api.listAssets(effectiveConfig),
    enabled: Boolean(session?.authenticated && effectiveWorkspaceId),
  })

  const methodsQuery = useQuery({
    queryKey: ['methods', effectiveConfig],
    queryFn: () => api.listMethods(effectiveConfig),
    enabled: Boolean(session?.authenticated && effectiveWorkspaceId),
  })

  const auditQuery = useQuery({
    queryKey: ['audit', effectiveConfig, auditPage],
    queryFn: () => api.listAudit(effectiveConfig, { page: auditPage, pageSize: 20 }),
    enabled: Boolean(session?.authenticated && effectiveWorkspaceId && session.uiCapabilities.canViewAudit),
  })

  const createAnalysis = useMutation({
    mutationFn: (input: CreateAnalysisRequest) => api.createAnalysis(effectiveConfig, input),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['analyses'] })
    },
  })

  const uploadAssets = useMutation({
    mutationFn: (input: { files: File[]; assetKind: string }) =>
      api.uploadAssets({ ...effectiveConfig, tenantId: session?.currentTenantId ?? '' }, input),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['assets'] })
    },
  })

  function persistConnection(nextApiBaseUrl: string, nextAccessToken: string) {
    window.localStorage.setItem('lite-interpreter:apiBaseUrl', nextApiBaseUrl)
    window.localStorage.setItem('lite-interpreter:accessToken', nextAccessToken)
    setApiBaseUrl(nextApiBaseUrl)
    setAccessToken(nextAccessToken)
  }

  function persistViewMode(nextViewMode: ViewMode) {
    window.localStorage.setItem('lite-interpreter:viewMode', nextViewMode)
    setPreferredViewMode(nextViewMode)
    navigate(resolveWorkbenchPath(nextViewMode, location.pathname))
  }

  if (!accessToken || sessionQuery.isError || session?.authenticated === false) {
    return (
      <SessionGate
        apiBaseUrl={apiBaseUrl}
        accessToken={accessToken}
        errorMessage={sessionGateMessage}
        onSubmit={({ apiBaseUrl: nextApiBaseUrl, accessToken: nextAccessToken }) => {
          persistConnection(nextApiBaseUrl, nextAccessToken)
          client.invalidateQueries({ queryKey: ['app-session'] })
        }}
      />
    )
  }

  if (!session) {
    return <div className="flex min-h-screen items-center justify-center bg-canvas text-muted">正在加载会话信息…</div>
  }

  return (
    <Routes>
      <Route
        path="/"
        element={
          <AppShell
            session={session}
            workspaceId={effectiveWorkspaceId}
            onWorkspaceChange={(nextWorkspaceId) => {
              window.localStorage.setItem('lite-interpreter:workspaceId', nextWorkspaceId)
              setWorkspaceId(nextWorkspaceId)
              setAuditPage(1)
            }}
            viewMode={shellViewMode}
            onViewModeChange={persistViewMode}
            onSignOut={() => {
              window.localStorage.removeItem('lite-interpreter:accessToken')
              window.localStorage.removeItem('lite-interpreter:workspaceId')
              setAccessToken('')
              setWorkspaceId('')
              setAuditPage(1)
            }}
          />
        }
      >
        <Route index element={<Navigate replace to={preferredViewMode === 'runtime' ? '/runtime' : '/analyses'} />} />
        <Route
          path="analyses"
          element={
            <AnalysesPage
              data={analysesQuery.data}
              assets={assetsQuery.data?.items ?? []}
              isLoading={analysesQuery.isLoading || assetsQuery.isLoading}
              errorMessage={analysesQuery.isError ? errorMessage(analysesQuery.error) : assetsQuery.isError ? errorMessage(assetsQuery.error) : null}
              onRetry={() => {
                void analysesQuery.refetch()
                void assetsQuery.refetch()
              }}
              viewMode="business"
              detailBasePath="/analyses"
              newAnalysisPath="/analyses/new"
              onSubmit={(input) => createAnalysis.mutateAsync(input)}
            />
          }
        />
        <Route
          path="analyses/new"
          element={
            <NewAnalysisPage
              assets={assetsQuery.data?.items ?? []}
              assetsLoading={assetsQuery.isLoading}
              assetsErrorMessage={assetsQuery.isError ? errorMessage(assetsQuery.error) : null}
              onRetryAssets={() => {
                void assetsQuery.refetch()
              }}
              onSubmit={(input) => createAnalysis.mutateAsync(input)}
            />
          }
        />
        <Route
          path="analyses/:analysisId"
          element={<AnalysisDetailRoute config={effectiveConfig} viewMode="business" />}
        />
        <Route
          path="runtime"
          element={
            <AnalysesPage
              data={analysesQuery.data}
              assets={assetsQuery.data?.items ?? []}
              isLoading={analysesQuery.isLoading || assetsQuery.isLoading}
              errorMessage={analysesQuery.isError ? errorMessage(analysesQuery.error) : assetsQuery.isError ? errorMessage(assetsQuery.error) : null}
              onRetry={() => {
                void analysesQuery.refetch()
                void assetsQuery.refetch()
              }}
              viewMode="runtime"
              detailBasePath="/runtime/analyses"
              newAnalysisPath="/analyses/new"
              onSubmit={(input) => createAnalysis.mutateAsync(input)}
            />
          }
        />
        <Route
          path="runtime/analyses/:analysisId"
          element={<AnalysisDetailRoute config={effectiveConfig} viewMode="runtime" />}
        />
        <Route
          path="assets"
          element={
            <AssetsPage
              assets={assetsQuery.data?.items ?? []}
              isLoading={assetsQuery.isLoading}
              errorMessage={assetsQuery.isError ? errorMessage(assetsQuery.error) : null}
              onRetry={() => {
                void assetsQuery.refetch()
              }}
              onUpload={(input) => uploadAssets.mutateAsync(input)}
            />
          }
        />
        <Route
          path="methods"
          element={
            <MethodsPage
              methods={methodsQuery.data?.items ?? []}
              isLoading={methodsQuery.isLoading}
              errorMessage={methodsQuery.isError ? errorMessage(methodsQuery.error) : null}
              onRetry={() => {
                void methodsQuery.refetch()
              }}
            />
          }
        />
        <Route
          path="audit"
          element={
            <AuditPage
              data={auditQuery.data}
              page={auditPage}
              isLoading={auditQuery.isLoading}
              errorMessage={session.uiCapabilities.canViewAudit && auditQuery.isError ? errorMessage(auditQuery.error) : null}
              onRetry={() => {
                void auditQuery.refetch()
              }}
              onPageChange={setAuditPage}
            />
          }
        />
        <Route
          path="settings/session"
          element={
            <SessionSettingsPage
              apiBaseUrl={apiBaseUrl}
              accessToken={accessToken}
              onSave={({ apiBaseUrl: nextApiBaseUrl, accessToken: nextAccessToken }) => {
                persistConnection(nextApiBaseUrl, nextAccessToken)
                client.invalidateQueries()
              }}
            />
          }
        />
      </Route>
    </Routes>
  )
}

function AnalysisDetailRoute({ config, viewMode }: { config: ApiClientConfig; viewMode: ViewMode }) {
  const { analysisId = '' } = useParams<{ analysisId: string }>()
  const [events, setEvents] = useState<AnalysisEvent[]>([])
  const [terminalSyncState, setTerminalSyncState] = useState<'idle' | 'syncing' | 'done'>('idle')
  const lastEventIdRef = useRef<string | null>(null)

  useEffect(() => {
    setEvents([])
    setTerminalSyncState('idle')
    lastEventIdRef.current = null
  }, [analysisId, config.apiBaseUrl, config.accessToken, config.workspaceId])

  const detailQuery = useQuery({
    queryKey: ['analysis-detail', config, analysisId],
    queryFn: () => api.getAnalysis(config, analysisId),
    enabled: Boolean(analysisId),
    refetchInterval: (query) => {
      const status = (query.state.data as { status?: string | null } | undefined)?.status
      if (!status || isTerminalAnalysisStatus(status)) {
        return false
      }
      return ANALYSIS_REFRESH_INTERVAL_MS
    },
  })
  const eventsQuery = useQuery({
    queryKey: ['analysis-events', config, analysisId],
    queryFn: async () => api.getAnalysisEvents(config, analysisId, lastEventIdRef.current),
    enabled: Boolean(analysisId),
    refetchInterval: (query) => {
      if (!query.state.data && !detailQuery.data?.status) {
        return ANALYSIS_REFRESH_INTERVAL_MS
      }
      if (isTerminalAnalysisStatus(detailQuery.data?.status)) {
        return false
      }
      return ANALYSIS_REFRESH_INTERVAL_MS
    },
  })
  const detailStatus = detailQuery.data?.status
  const refetchDetail = detailQuery.refetch
  const refetchEvents = eventsQuery.refetch

  useEffect(() => {
    if (!eventsQuery.data) {
      return
    }
    const incomingEvents = eventsQuery.data.events ?? []
    if (incomingEvents.length) {
      setEvents((current) => {
        const seenIds = new Set(current.map((item) => item.eventId))
        const appended = incomingEvents.filter((item) => !seenIds.has(item.eventId))
        return appended.length ? [...current, ...appended] : current
      })
    }
    if (eventsQuery.data.lastEventId) {
      lastEventIdRef.current = eventsQuery.data.lastEventId
    }
  }, [eventsQuery.data])

  useEffect(() => {
    if (!detailStatus || !isTerminalAnalysisStatus(detailStatus) || terminalSyncState !== 'idle') {
      return
    }
    setTerminalSyncState('syncing')
    void Promise.all([refetchDetail(), refetchEvents()]).finally(() => setTerminalSyncState('done'))
  }, [detailStatus, refetchDetail, refetchEvents, terminalSyncState])

  return (
    <AnalysisDetailPage
      config={config}
      detail={detailQuery.data}
      events={events}
      isLoading={detailQuery.isLoading}
      errorMessage={detailQuery.isError ? errorMessage(detailQuery.error) : eventsQuery.isError ? errorMessage(eventsQuery.error) : null}
      onRetry={() => {
        void detailQuery.refetch()
        void eventsQuery.refetch()
      }}
      isLiveRefreshing={!isTerminalAnalysisStatus(detailQuery.data?.status)}
      viewMode={viewMode}
    />
  )
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppInner />
    </QueryClientProvider>
  )
}
