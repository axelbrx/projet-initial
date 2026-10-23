import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import IssuesTable from '@/components/dashboard/issues/IssuesTable'
import { Button } from '@/components/ui/button'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import { getIssuesForDay, MAX_DAY } from '@/demo-data/mockIssues'

export default function IssuesPanel() {
  const [day, setDay] = useState(1)
  const issuesData = getIssuesForDay(day)

  const runAgent = () => {
    console.log('Run agent clicked')
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-2xl text-foreground">
          Today&apos;s Issues
        </CardTitle>
      </CardHeader>
      <CardContent>

        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center justify-start gap-2">
            <Button size="lg" onClick={runAgent}>
              Run agent
            </Button>
            <Button
              size="lg"
              variant="outline"
              onClick={() => setDay((d) => d - 1)}
              disabled={day <= 1}
            >
              <ArrowLeft />
              Previous day
            </Button>
            <Button
              size="lg"
              variant="outline"
              onClick={() => setDay((d) => d + 1)}
              disabled={day >= MAX_DAY}
            >
              Next day
              <ArrowRight />
            </Button>
          </div>
          <p className="text-md text-muted-foreground">
            Simulation day {day}/{MAX_DAY}
          </p>
        </div>
        
        <IssuesTable data={issuesData} />
      </CardContent>
    </Card>
  )
}