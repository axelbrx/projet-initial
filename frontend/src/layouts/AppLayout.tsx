import { Outlet, useLocation, useNavigate } from "react-router";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

const tabs = [
  { path: "/", label: "Dashboard" },
  { path: "/fixes", label: "Fixes" },
  { path: "/agent-log", label: "Agent log" }
];

export default function AppLayout() {
  const { pathname } = useLocation();
  const navigate = useNavigate();

  const current = tabs.find((tab) => tab.path === pathname)?.path ?? "/";

  return (
    <div className="mx-auto min-h-screen max-w-7xl px-3 pt-2 pb-10">
      <div className="flex justify-between items-center">
        <h1 className="mt-8 text-center text-2xl font-medium">
          Data Hygiene Watchdog
        </h1>

        <div className="mt-6 flex justify-center">
          <Tabs
            value={current}
            onValueChange={(value) => navigate(String(value))}
          >
            <TabsList>
              {tabs.map((tab) => (
                <TabsTrigger key={tab.path} value={tab.path}>
                  {tab.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>
      </div>

      <div className="mt-8">
        <Outlet />
      </div>
    </div>
  );
}
