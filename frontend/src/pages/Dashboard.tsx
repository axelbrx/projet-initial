import { KpiCard } from "@/components/dashboard/KpiCard";

export default function Dashboard() {
  return (
    <div className="min-h-screen mx-auto max-w-7xl px-3 pt-2">
      <h1 className="text-2xl font-medium flex w-full justify-center items-center mt-8">
        Data Hygiene Watchdog
      </h1>

      
      <div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 mt-8">
        <KpiCard title="Total Records" value={1000} />
        <KpiCard title="Total Fixes" value={100} />
        <KpiCard title="Total Errors" value={50} />
        <KpiCard title="Total Warnings" value={98.8} />
        </div>

      </div>
    </div>
  )
}