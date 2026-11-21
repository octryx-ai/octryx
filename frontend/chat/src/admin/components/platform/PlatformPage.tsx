import { AdminDevicesList } from "../../../chat/devices/AdminDevicesList";
import { PlatformVersionPage } from "./PlatformVersionPage";
import "./platform.css";

// Admin › Platform pages built on existing endpoints: Version and Devices. Storage and Logs have no endpoint
// of their own yet (Logs is Operations › Audit log), so they are not entries.
export function PlatformPage({ page }: { page: "platformVersion" | "platformDevices" }) {
  return page === "platformVersion" ? <PlatformVersionPage /> : <AdminDevicesList />;
}
