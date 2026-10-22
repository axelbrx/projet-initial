import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type KpiCardProps = {
  title: string
  value: string | number
}

export function KpiCard({ title, value }: KpiCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-semibold">{value}</p>
      </CardContent>
    </Card>
  )
}