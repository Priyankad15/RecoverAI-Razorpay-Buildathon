import { BrowserRouter, Route, Routes } from "react-router-dom";

import AppShell from "./components/AppShell";
import Analytics from "./pages/Analytics";
import AuditTrail from "./pages/AuditTrail";
import Dashboard from "./pages/Dashboard";
import FailedPayments from "./pages/FailedPayments";
import TransactionDetail from "./pages/TransactionDetail";

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/payments" element={<FailedPayments />} />
          <Route path="/payments/:transactionId" element={<TransactionDetail />} />
          <Route path="/audit" element={<AuditTrail />} />
          <Route path="/analytics" element={<Analytics />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
