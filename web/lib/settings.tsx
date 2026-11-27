"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { api, NumberSystem } from "./api";

const Ctx = createContext<{ sys: NumberSystem; setSys: (s: NumberSystem) => void }>({ sys: "indian", setSys: () => {} });

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [sys, setSysState] = useState<NumberSystem>("indian");
  useEffect(() => {
    api("/settings").then((s) => setSysState(s.number_system)).catch(() => {});
  }, []);
  const setSys = (s: NumberSystem) => {
    setSysState(s);
    api("/settings", { number_system: s }).catch(() => {});
  };
  return <Ctx.Provider value={{ sys, setSys }}>{children}</Ctx.Provider>;
}

export const useSettings = () => useContext(Ctx);

export function NumberToggle() {
  const { sys, setSys } = useSettings();
  return (
    <label className="row" style={{ gap: 6 }}>
      Numbers
      <select value={sys} onChange={(e) => setSys(e.target.value as NumberSystem)}>
        <option value="indian">Indian (Lakh, Crore)</option>
        <option value="international">International (Mn)</option>
      </select>
    </label>
  );
}
