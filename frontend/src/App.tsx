import { BrowserRouter, Routes, Route } from 'react-router'
import Dashboard from './pages/Dashboard'
import Fixes from './pages/Fixes'


function App() {

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/fixes" element={<Fixes />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
