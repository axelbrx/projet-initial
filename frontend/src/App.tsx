import { BrowserRouter, Routes, Route } from 'react-router'
import AppLayout from '@/layouts/AppLayout'
import Dashboard from '@/pages/Dashboard'
import Fixes from '@/pages/Fixes'
import AgentLog from '@/pages/AgentLog'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/fixes" element={<Fixes />} />
          <Route path="/agent-log" element={<AgentLog />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}