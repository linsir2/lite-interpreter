import { BarChart3, ChevronDown, FileStack, FlaskConical, History, Home, LayoutDashboard, Search, Settings2, Sparkles } from 'lucide-react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'

import { Button, Select, StatusPill, focusRing } from '@/components/ui'
import type { AppSession } from '@/lib/types'
import { cn } from '@/lib/utils'

type ViewMode = 'business' | 'runtime'

const NAV_ITEMS = [
  { to: '/analyses', label: '业务工作台', icon: LayoutDashboard },
  { to: '/assets', label: '资料库', icon: FileStack },
  { to: '/methods', label: '方法库', icon: FlaskConical },
  { to: '/audit', label: '治理与审计', icon: History },
  { to: '/settings/session', label: '连接与会话', icon: Settings2 },
]

export function AppShell({
  session,
  workspaceId,
  onWorkspaceChange,
  onSignOut,
  viewMode,
  onViewModeChange,
}: {
  session: AppSession
  workspaceId: string
  onWorkspaceChange: (workspaceId: string) => void
  onSignOut: () => void
  viewMode: ViewMode
  onViewModeChange: (viewMode: ViewMode) => void
}) {
  const location = useLocation()
  const currentNav = NAV_ITEMS.find((item) => location.pathname === item.to || location.pathname.startsWith(`${item.to}/`)) ?? NAV_ITEMS[0]
  const visibleNavItems = NAV_ITEMS.filter((item) => item.to !== '/audit' || session.uiCapabilities.canViewAudit)
  const workspaceLabel = session.grants.find((grant) => grant.workspaceId === workspaceId)?.label ?? session.grants[0]?.label ?? '未选择工作区'

  return (
    <div className="min-h-screen overflow-x-hidden bg-canvas text-ink">
      <a
        className="sr-only fixed left-4 top-4 z-50 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-[#0a0d10] focus:not-sr-only"
        href="#main-content"
      >
        跳到主内容
      </a>
      <div className="grid min-h-screen min-w-0 lg:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="flex min-w-0 flex-col border-b border-white/10 bg-[rgba(5,6,8,0.96)] backdrop-blur-xl lg:h-screen lg:border-b-0 lg:border-r">
          <div className="border-b border-white/10 px-4 py-3 sm:px-6 sm:py-4 lg:py-6">
            <Link to="/analyses" className={cn('flex items-center gap-3 rounded-2xl sm:gap-4', focusRing)}>
              <div className="flex h-10 w-10 items-center justify-center rounded-[18px] sm:h-12 sm:w-12 sm:rounded-2xl border border-primary/25 bg-primary/10 text-primary shadow-[0_0_0_1px_rgba(255,255,255,0.04)]">
                <BarChart3 className="h-5 w-5" />
              </div>
              <div className="hidden min-w-0 sm:block">
                <div className="text-[0.68rem] font-semibold uppercase tracking-[0.28em] text-[#d7b06e]">lite-interpreter</div>
                <div className="mt-1 text-base font-semibold text-ink sm:text-lg">可复核的 AI 财务分析</div>
                <div className="mt-1 hidden text-xs leading-5 text-muted sm:block">业务与运行时的统一分析指挥中心</div>
              </div>
            </Link>
          </div>

          <div className="hidden border-b border-white/10 px-5 py-5 lg:block">
            <div className="rounded-[26px] border border-white/10 bg-white/5 p-4 shadow-subtle">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted">当前工作区</div>
                  <div className="mt-2 text-sm font-semibold text-ink">{workspaceLabel}</div>
                </div>
                <StatusPill tone="success">已连接</StatusPill>
              </div>
              <div className="mt-2 text-xs text-muted">{workspaceId || '尚未选择工作区'}</div>
              <Select className="mt-4" value={workspaceId} onChange={(event) => onWorkspaceChange(event.target.value)}>
                {session.grants.map((grant) => (
                  <option key={grant.workspaceId} value={grant.workspaceId}>
                    {grant.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="hidden px-3 py-2 sm:px-4 sm:py-3 lg:flex lg:flex-1 lg:flex-col lg:overflow-y-auto lg:px-4 lg:py-5">
            <div className="hidden px-2 text-[0.68rem] font-semibold uppercase tracking-[0.24em] text-muted lg:block">主导航</div>
            <nav className="mt-0 flex max-w-full gap-1.5 overflow-x-auto pb-1 lg:mt-3 lg:block lg:space-y-2 lg:overflow-visible lg:pb-0">
              {visibleNavItems.map((item) => {
                const Icon = item.icon
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      cn(
                        'group flex min-h-11 shrink-0 items-center gap-2.5 rounded-2xl border px-3 py-2 text-sm font-medium transition sm:gap-3 sm:px-4 sm:py-3',
                        focusRing,
                        isActive
                          ? 'border-primary/25 bg-primary/10 text-ink shadow-[0_0_0_1px_rgba(215,176,110,0.08)]'
                          : 'border-transparent text-muted hover:border-white/10 hover:bg-white/5 hover:text-ink',
                      )
                    }
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span>{item.label}</span>
                  </NavLink>
                )
              })}
            </nav>

            <div className="mt-5 hidden rounded-[26px] border border-white/10 bg-white/5 px-4 py-4 shadow-subtle lg:block">
              <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted">工作方式</div>
              <ol className="mt-3 space-y-2 text-sm leading-6 text-muted">
                <li>1. 提出可复核问题</li>
                <li>2. 选择本次引用资料</li>
                <li>3. 查看结论、产物与透明度</li>
              </ol>
              <div className="mt-4 rounded-2xl border border-white/10 bg-black/20 px-3 py-3 text-xs leading-5 text-muted">
                当前视图：<span className="text-ink">{viewMode === 'business' ? '业务视图' : '运行时视图'}</span>
              </div>
            </div>
          </div>

          <div className="hidden border-t border-white/10 px-5 py-5 lg:block">
            <div className="rounded-[26px] border border-white/10 bg-white/5 px-4 py-4 shadow-subtle">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-ink">{session.subject ?? '未登录'}</div>
                  <div className="mt-1 text-xs text-muted">{session.role ?? 'visitor'} · {viewMode === 'business' ? '业务视图' : '运行时视图'}</div>
                </div>
                <ChevronDown className="mt-0.5 h-4 w-4 text-muted" />
              </div>
              <Button className="mt-4 w-full" variant="secondary" onClick={onSignOut} type="button">
                退出当前会话
              </Button>
            </div>
          </div>
        </aside>

        <div className="flex min-w-0 flex-col">
          <header className="sticky top-0 z-20 border-b border-white/10 bg-[rgba(6,7,8,0.76)] backdrop-blur-xl">
            <div className="mx-auto flex max-w-[1720px] flex-wrap items-center gap-3 px-4 py-3 lg:gap-4 lg:px-8 lg:py-4">
              <div className="hidden min-w-0 sm:block">
                <div className="flex items-center gap-2 text-[0.68rem] font-semibold uppercase tracking-[0.24em] text-muted">
                  <Home className="h-3.5 w-3.5" />
                  {currentNav.label}
                </div>
                <div className="mt-1 truncate text-sm text-muted">{workspaceLabel} · {session.role ?? 'visitor'}</div>
              </div>

              <Link
                to="/analyses/new"
                className={cn('flex min-h-11 min-w-0 flex-1 items-center gap-3 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-muted transition hover:border-primary/30 hover:bg-white/10', focusRing)}
              >
                <Search className="h-4 w-4 shrink-0 text-primary" />
                <span className="truncate">输入一个可复核的财务分析问题…</span>
                <span className="ml-auto hidden rounded-full border border-white/10 px-2 py-0.5 text-[11px] uppercase tracking-[0.18em] text-muted md:inline-flex">新建流程</span>
              </Link>

              <div className="inline-flex items-center rounded-full border border-white/10 bg-white/5 p-1 shadow-subtle">
                <button
                  className={cn(
                    'inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full px-3 py-2 text-sm font-semibold transition',
                    focusRing,
                    viewMode === 'business' ? 'bg-primary text-[#0a0d10]' : 'text-muted hover:text-ink',
                  )}
                  aria-label="切换到业务视图"
                  aria-pressed={viewMode === 'business'}
                  title="业务视图"
                  onClick={() => onViewModeChange('business')}
                  type="button"
                >
                  <Sparkles className="h-4 w-4" />
                  <span className="hidden sm:inline">业务视图</span>
                </button>
                <button
                  className={cn(
                    'inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full px-3 py-2 text-sm font-semibold transition',
                    focusRing,
                    viewMode === 'runtime' ? 'bg-primary text-[#0a0d10]' : 'text-muted hover:text-ink',
                  )}
                  aria-label="切换到运行时视图"
                  aria-pressed={viewMode === 'runtime'}
                  title="运行时视图"
                  onClick={() => onViewModeChange('runtime')}
                  type="button"
                >
                  <LayoutDashboard className="h-4 w-4" />
                  <span className="hidden sm:inline">运行时视图</span>
                </button>
              </div>

              <span className="hidden sm:inline-flex"><StatusPill tone="neutral">{session.authenticated ? '会话已连接' : '未连接'}</StatusPill></span>
            </div>
          </header>

          <main id="main-content" className="flex-1 px-4 pb-36 pt-4 md:pb-4 lg:px-8 lg:py-6" tabIndex={-1}>
            <div className="mx-auto max-w-[1720px]">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
      <nav className="fixed inset-x-3 bottom-3 z-30 rounded-[26px] border border-white/10 bg-[rgba(5,6,8,0.92)] p-2 shadow-panel backdrop-blur-xl md:hidden" aria-label="移动端主导航">
        <div className="grid grid-cols-5 gap-1">
          {visibleNavItems.map((item) => {
            const Icon = item.icon
            const isActive = location.pathname === item.to || location.pathname.startsWith(`${item.to}/`)
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={cn(
                  'flex min-h-14 flex-col items-center justify-center gap-1 rounded-2xl px-2 text-[11px] font-semibold transition',
                  focusRing,
                  isActive ? 'bg-primary text-[#0a0d10]' : 'text-muted hover:bg-white/5 hover:text-ink',
                )}
              >
                <Icon className="h-4 w-4" />
                <span className="max-w-full truncate">{item.label.replace('治理与审计', '审计').replace('连接与会话', '会话')}</span>
              </NavLink>
            )
          })}
        </div>
      </nav>
    </div>
  )
}
