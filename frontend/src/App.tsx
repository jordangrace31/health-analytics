import { Routes, Route } from "react-router-dom";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<div>login</div>} />
      <Route path="/register" element={<div>register</div>} />
      <Route path="/" element={<div>dashboard</div>} />
      <Route path="/import" element={<div>import</div>} />
    </Routes>
  );
}
