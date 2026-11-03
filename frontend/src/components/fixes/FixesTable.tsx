import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FIX_STATUS, FIX_TYPE, type Fix, type FixStatus } from '@/demo-data/mockFixes'

const statusVariant: Record<
  FixStatus,
  'default' | 'secondary' | 'destructive' | 'outline'
> = {
  applied: 'default',
  awaiting_approval: 'secondary',
  approved: 'secondary',
  rejected: 'destructive',
  undone: 'outline',
}

type FixesTableProps = {
  fixes: Fix[]
  onUndo: (fix: Fix) => void
}

export default function FixesTable({ fixes, onUndo }: FixesTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Day</TableHead>
          <TableHead>Table · column</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Before</TableHead>
          <TableHead>After</TableHead>
          <TableHead>Agent reasoning</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Action</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {fixes.length === 0 ? (
          <TableRow>
            <TableCell colSpan={8} className="text-center text-muted-foreground">
              No fixes for this filter
            </TableCell>
          </TableRow>
        ) : (
          fixes.map((fix) => (
            <TableRow key={fix.fix_id}>
              <TableCell>{fix.day}</TableCell>
              <TableCell>
                {fix.table_name}.{fix.column_name}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {FIX_TYPE[fix.fix_type] ?? fix.fix_type}
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">
                {fix.before_value}
              </TableCell>
              <TableCell className="font-mono text-xs">{fix.after_value}</TableCell>
              <TableCell className="max-w-xs">
                <p className="line-clamp-2 text-sm" title={fix.reasoning}>
                  {fix.reasoning}
                </p>
              </TableCell>
              <TableCell>
                <Badge variant={statusVariant[fix.status]}>
                  {FIX_STATUS[fix.status]}
                </Badge>
              </TableCell>
              <TableCell className="text-right">
                {fix.status === 'applied' ? (
                  <Button variant="outline" size="sm" onClick={() => onUndo(fix)}>
                    Undo
                  </Button>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  )
}