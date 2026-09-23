import { Navigate, Route, Routes } from "react-router-dom";

import { useSession } from "@/features/auth/session-context";
import { RestaurantLayout } from "@/layouts/RestaurantLayout";
import Login from "@/pages/auth/Login";
import Categories from "@/pages/restaurant/Categories";
import Dashboard from "@/pages/restaurant/Dashboard";
import OperatingHours from "@/pages/restaurant/OperatingHours";
import OrderDetails from "@/pages/restaurant/OrderDetails";
import Orders from "@/pages/restaurant/Orders";
import Products from "@/pages/restaurant/Products";
import RestaurantProfile from "@/pages/restaurant/RestaurantProfile";
import { RestaurantOwnerRoute } from "@/routes/RestaurantOwnerRoute";

export default function App() {
  const { status } = useSession();

  if (status === "loading") {
    return <div className="page-center">Loading…</div>;
  }

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RestaurantOwnerRoute />}>
        <Route element={<RestaurantLayout />}>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/profile" element={<RestaurantProfile />} />
          <Route path="/hours" element={<OperatingHours />} />
          <Route path="/categories" element={<Categories />} />
          <Route path="/products" element={<Products />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/orders/:orderId" element={<OrderDetails />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to={status === "authenticated" ? "/dashboard" : "/login"} replace />} />
    </Routes>
  );
}
