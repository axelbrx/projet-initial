import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import FixesTable from '@/components/fixes/FixesTable'
import UndoFixDialog from '@/components/fixes/UndoFixDialog'
import { FIX_STATUS, mockFixes, type Fix, type FixStatus } from '@/demo-data/mockFixes'

type Filter = 'all' | FixStatus

const filters: Filter[] = ['all', ...(Object.keys(FIX_STATUS) as FixStatus[])]

export default function Fixes() {
  const [fixes, setFixes] = useState(mockFixes)
  const [filter, setFilter] = useState<Filter>('all')
  const [fixToUndo, setFixToUndo] = useState<Fix | null>(null)

  const visibleFixes =
    filter === 'all' ? fixes : fixes.filter((fix) => fix.status === filter)

  const confirmUndo = () => {
    setFixes((list) =>
      list.map((fix) =>
        fix.fix_id === fixToUndo?.fix_id ? { ...fix, status: 'undone' } : fix,
      ),
    )
    setFixToUndo(null)
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl text-foreground">All fixes</CardTitle>
          <div className="mt-2 flex flex-wrap gap-2">
            {filters.map((f) => (
              <Button
                key={f}
                size="sm"
                variant={filter === f ? 'default' : 'outline'}
                onClick={() => setFilter(f)}
              >
                {f === 'all' ? 'All' : FIX_STATUS[f]}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          <FixesTable fixes={visibleFixes} onUndo={setFixToUndo} />
        </CardContent>
      </Card>

      <UndoFixDialog
        fix={fixToUndo}
        onConfirm={confirmUndo}
        onCancel={() => setFixToUndo(null)}
      />
    </>
  )
}