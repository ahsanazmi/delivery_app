import { Navigate, Route, Routes } from "react-router-dom";

import { useSession } from "@/features/auth/session-context";
import { AdminLayout } from "@/layouts/AdminLayout";
import AuditLogs from "@/pages/AuditLogs";
import Categories from "@/pages/Categories";
import CODReconciliation from "@/pages/CODReconciliation";
import Coupons from "@/pages/Coupons";
import CustomerDetails from "@/pages/CustomerDetails";
import Customers from "@/pages/Customers";
import Dashboard from "@/pages/Dashboard";
import DeliveryAssignmentDetails from "@/pages/DeliveryAssignmentDetails";
import DeliveryAssignments from "@/pages/DeliveryAssignments";
import Login from "@/pages/Login";
import Notifications from "@/pages/Notifications";
import OrderDetails from "@/pages/OrderDetails";
import Orders from "@/pages/Orders";
import PaymentDetails from "@/pages/PaymentDetails";
import Payments from "@/pages/Payments";
import Reports from "@/pages/Reports";
import RestaurantDetails from "@/pages/RestaurantDetails";
import RestaurantOwnerDetails from "@/pages/RestaurantOwnerDetails";
import RestaurantOwners from "@/pages/RestaurantOwners";
import Restaurants from "@/pages/Restaurants";
import RiderDetails from "@/pages/RiderDetails";
import Riders from "@/pages/Riders";
import ServiceAreas from "@/pages/ServiceAreas";
import Settings from "@/pages/Settings";
import { AdminRoute } from "@/routes/AdminRoute";

export default function App() {
  const { status } = useSession();

  if (status === "loading") {
    return <div className="page-center">Loading…</div>;
  }

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<AdminRoute />}>
        <Route element={<AdminLayout />}>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/customers" element={<Customers />} />
          <Route path="/customers/:customerId" element={<CustomerDetails />} />
          <Route path="/restaurants" element={<Restaurants />} />
          <Route path="/restaurants/:restaurantId" element={<RestaurantDetails />} />
          <Route path="/restaurant-owners" element={<RestaurantOwners />} />
          <Route path="/restaurant-owners/:ownerId" element={<RestaurantOwnerDetails />} />
          <Route path="/riders" element={<Riders />} />
          <Route path="/riders/:riderId" element={<RiderDetails />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/orders/:orderId" element={<OrderDetails />} />
          <Route path="/delivery-assignments" element={<DeliveryAssignments />} />
          <Route path="/delivery-assignments/:assignmentId" element={<DeliveryAssignmentDetails />} />
          <Route path="/payments" element={<Payments />} />
          <Route path="/payments/:paymentId" element={<PaymentDetails />} />
          <Route path="/cod" element={<CODReconciliation />} />
          <Route path="/categories" element={<Categories />} />
          <Route path="/service-areas" element={<ServiceAreas />} />
          <Route path="/coupons" element={<Coupons />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/audit-logs" element={<AuditLogs />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to={status === "authenticated" ? "/dashboard" : "/login"} replace />} />
    </Routes>
  );
}
