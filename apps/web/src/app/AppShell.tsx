import { BarChart3, FileStack, FlaskConical, History, LayoutDashboard, Settings2 } from 'lucide-react'
import { Link, NavLink, Outlet } from 'react-router-dom'

import { Button, Select } from '@/components/ui'
import type { AppSession } from '@/lib/types'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/analyses', label: '分析总览', icon: LayoutDashboard },
  { to: '/assets', label: '资料库', icon: FileStack },
  { to: '/methods', label: '分析方法', icon: FlaskConical },
  { to: '/audit', label: '审计记录', icon: History },
  { to: '/settings/session', label: '连接与会话', icon: Settings2 },
]

export function AppShell({
  session,
  workspaceId,
  onWorkspaceChange,
  onSignOut,
}: {
  session: AppSession
  workspaceId: string
  onWorkspaceChange: (workspaceId: string) => void
  onSignOut: () => void
}) {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <div className="mx-auto grid min-h-screen max-w-[1600px] grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="border-r border-[#1d3c35] bg-[#0f2e29] px-5 py-6 text-white">
          <Link to="/analyses" className="block overflow-hidden rounded-[28px] border border-white/10 bg-white/5 shadow-panel backdrop-blur-sm">
            <div className="h-1.5 bg-gradient-to-r from-accent via-[#d7b06d] to-accent" />
            <div className="px-5 py-5">
              <div className="mb-3 inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-white/10 text-white">
                <BarChart3 className="h-5 w-5" />
              </div>
              <div className="text-xs font-semibold uppercase tracking-[0.22em] text-[#d8bd89]">lite-interpreter</div>
              <h1 className="mt-3 text-xl font-semibold text-white">财务与经营分析平台</h1>
              <p className="mt-2 text-sm leading-6 text-white/70">给财务、会计和经营分析团队使用的智能分析工作台。</p>
            </div>
          </Link>

          <div className="mt-6 rounded-[28px] border border-white/10 bg-white/5 px-4 py-4 shadow-subtle backdrop-blur-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-white/50">当前工作区</div>
                <div className="mt-2 text-sm font-semibold text-white">{workspaceId || '未选择'}</div>
              </div>
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-semibold text-white/70">
                {session.role ?? 'visitor'}
              </span>
            </div>
            <Select className="mt-4 border-white/10 bg-white/10 text-white" value={workspaceId} onChange={(event) => onWorkspaceChange(event.target.value)}>
              {session.grants.map((grant) => (
                <option key={grant.workspaceId} value={grant.workspaceId}>
                  {grant.label}
                </option>
              ))}
            </Select>
            <p className="mt-3 text-xs leading-5 text-white/55">切换工作区后，分析列表、资料和方法库会同步切换。</p>
          </div>

          <div className="mt-6">
            <div className="mb-2 px-2 text-xs font-semibold uppercase tracking-[0.16em] text-white/50">主导航</div>
            <nav className="space-y-1">
              {NAV_ITEMS.filter((item) => item.to !== '/audit' || session.uiCapabilities.canViewAudit).map((item) => {
                const Icon = item.icon
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      cn(
                        'group flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-medium transition',
                        isActive
                          ? 'bg-white text-[#0f2e29] shadow-subtle'
                          : 'text-white/68 hover:bg-white/8 hover:text-white',
                      )
                    }
                  >
                    <Icon className="h-4 w-4" />
                    <span>{item.label}</span>
                  </NavLink>
                )
              })}
            </nav>
          </div>

          <div className="mt-6 rounded-[28px] border border-white/10 bg-white/5 px-4 py-4 text-sm shadow-subtle backdrop-blur-sm">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-white/50">工作方式</div>
            <ol className="mt-3 space-y-3 text-sm leading-6 text-white/72">
              <li><span className="font-semibold text-white">1.</span> 明确问题与时间范围</li>
              <li><span className="font-semibold text-white">2.</span> 选择本次分析要引用的资料</li>
              <li><span className="font-semibold text-white">3.</span> 查看结论、证据与结果产物</li>
            </ol>
          </div>

          <div className="mt-6 rounded-[28px] border border-white/10 bg-white/5 px-4 py-4 text-sm shadow-subtle backdrop-blur-sm">
            <div className="font-semibold text-white">当前账号</div>
            <div className="mt-1 text-white/70">{session.subject ?? '未登录'} · {session.role ?? 'visitor'}</div>
            <Button className="mt-4 w-full border-white/10 bg-white text-[#0f2e29] hover:bg-[#f6efe2]" variant="secondary" onClick={onSignOut}>退出当前会话</Button>
          </div>
        </aside>

        <main className="px-4 py-4 sm:px-6 lg:px-8 lg:py-8">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-[24px] border border-border bg-white/75 px-5 py-3 shadow-subtle backdrop-blur-sm">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted">Workspace Focus</div>
              <div className="mt-1 text-sm font-semibold text-ink">围绕当前工作区组织分析、资料、方法和审计记录</div>
            </div>
            <div className="flex flex-wrap gap-2">
              <span className="rounded-full border border-border bg-surface px-3 py-1 text-xs font-semibold text-muted">分析优先</span>
              <span className="rounded-full border border-border bg-surface px-3 py-1 text-xs font-semibold text-muted">证据可复核</span>
              <span className="rounded-full border border-border bg-surface px-3 py-1 text-xs font-semibold text-muted">结果可交付</span>
            </div>
          </div>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
