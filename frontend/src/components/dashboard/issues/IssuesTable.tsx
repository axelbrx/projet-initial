import { motion, useReducedMotion } from 'motion/react'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

// Version animée du TableRow de shadcn
const MotionTableRow = motion.create(TableRow)

export default function IssuesTable({ data }: { data: any[] }) {
  const reduceMotion = useReducedMotion()

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Table - column</TableHead>
          <TableHead>Check</TableHead>
          <TableHead>Rows</TableHead>
          <TableHead>Statut</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.length === 0 ? (
          <TableRow>
            <TableCell colSpan={4} className="text-center">
              No data available
            </TableCell>
          </TableRow>
        ) : (
          data.map((row, index) => (
            <MotionTableRow
              // La key inclut le contenu: les lignes sont rejouées quand les données changent (ex. changement de jour)
              key={`${index}-${row.column}-${row.check}-${row.rows}-${row.status}`}
              initial={reduceMotion ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.2, delay: index * 0.04 }}
            >
              <TableCell>{row.column}</TableCell>
              <TableCell>{row.check}</TableCell>
              <TableCell>{row.rows}</TableCell>
              <TableCell>
                <Badge variant="secondary">{row.status}</Badge>
              </TableCell>
            </MotionTableRow>
          ))
        )}
      </TableBody>
    </Table>
  )
}