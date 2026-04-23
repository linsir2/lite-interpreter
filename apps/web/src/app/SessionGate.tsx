import { Database, KeyRound } from 'lucide-react'
import { useState } from 'react'

import { Button, FieldLabel, PageCard, TextInput } from '@/components/ui'

export function SessionGate({
  apiBaseUrl,
  accessToken,
  onSubmit,
}: {
  apiBaseUrl: string
  accessToken: string
  onSubmit: (input: { apiBaseUrl: string; accessToken: string }) => void
}) {
  const [nextApiBaseUrl, setNextApiBaseUrl] = useState(apiBaseUrl)
  const [nextAccessToken, setNextAccessToken] = useState(accessToken)

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 py-12">
      <PageCard className="w-full max-w-3xl overflow-hidden">
        <div className="grid gap-0 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="border-b border-border bg-white px-8 py-10 lg:border-b-0 lg:border-r">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] text-accent">lite-interpreter</div>
            <h1 className="mt-4 text-4xl font-semibold tracking-tight text-ink">连接分析平台</h1>
            <p className="mt-4 max-w-xl text-base leading-7 text-muted">
              输入 API 地址和 Bearer Token 后，即可进入当前工作区的分析平台。
            </p>
          </div>
          <form
            className="space-y-5 bg-surface-2 px-8 py-10"
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
