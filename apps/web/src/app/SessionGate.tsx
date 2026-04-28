import { Database, KeyRound } from 'lucide-react'
import { useState } from 'react'

import { Button, FeedbackState, FieldLabel, PageCard, TextInput } from '@/components/ui'

export function SessionGate({
  apiBaseUrl,
  accessToken,
  errorMessage,
  onSubmit,
}: {
  apiBaseUrl: string
  accessToken: string
  errorMessage?: string | null
  onSubmit: (input: { apiBaseUrl: string; accessToken: string }) => void
}) {
  const [nextApiBaseUrl, setNextApiBaseUrl] = useState(apiBaseUrl)
  const [nextAccessToken, setNextAccessToken] = useState(accessToken)

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 py-12">
      <PageCard className="w-full max-w-4xl">
        <div className="grid gap-0 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="relative border-b border-white/10 px-8 py-10 lg:border-b-0 lg:border-r lg:border-white/10">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_15%_0%,rgba(215,176,110,0.18),transparent_30%)]" />
            <div className="relative">
              <div className="text-sm font-semibold uppercase tracking-[0.24em] text-primary">lite-interpreter</div>
              <h1 className="mt-5 text-4xl font-semibold tracking-[-0.04em] text-ink">连接分析平台</h1>
              <p className="mt-4 max-w-xl text-base leading-8 text-muted">
                输入 API 地址和 Bearer Token 后，即可进入当前工作区的业务分析与运行时透明度控制台。
              </p>
              <div className="mt-8 rounded-[28px] border border-primary/20 bg-primary/10 px-5 py-4 text-sm leading-6 text-[#f1dfbd]">
                产品面只读取稳定的 `/api/app/*` 合同，不会直接暴露内部 DAG 合同。
              </div>
              {errorMessage ? (
                <div className="mt-6">
                  <FeedbackState
                    title="进入失败"
                    description={errorMessage}
                    tone="error"
                  />
                </div>
              ) : null}
            </div>
          </div>
          <form
            className="space-y-5 bg-white/5 px-8 py-10"
            onSubmit={(event) => {
              event.preventDefault()
              onSubmit({ apiBaseUrl: nextApiBaseUrl, accessToken: nextAccessToken })
            }}
          >
            <div>
              <FieldLabel htmlFor="session-gate-api-base-url">API 地址</FieldLabel>
              <div className="relative">
                <Database className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <TextInput
                  id="session-gate-api-base-url"
                  className="pl-11"
                  value={nextApiBaseUrl}
                  onChange={(event) => setNextApiBaseUrl(event.target.value)}
                />
              </div>
            </div>
            <div>
              <FieldLabel htmlFor="session-gate-access-token">Bearer Token</FieldLabel>
              <div className="relative">
                <KeyRound className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <TextInput
                  id="session-gate-access-token"
                  className="pl-11"
                  type="password"
                  value={nextAccessToken}
                  onChange={(event) => setNextAccessToken(event.target.value)}
                />
              </div>
            </div>
            <Button className="w-full" type="submit">进入分析平台</Button>
          </form>
        </div>
      </PageCard>
    </div>
  )
}
