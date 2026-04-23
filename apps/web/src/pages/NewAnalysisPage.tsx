import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button, FieldLabel, PageCard, SectionHeader, Select, TextArea } from '@/components/ui'
import type { AssetListItem, CreateAnalysisResponse } from '@/lib/types'

export function NewAnalysisPage({
  assets,
  onSubmit,
}: {
  assets: AssetListItem[]
  onSubmit: (input: { question: string; assetIds: string[]; analysisModePreset?: string | null }) => Promise<CreateAnalysisResponse>
}) {
  const navigate = useNavigate()
  const [question, setQuestion] = useState('')
  const [analysisModePreset, setAnalysisModePreset] = useState('researcher')
  const [assetIds, setAssetIds] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  return (
    <div className="space-y-6">
      <PageCard>
        <SectionHeader title="新建分析任务" description="明确分析目标、选择资料，然后开始运行。" />
        <form
          className="grid gap-6 px-6 py-6 lg:grid-cols-[1.1fr_0.9fr]"
          onSubmit={async (event) => {
            event.preventDefault()
            setSubmitting(true)
            setError(null)
            try {
              const result = await onSubmit({ question, assetIds, analysisModePreset })
              navigate(`/analyses/${result.analysisId}`)
            } catch (submitError) {
              setError(submitError instanceof Error ? submitError.message : '提交失败')
            } finally {
              setSubmitting(false)
            }
          }}
        >
          <div className="space-y-5">
            <div className="rounded-[30px] border border-border bg-gradient-to-br from-[#183d37] to-[#102d29] px-5 py-5 text-white">
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#dec390]">填写建议</div>
              <div className="mt-3 space-y-2 text-sm leading-6 text-white/72">
                <p>说明时间范围、对比对象和希望验证的异常点。</p>
                <p>如果已经有怀疑方向，可以直接写明，例如折扣、费用分摊、账龄风险。</p>
              </div>
            </div>
            <div>
              <FieldLabel htmlFor="new-analysis-question">分析目标与问题</FieldLabel>
              <TextArea
                id="new-analysis-question"
                placeholder="例如：请结合利润表、费用明细和销售数据，解释本月利润下降的主要原因，并列出需要优先核对的异常项目。"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                required
              />
            </div>
            <div>
              <FieldLabel htmlFor="new-analysis-mode">分析策略</FieldLabel>
              <Select id="new-analysis-mode" value={analysisModePreset} onChange={(event) => setAnalysisModePreset(event.target.value)}>
                <option value="researcher">Researcher · 先探索原因与线索</option>
                <option value="reviewer">Reviewer · 更强调核验和风险控制</option>
                <option value="planner">Planner · 更强调结构化拆解</option>
              </Select>
            </div>
            {error ? <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-error">{error}</div> : null}
            <Button disabled={submitting} type="submit">{submitting ? '提交中…' : '开始分析'}</Button>
          </div>

          <div className="rounded-[30px] border border-border bg-surface-2 p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="text-base font-semibold text-ink">选择引用资料</div>
              <span className="rounded-full border border-border bg-white px-3 py-1 text-xs font-semibold text-muted">
                已选 {assetIds.length} 项
              </span>
            </div>
            <p className="mt-2 text-sm leading-6 text-muted">只勾选本次分析真正需要的报表、台账和说明材料，避免结论被无关输入污染。</p>
            <div className="mt-5 space-y-3">
              {assets.map((asset) => (
                <label key={asset.assetId} className="flex items-start gap-3 rounded-2xl border border-border bg-white px-4 py-3 transition hover:border-primary/20">
                  <input
                    className="mt-1"
                    type="checkbox"
                    checked={assetIds.includes(asset.assetId)}
                    onChange={(event) => {
                      setAssetIds((current) =>
                        event.target.checked
                          ? [...current, asset.assetId]
                          : current.filter((item) => item !== asset.assetId),
                      )
                    }}
                  />
                  <div>
                    <div className="font-medium text-ink">{asset.name}</div>
                    <div className="mt-1 text-xs text-muted">{asset.kind} · {asset.readinessLabel}</div>
                  </div>
                </label>
              ))}
              {!assets.length ? <div className="text-sm text-muted">当前工作区还没有可选资料。</div> : null}
            </div>
          </div>
        </form>
      </PageCard>
    </div>
  )
}
