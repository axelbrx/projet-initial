
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type KpiCardProps = {
  title: string
  value: string | number
  // Sets the KPI type of value, to determine how is it displayed
  type: 'number' | 'percentage' | 'string'
}

export function KpiCard({ title, value, type }: KpiCardProps) {

  // Format the value based on the type
  const formattedValue =
    type === 'percentage'
      ? `${value} %`
      : type === 'number' && typeof value === 'number'
        ? new Intl.NumberFormat('fr-FR').format(value)
        : value

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-semibold">{formattedValue}</p>
      </CardContent>
    </Card>
  )
}
