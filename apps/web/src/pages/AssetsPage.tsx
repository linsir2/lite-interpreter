import { useRef, useState } from 'react'

import { Button, FieldLabel, PageCard, SectionHeader, Select, StatusPill } from '@/components/ui'
import type { AssetListItem, AssetUploadResponse } from '@/lib/types'

export function AssetsPage({
  assets,
  onUpload,
}: {
  assets: AssetListItem[]
  onUpload: (input: { files: File[]; assetKind: string }) => Promise<AssetUploadResponse>
}) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [assetKind, setAssetKind] = useState('structured_dataset')
  const [files, setFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-[0.92fr_1.08fr]">
        <PageCard>
          <SectionHeader title="上传资料" level="h1" description="上传本次分析要引用的报表、台账或口径说明材料。" />
          <div className="space-y-5 px-6 py-6 sm:px-7">
            <div className="rounded-[28px] border border-primary/20 bg-primary/10 px-5 py-4 text-sm leading-6 text-[#f1dfbd]">
              稳定结构化输入以 csv / tsv / json 为准；其他文件先作为业务说明材料进入资料库。
            </div>
            <div>
              <FieldLabel htmlFor="asset-kind-select">材料类型</FieldLabel>
              <Select id="asset-kind-select" value={assetKind} onChange={(event) => setAssetKind(event.target.value)}>
                <option value="structured_dataset">结构化数据</option>
                <option value="business_document">说明文档</option>
                <option value="auto">自动识别</option>
              </Select>
            </div>
            <button
              className="flex min-h-52 w-full flex-col items-center justify-center rounded-[28px] border-2 border-dashed border-primary/25 bg-black/20 px-6 text-center transition hover:border-primary/40 hover:bg-white/5"
              type="button"
              onClick={() => inputRef.current?.click()}
            >
              <span className="text-base font-semibold text-ink">拖入文件或点击选择</span>
              <span className="mt-2 max-w-md text-sm leading-6 text-muted">建议只上传本次分析真正需要引用的材料，保证证据链清晰。</span>
            </button>
            <input ref={inputRef} className="hidden" type="file" multiple onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
            {files.length ? (
              <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4 text-sm text-muted">
                已选择 {files.length} 个文件：{files.map((file) => file.name).join('，')}
              </div>
            ) : null}
            {message ? <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-muted">{message}</div> : null}
            <Button
              disabled={!files.length || uploading}
              onClick={async () => {
                setUploading(true)
                setMessage(null)
                try {
                  const result = await onUpload({ files, assetKind })
                  setMessage(`已上传 ${result.uploaded.length} 个文件。`)
                  setFiles([])
                } catch (error) {
                  setMessage(error instanceof Error ? error.message : '上传失败')
                } finally {
                  setUploading(false)
                }
              }}
              type="button"
            >
              {uploading ? '上传中…' : '上传到当前工作区'}
            </Button>
          </div>
        </PageCard>

        <PageCard>
          <SectionHeader title="当前资料库" description="查看当前工作区中的资料，以及每份材料是否已经准备好供分析使用。" />
          <div className="grid gap-4 border-b border-white/10 px-6 py-5 md:grid-cols-3 sm:px-7">
            <AssetMetric label="资料总数" value={String(assets.length)} />
            <AssetMetric label="可直接分析" value={String(assets.filter((asset) => asset.readinessLabel === '可直接分析').length)} tone="success" />
            <AssetMetric label="待处理" value={String(assets.filter((asset) => asset.readinessLabel !== '可直接分析').length)} tone="warning" />
          </div>
          <div className="border-b border-white/10 px-6 py-4 text-sm leading-6 text-muted sm:px-7">
            优先保证报表、台账和说明材料的口径一致。准备好的资料越干净，后续分析结论越容易复核。
          </div>
          <div className="overflow-x-auto px-4 pb-4">
            <table className="min-w-full border-separate border-spacing-y-2 text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-[0.14em] text-muted">
                  <th className="px-3 py-2">资料名称</th>
                  <th className="px-3 py-2">类型</th>
                  <th className="px-3 py-2">状态</th>
                </tr>
              </thead>
              <tbody>
                {assets.map((asset) => (
                  <tr key={asset.assetId} className="bg-white/5 transition hover:bg-white/10">
                    <td className="rounded-l-2xl px-3 py-4">
                      <div className="font-medium text-ink">{asset.name}</div>
                      <div className="mt-1 text-xs text-muted">{asset.filePath || '无本地路径展示'}</div>
                    </td>
                    <td className="px-3 py-4 text-muted">{asset.kind}</td>
                    <td className="rounded-r-2xl px-3 py-4"><StatusPill tone={asset.readinessLabel === '可直接分析' ? 'success' : 'warning'}>{asset.readinessLabel}</StatusPill></td>
                  </tr>
                ))}
                {!assets.length ? <tr><td className="px-3 py-10 text-center text-muted" colSpan={3}>当前工作区还没有资料。</td></tr> : null}
              </tbody>
            </table>
          </div>
        </PageCard>
      </div>
    </div>
  )
}

function AssetMetric({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: 'neutral' | 'success' | 'warning' }) {
  const borderClass = tone === 'success' ? 'border-emerald-400/20' : tone === 'warning' ? 'border-amber-400/20' : 'border-white/10'
  return (
    <div className={`rounded-2xl border ${borderClass} bg-white/5 px-4 py-4`}>
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">{label}</div>
      <div className="mt-2 font-mono text-2xl font-semibold text-ink">{value}</div>
    </div>
  )
}
