import { QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, Route, Routes, useParams } from 'react-router-dom'

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

function loadStoredValue(key: string, fallback: string) {
  return window.localStorage.getItem(key) ?? fallback
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
  const [apiBaseUrl, setApiBaseUrl] = useState(() => loadStoredValue('lite-interpreter:apiBaseUrl', DEFAULT_API_BASE_URL))
  const [accessToken, setAccessToken] = useState(() => loadStoredValue('lite-interpreter:accessToken', ''))
  const [workspaceId, setWorkspaceId] = useState(() => window.localStorage.getItem('lite-interpreter:workspaceId') ?? '')
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
  const effectiveWorkspaceId = useMemo(() => resolveWorkspaceId(session, workspaceId), [session, workspaceId])
  const effectiveConfig = useMemo<ApiClientConfig>(
    () => ({ ...config, workspaceId: effectiveWorkspaceId || undefined }),
    [config, effectiveWorkspaceId],
  )

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

  if (!accessToken || sessionQuery.isError || session?.authenticated === false) {
    return (
      <SessionGate
        apiBaseUrl={apiBaseUrl}
        accessToken={accessToken}
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
        <Route index element={<Navigate replace to="/analyses" />} />
        <Route path="analyses" element={<AnalysesPage data={analysesQuery.data} />} />
        <Route
          path="analyses/new"
          element={<NewAnalysisPage assets={assetsQuery.data?.items ?? []} onSubmit={(input) => createAnalysis.mutateAsync(input)} />}
        />
        <Route
          path="analyses/:analysisId"
          element={<AnalysisDetailRoute config={effectiveConfig} />}
        />
        <Route path="assets" element={<AssetsPage assets={assetsQuery.data?.items ?? []} onUpload={(input) => uploadAssets.mutateAsync(input)} />} />
        <Route path="methods" element={<MethodsPage methods={methodsQuery.data?.items ?? []} />} />
        <Route
          path="audit"
          element={<AuditPage data={auditQuery.data} page={auditPage} onPageChange={setAuditPage} />}
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

function AnalysisDetailRoute({ config }: { config: ApiClientConfig }) {
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
      isLiveRefreshing={!isTerminalAnalysisStatus(detailQuery.data?.status)}
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
