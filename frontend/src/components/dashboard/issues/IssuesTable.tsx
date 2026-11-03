import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export default function IssuesTable({ data }: { data: any[] }) {
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
            <TableRow key={index}>
              <TableCell>{row.column}</TableCell>
              <TableCell>{row.check}</TableCell>
              <TableCell>{row.rows}</TableCell>
              <TableCell>
                <Badge variant="secondary">{row.status}</Badge>
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  )
}