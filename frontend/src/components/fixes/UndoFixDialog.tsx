import { ArrowDown } from 'lucide-react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import type { Fix } from '@/demo-data/mockFixes'

const color = {
  red: {
    container: 'border-red-500/30 bg-red-500/10',
    label: 'text-red-600 dark:text-red-400',
  },
  green: {
    container: 'border-green-500/30 bg-green-500/10',
    label: 'text-green-600 dark:text-green-400',
  },
}

function ValueBox({
  label,
  value,
  col,
}: {
  label: string
  value: string
  col: keyof typeof color
}) {
  return (
    <div className={`rounded-md border p-3 ${color[col].container}`}>
      <p className={`mb-1 text-xs font-medium uppercase ${color[col].label}`}>
        {label}
      </p>
      <code className="block break-all font-mono text-sm">{value}</code>
    </div>
  )
}

type UndoFixDialogProps = {
  fix: Fix | null
  onConfirm: () => void
  onCancel: () => void
}

export default function UndoFixDialog({ fix, onConfirm, onCancel }: UndoFixDialogProps) {
  return (
    <AlertDialog open={fix !== null} onOpenChange={(open) => !open && onCancel()}>
      <AlertDialogContent>
        {fix && (
          <>
            <AlertDialogHeader>
              <AlertDialogTitle>Undo this fix?</AlertDialogTitle>
              <AlertDialogDescription>
                <code className="font-mono text-foreground">
                  {fix.table_name}.{fix.column_name}
                </code>{' '}
                (record{' '}
                <code className="font-mono text-foreground">{fix.record_id}</code>) will
                go back to its previous value.
              </AlertDialogDescription>
            </AlertDialogHeader>

            <div className="space-y-2">
              <ValueBox label="Now" value={fix.after_value} col="red" />
              <ArrowDown className="mx-auto size-4 text-muted-foreground" />
              <ValueBox label="After undo" value={fix.before_value} col="green" />
            </div>

            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={onConfirm}>Undo fix</AlertDialogAction>
            </AlertDialogFooter>
          </>
        )}
      </AlertDialogContent>
    </AlertDialog>
  )
}