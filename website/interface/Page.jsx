import React, { useState } from "react";
import { ListFilter, LayoutDashboard, Terminal } from "lucide-react";
import { Action, Choices, Figure } from "./ui.jsx";
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
    <section className="pi-hero ledger-hero" aria-labelledby="hero-title">
      <div className="pi-container">
        <header className="ledger-toolbar">
          <div>
            <h1 id="hero-title">Clash Verge Monitor</h1>
            <p>按天回看各应用的代理流量。</p>
          </div>
          <Action href="#start" icon={Terminal}>
            本机安装
          </Action>
        </header>
        <article className="ledger-statement">
          <div className="ledger-heading">
            <h2>10 月 24 日的流量</h2>
            <span>隔离样例</span>
          </div>
          <div className="ledger-stat">
            <strong>14.62</strong>
            <span>GiB</span>
          </div>
          <p className="ledger-annotation">
            Browser 使用了 7.89 GiB，占当天记录的 54%。
          </p>
          <div className="ledger-distribution" aria-hidden="true">
            <i />
            <i />
            <i />
          </div>
          <Choices
            label="查看账本"
            tabs={views}
            value={view}
            onChange={setView}
          >
            {(item) =>
              item.id === "ranking" ? (
                <table className="ledger-rows">
                  <thead>
                    <tr>
                      <th scope="col">应用</th>
                      <th scope="col">占比</th>
                      <th scope="col">记录流量</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.map(([name, amount]) => (
                      <tr key={name}>
                        <th scope="row">{name}</th>
                        <td>
                          <meter
                            aria-label={name + " 的流量"}
                            min={0}
                            max={14.62}
                            value={amount}
                          />
                          <span>{((amount / 14.62) * 100).toFixed(1)}%</span>
                        </td>
                        <td>{amount.toFixed(2)} GiB</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
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
          <p className="ledger-footnote">
            采样中断的时段不计入总量。<a href="#limits">查看采样边界</a>
          </p>
        </article>
      </div>
    </section>
  );
}
