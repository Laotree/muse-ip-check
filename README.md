# muse.ai 出口 IP 检查

在线版：<https://laotree.github.io/muse-ip-check/>

检查访问 `muse.ai` 时，这台机器用的是哪个 IP：家里宽带的直连 IP，还是代理/VPN 分流后的出口 IP。
思路参考 <https://ip.skk.moe/split-tunnel>，只聚焦 muse.ai 一个站。

页面没有后端、没有统计代码，不收集也不上报任何数据。检测请求由你的浏览器直接发往各探针站点，
结果只显示在你眼前。

## 快速上手

在线版直接打开上面的地址，页面加载后自动检测。

本地运行（零依赖，Python 3.8+）：

```bash
python3 server.py          # 默认 http://localhost:8765/，换端口：python3 server.py 9000
```

在要检测的那台机器上打开 `http://localhost:8765/`。也可以直接用浏览器打开 `index.html`，
但部分浏览器对 `file://` 下的脚本有限制，建议用 `server.py`。

命令行版：

```bash
python3 check.py                    # 用 claude.ai 作参考站
python3 check.py example.com        # 用自定义参考站
```

注意终端与浏览器可能走不同的代理。如果代理只接管浏览器（插件模式），以网页版为准；
如果是 TUN / 系统代理模式，两边结果应一致，可以互相印证。

## 原理

页面打开后，浏览器从 JavaScript 请求不同公司自家域名下的「IP 回显」接口，对方服务器把看到的
客户端 IP 原样返回（JSONP，或带 `Access-Control-Allow-Origin: *` 的响应）。

关键在于：请求的目的域名不同，代理客户端的分流规则就会把它分到不同的出站。
所以某一行显示的 IP，就是「访问这个域名时」用的出口 IP。

| 探针 | 接口 | 返回方式 |
|---|---|---|
| 阿里巴巴 | `{随机}.dns-detect.alicdn.com/api/detect/DescribeDNSLookup?cb=` | JSONP，`content.localIp` |
| 腾讯 | `r.inews.qq.com/api/ip2city?otype=jsonp&callback=` | JSONP，`ip` + 地理位置 |
| 网易 | `necaptcha.nosdn.127.net/*.png`（HEAD） | 响应头 `cdn-user-ip`（带 `Expose-Headers: *`） |
| Cloudflare 系 | `https://<域名>/cdn-cgi/trace` | 纯文本，含 `ip=` / `loc=` |
| 归属地 | `ipwho.is/<ip>` | JSON（给任意一行 IP 补地理位置/运营商） |

## 为什么 muse.ai 这一行读不到 IP

2026-10-20 实测：

- `muse.ai` 跑在 **Vercel**（响应头 `Server: Vercel`），没有 Cloudflare 的 `/cdn-cgi/trace`；
  请求 `https://muse.ai/cdn-cgi/trace` 返回 401 `{"error":"Authentication required"}`。
- 全站没有公开的「回显客户端 IP」接口，浏览器跨域也读不到对方服务器日志。

所以浏览器里不可能直接读出访问 muse.ai 时对方看到的 IP。页面给的是可落地的替代判定：

1. **国内参照**（阿里/腾讯/网易）= 直连时的 IP。
2. **参考站**：`claude.ai` 与 muse.ai 同属「国外 AI 站」，在常见分流规则里会被分到同一个出站；
   它的 `/cdn-cgi/trace` 报出的 IP 就是这类站可能的出口 IP。这个假设不保证成立，见下。
3. **muse.ai 本站探针**：请求 `https://muse.ai/favicon.ico`（带 `Access-Control-Allow-Origin: *`，可测）
   测可达性和 HTTP 耗时，确认 muse.ai 本身在当前网络下到底通不通。
4. **判定**：参考站 IP ≠ 直连 IP → muse.ai 大概率走代理，出口 = 参考站 IP；相等 → 大概率直连。

### 为什么「耗时」不能直接和 ping 比

页面量的是 `fetch` 从发起到收到响应头的时间，包含 DNS、TCP 握手、TLS 握手和请求往返。
ICMP ping 只含一次往返，两者不是同一个量。本机实测 ping 218 ms 时，同一时刻首请求约 880 ms。

因此页面分开报两个数：

- **首请求**：冷连接，含连接建立，数值天然比 ping 大。
- **复用连接**：紧接着在同一连接上再请求一次，更接近单程往返；要和 `ping` 对照，请看这个值。

浏览器不能发 ICMP。命令行版 `check.py` 只报首请求：`urllib` 每次新建连接，拿不到复用值。
若本机经代理访问，`ping muse.ai` 打到的是代理那一跳，浏览器请求的终点可能不同，两者只能比较数量级。

### 判定在什么时候会失效

- **全局代理 / 未启用代理**：所有探针会报同一个 IP，直连与代理无从区分。页面此时显示
  「无法区分」，不会给出直连或走代理的结论。
- **分流规则按域名分组**：`www.cloudflare.com` 可能直连，而 `claude.ai`、`chatgpt.com` 走代理。
  这说明规则是逐域名的，参考站与 muse.ai 不一定同组。页面因此把 claude.ai 标为「参考站」而不是
  「同规则」。
- **国内探针结果不一致**：页面取出现次数最多的 IP，并提示存在分歧。

## 想做到 100% 精确

1. **看代理客户端日志**：检测时在 Clash/Mihomo/Surge/Shadowrocket 里打开「连接（Connections）」，
   过滤 `muse.ai`，直接看这条连接走了哪个出站。这是最权威的。
2. **同策略组参照法**：把某个支持 `/cdn-cgi/trace` 的域名和 `muse.ai` 放进**同一个策略组**，
   然后在页面「自定义参照」里填这个域名，它报出的 IP 就是 muse.ai 的真实出口 IP。

## 文件清单

| 文件 | 说明 |
|---|---|
| `index.html` | 单文件页面，全部逻辑都在里面 |
| `check.py` | 零依赖命令行版，逻辑与页面一致 |
| `server.py` | 零依赖本地静态服务器（Python 3 标准库） |
| `robots.txt` / `sitemap.xml` | 搜索引擎配置 |
| `og.png` | 分享卡图片 |
| `LICENSE` | MIT 许可证 |
| `README.md` | 本文件 |

## 部署

站点由 GitHub Pages 直接发布：仓库默认分支 `main` 的根目录。没有构建步骤，改完推送即可。

换到自有域名时改三处：

1. `index.html` 里的 `canonical`、`og:url`、`og:image`、`twitter:image`；
2. `sitemap.xml` 的 `<loc>`；
3. `robots.txt` 的 `Sitemap`。

## 隐私

- 页面没有后端、没有 Cookie、没有统计脚本。
- 检测请求由浏览器直接发往阿里、腾讯、网易、Cloudflare、ipwho.is。这些第三方会看到你的 IP，
  其中 ipwho.is 会收到被查询的 IP。这是工具本身必需的数据流向。
- 页面不会把这些结果发送到其他地方。

## 注意事项

- 必须在**要检测的机器上**打开页面；在别的机器上打开，看到的是那台机器的 IP。
- 探针都依赖第三方接口，对方改动接口或限流时会降级：归属地一列可能只显示国家代码或「—」，
  重新检测即可重试。
- `muse.ai` 的站点地址、Cloudflare trace 行为都可能变化，页面底部的说明以最近一次实测为准。

## License

MIT 许可证，详见 [LICENSE](LICENSE)。
