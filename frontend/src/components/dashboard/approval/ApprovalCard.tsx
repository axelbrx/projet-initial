import { Button } from '@/components/ui/button'
import type { Approval } from '@/demo-data/mockApprovals'

type ApprovalCardProps = {
  approval: Approval
  onApprove: (id: number) => void
  onReject: (id: number) => void
}

export default function ApprovalCard({
  approval,
  onApprove,
  onReject,
}: ApprovalCardProps) {
  return (
    <div className="rounded-lg border bg-muted/30 p-5">
      <h3 className="text-lg font-semibold text-foreground">{approval.title}</h3>
      <p className="mt-1 text-sm text-muted-foreground">{approval.subtitle}</p>
      <p className="mt-4 text-sm text-foreground">{approval.description}</p>

      <div className="mt-5 flex gap-2">
        <Button onClick={() => onApprove(approval.id)}>Approve</Button>
        <Button variant="outline" onClick={() => onReject(approval.id)}>
          Reject
        </Button>
      </div>
    </div>
  )
}