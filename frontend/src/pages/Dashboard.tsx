import { useState } from 'react'
import ApprovalPanel from '@/components/dashboard/approval/ApprovalPanel'
import IssuesPanel from '@/components/dashboard/issues/IssuesPanel'
import KpiContainer from '@/components/dashboard/KPI/KpiContainer'
import { mockApprovals } from '@/demo-data/mockApprovals'

export default function Dashboard() {
  const [approvals, setApprovals] = useState(mockApprovals)

  const removeApproval = (id: number) =>
    setApprovals((list) => list.filter((a) => a.id !== id))

  const handleApprove = (id: number) => {
    console.log('Approved', id)
    removeApproval(id)
  }

  const handleReject = (id: number) => {
    console.log('Rejected', id)
    removeApproval(id)
  }

  /*
   * Simulated data for week 1 UI
   */
  const kpiData = [
    { title: 'Issues caught', value: 40, type: 'number' },
    { title: 'Auto-fixed', value: 21, type: 'number' },
    // Lié à la vraie file d'approbation
    { title: 'Awaiting approval', value: approvals.length, type: 'number' },
    { title: 'Data health', value: 98.8, type: 'percentage' },
  ] satisfies {
    title: string
    value: string | number
    type: 'number' | 'percentage' | 'string'
  }[]

  return (
    <div className="min-h-screen mx-auto max-w-7xl px-3 pt-2 pb-10">
      <h1 className="text-2xl font-medium flex w-full justify-center items-center mt-8">
        Data Hygiene Watchdog
      </h1>

      <div className="mt-8">
        <KpiContainer data={kpiData} />
        <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <IssuesPanel />
          <ApprovalPanel
            approvals={approvals}
            onApprove={handleApprove}
            onReject={handleReject}
          />
        </div>
      </div>
    </div>
  )
}