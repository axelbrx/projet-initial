export type IssueStatus =
  | 'ticket'
  | 'auto-fixed'
  | 'approval'
  | 'quarantined'
  | 'hand-off'

export type Issue = {
  column: string
  check: string
  rows: number | string
  status: IssueStatus
}

export const MAX_DAY = 28

const issuePool: Issue[] = [
  { column: 'customers.email', check: 'completeness', rows: 712, status: 'ticket' },
  { column: 'orders', check: 'uniqueness', rows: 38, status: 'auto-fixed' },
  { column: 'products.unit_price', check: 'validity', rows: 4, status: 'approval' },
  { column: 'orders.sku_id', check: 'consistency', rows: 21, status: 'quarantined' },
  { column: 'pos feed', check: 'schema drift', rows: 'all', status: 'auto-fixed' },
  { column: 'web feed', check: 'volume', rows: '–', status: 'hand-off' },
  { column: 'customers.phone', check: 'validity', rows: 56, status: 'auto-fixed' },
  { column: 'customers', check: 'uniqueness', rows: 12, status: 'approval' },
]

// Génère des issues différentes (mais stables) pour chacun des 28 jours
export function getIssuesForDay(day: number): Issue[] {
  const count = 2 + (day % 4) // entre 2 et 5 issues par jour

  return Array.from({ length: count }, (_, i) => {
    const issue = issuePool[(day * 3 + i) % issuePool.length]
    return typeof issue.rows === 'number'
      ? { ...issue, rows: issue.rows + day }
      : issue
  })
}