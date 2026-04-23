import { QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Navigate, Route, Routes, useParams } from 'react-router-dom'

import { AppShell } from '@/app/AppShell'
import { SessionGate } from '@/app/SessionGate'
import { api } from '@/lib/api'
import { queryClient } from '@/lib/query-client'
import type { ApiClientConfig } from '@/lib/api'
import type { AppSession, CreateAnalysisRequest } from '@/lib/types'
import { AnalysesPage } from '@/pages/AnalysesPage'
import { AnalysisDetailPage } from '@/pages/AnalysisDetailPage'
import { AssetsPage } from '@/pages/AssetsPage'
import { AuditPage } from '@/pages/AuditPage'
import { MethodsPage } from '@/pages/MethodsPage'
import { NewAnalysisPage } from '@/pages/NewAnalysisPage'
import { SessionSettingsPage } from '@/pages/SessionSettingsPage'

const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000'

function loadStoredValue(key: string, fallback: string) {
  return window.localStorage.getItem(key) ?? fallback
}

function AppInner() {
  const [apiBaseUrl, setApiBaseUrl] = useState(() => loadStoredValue('lite-interpreter:apiBaseUrl', DEFAULT_API_BASE_URL))
  const [accessToken, setAccessToken] = useState(() => loadStoredValue('lite-interpreter:accessToken', ''))
  const [workspaceId, setWorkspaceId] = useState(() => window.localStorage.getItem('lite-interpreter:workspaceId') ?? '')

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
  const effectiveWorkspaceId = workspaceId || session?.currentWorkspaceId || ''
  const effectiveConfig = useMemo<ApiClientConfig>(
    () => ({ ...config, workspaceId: effectiveWorkspaceId || undefined }),
    [config, effectiveWorkspaceId],
  )

  const analysesQuery = useQuery({
    queryKey: ['analyses', effectiveConfig],
    queryFn: () => api.listAnalyses(effectiveConfig),
    enabled: Boolean(session?.authenticated && effectiveWorkspaceId),
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
    queryKey: ['audit', effectiveConfig],
    queryFn: () => api.listAudit(effectiveConfig),
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

  function persistConnection(nextApiBaseUrl: string, nextAccessToken: string, nextWorkspaceId?: string | null) {
    window.localStorage.setItem('lite-interpreter:apiBaseUrl', nextApiBaseUrl)
    window.localStorage.setItem('lite-interpreter:accessToken', nextAccessToken)
    if (nextWorkspaceId) {
      window.localStorage.setItem('lite-interpreter:workspaceId', nextWorkspaceId)
    }
    setApiBaseUrl(nextApiBaseUrl)
    setAccessToken(nextAccessToken)
    if (nextWorkspaceId) {
      setWorkspaceId(nextWorkspaceId)
    }
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
            }}
            onSignOut={() => {
              window.localStorage.removeItem('lite-interpreter:accessToken')
              setAccessToken('')
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
        <Route path="audit" element={<AuditPage items={auditQuery.data?.items ?? []} />} />
        <Route
          path="settings/session"
          element={
            <SessionSettingsPage
              apiBaseUrl={apiBaseUrl}
              accessToken={accessToken}
              onSave={({ apiBaseUrl: nextApiBaseUrl, accessToken: nextAccessToken }) => {
                persistConnection(nextApiBaseUrl, nextAccessToken, effectiveWorkspaceId)
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
  const detailQuery = useQuery({
    queryKey: ['analysis-detail', config, analysisId],
    queryFn: () => api.getAnalysis(config, analysisId),
    enabled: Boolean(analysisId),
  })
  const eventsQuery = useQuery({
    queryKey: ['analysis-events', config, analysisId],
    queryFn: async () => api.getAnalysisEvents(config, analysisId),
    refetchInterval: 4000,
    enabled: Boolean(analysisId),
  })

  return <AnalysisDetailPage detail={detailQuery.data} events={eventsQuery.data?.events ?? []} />
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppInner />
    </QueryClientProvider>
  )
}
