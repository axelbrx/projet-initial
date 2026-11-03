
import { KpiCard } from '@/components/dashboard/KPI/KpiCard'

type Kpi = {
  title: string
  value: string | number
  type: 'number' | 'percentage' | 'string'
}

type KpiContainerProps = {
  data: Kpi[]
}

export default function KpiContainer({ data }: KpiContainerProps) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {data.map((kpi) => (
        <KpiCard
          key={kpi.title}
          title={kpi.title}
          value={kpi.value}
          type={kpi.type}
        />
      ))}
    </div>
  )
}
