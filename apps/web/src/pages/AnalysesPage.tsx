import { ArrowRight, Play, ShieldCheck, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Button, PageCard, QueryFeedback, Select, StatusPill, TextArea, focusRing } from '@/components/ui'
import type { AnalysisListResponse, AssetListItem, CreateAnalysisResponse } from '@/lib/types'
import { cn, formatDate } from '@/lib/utils'

type ViewMode = 'business' | 'runtime'

const RECENT_ANALYSIS_DISPLAY_LIMIT = 10

export function AnalysesPage({
  data,
  assets,
  isLoading = false,
  errorMessage,
  onRetry,
  viewMode,
  detailBasePath,
  newAnalysisPath,
  onSubmit,
}: {
  data: AnalysisListResponse | undefined
  assets: AssetListItem[]
  isLoading?: boolean
  errorMessage?: string | null
  onRetry?: () => void
  viewMode: ViewMode
  detailBasePath: string
  newAnalysisPath: string
  onSubmit: (input: { question: string; assetIds: string[]; analysisModePreset?: string | null }) => Promise<CreateAnalysisResponse>
}) {
  const navigate = useNavigate()
  const analysisHref = (analysisId: string) => `${detailBasePath}/${analysisId}`
  const items = data?.items ?? []
  const visibleRecentItems = items.slice(0, RECENT_ANALYSIS_DISPLAY_LIMIT)
  const hiddenRecentItemCount = Math.max(items.length - visibleRecentItems.length, 0)
  const failedItems = items.filter((item) => item.status === 'failed')
  const waitingHumanItems = items.filter((item) => item.status === 'waiting_for_human')
  const runningItems = items.filter((item) => !['success', 'failed', 'waiting_for_human'].includes(item.status))
  const followUpItems = [...waitingHumanItems, ...runningItems, ...failedItems]
  const reviewItems = items.filter((item) => item.status === 'waiting_for_human' || (item.status === 'success' && item.hasWarnings))
  const completedCount = items.filter((item) => item.status === 'success').length
  const assetSignature = useMemo(() => assets.map((asset) => asset.assetId).join('|'), [assets])

  const [question, setQuestion] = useState('')
  const [analysisModePreset, setAnalysisModePreset] = useState('researcher')
  const [assetIds, setAssetIds] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setAssetIds(assetSignature ? assetSignature.split('|').slice(0, 3) : [])
  }, [assetSignature])

  const selectedAssets = assets.filter((asset) => assetIds.includes(asset.assetId))
  const visibleAssetOptions = assets.slice(0, 6)
  const reviewQueue = reviewItems.slice(0, 4)
  const failureQueue = failedItems.slice(0, 4)
  const runtimeLatestFinished = items.find((item) => item.status === 'success')
  const readyOutputCount = items.filter((item) => item.hasOutputs).length
  const humanReviewCount = items.filter((item) => item.status === 'waiting_for_human').length
  const heroTitle = viewMode === 'runtime' ? '运行时透明度中心' : '可复核的 AI 财务分析'
  const heroDescription = viewMode === 'runtime'
    ? '把进行中、等待人工处理与失败任务分开观察，不在首页把异常和活跃运行混成一团。'
    : '把可交付结论、待业务复核事项与运行失败排障拆开，让首页先服务业务判断。'

  return (
    <div className="space-y-6">
      {errorMessage || (isLoading && !data) ? (
        <PageCard className="p-5">
          <QueryFeedback
            errorMessage={errorMessage}
            loading={isLoading && !data}
            loadingTitle="正在加载工作台"
            loadingDescription="正在读取当前工作区的分析任务、状态和复核队列。"
            errorTitle="分析列表加载失败"
            onRetry={onRetry}
          />
        </PageCard>
      ) : null}
      <PageCard className="overflow-hidden">
        <div className="grid gap-0 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,0.85fr)]">
          <div className="relative px-6 py-7 sm:px-8 sm:py-8">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_78%_10%,rgba(215,176,110,0.16),transparent_26%),radial-gradient(circle_at_10%_90%,rgba(74,222,128,0.08),transparent_28%)]" />
            <div className="relative">
              <div className="flex flex-wrap items-center gap-3">
                <span className="rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                  {viewMode === 'runtime' ? 'Runtime View' : 'Business View'}
                </span>
                <StatusPill tone="success">受控执行</StatusPill>
              </div>
              <h1 className="mt-5 max-w-4xl text-4xl font-semibold tracking-[-0.04em] text-ink sm:text-5xl">
                {heroTitle}
              </h1>
              <p className="mt-4 max-w-3xl text-base leading-8 text-muted">{heroDescription}</p>

              <div className="mt-7 grid gap-3 md:grid-cols-3">
                {viewMode === 'runtime' ? (
                  <>
                    <MiniStat label="活跃运行" value={String(runningItems.length)} />
                    <MiniStat label="待人工处理" value={String(waitingHumanItems.length)} />
                    <MiniStat label="运行失败" value={String(failedItems.length)} />
                  </>
                ) : (
                  <>
                    <MiniStat label="任务总数" value={String(data?.pagination.totalItems ?? 0)} />
                    <MiniStat label="待业务复核" value={String(reviewItems.length)} />
                    <MiniStat label="运行失败" value={String(failedItems.length)} />
                  </>
                )}
              </div>

              <form
                className="mt-7 rounded-[28px] border border-white/10 bg-black/25 p-4 shadow-subtle sm:p-5"
                onSubmit={async (event) => {
                  event.preventDefault()
                  setSubmitting(true)
                  setError(null)
                  try {
                    const result = await onSubmit({ question, assetIds, analysisModePreset })
                    navigate(analysisHref(result.analysisId))
                  } catch (submitError) {
                    setError(submitError instanceof Error ? submitError.message : '提交失败')
                  } finally {
                    setSubmitting(false)
                  }
                }}
              >
                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#b7b0a2]">提出您的分析问题</div>
                    <TextArea
                      className="min-h-28 resize-none"
                      placeholder="例如：分析本期毛利率下降的主要原因，并给出下一季度趋势建议。"
                      value={question}
                      onChange={(event) => setQuestion(event.target.value)}
                      required
                    />
                  </div>
                  <div className="space-y-4">
                    <div>
                      <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-[#b7b0a2]" htmlFor="quick-analysis-mode">分析模式</label>
                      <Select id="quick-analysis-mode" value={analysisModePreset} onChange={(event) => setAnalysisModePreset(event.target.value)}>
                        <option value="researcher">深度分析（推荐）</option>
                        <option value="reviewer">规则审计</option>
                        <option value="planner">结构化拆解</option>
                      </Select>
                    </div>
                    <Button className="w-full justify-center" disabled={submitting || !question.trim()} type="submit">
                      <Play className="h-4 w-4" />
                      {submitting ? '创建中…' : '开始分析'}
                    </Button>
                    {error ? <div className="rounded-2xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-sm text-rose-200" role="alert">{error}</div> : null}
                  </div>
                </div>

                <div className="mt-4 border-t border-white/10 pt-4">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-semibold uppercase tracking-[0.16em] text-[#b7b0a2]">本次引用资料</span>
                    <span className="text-xs text-muted">已选 {selectedAssets.length} 项</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {visibleAssetOptions.map((asset) => {
                      const selected = assetIds.includes(asset.assetId)
                      return (
                        <button
                          key={asset.assetId}
                          className={cn(
                            'cursor-pointer rounded-full border px-3 py-2 text-xs transition',
                            focusRing,
                            selected
                              ? 'border-primary/30 bg-primary/10 text-primary'
                              : 'border-white/10 bg-white/5 text-muted hover:border-white/20 hover:text-ink',
                          )}
                          type="button"
                          onClick={() => {
                            setAssetIds((current) =>
                              current.includes(asset.assetId)
                                ? current.filter((item) => item !== asset.assetId)
                                : [...current, asset.assetId],
                            )
                          }}
                        >
                          {asset.name}
                        </button>
                      )
                    })}
                    {!assets.length ? <span className="text-sm text-muted">当前工作区暂无资料，可先到资料库上传。</span> : null}
                  </div>
                </div>
              </form>
            </div>
          </div>

          <aside className="border-t border-white/10 bg-black/20 px-6 py-7 xl:border-l xl:border-t-0">
            {viewMode === 'runtime' ? (
              <div className="space-y-4">
                <div className="rounded-[28px] border border-sky-400/20 bg-sky-500/10 p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-semibold text-ink">活跃运行观察</div>
                    <ShieldCheck className="h-5 w-5 text-sky-300" />
                  </div>
                  <div className="mt-4 grid gap-3">
                    <RuntimeMetric label="活跃任务" value={String(runningItems.length)} />
                    <RuntimeMetric label="待人工处理" value={String(humanReviewCount)} />
                    <RuntimeMetric label="运行失败" value={String(failedItems.length)} />
                  </div>
                  <p className="mt-4 text-sm leading-6 text-muted">
                    运行时视图优先看状态推进、人工介入点和失败排障。业务问法与证据结论下沉到详情页。
                  </p>
                </div>

                <div className="rounded-[28px] border border-white/10 bg-white/5 p-5">
                  <div className="text-sm font-semibold text-ink">最近完成</div>
                  {runtimeLatestFinished ? (
                    <div className="mt-4 space-y-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                    <div className="font-semibold text-ink">{runtimeLatestFinished.title}</div>
                          <div className="mt-1 font-mono text-xs text-muted">{formatDate(runtimeLatestFinished.updatedAt)}</div>
                        </div>
                        <StatusPill tone={toneForStatus(runtimeLatestFinished.status)}>{runtimeLatestFinished.statusLabel}</StatusPill>
                      </div>
                      <p className="text-sm leading-6 text-muted">{runtimeLatestFinished.summary || runtimeLatestFinished.question}</p>
                      <Link className={cn('inline-flex min-h-11 items-center gap-2 rounded-full text-sm font-semibold text-primary hover:text-primary-hover', focusRing)} to={analysisHref(runtimeLatestFinished.analysisId)}>
                        进入终态详情
                        <ArrowRight className="h-4 w-4" />
                      </Link>
                    </div>
                  ) : (
                    <div className="mt-4 text-sm leading-6 text-muted">当前还没有成功终态任务，可先查看活跃运行、失败任务或新建分析。</div>
                  )}
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="rounded-[28px] border border-white/10 bg-white/5 p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-semibold text-ink">待业务复核</div>
                    <ShieldCheck className="h-5 w-5 text-emerald-300" />
                  </div>
                  <div className="mt-4 space-y-3">
                    {reviewQueue.map((item) => (
                      <Link
                        key={item.analysisId}
                        className={cn('block rounded-2xl border border-white/10 bg-black/20 px-4 py-3 transition hover:border-primary/25 hover:bg-white/5', focusRing)}
                        to={analysisHref(item.analysisId)}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0 font-medium text-ink">{item.title}</div>
                          <StatusPill tone={toneForStatus(item.status)}>{item.statusLabel}</StatusPill>
                        </div>
                        <div className="mt-2 text-xs leading-5 text-muted">
                          {item.status === 'waiting_for_human'
                            ? '当前需要人工处理后再继续推进。'
                            : item.hasWarnings
                              ? '结论已生成，但含风险提示，需要业务复核。'
                              : item.summary || item.question}
                        </div>
                      </Link>
                    ))}
                    {!reviewQueue.length ? <div className="rounded-2xl border border-emerald-400/20 bg-emerald-500/10 px-4 py-3 text-sm leading-6 text-emerald-200">当前没有待业务复核的结论或人工处理项。</div> : null}
                  </div>
                </div>

                <div className="rounded-[28px] border border-white/10 bg-white/5 p-5">
                  <div className="text-sm font-semibold text-ink">运行失败 / 排障</div>
                  {failureQueue.length ? (
                    <div className="mt-4 space-y-4">
                      {failureQueue.map((item) => (
                        <Link
                          key={item.analysisId}
                          className={cn('block rounded-2xl border border-rose-400/20 bg-rose-500/10 px-4 py-3 transition hover:border-rose-300/30 hover:bg-rose-500/15', focusRing)}
                          to={`/analyses/${item.analysisId}`}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 font-medium text-ink">{item.title}</div>
                            <StatusPill tone="error">{item.statusLabel}</StatusPill>
                          </div>
                          <div className="mt-2 text-xs leading-5 text-muted">{item.summary || item.question}</div>
                        </Link>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-4 text-sm leading-6 text-muted">当前没有运行失败任务；最近完成和待复核内容请看左侧分析列表与复核区。</div>
                  )}
                </div>
              </div>
            )}
          </aside>
        </div>
      </PageCard>

      {viewMode === 'runtime' ? (
        <>
          <div className="grid gap-4 md:grid-cols-4">
            <MetricCard label="当前工作区" value={data?.currentWorkspaceId ?? '—'} caption="运行态读取 scope" />
            <MetricCard label="活跃运行" value={String(runningItems.length)} caption="进行中但未失败" tone={runningItems.length ? 'warning' : 'success'} />
            <MetricCard label="待人工处理" value={String(humanReviewCount)} caption="status=waiting_for_human" tone={humanReviewCount ? 'warning' : 'neutral'} />
            <MetricCard label="运行失败" value={String(failedItems.length)} caption="需要排障或重跑" tone={failedItems.length ? 'warning' : 'neutral'} />
            <MetricCard label="可下载产物" value={String(readyOutputCount)} caption="已有 outputs 的任务数" />
          </div>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_420px]">
            <PageCard>
              <div className="border-b border-white/10 px-6 py-5 sm:px-7">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-ink">运行态队列</div>
                    <p className="mt-1 text-sm text-muted">优先呈现当前还在推进、失败或等待人工处理的真实运行记录。</p>
                  </div>
                  <Link className={cn('inline-flex min-h-11 items-center justify-center rounded-full border border-white/10 bg-white/5 px-4 text-sm font-semibold text-ink transition hover:-translate-y-[1px] hover:border-white/20 hover:bg-white/10', focusRing)} to={newAnalysisPath}>前往业务提问</Link>
                </div>
              </div>
              <div className="overflow-x-auto px-4 pb-4">
                <table className="min-w-full border-separate border-spacing-y-2 text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-[0.14em] text-muted">
                      <th className="px-3 py-2">运行主题</th>
                      <th className="px-3 py-2">状态</th>
                      <th className="px-3 py-2">人工复核</th>
                      <th className="px-3 py-2">更新时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(followUpItems.length ? followUpItems.slice(0, 6) : visibleRecentItems).map((item) => (
                      <tr key={item.analysisId} className="rounded-2xl bg-white/5 text-ink shadow-[inset_0_0_0_1px_rgba(255,255,255,0.05)] transition hover:bg-white/10">
                        <td className="rounded-l-2xl px-3 py-4 align-top">
                          <Link className={cn('inline-flex min-h-11 items-center rounded-lg font-semibold hover:text-primary', focusRing)} to={analysisHref(item.analysisId)}>
                            {item.title}
                          </Link>
                          <div className="mt-1 max-w-xl text-xs leading-5 text-muted">{item.summary || item.question}</div>
                        </td>
                        <td className="px-3 py-4 align-top"><StatusPill tone={toneForStatus(item.status)}>{item.statusLabel}</StatusPill></td>
                        <td className="px-3 py-4 align-top text-xs text-muted">
                          {item.status === 'waiting_for_human'
                            ? '等待人工'
                            : item.status === 'failed'
                              ? '需要排障'
                              : item.hasWarnings
                                ? '需要复核'
                                : '推进中'}
                        </td>
                        <td className="rounded-r-2xl px-3 py-4 align-top font-mono text-xs text-muted">{formatDate(item.updatedAt)}</td>
                      </tr>
                    ))}
                    {!items.length ? (
                      <tr>
                        <td className="px-3 py-10 text-center text-muted" colSpan={4}>当前工作区还没有运行记录。</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </PageCard>

            <PageCard>
              <div className="border-b border-white/10 px-6 py-5">
                <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                  <Sparkles className="h-4 w-4 text-primary" />
                  运行态关注点
                </div>
                <p className="mt-1 text-sm text-muted">把容易卡住的人工介入点、产物就绪度和最新终态放在一侧集中观察。</p>
              </div>
              <div className="space-y-3 px-5 py-5">
                {followUpItems.slice(0, 4).map((item) => (
                  <Link key={item.analysisId} to={analysisHref(item.analysisId)} className={cn('block rounded-2xl border border-white/10 bg-white/5 px-4 py-3 transition hover:border-primary/25 hover:bg-white/10', focusRing)}>
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-ink">{item.title}</div>
                      <StatusPill tone={toneForStatus(item.status)}>{item.statusLabel}</StatusPill>
                    </div>
                    <div className="mt-2 text-xs leading-5 text-muted">
                      {item.status === 'failed'
                        ? '本次运行已失败，请进入详情查看失败原因与下一步建议。'
                        : item.status === 'waiting_for_human'
                          ? '当前在等待人工补充输入或确认。'
                          : item.hasOutputs
                            ? '已有可交付产物，运行仍在推进。'
                            : '产物仍在生成中。'}
                    </div>
                  </Link>
                ))}
                {!followUpItems.length ? <div className="text-sm leading-6 text-muted">当前没有活跃运行、人工处理或失败任务；你可以查看最近完成任务或发起新的运行。</div> : null}
              </div>
            </PageCard>
          </div>
        </>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-4">
            <MetricCard label="当前工作区" value={data?.currentWorkspaceId ?? '—'} caption="来自 app-facing API" />
            <MetricCard label="任务总数" value={String(data?.pagination.totalItems ?? 0)} caption="真实分页总数" />
            <MetricCard label="已完成" value={String(completedCount)} caption="状态为 success" />
            <MetricCard label="待业务复核" value={String(reviewItems.length)} caption="成功但有风险提示，或等待人工处理" tone={reviewItems.length ? 'warning' : 'success'} />
          </div>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_420px]">
            <PageCard>
              <div className="border-b border-white/10 px-6 py-5 sm:px-7">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-ink">最近分析</div>
                    <p className="mt-1 text-sm text-muted">按最近更新时间排序，首页仅展示最需要快速复核的最近记录。</p>
                  </div>
                  <Link className={cn('inline-flex min-h-11 items-center justify-center rounded-full border border-white/10 bg-white/5 px-4 text-sm font-semibold text-ink transition hover:-translate-y-[1px] hover:border-white/20 hover:bg-white/10', focusRing)} to={newAnalysisPath}>进入完整新建流程</Link>
                </div>
              </div>
              <div className="overflow-x-auto px-4 pb-4">
                <table className="min-w-full border-separate border-spacing-y-2 text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-[0.14em] text-muted">
                      <th className="px-3 py-2">分析主题</th>
                      <th className="px-3 py-2">状态</th>
                      <th className="px-3 py-2">更新时间</th>
                      <th className="px-3 py-2">结果摘要</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRecentItems.map((item) => (
                      <tr key={item.analysisId} className="rounded-2xl bg-white/5 text-ink shadow-[inset_0_0_0_1px_rgba(255,255,255,0.05)] transition hover:bg-white/10">
                        <td className="rounded-l-2xl px-3 py-4 align-top">
                          <Link className={cn('inline-flex min-h-11 items-center rounded-lg font-semibold hover:text-primary', focusRing)} to={analysisHref(item.analysisId)}>
                            {item.title}
                          </Link>
                          <div className="mt-1 max-w-xl text-xs leading-5 text-muted">{item.question}</div>
                        </td>
                        <td className="px-3 py-4 align-top"><StatusPill tone={toneForStatus(item.status)}>{item.statusLabel}</StatusPill></td>
                        <td className="px-3 py-4 align-top font-mono text-xs text-muted">{formatDate(item.updatedAt)}</td>
                        <td className="rounded-r-2xl px-3 py-4 align-top text-muted">{item.summary || '等待结果'}</td>
                      </tr>
                    ))}
                    {!items.length ? (
                      <tr>
                        <td className="px-3 py-10 text-center text-muted" colSpan={4}>当前工作区还没有分析任务。</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
                {hiddenRecentItemCount ? (
                  <div className="border-t border-white/10 px-3 py-4 text-sm text-muted">
                    已收起 {hiddenRecentItemCount} 条更早记录；全量历史应通过真实分页能力查看。
                  </div>
                ) : null}
              </div>
            </PageCard>

            <PageCard>
              <div className="border-b border-white/10 px-6 py-5">
                <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                  <Sparkles className="h-4 w-4 text-primary" />
                  需要继续跟进
                </div>
                <p className="mt-1 text-sm text-muted">优先处理非成功终态或带风险提示的任务。</p>
              </div>
              <div className="space-y-3 px-5 py-5">
                {followUpItems.slice(0, 5).map((item) => (
                  <Link key={item.analysisId} to={analysisHref(item.analysisId)} className={cn('block rounded-2xl border border-white/10 bg-white/5 px-4 py-3 transition hover:border-primary/25 hover:bg-white/10', focusRing)}>
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-ink">{item.title}</div>
                      <StatusPill tone={toneForStatus(item.status)}>{item.statusLabel}</StatusPill>
                    </div>
                    <div className="mt-2 text-xs leading-5 text-muted">
                      {item.status === 'failed'
                        ? '运行失败，请先排查执行原因，再决定是否重跑。'
                        : item.status === 'waiting_for_human'
                          ? '等待人工处理后才能继续。'
                          : item.summary || item.question}
                    </div>
                  </Link>
                ))}
                {!followUpItems.length ? <div className="text-sm leading-6 text-muted">当前没有需要继续跟进的任务。</div> : null}
              </div>
            </PageCard>
          </div>
        </>
      )}
    </div>
  )
}

function MetricCard({ label, value, caption, tone = 'neutral' }: { label: string; value: string; caption: string; tone?: 'neutral' | 'success' | 'warning' }) {
  return (
    <div className={cn('rounded-[26px] border bg-white/5 px-5 py-5 shadow-subtle', tone === 'success' ? 'border-emerald-400/20' : tone === 'warning' ? 'border-amber-400/20' : 'border-white/10')}>
      <div className="text-xs uppercase tracking-[0.16em] text-muted">{label}</div>
      <div className="mt-3 font-mono text-[1.9rem] font-semibold text-ink">{value}</div>
      <div className="mt-2 text-xs leading-5 text-muted">{caption}</div>
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/20 px-3 py-3">
      <div className="text-[11px] uppercase tracking-[0.16em] text-muted">{label}</div>
      <div className="mt-2 font-mono text-xl font-semibold text-ink">{value}</div>
    </div>
  )
}

function RuntimeMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/20 px-4 py-3">
      <div className="text-[11px] uppercase tracking-[0.16em] text-muted">{label}</div>
      <div className="mt-2 font-mono text-2xl font-semibold text-ink">{value}</div>
    </div>
  )
}

function toneForStatus(status: string) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'waiting_for_human') return 'warning'
  return 'neutral'
}
