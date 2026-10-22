import ApprovalPanel from "@/components/dashboard/approval/ApprovalPanel";
import IssuesPanel from "@/components/dashboard/issues/IssuesPanel";
import KpiContainer from "@/components/dashboard/KPI/KpiContainer";

export default function Dashboard() {

  /*
   * Simulated data for week 1 UI
  */
  const kpiData = [
    { title: 'Issues caught', value: 40, type: 'number' },
    { title: 'Auto-fixed', value: 21, type: 'number' },
    { title: 'Awaiting approval', value: 3, type: 'number' },
    { title: 'Data health', value: 98.8, type: 'percentage' },
  ] satisfies { // Satisfies is used to ensure that the array conforms to the expected type without changing the inferred type of the array itself
    title: string
    value: string | number
    type: 'number' | 'percentage' | 'string'
  }[]



  return (
    <div className="min-h-screen mx-auto max-w-7xl px-3 pt-2">
      <h1 className="text-2xl font-medium flex w-full justify-center items-center mt-8">
        Data Hygiene Watchdog
      </h1>

      
      <div className="mt-8">
        <KpiContainer data={kpiData} />
        <div className="mt-8 grid *:grid-cols-1 gap-4 sm:grid-cols-2">
          <IssuesPanel />
          <ApprovalPanel />
        </div>
      </div>
    </div>  
  )
}