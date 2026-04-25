import { Database, KeyRound } from 'lucide-react'

import { Button, FieldLabel, PageCard, SectionHeader, TextInput } from '@/components/ui'

export function SessionSettingsPage({
  apiBaseUrl,
  accessToken,
  onSave,
}: {
  apiBaseUrl: string
  accessToken: string
  onSave: (input: { apiBaseUrl: string; accessToken: string }) => void
}) {
  return (
    <PageCard>
      <SectionHeader title="连接与会话" level="h1" description="管理 API 地址和 Bearer Token。切换后会重新拉取当前会话信息。" />
      <div className="grid gap-4 border-b border-white/10 px-6 py-5 lg:grid-cols-[1.1fr_0.9fr] sm:px-7">
        <div className="rounded-[28px] border border-primary/20 bg-primary/10 px-5 py-5 text-[#f1dfbd]">
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">连接说明</div>
          <div className="mt-3 space-y-2 text-sm leading-6">
            <p>这里只处理环境连接和令牌，不影响当前工作区的业务数据。</p>
            <p>切换后会重新拉取会话、分析列表、资料库和方法库。</p>
          </div>
        </div>
        <div className="rounded-[28px] border border-white/10 bg-white/5 px-5 py-5 text-sm text-muted">
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted">连接建议</div>
          <ul className="mt-3 space-y-2 leading-6">
            <li>• 日常开发优先使用本地 API 地址。</li>
            <li>• Bearer Token 建议按 workspace 权限发放。</li>
            <li>• 变更连接后先确认会话和工作区是否正确。</li>
          </ul>
        </div>
      </div>
      <form
        className="grid gap-6 px-6 py-6 lg:grid-cols-2 sm:px-7"
        onSubmit={(event) => {
          event.preventDefault()
          const form = new FormData(event.currentTarget)
          onSave({
            apiBaseUrl: String(form.get('apiBaseUrl') || ''),
            accessToken: String(form.get('accessToken') || ''),
          })
        }}
      >
        <div>
          <FieldLabel htmlFor="session-settings-api-base-url">API 地址</FieldLabel>
          <div className="relative">
            <Database className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <TextInput id="session-settings-api-base-url" className="pl-11" defaultValue={apiBaseUrl} name="apiBaseUrl" />
          </div>
        </div>
        <div>
          <FieldLabel htmlFor="session-settings-access-token">Bearer Token</FieldLabel>
          <div className="relative">
            <KeyRound className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <TextInput id="session-settings-access-token" className="pl-11" defaultValue={accessToken} name="accessToken" type="password" />
          </div>
        </div>
        <div className="lg:col-span-2">
          <Button type="submit">保存连接配置</Button>
        </div>
      </form>
    </PageCard>
  )
}
