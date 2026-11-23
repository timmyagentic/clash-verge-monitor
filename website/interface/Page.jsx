import React, { useState } from "react";
import {
  ChartNoAxesColumn,
  ListFilter,
  LayoutDashboard,
  HardDrive,
  Terminal,
} from "lucide-react";
import { Action, Choices, Figure, HeroCopy, Mark } from "./ui.jsx";
export const site = {
  name: "Clash Verge Monitor",
  lang: "zh",
  nav: [
    ["仪表盘", "#preview"],
    ["采样方式", "#features"],
    ["安装", "#start"],
    ["数据边界", "#limits"],
  ],
};
const views = [
  { id: "ranking", label: "应用排行", icon: ListFilter },
  { id: "ledger", label: "完整账本", icon: LayoutDashboard },
];
const usage = [
  ["Browser", 7.89],
  ["Editor", 3.02],
  ["其余应用", 3.71],
];
export function Hero() {
  const [view, setView] = useState("ranking");
  return (
    <section className="pi-hero ledger-hero">
      <div className="pi-container pi-split">
        <HeroCopy
          mark={<Mark Icon={HardDrive}>Clash Verge · 本地 SQLite</Mark>}
          title={
            <>
              一天的流量，
              <br />
              用在哪个应用？
            </>
          }
          description="把实时连接整理成按天的流量账本。点开应用排行，再回到整张仪表盘核对。"
        >
          <div className="pi-actions">
            <Action href="#start" icon={Terminal}>
              在本机安装
            </Action>
            <Action href="#preview" tone="ghost">
              查看真实界面
            </Action>
          </div>
        </HeroCopy>
        <article className="ledger-book">
          <div className="ledger-head">
            <div>
              <ChartNoAxesColumn size={21} />
              <h2>流量账本</h2>
            </div>
            <span>10 月 24 日 · 隔离样例</span>
          </div>
          <div className="ledger-total">
            <strong>14.62</strong>
            <span>GiB 已记录</span>
          </div>
          <Choices
            label="查看账本"
            tabs={views}
            value={view}
            onChange={setView}
          >
            {(item) =>
              item.id === "ranking" ? (
                <div className="ledger-bars">
                  {usage.map(([name, amount]) => (
                    <div key={name}>
                      <div>
                        <strong>{name}</strong>
                        <span>{amount.toFixed(2)} GiB</span>
                      </div>
                      <meter
                        aria-label={name + " 的流量"}
                        min="0"
                        max="14.62"
                        value={amount}
                      />
                    </div>
                  ))}
                  <p>Browser 占已记录流量的 54%。采样中断时段不计入总量。</p>
                </div>
              ) : (
                <Figure
                  src="/assets/app-overview.png"
                  width={1425}
                  height={990}
                  title="完整流量账本"
                  alt="隔离样例的仪表盘，展示流量趋势、应用排行和连接目标。"
                  priority
                />
              )
            }
          </Choices>
        </article>
      </div>
    </section>
  );
}
