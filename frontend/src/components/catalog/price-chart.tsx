import { CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts'
import type { HistoryPoint } from '@/api/types'
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart'
import { formatDate, formatPrice } from '@/lib/format'

const config = {
  price: { label: 'Price', color: 'var(--chart-2)' },
  regular: { label: 'Regular', color: 'var(--chart-4)' },
} satisfies ChartConfig

/** Step chart of the price change log; the last point is extended to "now". */
export function PriceChart({ history }: { history: readonly HistoryPoint[] }) {
  const points = history.map((h) => ({
    t: Date.parse(h.observed_at),
    price: h.price,
    regular: h.price_regular,
  }))
  const last = points.at(-1)
  if (last) points.push({ ...last, t: Math.max(Date.now(), last.t + 1) })

  return (
    <ChartContainer config={config} className="aspect-auto h-48 w-full">
      <LineChart data={points} margin={{ left: 4, right: 12, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="t"
          type="number"
          scale="time"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(t: number) => formatDate(new Date(t).toISOString())}
          tickLine={false}
          axisLine={false}
          minTickGap={40}
        />
        <YAxis
          width={70}
          tickFormatter={(v: number) => formatPrice(v)}
          tickLine={false}
          axisLine={false}
          domain={['auto', 'auto']}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(_label, payload) => {
                const t = payload[0]?.payload?.t
                return typeof t === 'number' ? formatDate(new Date(t).toISOString()) : ''
              }}
              formatter={(value, name) => (
                <span className="flex w-full justify-between gap-4">
                  <span className="text-muted-foreground">
                    {config[name as keyof typeof config]?.label}
                  </span>
                  <span className="font-medium tabular-nums">{formatPrice(Number(value))}</span>
                </span>
              )}
            />
          }
        />
        <Line
          dataKey="regular"
          type="stepAfter"
          stroke="var(--color-regular)"
          strokeDasharray="4 4"
          dot={false}
        />
        <Line
          dataKey="price"
          type="stepAfter"
          stroke="var(--color-price)"
          strokeWidth={2}
          dot={{ r: 2 }}
        />
      </LineChart>
    </ChartContainer>
  )
}
