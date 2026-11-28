import { AdminDevicesList } from "../../../chat/devices/AdminDevicesList";
import { PlatformVersionPage } from "./PlatformVersionPage";
import "./platform.css";

export function PlatformPage({ page }: { page: "platformVersion" | "platformDevices" }) {
  return page === "platformVersion" ? <PlatformVersionPage /> : <AdminDevicesList />;
}
