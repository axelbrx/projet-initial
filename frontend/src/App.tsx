import { BrowserRouter, Routes, Route } from 'react-router'
import Dashboard from '@/pages/Dashboard'
import Fixes from './pages/Fixes'


function App() {

  return (
    <div className="min-h-screen bg-gray-100">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/fixes" element={<Fixes />} />
        </Routes>
      </BrowserRouter>
    </div>

  )
}

export default App
