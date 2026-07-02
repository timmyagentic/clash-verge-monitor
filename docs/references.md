# Reference Projects

Checked on 2026-07-02 while planning the MVP.

| Project | Stars | License | Relevant idea |
| --- | ---: | --- | --- |
| [MetaCubeX/metacubexd](https://github.com/MetaCubeX/metacubexd) | 3,883 | MIT | Official Mihomo dashboard; uses controller connection and traffic APIs. |
| [haishanh/yacd](https://github.com/haishanh/yacd) | 4,819 | MIT | Mature Clash dashboard interaction patterns. |
| [foru17/neko-master](https://github.com/foru17/neko-master) | 1,922 | MIT | Larger traffic analytics platform with buffering and reconnect patterns. |
| [zhf883680/clash-traffic-monitor](https://github.com/zhf883680/clash-traffic-monitor) | 66 | MIT | Go + SQLite traffic monitor; useful aggregation model. |
| [Mooouy/clash-traffic-monitor](https://github.com/Mooouy/clash-traffic-monitor) | 0 | MIT | Small Python per-process accounting through `/connections`. |
| [xth1227/Clash-Traffic-Bar](https://github.com/xth1227/Clash-Traffic-Bar) | 0 | Not found | macOS Clash Verge unix-socket access and `lsof` fallback. |

## Design decision

The high-star projects are strong dashboards, but this MVP should not start with another dashboard. The missing piece on this Mac is durable byte accounting by day and process. A CLI sampler with SQLite gives a small, testable core that can later power a Web UI or menu bar app.

