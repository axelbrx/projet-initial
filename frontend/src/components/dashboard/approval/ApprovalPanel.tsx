import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CheckCircle2 } from 'lucide-react'

export default function ApprovalPanel() {
  const approvals: unknown[] = []

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="text-2xl text-foreground">
          Approval queue
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 items-center justify-center">
        {approvals.length === 0 ? (
          <div className="flex flex-col items-center gap-2 text-center text-muted-foreground">
            <CheckCircle2 className="size-8" />
            <p>No approval in queue, everything is good!</p>
          </div>
        ) : (
          <p>{approvals.length} approvals waiting</p>
        )}
      </CardContent>
    </Card>
  )
}