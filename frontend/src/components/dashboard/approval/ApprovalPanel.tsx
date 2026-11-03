import { AnimatePresence, motion } from 'motion/react'
import { CheckCircle2 } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { Approval } from '@/demo-data/mockApprovals'
import ApprovalCard from '@/components/dashboard/approval/ApprovalCard'

type ApprovalPanelProps = {
  approvals: Approval[]
  onApprove: (id: number) => void
  onReject: (id: number) => void
}

export default function ApprovalPanel({
  approvals,
  onApprove,
  onReject,
}: ApprovalPanelProps) {
  const isEmpty = approvals.length === 0

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="text-2xl text-foreground">
          Approval queue
        </CardTitle>
      </CardHeader>
      <CardContent
        className={cn(
          'flex flex-1 flex-col gap-4',
          isEmpty && 'items-center justify-center',
        )}
      >
        {isEmpty ? (
          <div className="flex flex-col items-center gap-2 text-center text-muted-foreground">
            <CheckCircle2 className="size-8" />
            <p>No approval in queue, everything is good!</p>
          </div>
        ) : (
          <AnimatePresence>
            {approvals.map((approval) => (
              <motion.div
                key={approval.id}
                layout
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
              >
                <ApprovalCard
                  approval={approval}
                  onApprove={onApprove}
                  onReject={onReject}
                />
              </motion.div>
            ))}
          </AnimatePresence>
        )}
      </CardContent>
    </Card>
  )
}